"""サーチコンソールを「Google でログイン」型でつなぐための道具（SETUP_SC.md から使う）。

使い方（鍵や中身は表示しない）:
  python3 -I sc_login.py url                  -> お客さんに押してもらうリンクを出す
  python3 -I sc_login.py exchange '<貼られた文>' -> 貼られた文（ichigyo-sc:... ）を鍵に換え、
                                                 /tmp/kit/gsc_user.json に保存し、見えるプロパティの一覧を出す
  python3 -I sc_login.py patch <$W>           -> 作業フォルダの gsc_fetch.py を、この鍵でも動くようにする（毎回 R章で）

入口の情報（client_id / client_secret）は sc_client.enc に合言葉（ICHIGYO_PASS）で鍵をかけてある。
"""
import json
import os
import subprocess
import sys
import urllib.parse
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
REDIRECT = 'https://nihongo1000.wpx.jp/ichigyo-sc/'
SCOPE = 'https://www.googleapis.com/auth/webmasters.readonly'
OUT = Path('/tmp/kit/gsc_user.json')


def client():
    if not os.environ.get('ICHIGYO_PASS'):
        sys.exit('ERROR: ICHIGYO_PASS がありません')
    enc = HERE / 'sc_client.enc'
    if not enc.exists():
        sys.exit('ERROR: sc_client.enc がありません')
    raw = subprocess.run(['openssl', 'enc', '-d', '-aes-256-cbc', '-pbkdf2', '-iter', '200000',
                          '-in', str(enc), '-pass', 'env:ICHIGYO_PASS'], capture_output=True)
    if raw.returncode:
        sys.exit('ERROR: sc_client.enc を開けません（合言葉ちがい）')
    return json.loads(raw.stdout)


def url():
    c = client()
    q = {'client_id': c['client_id'], 'redirect_uri': REDIRECT, 'response_type': 'code',
         'scope': SCOPE, 'access_type': 'offline', 'prompt': 'consent select_account'}
    print('https://accounts.google.com/o/oauth2/v2/auth?' + urllib.parse.urlencode(q))


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
    body = urllib.parse.urlencode({'code': t, 'client_id': c['client_id'], 'client_secret': c['client_secret'],
                                   'redirect_uri': REDIRECT, 'grant_type': 'authorization_code'}).encode()
    try:
        with urllib.request.urlopen(urllib.request.Request('https://oauth2.googleapis.com/token', data=body), timeout=30) as r:
            tok = json.loads(r.read())
    except urllib.error.HTTPError as e:
        msg = e.read().decode()[:200]
        sys.exit('ERROR: 換えられません（古い・使用済みの可能性。リンクから、もう一度）: ' + ('invalid_grant' if 'invalid_grant' in msg else msg))
    if not tok.get('refresh_token'):
        sys.exit('ERROR: refresh_token が出ませんでした（リンクから、もう一度）')
    info = {'type': 'authorized_user', 'client_id': c['client_id'], 'client_secret': c['client_secret'],
            'refresh_token': tok['refresh_token']}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(info))
    os.chmod(OUT, 0o600)
    req = urllib.request.Request('https://searchconsole.googleapis.com/webmasters/v3/sites',
                                 headers={'Authorization': 'Bearer ' + tok['access_token']})
    with urllib.request.urlopen(req, timeout=30) as r:
        sites = [s['siteUrl'] for s in json.loads(r.read()).get('siteEntry', [])]
    print('SC_LOGIN_OK')
    print('SITES ' + json.dumps(sites, ensure_ascii=False))


OLD = "    cred = service_account.Credentials.from_service_account_info(json.loads(raw), scopes=[SCOPE])\n"
NEW = ("    _info = json.loads(raw)\n"
       "    if _info.get('type') == 'authorized_user':\n"
       "        from google.oauth2.credentials import Credentials as _UC\n"
       "        cred = _UC.from_authorized_user_info(_info, [SCOPE])\n"
       "    else:\n"
       "        cred = service_account.Credentials.from_service_account_info(_info, scopes=[SCOPE])\n")


def patch(w):
    f = Path(w) / 'wp_auto' / 'scripts' / 'gsc_fetch.py'
    s = f.read_text(encoding='utf-8')
    if "authorized_user" in s:
        print('PATCH_ALREADY')
        return
    if OLD not in s:
        sys.exit('ERROR: gsc_fetch.py の形が想定とちがいます')
    f.write_text(s.replace(OLD, NEW), encoding='utf-8')
    print('PATCH_OK')


if __name__ == '__main__':
    a = sys.argv[1:]
    if a[:1] == ['url']:
        url()
    elif a[:1] == ['exchange'] and len(a) > 1:
        exchange(' '.join(a[1:]))
    elif a[:1] == ['patch'] and len(a) > 1:
        patch(a[1])
    else:
        sys.exit(__doc__)
