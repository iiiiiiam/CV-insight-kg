"""A→B delivery, including withdrawal and version-bound receipts."""
import os
import json
from contextlib import contextmanager

import requests
from sqlalchemy import select

from .data_overview import handoff
from .models import Job, WorkflowTask
from .operations import HandoffReceipt


class DeliveryError(ValueError):
    def __init__(self, message, *, retryable=True):
        super().__init__(message)
        self.retryable = retryable


@contextmanager
def b_session(http_factory=None):
    if os.getenv('A_B_TRANSPORT','http')=='local' and http_factory is None:
        from .paths import configured_path
        from src.knowledge_builder.batches import BatchRegistry, _snapshot
        registry=BatchRegistry(configured_path('B_BATCH_REGISTRY','data/knowledge_builder/batches/ledger.json'))
        def local_request(method,path,body=None):
            endpoint='/api/admin/knowledge/batches'
            if method=='GET' and path==endpoint:
                state=registry.read();snapshot=_snapshot(state)
                return dict(revision=state['revision'],snapshot_revision=snapshot['revision'],paper_count=snapshot['paper_count'],
                    source_enrichment={'running':False},batches=[dict(batch_id=b['batch_id'],batch_code=b['batch_code'],
                        active=b['active'],handoff_digest=b['handoff_digest'],a_batch_revision=b['document'].get('batch_revision'))
                        for b in state['batches']])
            if method=='POST' and path==endpoint:
                return registry.ingest(body['document'],expected_revision=body['revision'])
            if method=='POST' and path.startswith(endpoint+'/') and path.endswith('/withdraw'):
                return registry.withdraw(path.split('/')[-2],expected_revision=body['revision'])
            raise DeliveryError('不支持的后台批次操作',retryable=False)
        yield local_request
        return
    root = os.getenv('B_API_BASE_URL', '').rstrip('/')
    username, password = os.getenv('B_ADMIN_USERNAME'), os.getenv('B_ADMIN_PASSWORD')
    if not all((root, username, password)):
        raise DeliveryError('尚未配置 B 接收服务；使用项目启动入口或配置 B_API_BASE_URL 和服务端账号')
    with (http_factory or requests.Session)() as http:
        http.trust_env = False
        def request(method, path, body=None):
            response = http.request(method, root + path, json=body, timeout=(5, 30), allow_redirects=False)
            if not 200 <= response.status_code < 300:
                raise DeliveryError(f'B 接收接口返回 HTTP {response.status_code}，请检查接收服务后重试')
            return response.json()
        login = request('POST', '/api/admin/sessions', {'username': username, 'password': password})
        http.headers['X-CSRF-Token'] = login['csrf_token']
        yield request


def queue_withdrawal_notification(db, document, *, repair=False):
    """Persist the notification in the same transaction as A's withdrawal."""
    from .auto_handoff import queue_delivery
    identifier = document['batch_id']
    known = db.scalar(select(WorkflowTask.id).where(
        WorkflowTask.kind == 'handoff', WorkflowTask.batch_id == identifier).limit(1))
    receipt = db.scalar(select(HandoffReceipt.id).where(
        HandoffReceipt.job_id == identifier, HandoffReceipt.recipient == 'B').limit(1))
    if known is None and receipt is None:
        return dict(status='not_required', reason='本批次尚未向 B 交接')
    return queue_delivery(db, document, repair=repair)


def batch_document(db, job_id):
    job = db.get(Job, job_id)
    if job is None:
        raise LookupError('未找到论文批次')
    document = handoff(db, job)
    if job.status != 'succeeded' and document.get('state') != 'withdrawn':
        raise DeliveryError('请先完成导入或重试失败记录，再交接完整批次', retryable=False)
    if document.get('state')=='active' and not document.get('exported_papers'):
        raise DeliveryError('该批次尚无可交接论文，请核对来源标识和排除明细',retryable=False)
    if not document.get('batch_revision'):
        raise ValueError('该历史批次尚无版本账本，请使用本周正式或补充库导入批次')
    return document


def owns_remote_batch(db, identifier, known):
    """A matching frozen input is required before withdrawing a B-side batch."""
    from src.knowledge_builder.extraction import fingerprint
    checksum = known.get('handoff_digest')
    if checksum:
        for value in db.scalars(select(WorkflowTask.payload_json).where(
            WorkflowTask.kind=='handoff', WorkflowTask.batch_id==identifier)):
            original=json.loads(value).get('document',{})
            if original.get('state')=='active' and fingerprint(original)==checksum:
                return True
    upstream_revision=known.get('a_batch_revision')
    return bool(upstream_revision and db.scalar(select(HandoffReceipt.id).where(
        HandoffReceipt.job_id==identifier,HandoffReceipt.recipient=='B',
        HandoffReceipt.revision==upstream_revision,HandoffReceipt.status.in_(('received','processed'))).limit(1)))


def send(db, payload, checkpoint, http_factory=None):
    document = payload['document']
    identifier, revision = payload['batch_id'], payload['batch_revision']
    def check_revision():
        db.expire_all()
        current = batch_document(db, identifier)
        if current['batch_revision'] != revision:
            raise DeliveryError('A 批次已更新或撤回，旧交接任务已停止，新版本由自动补扫处理', retryable=False)
    check_revision()
    checkpoint('sending',20,'正在提交到后台知识模块' if os.getenv('A_B_TRANSPORT')=='local' else '正在连接 B 的现有批次接收接口')
    with b_session(http_factory) as request:
        endpoint = '/api/admin/knowledge/batches'
        before = request('GET', endpoint)
        checkpoint('receiving', 45, 'B 正在按稳定论文 ID 接收或撤回批次')
        if document['state'] == 'withdrawn':
            known = next((item for item in before['batches'] if item['batch_code'] == document['batch_code']), None)
            if known and known['active'] and not owns_remote_batch(db,identifier,known):
                raise DeliveryError('B 的同编号批次与 A 已存交接内容不一致，已停止自动撤回，请核对来源',retryable=False)
            result = (request('POST', endpoint + '/' + document['batch_code'] + '/withdraw',
                              {'revision': before['revision']}) if known else
                      {'status': 'unchanged', 'reason': 'B 尚未接收本批次，无需移除'})
        else:
            known = next((b for b in before['batches'] if b['batch_code']==document['batch_code']),None)
            if known is None and any(b.get('active') and b.get('batch_id',0)>identifier for b in before['batches']):
                raise DeliveryError('B 已存在更新批次，补交旧批次会改变论文版本优先级；请核对或恢复 B 账本',retryable=False)
            result = request('POST', endpoint, {'revision': before['revision'], 'document': document,
                                               'acknowledge_switch': True})
        if result.get('status') not in ('accepted', 'unchanged', 'withdrawn'):
            raise DeliveryError('B 未成功接收本批次，请检查 B 的失败记录后重试', retryable=False)
        if document['state'] != 'withdrawn' and result['status'] == 'withdrawn':
            raise DeliveryError('B 已撤回该批次，请使用新批次编号导入', retryable=False)
        after = request('GET', endpoint)
    check_revision()
    checkpoint('receipt', 85, '保存 B 实际返回的接收结果')
    receipt = db.scalar(select(HandoffReceipt).where(HandoffReceipt.job_id == identifier,
        HandoffReceipt.revision == revision, HandoffReceipt.recipient == 'B'))
    if receipt is None:
        receipt = HandoffReceipt(job_id=identifier, revision=revision, recipient='B', status='received')
        db.add(receipt)
    if receipt.status != 'processed':
        receipt.status = 'received'
    receipt.message = f"B 已{'核对撤回' if document['state'] == 'withdrawn' else '接收'}，当前有效论文 {after['paper_count']} 篇"
    receipt.snapshot_revision = after['snapshot_revision']
    db.commit()
    return dict(batch_id=identifier, batch_revision=revision, batch_state=document['state'],
                b_status=result['status'], b_paper_count=after['paper_count'],
                b_snapshot_revision=after['snapshot_revision'], received=True,
                knowledge_processing='running' if after.get('source_enrichment', {}).get('running') else 'pending_check',
                graph_publication='pending_check')
