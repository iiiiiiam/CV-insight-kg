"""Owner-only first-account initializer. Later account management is in the software UI."""
import getpass
import hashlib
import re
import secrets


def main():
    print('仅首次初始化账号管理员使用。以后新增、停用、改密均在软件里操作。')
    name = input('首位账号管理员登录名（3–50 位小写字母、数字或 _.-，字母开头）：').strip().lower()
    if not re.fullmatch(r'[a-z][a-z0-9_.-]{2,49}', name):
        print('登录名格式不正确，未生成。')
        return
    password = getpass.getpass('设置登录密码（至少 12 位，不显示）：')
    again = getpass.getpass('再输一次：')
    if password != again or not 12 <= len(password) <= 256:
        print('密码不一致或长度不符合，未生成。')
        return
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode('utf-8'), salt=salt, n=16384, r=8, p=1, dklen=32)
    verifier = f'scrypt${salt.hex()}${digest.hex()}'
    print('先在数据库 SQL 编辑器执行 002_team_accounts.sql，再以建表账号执行下面一条 SQL：')
    print(f"SELECT public.ri_team_bootstrap('{name}', '{verifier}');")
    print('只在账号库为空时建立首位账号管理员；已有任何账号都会拒绝，不会覆盖。')
    print('不联网、不自动修改数据库；不用发给别人或粘贴到环境变量。')


if __name__ == '__main__':
    try:
        main()
    except (KeyboardInterrupt, EOFError):
        print('\n已取消，未更改云端。')
