from types import SimpleNamespace

from server.configuration.settings import Settings
from server.domain.auth import AuthService
from server.domain.users import UserAlreadyExists, UserStore


def test_user_store_persists_hashed_case_insensitive_accounts(tmp_path):
    path=tmp_path/'users.json'
    store=UserStore(path)
    created=store.register('Researcher01','Research2026','研究用户')
    assert path.exists() and 'Research2026' not in path.read_text(encoding='utf-8')
    authenticated=UserStore(path).authenticate('RESEARCHER01','Research2026')
    assert authenticated['id']==created['id']
    assert authenticated['feedback_token']==created['feedback_token']
    assert UserStore(path).authenticate('researcher01','incorrect') is None


def test_user_store_rejects_duplicates_and_weak_passwords(tmp_path):
    store=UserStore(tmp_path/'users.json')
    store.register('reader01','Reader2026','读者')
    try:
        store.register('READER01','Reader2026','另一个读者')
    except UserAlreadyExists:
        pass
    else:
        raise AssertionError('case-insensitive duplicate should fail')
    for password in ('short1','onlyletters'):
        try:
            store.register('reader02',password,'读者')
        except ValueError:
            pass
        else:
            raise AssertionError('weak password should fail')


def test_auth_service_keeps_admin_and_user_roles_separate(tmp_path):
    settings=Settings(username='admin',password='UnitTest-Password-2026!',secret='s'*48,
                      user_store=str(tmp_path/'users.json'),auto_graph_sync=False)
    auth=AuthService(settings)
    request=SimpleNamespace(client=SimpleNamespace(host='127.0.0.1'),session={})
    user=auth.register_user(request,'reader01','Reader2026','研究用户')
    assert user.role=='user' and user.user_id and user.feedback_token
    auth.logout(request)
    logged=auth.login_user(request,'READER01','Reader2026')
    assert logged.user_id==user.user_id and logged.role=='user'
    admin=auth.login_admin(request,'admin','UnitTest-Password-2026!')
    assert admin.role=='admin' and admin.user_id is None and admin.feedback_token is None
