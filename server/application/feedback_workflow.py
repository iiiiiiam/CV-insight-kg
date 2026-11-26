"""One administrator workflow: existing knowledge decisions plus durable reply delivery.

The domain's decision methods remain unchanged. A store decorator records the reply
intent inside the SAME local decision transaction, so network retry never reapplies it.
"""
from contextlib import contextmanager
from copy import deepcopy
import hmac

from src.knowledge_builder.extraction import fingerprint
from src.knowledge_builder.feedback import FeedbackConflict
from server.application.cloud_feedback import CloudFeedbackError


class ReplyIntentStore:
    def __init__(self, store, identifier, intent):
        self.store,self.identifier,self.intent=store,identifier,intent
        self.path=store.path

    def read(self):
        return self.store.read()

    @contextmanager
    def transaction(self, expected_revision=None):
        with self.store.transaction(expected_revision) as data:
            yield data
            row=next(item for item in data['requests'] if item['id']==self.identifier)
            row['_team_reply']=deepcopy(self.intent)


class FeedbackWorkflow:
    def __init__(self, cloud, workspace):
        self.cloud,self.workspace=cloud,workspace

    def refresh(self, token):
        rows=self.cloud.queue(token)['requests']
        self.cloud.remember_team(rows)
        return self.queue()

    def queue(self):
        workspace=self.workspace()
        result=workspace.queue()
        originals={row['id']:row for row in result['requests']}
        cached,links=self.cloud.team_cache()
        merged=[];hidden=set()
        for item in cached:
            remote=item['document'];payload=remote['payload']
            local_id=item['local_id'] or links.get(remote['id'])
            local=originals.get(local_id)
            if local:
                hidden.add(local_id)
                row=deepcopy(local)
                warning=''
                can_apply=True
            else:
                paper_id=payload.get('paper_id','')
                term=payload.get('display_name') or None
                row=dict(id='',paper_id=paper_id,paper_title=paper_id or '一般反馈',
                         candidate_id=payload.get('candidate_id') or None,term=term,
                         message=payload.get('message',''),context={},resolution=None,
                         status=remote['status'],created_at=remote['created_at'],updated_at=remote['updated_at'])
                can_apply=False;warning='当前数据未包含对应论文，可先回复处理说明。'
                try:
                    view=workspace.view(paper_id)
                    row['paper_title']=view['paper']['title']
                    candidate=next((entry for entry in view['entities']+view['relations']
                                    if entry['candidate_id']==row['candidate_id']),None)
                    if candidate:
                        row['context']=deepcopy(candidate)
                    if term:
                        row['context']={'quote':term}
                    can_apply=(payload.get('knowledge_revision')==view['revision'] and bool(candidate or term))
                    warning='' if can_apply else '论文版本或反馈依据与当前数据不一致；可先回复，核对后再修正。'
                except (LookupError,ValueError):
                    pass
            intent=(local or {}).get('_team_reply')
            pending=bool((intent and intent.get('state')!='sent') or
                         (local and local.get('resolution') and remote['status']=='open'))
            row.update(id='cloud:'+remote['id'],status=(local['status'] if pending else remote['status']),
                cloud=dict(id=remote['id'],revision=remote['state_revision'],reply=remote['processing_note'],
                           delivery='pending' if pending else 'sent',can_apply=can_apply,warning=warning,
                           local_id=local_id,can_reopen=bool(local and local.get('resolution'))))
            merged.append(row)
        result['requests']=[row for row in result['requests'] if row['id'] not in hidden]+merged
        result['counts']={state:sum(row['status']==state for row in result['requests'])
                          for state in ('open','resolved','dismissed')}
        return result

    def selected(self, identifier):
        row=next((row for row in self.queue()['requests'] if row['id']==identifier),None)
        if row is None or not row.get('cloud'):
            raise LookupError('请先获取团队反馈，再选择这条记录。')
        return row

    def _mark(self, local_id, intent, state):
        workspace=self.workspace()
        with workspace.store.transaction() as data:
            row=next(item for item in data['requests'] if item['id']==local_id)
            if row.get('_team_reply',{}).get('key')==intent['key']:
                row['_team_reply']['state']=state

    def _deliver(self, local_id, intent, token):
        try:
            try:
                result=self.cloud.reply(intent['cloud_id'],intent['status'],intent['note'],intent['cloud_revision'],token)
                # Preserve full payload in the inbox when updating the reply cache.
                cached,_=self.cloud.team_cache()
                original=next(item['document'] for item in cached if item['document']['id']==intent['cloud_id'])
                self.cloud.remember_team([{**original,**result}])
            except CloudFeedbackError as exc:
                if exc.status!=409:
                    raise
                # A prior attempt may have committed before its response was lost.
                fresh=self.cloud.queue(token)['requests']
                self.cloud.remember_team(fresh)
                remote=next((item for item in fresh if item['id']==intent['cloud_id']),None)
                if (not remote or remote['status']!=intent['status'] or remote['processing_note']!=intent['note']
                        or remote['state_revision']!=intent['cloud_revision']+1):
                    raise CloudFeedbackError('知识处理已保存，但团队记录已被其他人更新；请刷新核对后处理回复。',409)
            self._mark(local_id,intent,'sent')
            return {'reply_delivery':'sent','message':'处理和回复已保存。'}
        except CloudFeedbackError as exc:
            return {'reply_delivery':'pending','message':'知识处理已保存，回复尚未确认送达：'+str(exc)}

    def resolve(self, identifier, body, reviewer, token):
        row=self.selected(identifier);cloud=row['cloud']
        workspace=self.workspace()
        if workspace.store.read()['revision']!=body['revision']:
            raise FeedbackConflict('反馈列表已变化，请刷新后再处理。')
        if cloud['revision']!=body.get('cloud_revision'):
            raise FeedbackConflict('团队反馈已变化，请刷新后再处理。')
        local_id=cloud['local_id']
        expected_revision=body['revision']
        existing=next((item for item in workspace.store.read()['requests'] if item['id']==local_id),None)
        if existing and existing.get('_team_reply',{}).get('state')=='pending':
            raise FeedbackConflict('该知识处理已经保存，请使用“重试发送回复”，不要重复修正。')
        if not cloud['can_apply']:
            if body['action']!='dismiss':
                raise FeedbackConflict(cloud['warning'])
            result=self.cloud.reply(cloud['id'],'dismissed',body['reason'],cloud['revision'],token)
            cached,_=self.cloud.team_cache()
            original=next(item['document'] for item in cached if item['document']['id']==cloud['id'])
            self.cloud.remember_team([{**original,**result}])
            return {'reply_delivery':'sent','message':'已保留原知识并保存回复。'}
        if not local_id:
            # Materialize a remote request only when the operator actually processes it.
            cached,_=self.cloud.team_cache()
            remote=next(item['document'] for item in cached if item['document']['id']==cloud['id'])
            payload=remote['payload']
            owner=hmac.digest(self.cloud.secret.encode(),('review:'+cloud['id']).encode(),'sha256').hex()
            added=workspace.submit(row['paper_id'],payload['knowledge_revision'],row['message'],
                candidate_id=row['candidate_id'],term=row['term'],owner_token=owner)
            local_id=added['id'];self.cloud.link_team(cloud['id'],local_id)
            if not added['duplicate']:
                expected_revision+=1
            workspace=self.workspace()
        intent=dict(cloud_id=cloud['id'],cloud_revision=cloud['revision'],note=body['reason'],
                    status='dismissed' if body['action']=='dismiss' else 'resolved',state='pending')
        intent['key']=fingerprint(intent)
        workspace.store=ReplyIntentStore(workspace.store,local_id,intent)
        values={key:value for key,value in body.items() if key not in ('revision','cloud_revision')}
        workspace.resolve(local_id,revision=expected_revision,reviewer=reviewer,**values)
        return self._deliver(local_id,intent,token)

    def retry(self, identifier, token):
        row=self.selected(identifier)
        local_id=row['cloud']['local_id']
        request=next((item for item in self.workspace().store.read()['requests'] if item['id']==local_id),None)
        intent=(request or {}).get('_team_reply')
        if not intent and request and request.get('resolution'):
            intent=dict(cloud_id=row['cloud']['id'],cloud_revision=row['cloud']['revision'],
                        note=request['resolution']['reason'],status=request['status'],state='pending')
            intent['key']=fingerprint(intent)
            with self.workspace().store.transaction() as data:
                target=next(item for item in data['requests'] if item['id']==local_id)
                if target.get('resolution')!=request['resolution']:
                    raise FeedbackConflict('处理记录已变化，请刷新。')
                target['_team_reply']=deepcopy(intent)
        if not intent:
            raise FeedbackConflict('没有等待发送的回复。')
        if intent['state']=='sent':
            return {'reply_delivery':'sent','message':'回复已送达，无需重复发送。'}
        return self._deliver(local_id,intent,token)

    def reopen(self, identifier, body, reviewer, token):
        row=self.selected(identifier);cloud=row['cloud'];local_id=cloud['local_id']
        if cloud['revision']!=body.get('cloud_revision'):
            raise FeedbackConflict('团队反馈已变化，请刷新后再处理。')
        if not local_id or not cloud['can_reopen']:
            raise FeedbackConflict('当前没有可撤回的本机知识处理记录。')
        intent=dict(cloud_id=cloud['id'],cloud_revision=cloud['revision'],status='open',
                    note='已撤回原处理，重新核对中。',state='pending')
        intent['key']=fingerprint(intent)
        workspace=self.workspace()
        workspace.store=ReplyIntentStore(workspace.store,local_id,intent)
        workspace.reopen(local_id,revision=body['revision'],reviewer=reviewer)
        return self._deliver(local_id,intent,token)
