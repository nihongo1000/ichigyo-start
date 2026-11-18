"""はてなブログ版：サーチコンソールを「Google でログイン」型でつなぐ道具（hatena/SETUP_SC_HATENA.md から使う）。

使い方（鍵や中身は表示しない）:
  python3 -I sc_login.py url                  -> お客さんに押してもらうリンクを出す
  python3 -I sc_login.py exchange '<貼られた文>' -> 貼られた文（ichigyo-sc:... ）を鍵に換え、
                                                 /tmp/hkit/gsc_user.json に保存し、見えるプロパティの一覧を出す
  python3 -I sc_login.py sites                -> 保存した鍵で、見えるプロパティの一覧をもう一度出す（登録のあと）

入口の情報（client_id / client_secret）は hatena/sc_client.enc に、はてな版の合言葉（ICHIGYO_HATENA_PASS）で鍵をかけてある。
受け取りページ（https://ichigyo.com/sc/）と Google 側の入口は WordPress 版と同じもの。
"""
import json
import os
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
REDIRECT = 'https://ichigyo.com/sc/'
SCOPE = 'https://www.googleapis.com/auth/webmasters.readonly'
OUT = Path('/tmp/hkit/gsc_user.json')
PASS_ENV = 'ICHIGYO_HATENA_PASS'


def client():
    if not os.environ.get(PASS_ENV):
        sys.exit(f'ERROR: {PASS_ENV} がありません')
    enc = HERE / 'sc_client.enc'
    if not enc.exists():
        sys.exit('ERROR: sc_client.enc がありません')
    raw = subprocess.run(['openssl', 'enc', '-d', '-aes-256-cbc', '-pbkdf2', '-iter', '200000',
                          '-in', str(enc), '-pass', 'env:' + PASS_ENV], capture_output=True)
    if raw.returncode:
        sys.exit('ERROR: sc_client.enc を開けません（合言葉ちがい）')
    return json.loads(raw.stdout)


def url():
    c = client()
    q = {'client_id': c['client_id'], 'redirect_uri': REDIRECT, 'response_type': 'code',
         'scope': SCOPE, 'access_type': 'offline', 'prompt': 'consent select_account'}
    print('https://accounts.google.com/o/oauth2/v2/auth?' + urllib.parse.urlencode(q))


def post_token(body):
    req = urllib.request.Request('https://oauth2.googleapis.com/token', data=urllib.parse.urlencode(body).encode())
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        msg = e.read().decode()[:200]
        sys.exit('ERROR: 換えられません（古い・使用済みの可能性。リンクから、もう一度）: '
                 + ('invalid_grant' if 'invalid_grant' in msg else msg))


def list_sites(access_token):
    req = urllib.request.Request('https://searchconsole.googleapis.com/webmasters/v3/sites',
                                 headers={'Authorization': 'Bearer ' + access_token})
    with urllib.request.urlopen(req, timeout=30) as r:
        sites = [s['siteUrl'] for s in json.loads(r.read()).get('siteEntry', [])]
    print('SITES ' + json.dumps(sites, ensure_ascii=False))


def exchange(text):
    t = text.strip().strip('「」"\' ')
    if 'code=' in t:  # アドレスごと貼られたとき
        t = urllib.parse.parse_qs(urllib.parse.urlparse(t).query).get('code', [''])[0]
    if t.startswith('ichigyo-sc:'):
        t = t[len('ichigyo-sc:'):]
    t = urllib.parse.unquote(t.strip())
    if not t:
        sys.exit('ERROR: 文が空です')
    c = client()
    tok = post_token({'code': t, 'client_id': c['client_id'], 'client_secret': c['client_secret'],
                      'redirect_uri': REDIRECT, 'grant_type': 'authorization_code'})
    if not tok.get('refresh_token'):
        sys.exit('ERROR: refresh_token が出ませんでした（リンクから、もう一度）')
    info = {'type': 'authorized_user', 'client_id': c['client_id'], 'client_secret': c['client_secret'],
            'refresh_token': tok['refresh_token']}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(info))
    os.chmod(OUT, 0o600)
    print('SC_LOGIN_OK')
    list_sites(tok['access_token'])


def sites():
    if not OUT.exists():
        sys.exit('ERROR: まだログインしていません（url から）')
    info = json.loads(OUT.read_text())
    tok = post_token({'client_id': info['client_id'], 'client_secret': info['client_secret'],
                      'refresh_token': info['refresh_token'], 'grant_type': 'refresh_token'})
    list_sites(tok['access_token'])


if __name__ == '__main__':
    a = sys.argv[1:]
    if a[:1] == ['url']:
        url()
    elif a[:1] == ['exchange'] and len(a) > 1:
        exchange(' '.join(a[1:]))
    elif a[:1] == ['sites']:
        sites()
    else:
        sys.exit(__doc__)
