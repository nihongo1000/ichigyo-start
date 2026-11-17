#!/usr/bin/env python3
"""ichigyo note 版の記録（設定・キーワード在庫・投稿の記録）を、お客さんの note の「下書き」1本にしまう／取り出す。
GitHub の置き場所を使わないための道具。note とのやりとりはキットの note_auto/scripts/note_api.py を使う。

使い方:
  python3 note_state.py pull <作業フォルダ>   # note → フォルダ（無ければ NO_STATE）
  python3 note_state.py push <作業フォルダ>   # フォルダ → note（STATE_SAVED <sha> …）
  python3 note_state.py check <作業フォルダ>  # ログインできるかだけ確かめる（STATE_OK）

ログイン情報は環境の設定から読む: NOTE_SESSION, NOTE_URLNAME。値は表示しない。
記録の下書きの場所は環境の設定 NOTE_STATE_ID（"<id>:<key>"。鍵ではない）。まだ無いときは push が新しく作り、
`STATE_NEW_ID <id>:<key>` を表示する（担当の Claude が環境の設定に足す）。同じセッションの中では /tmp に覚えておく。
しまう前に、鍵・ログイン情報の値が記録に混じっていないか確かめる。
"""
import base64, hashlib, io, os, re, sys, tarfile

TITLE = "ichigyo の記録（公開しないでください・消さないでください）"
HEAD = "ICHIGYO_NOTE_STATE_V1"
KEEP_EXT = (".md", ".csv", ".json", ".txt")
SKIP_DIRS = {"note_auto", "generated", ".git", "__pycache__"}  # note_auto はキットの写し（毎回置き直す）
SKIP_PATHS = {"ichigyo/SETUP_NOTE.md"}
MAX_FILE = 200_000
MAX_TOTAL = 600_000
SECRET_VARS = ("NOTE_SESSION", "MUSE_API_KEY", "ICHIGYO_NOTE_PASS", "RAKKO_API_KEY")
CACHE = "/tmp/ichigyo_note_state_id"


def die(msg):
    print(msg)
    sys.exit(1)


def api(work):
    sys.path.insert(0, os.path.join(work, "note_auto", "scripts"))
    try:
        import note_api
    except ImportError:
        die("FAIL kit_missing（先に R章の 2 で作業フォルダを作る）")
    return note_api


def state_id():
    v = os.environ.get("NOTE_STATE_ID", "").strip()
    if not v and os.path.exists(CACHE):
        v = open(CACHE).read().strip()
    if ":" not in v:
        return None, None
    i, k = v.split(":", 1)
    return i.strip(), k.strip()


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
    return blob


def to_html(blob):
    sha = hashlib.sha256(blob).hexdigest()[:16]
    b64 = base64.b64encode(blob).decode()
    lines = ["このページは ichigyo の設定と記録の保管用です。公開しないでください。消さないでください。",
             f"{HEAD} sha={sha}"] + [b64[i:i + 76] for i in range(0, len(b64), 76)] + ["END"]
    return sha, "".join(f"<p>{x}</p>" for x in lines)


def decode(body):
    text = re.sub(r"<[^>]+>", "\n", body)
    m = re.search(HEAD + r" sha=([0-9a-f]{16})\s+([A-Za-z0-9+/=\s]+?)\s*(?:END|$)", text)
    if not m:
        return None, None
    try:
        blob = base64.b64decode("".join(m.group(2).split()))
    except Exception:
        return None, None
    if hashlib.sha256(blob).hexdigest()[:16] != m.group(1):
        return None, None
    return m.group(1), blob


def pull(work):
    i, k = state_id()
    if not i:
        print("NO_STATE")
        return
    na = api(work)
    n = na.Note()
    d = n.read_draft(k, i)
    if d is None:
        die("FAIL state_unreadable")
    if d.get("gone"):
        print("NO_STATE STATE_GONE（記録の下書きが見つかりません。次の push で作り直します）")
        if os.path.exists(CACHE):
            os.remove(CACHE)
        return
    sha, blob = decode(d["body"])
    if not blob:
        die("FAIL state_broken")
    with tarfile.open(fileobj=io.BytesIO(blob)) as tar:
        for m in tar.getmembers():
            if not m.isfile() or m.name.startswith(("/", "..")) or "/../" in m.name:
                continue
            if hasattr(tarfile, "data_filter"):
                tar.extract(m, work, filter="data")
            else:
                tar.extract(m, work)
    warn = " WARN_PUBLISHED" if d.get("status") == "published" else ""
    if warn:
        open(CACHE + ".published", "w").write("1")
    print(f"STATE_LOADED {sha}{warn}")


def push(work):
    blob = pack(work)
    sha, body = to_html(blob)
    na = api(work)
    n = na.Note()
    n.check()
    i, k = state_id()
    new = False
    if not i or os.path.exists(CACHE + ".published"):
        i, k = n.create()
        new = True
        if os.path.exists(CACHE + ".published"):
            os.remove(CACHE + ".published")
    n.draft_save(i, TITLE, body, [])
    d = n.read_draft(k, i)
    got = decode(d["body"])[0] if d and not d.get("gone") else None
    if got != sha:
        die("FAIL state_not_saved")
    with open(CACHE, "w") as f:
        f.write(f"{i}:{k}")
    print(f"STATE_SAVED {sha} kb={len(body) // 1024} status={d.get('status') or '?'}")
    if new:
        print(f"STATE_NEW_ID {i}:{k}")


def check(work):
    na = api(work)
    na.Note().check()
    print("STATE_OK")


if __name__ == "__main__":
    if len(sys.argv) < 3 or sys.argv[1] not in ("pull", "push", "check"):
        die(__doc__)
    {"pull": pull, "push": push, "check": check}[sys.argv[1]](sys.argv[2])
