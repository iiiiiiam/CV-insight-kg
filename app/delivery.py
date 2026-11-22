"""One-click A→B delivery, including withdrawal and version-bound receipts."""
import os

import requests
from sqlalchemy import select

from .data_overview import handoff
from .models import Job, WorkflowTask
from .operations import HandoffReceipt


def queue_withdrawal_notification(db, document):
    """Persist the notification in the same transaction as A's withdrawal."""
    from .workflow_tasks import enqueue, view
    identifier = document['batch_id']
    known = db.scalar(select(WorkflowTask.id).where(
        WorkflowTask.kind == 'handoff', WorkflowTask.batch_id == identifier).limit(1))
    receipt = db.scalar(select(HandoffReceipt.id).where(
        HandoffReceipt.job_id == identifier, HandoffReceipt.recipient == 'B').limit(1))
    if known is None and receipt is None:
        return dict(status='not_required', reason='本批次尚未向 B 交接')
    revision = document['batch_revision']
    payload = dict(batch_id=identifier, batch_revision=revision, document=document)
    task, _ = enqueue(db, 'handoff', f'withdraw:{identifier}:{revision}',
                      dict(batch_id=identifier, batch_revision=revision, action='withdraw'),
                      payload, commit=False)
    return view(task)


def batch_document(db, job_id):
    job = db.get(Job, job_id)
    if job is None:
        raise LookupError('未找到论文批次')
    if job.status != 'succeeded':
        raise ValueError('请先完成导入或重试失败记录，再交接完整批次')
    document = handoff(db, job)
    if not document.get('batch_revision'):
        raise ValueError('该历史批次尚无版本账本，请使用本周正式或补充库导入批次')
    return document


def send(db, payload, checkpoint, http_factory=requests.Session):
    document = payload['document']
    identifier, revision = payload['batch_id'], payload['batch_revision']
    def check_revision():
        db.expire_all()
        current = batch_document(db, identifier)
        if current['batch_revision'] != revision:
            raise ValueError('A 批次已更新或撤回，请刷新后创建新的交接任务')
    check_revision()
    root = os.getenv('B_API_BASE_URL', '').rstrip('/')
    username, password = os.getenv('B_ADMIN_USERNAME'), os.getenv('B_ADMIN_PASSWORD')
    if not all((root, username, password)):
        raise ValueError('尚未配置 B 接收服务；使用项目启动入口或配置 B_API_BASE_URL 和服务端账号')
    checkpoint('sending', 20, '正在连接 B 的现有批次接收接口')
    with http_factory() as http:
        http.trust_env = False
        def request(method, path, body=None):
            response = http.request(method, root + path, json=body, timeout=120, allow_redirects=False)
            if response.status_code >= 400 or response.status_code < 200 or response.status_code >= 300:
                raise ValueError(f'B 接收接口返回 HTTP {response.status_code}，请检查接收服务后重试')
            return response.json()
        login = request('POST', '/api/admin/sessions', {'username': username, 'password': password})
        http.headers['X-CSRF-Token'] = login['csrf_token']
        endpoint = '/api/admin/knowledge/batches'
        before = request('GET', endpoint)
        checkpoint('receiving', 45, 'B 正在按稳定论文 ID 接收或撤回批次')
        if document['state'] == 'withdrawn':
            known = next((item for item in before['batches'] if item['batch_code'] == document['batch_code']), None)
            result = (request('POST', endpoint + '/' + document['batch_code'] + '/withdraw',
                              {'revision': before['revision']}) if known else
                      {'status': 'unchanged', 'reason': 'B 尚未接收本批次，无需移除'})
        else:
            result = request('POST', endpoint, {'revision': before['revision'], 'document': document,
                                               'acknowledge_switch': True})
        if result.get('status') not in ('accepted', 'unchanged', 'withdrawn'):
            raise ValueError('B 未成功接收本批次，请检查 B 的失败记录后重试')
        if document['state'] != 'withdrawn' and result['status'] == 'withdrawn':
            raise ValueError('B 已撤回该批次，请使用新批次编号导入')
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
