#!/usr/bin/env python3
"""ichigyo はてなブログ版の記録（設定・キーワード在庫・投稿の記録）を、お客さんのはてなブログの
「下書き」1本にしまう／取り出す。GitHub の置き場所を使わないための道具。

使い方:
  python3 hatena_state.py pull <作業フォルダ>   # はてな → フォルダ（無ければ NO_STATE）
  python3 hatena_state.py push <作業フォルダ>   # フォルダ → はてな（STATE_SAVED <sha>）
  python3 hatena_state.py check                 # 読み書きできるかだけ確かめる（STATE_OK）

鍵は環境の設定から読む: HATENA_ID, HATENA_BLOG_ID, HATENA_API_KEY。鍵の値は表示しない。
しまう前に、鍵の値が記録に混じっていないか確かめる。
記録の下書きは公開しない（タイトルにそう書く）。公開されていたら、次の push で下書きに戻す。
"""
import base64, hashlib, html, io, os, re, sys, tarfile, urllib.error, urllib.request
import xml.etree.ElementTree as ET

TITLE = "ichigyo の記録（公開しないでください・消さないでください）"
HEAD = "ICHIGYO_HATENA_STATE_V1"
KEEP_EXT = (".md", ".csv", ".json", ".txt")
SKIP_DIRS = {"hatena_auto", "generated", "_dryrun", ".git", "__pycache__"}  # hatena_auto はキットの写し（毎回置き直す）
SKIP_PATHS = {"ichigyo/SETUP_HATENA.md"}
MAX_FILE = 300_000
MAX_TOTAL = 1_500_000
MAX_PAGES = 60
SECRET_VARS = ("HATENA_API_KEY", "MUSE_API_KEY", "ICHIGYO_HATENA_PASS", "RAKKO_API_KEY", "GSC_SA_JSON")
NS = {"a": "http://www.w3.org/2005/Atom", "app": "http://www.w3.org/2007/app"}


def die(msg):
    print(msg)
    sys.exit(1)


def env():
    need = [v for v in ("HATENA_ID", "HATENA_BLOG_ID", "HATENA_API_KEY") if not os.environ.get(v, "").strip()]
    if need:
        die("ENV_MISSING " + ",".join(need))
    return (os.environ["HATENA_ID"].strip(), os.environ["HATENA_BLOG_ID"].strip(),
            os.environ["HATENA_API_KEY"].strip())


def root():
    hid, blog, _ = env()
    return f"https://blog.hatena.ne.jp/{hid}/{blog}/atom"


def call(method, url, body=None):
    hid, _, key = env()
    req = urllib.request.Request(url, data=body.encode("utf-8") if body else None, method=method, headers={
        "Authorization": "Basic " + base64.b64encode(f"{hid}:{key}".encode()).decode(),
        "Content-Type": "application/atom+xml; charset=utf-8", "User-Agent": "ichigyo-hatena-state/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        die(f"HATENA_HTTP {e.code} {method}")
    except urllib.error.URLError as e:
        die(f"HATENA_NET {getattr(e, 'reason', e)}")


def entry_xml(title, content):
    return ('<?xml version="1.0" encoding="utf-8"?>\n'
            '<entry xmlns="http://www.w3.org/2005/Atom" xmlns:app="http://www.w3.org/2007/app">\n'
            f'  <title>{html.escape(title)}</title>\n'
            f'  <content type="text/plain">{html.escape(content)}</content>\n'
            '  <app:control><app:draft>yes</app:draft></app:control>\n'
            '</entry>')


def parse_entry(e):
    edit = e.find("a:link[@rel='edit']", NS)
    c = e.find("a:content", NS)
    d = e.find("app:control/app:draft", NS)
    return {"title": (e.findtext("a:title", "", NS) or "").strip(),
            "type": c.get("type", "") if c is not None else "",
            "edit": edit.get("href") if edit is not None else "",
            "content": c.text if c is not None and c.text else "",
            "draft": (d.text or "").strip() if d is not None else ""}


def find_entries():
    """記録の下書き（同じタイトル）を全部返す。新しい順"""
    url, out = root() + "/entry", []
    for _ in range(MAX_PAGES):
        doc = ET.fromstring(call("GET", url))
        for e in doc.findall("a:entry", NS):
            x = parse_entry(e)
            if x["title"] == TITLE:
                out.append(x)
        nxt = doc.find("a:link[@rel='next']", NS)
        if nxt is None:
            break
        url = nxt.get("href")
    return out


def pack(work):
    buf, total = io.BytesIO(), 0
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for r, dirs, files in os.walk(work):
            dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS)
            for f in sorted(files):
                p = os.path.join(r, f)
                rel = os.path.relpath(p, work).replace(os.sep, "/")
                if rel in SKIP_PATHS or not f.endswith(KEEP_EXT) or os.path.getsize(p) > MAX_FILE:
                    continue
                total += os.path.getsize(p)
                if total > MAX_TOTAL:
                    die("STATE_TOO_BIG")
                tar.add(p, arcname=rel)
    blob = buf.getvalue()
    with tarfile.open(fileobj=io.BytesIO(blob)) as tar:
        text = b"".join(tar.extractfile(m).read() for m in tar.getmembers() if m.isfile())
    for v in SECRET_VARS:
        val = os.environ.get(v, "").strip()
        if len(val) >= 8 and val.encode() in text:
            die(f"FAIL secret_in_state {v}")
    if b"PRIVATE KEY-----" in text or b'"private_key"' in text:
        die("FAIL secret_in_state GSC_SA_JSON")
    return blob


def decode(content):
    m = re.search(HEAD + r" sha=([0-9a-f]{16})\s+([A-Za-z0-9+/=\s]+?)\s*(?:END|$)", content)
    if not m:
        return None, None
    blob = base64.b64decode("".join(m.group(2).split()))
    if hashlib.sha256(blob).hexdigest()[:16] != m.group(1):
        return None, None
    return m.group(1), blob


def push(work):
    blob = pack(work)
    sha = hashlib.sha256(blob).hexdigest()[:16]
    b64 = base64.b64encode(blob).decode()
    body = ("このページは ichigyo の設定と記録の保管用です。公開しないでください。消さないでください。\n\n"
            f"{HEAD} sha={sha}\n" + "\n".join(b64[i:i + 76] for i in range(0, len(b64), 76)) + "\nEND\n")
    old = find_entries()
    res = ET.fromstring(call("POST", root() + "/entry", entry_xml(TITLE, body)))
    new = parse_entry(res)
    back = parse_entry(ET.fromstring(call("GET", new["edit"])))
    got, _ = decode(back["content"])
    if got != sha:
        call("DELETE", new["edit"])
        die("FAIL state_not_saved")
    for o in old:
        call("DELETE", o["edit"])
    print(f"STATE_SAVED {sha} kb={len(body)//1024} draft={back['draft']} syntax={back['type']}")


def pull(work):
    ents = find_entries()
    if not ents:
        print("NO_STATE")
        return
    for e in ents:
        sha, blob = decode(e["content"])
        if not blob:
            continue
        os.makedirs(work, exist_ok=True)
        with tarfile.open(fileobj=io.BytesIO(blob)) as tar:
            for m in tar.getmembers():
                if not m.isfile() or m.name.startswith(("/", "..")) or "/../" in m.name:
                    continue
                if hasattr(tarfile, "data_filter"):
                    tar.extract(m, work, filter="data")
                else:
                    tar.extract(m, work)
        warn = " WARN_PUBLISHED" if e["draft"] == "no" else ""
        print(f"STATE_LOADED {sha}{warn}")
        return
    die("FAIL state_broken")


def check():
    call("GET", root() + "/entry")
    print("STATE_OK")


if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] not in ("pull", "push", "check"):
        die(__doc__)
    if sys.argv[1] == "check":
        check()
    elif len(sys.argv) < 3:
        die(__doc__)
    elif sys.argv[1] == "pull":
        pull(sys.argv[2])
    else:
        push(sys.argv[2])
