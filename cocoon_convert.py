#!/usr/bin/env python3
"""ichigyo 本体が作った下書き（SWELL の飾り）を、Cocoon の飾りに置きかえる。
本体は SWELL 用の形でしか書かないので、Cocoon のブログでは 8-3 でこれを通す。

使い方:
  python3 cocoon_convert.py theme [ブログのアドレス]   # THEME swell / THEME cocoon / THEME other:<名前> / THEME unknown
  python3 cocoon_convert.py convert <本文HTML> [--box-attr style|boxStyle]
      -> ファイルをその場で書きかえ、CONVERTED <数> と LEFT <数> <残った種類> を出す
  python3 cocoon_convert.py check <本文HTML>          # 書きかえずに、残っている SWELL の飾りを数えるだけ

アドレスを省くと環境の設定 WP_SITE（無ければ WP_URL）を使う。鍵は使わない（公開ページを見るだけ）。
置きかえ方は「サイト自動リライト Cocoon版」付録G（G-2 FAQ・G-4 アイコンボックス・G-5 タイムライン・
G-6b ラベル付き囲み・G-10 マーカー・G-11 リスト）に合わせている。
同じファイルに2回かけても、2回目は何も変えない。
"""
import html as htmlmod
import json
import os
import re
import sys
import urllib.request

# ---------------------------------------------------------------- テーマを見分ける

def detect_theme(url):
    url = (url or os.environ.get("WP_SITE") or os.environ.get("WP_URL") or "").strip()
    if not url:
        return "unknown"
    if not url.startswith("http"):
        url = "https://" + url
    try:
        req = urllib.request.Request(url.rstrip("/") + "/", headers={"User-Agent": "Mozilla/5.0 (ichigyo theme check)"})
        page = urllib.request.urlopen(req, timeout=20).read(600_000).decode("utf-8", "replace")
    except Exception:
        return "unknown"
    slugs = re.findall(r"/wp-content/themes/([A-Za-z0-9_.\-]+)/", page)
    low = [s.lower() for s in slugs]
    if any(s.startswith("cocoon") for s in low) or "cocoon-block-" in page:
        return "cocoon"
    if any(s.startswith("swell") for s in low) or "swell-block-" in page:
        return "swell"
    if low:
        # 子テーマが先に出ることがあるので、いちばん多い名前
        top = max(set(low), key=low.count)
        return "other:" + top
    return "unknown"


# ---------------------------------------------------------------- ブロックの扱い

COMMENT = re.compile(r"<!--\s*(/?)wp:([a-z0-9\-]+(?:/[a-z0-9\-]+)?)(\s+(\{.*?\}))?\s*(/?)-->", re.S)


def _full(name):
    return name if "/" in name else "core/" + name


def find_innermost(text, name, pred=None):
    """name のブロックで、中に同じ名前のブロックを含まない最後のものを返す。
    (start, end, attrs, inner_start, inner_end) か None。pred(attrs, inner) が False のものは飛ばす。"""
    want = _full(name)
    tokens = [(m, _full(m.group(2))) for m in COMMENT.finditer(text)]
    opens = [i for i, (m, n) in enumerate(tokens) if n == want and not m.group(1) and not m.group(5)]
    for oi in reversed(opens):
        m = tokens[oi][0]
        depth = 0
        for m2, n2 in tokens[oi + 1:]:
            if n2 != want or m2.group(5):
                continue
            if not m2.group(1):
                depth += 1
                continue
            if depth:
                depth -= 1
                continue
            attrs = {}
            if m.group(4):
                try:
                    attrs = json.loads(m.group(4))
                except Exception:
                    attrs = {}
            inner = text[m.end():m2.start()]
            if pred is None or pred(attrs, inner):
                return m.start(), m2.end(), attrs, m.end(), m2.start()
            break
    return None


def replace_all(text, name, fn, pred=None):
    """fn(attrs, inner) -> 置きかえ後の文字列（None なら置きかえない）。innermost から順に。"""
    count, skip = 0, set()
    while True:
        def p2(a, i):
            return (pred is None or pred(a, i)) and (i not in skip)
        hit = find_innermost(text, name, p2)
        if not hit:
            return text, count
        s, e, attrs, a, b = hit
        new = fn(attrs, text[a:b])
        if new is None:
            skip.add(text[a:b])
            continue
        text = text[:s] + new + text[e:]
        count += 1


def jattr(d):
    return (" " + json.dumps(d, ensure_ascii=False, separators=(",", ":"))) if d else ""


def outer_div_inner(inner, cls_word):
    """inner の最初の <div class="... cls_word ..."> の中身（対応する </div> まで）を返す。"""
    m = re.search(r'<div\b[^>]*class="[^"]*\b' + re.escape(cls_word) + r'\b[^"]*"[^>]*>', inner)
    if not m:
        return None
    pos, depth = m.end(), 1
    for t in re.finditer(r"<div\b[^>]*>|</div>", inner[pos:]):
        depth += 1 if t.group(0) != "</div>" else -1
        if depth == 0:
            return inner[pos:pos + t.start()]
    return None


def ensure_blocks(inner):
    """ブロックの印が無い素の文章を段落ブロックにする。"""
    s = inner.strip()
    if not s:
        return ""
    if "<!-- wp:" in s:
        return s
    if not s.startswith("<"):
        s = "<p>" + s + "</p>"
    if re.fullmatch(r"<p\b[^>]*>.*</p>", s, re.S):
        return "<!-- wp:paragraph -->\n" + s + "\n<!-- /wp:paragraph -->"
    return "<!-- wp:html -->\n" + s + "\n<!-- /wp:html -->"


# ---------------------------------------------------------------- 囲み（アイコンボックス・ラベル付き囲み）

def icon_box(kind, inner, box_attr):
    style = {"alert": "alert-box", "memo": "memo-box"}.get(kind, "")
    cls = style or "information-box"
    attr = jattr({box_attr: style} if style else {})
    return (f"<!-- wp:cocoon-blocks/icon-box{attr} -->\n"
            f'<div class="wp-block-cocoon-blocks-icon-box common-icon-box block-box {cls}">{inner}</div>\n'
            "<!-- /wp:cocoon-blocks/icon-box -->")


def tab_box(label, inner):
    attr = jattr({"label": "bb-" + label} if label != "check" else {})
    return (f"<!-- wp:cocoon-blocks/tab-box-1{attr} -->\n"
            f'<div class="wp-block-cocoon-blocks-tab-box-1 blank-box bb-tab bb-{label} block-box">{inner}</div>\n'
            "<!-- /wp:cocoon-blocks/tab-box-1 -->")


BOX_KIND = {  # SWELL の big_icon_* / 囲み → Cocoon
    "point": ("tab", "point"), "check": ("tab", "check"), "good": ("tab", "check"),
    "memo": ("icon", "memo"), "caution": ("icon", "alert"), "alert": ("icon", "alert"),
    "batsu": ("icon", "alert"), "bad": ("icon", "alert"),
}


def make_box(kind, inner, box_attr):
    how, k = BOX_KIND.get(kind, ("icon", "info"))
    inner = ensure_blocks(inner)
    has_frame = re.search(r"<!-- wp:(table|image|cocoon-blocks/)", inner)
    if has_frame:  # 枠の中に枠を入れない（二重枠）。囲みは外して中身だけ残す
        return inner
    return tab_box(k, inner) if how == "tab" else icon_box(k, inner, box_attr)


def conv_group(box_attr):
    def pred(a, inner):
        return "is-style-big_icon_" in (a.get("className") or "")

    def fn(a, inner):
        kind = re.search(r"is-style-big_icon_([a-z_]+)", a.get("className", "")).group(1)
        body = outer_div_inner(inner, "wp-block-group")
        if body is None:
            return None
        inside = outer_div_inner(body, "wp-block-group__inner-container")
        return make_box(kind, inside if inside is not None else body, box_attr)
    return pred, fn


def conv_capblock(box_attr):
    def fn(a, inner):
        ttl = re.search(r'class="[^"]*cap_box_ttl[^"]*"[^>]*>(.*?)</div>', inner, re.S)
        content = outer_div_inner(inner, "cap_box_content")
        if content is None:
            return None
        head = ""
        if ttl:
            t = re.sub(r"<[^>]+>", "", ttl.group(1)).strip()
            if t:
                head = f"<!-- wp:paragraph -->\n<p><strong>{t}</strong></p>\n<!-- /wp:paragraph -->\n"
        style = (a.get("className") or "") + " " + (a.get("style") or "")
        kind = "caution" if re.search(r"caution|alert|onborder_ttl2", style) else "info"
        return make_box(kind, head + ensure_blocks(content), box_attr)
    return fn


# ---------------------------------------------------------------- ステップ → タイムライン

def conv_step(a, inner):
    items = re.findall(r"<!--\s*wp:loos/step-item(?:\s+\{.*?\})?\s*-->(.*?)<!--\s*/wp:loos/step-item\s*-->", inner, re.S)
    if not items:
        return None
    out = []
    for n, it in enumerate(items, 1):
        t = re.search(r'class="[^"]*swell-block-step__title[^"]*"[^>]*>(.*?)</div>', it, re.S)
        title = t.group(1).strip() if t else ""
        body = outer_div_inner(it, "swell-block-step__body") or ""
        out.append(f"<!-- wp:cocoon-blocks/timeline-item{jattr({'label': f'STEP{n}', 'title': title})} -->\n"
                   f'<li class="wp-block-cocoon-blocks-timeline-item timeline-item cf"><div class="timeline-item-label">STEP{n}</div>'
                   f'<div class="timeline-item-content cf"><div class="timeline-item-title">{title}</div>'
                   f'<div class="timeline-item-snippet">{ensure_blocks(body)}</div></div></li>\n'
                   "<!-- /wp:cocoon-blocks/timeline-item -->")
    head = jattr({"title": "", "items": len(items)})
    return (f"<!-- wp:cocoon-blocks/timeline{head} -->\n"
            '<div class="wp-block-cocoon-blocks-timeline timeline-box cf block-box not-nested-style cocoon-block-timeline">'
            '<div class="timeline-title"></div><ul class="timeline">' + "\n".join(out) + "</ul></div>\n"
            "<!-- /wp:cocoon-blocks/timeline -->")


# ---------------------------------------------------------------- FAQ → H3「Q:」と段落

def conv_faq(a, inner):
    items = re.findall(r"<dt\b[^>]*>(.*?)</dt>\s*<dd\b[^>]*>(.*?)</dd>", inner, re.S)
    if not items:
        return None
    out = []
    for q, ans in items:
        q = re.sub(r"^\s*(Q|Ｑ)\s*[.．:：]\s*", "", q.strip())
        out.append(f'<!-- wp:heading {{"level":3}} -->\n<h3 class="wp-block-heading">Q: {q}</h3>\n<!-- /wp:heading -->')
        body = ensure_blocks(ans)
        body = re.sub(r"(<!-- wp:paragraph[^>]*-->\s*<p\b[^>]*>)(?!\s*A\s*[:：])", r"\1A: ", body, count=1)
        out.append(body)
    return "\n".join(out)


# ---------------------------------------------------------------- リスト・表・文字の飾り

SWELL_CLASS = re.compile(r"^(is-style-(check_list|num_circle|good_list|bad_list|triangle_list|note_list|index|double|big_icon_\w+)|"
                         r"is-all-centered|is-thead-centered|is-first-col-centered|swl-[\w-]+|u-[\w-]+|has-swl-[\w-]+)$")


def clean_classes(cls):
    keep = [c for c in cls.split() if not SWELL_CLASS.match(c)]
    return " ".join(keep)


def clean_block_comments(text):
    """wp:list / wp:table / wp:heading などの印から SWELL 専用の設定を外し、要素の class も合わせる。"""
    n = 0

    def fix_comment(m):
        nonlocal n
        close, name, attrs = m.group(1), m.group(2), m.group(4)
        if close or not attrs or name.startswith(("loos/", "cocoon-blocks/")):
            return m.group(0)
        try:
            d = json.loads(attrs)
        except Exception:
            return m.group(0)
        before = dict(d)
        md = d.get("metadata")
        if isinstance(md, dict) and "swell" in json.dumps(md):
            md = {k: v for k, v in md.items() if k not in ("categories", "patternName")}
            if md:
                d["metadata"] = md
            else:
                d.pop("metadata")
        for k in list(d):
            if k.startswith("swl"):
                d.pop(k)
        if "className" in d:
            c = clean_classes(d["className"])
            if c:
                d["className"] = c
            else:
                d.pop("className")
        if d == before:
            return m.group(0)
        n += 1
        return f"<!-- wp:{name}{jattr(d)} {m.group(5)}-->"

    text = COMMENT.sub(fix_comment, text)

    def fix_class(m):
        nonlocal n
        c = clean_classes(m.group(2))
        if c == m.group(2):
            return m.group(0)
        n += 1
        return f'{m.group(1)}class="{c}"' if c else m.group(1).rstrip()

    text = re.sub(r'(<(?:ul|ol|figure|table|div|p|h[1-6])\b[^>]*?\s)class="([^"]*)"', fix_class, text)
    return text, n


ICON_TEXT = {"check": "○", "circle": "○", "double-circle": "◎", "triangle": "△", "close": "×", "batsu": "×", "line": "－"}


def clean_inline(text):
    n = 0

    def cell_bg(m):
        nonlocal n
        n += 1
        icon = re.search(r'data-icon="([\w-]+)"', m.group(0))
        return ICON_TEXT.get(icon.group(1), "") if icon else ""

    text = re.sub(r'<span\b[^>]*class="swl-cell-bg"[^>]*>(?:&nbsp;|\s)*</span>', cell_bg, text)

    def inline_list(m):
        nonlocal n
        n += 1
        icon = re.search(r'data-icon="([\w-]+)"', m.group(1))
        mark = ICON_TEXT.get(icon.group(1), "・") if icon else "・"
        return f"{mark} {m.group(2)}"

    text = re.sub(r'<span\b([^>]*)class="swl-inline-list"[^>]*>(.*?)</span>', inline_list, text, flags=re.S)

    def marker(m):
        nonlocal n
        n += 1
        color = m.group(1)
        cls = {"yellow": "marker-under", "red": "marker-under-red", "orange": "marker-under-red", "blue": "marker-under-blue",
               "green": "marker-under"}.get(color, "marker-under")
        return f'<span class="{cls}">'

    text = re.sub(r'<span class="swl-marker mark_(\w+)">', marker, text)

    def textcolor(m):
        nonlocal n
        n += 1
        return f'<span class="{m.group(1)}">'

    text = re.sub(r'<span class="sbd-text-(red|blue|green)">', textcolor, text)
    return text, n


# ---------------------------------------------------------------- 全体

LEFT_PAT = re.compile(r"wp:loos/[a-z0-9\-]+|swell-block-[a-z\-]+|\bswl-[a-z\-]+|is-style-big_icon_\w+|\bcap_box\w*|sbd-text-\w+")


def leftovers(text):
    found = LEFT_PAT.findall(text)
    kinds = sorted(set(found))
    return len(found), kinds


def balance(text):
    opens, closes = {}, {}
    for m in COMMENT.finditer(text):
        if m.group(5):
            continue
        d = closes if m.group(1) else opens
        n = _full(m.group(2))
        d[n] = d.get(n, 0) + 1
    return {k for k in set(opens) | set(closes) if opens.get(k, 0) != closes.get(k, 0)}


def convert(text, box_attr="boxStyle"):
    total = 0
    pred, fn = conv_group(box_attr)
    text, c = replace_all(text, "group", fn, pred); total += c
    text, c = replace_all(text, "loos/cap-block", conv_capblock(box_attr)); total += c
    text, c = replace_all(text, "loos/step", conv_step); total += c
    text, c = replace_all(text, "loos/faq", conv_faq); total += c
    # 上で扱っていない SWELL のブロック（ふきだし など）は、印を外して中身だけ残す（編集画面で「未対応のブロック」にしない）
    for _ in range(50):
        m = re.search(r"<!--\s*wp:(loos/[a-z0-9\-]+)", text)
        if not m:
            break
        name = m.group(1)
        if re.search(r"<!--\s*wp:" + re.escape(name) + r"(\s+\{.*?\})?\s*/-->", text):  # 中身の無い印（自動で出す型）はそのまま残して LEFT で知らせる
            break
        text, c = replace_all(text, name, lambda a, inner: ensure_blocks(inner)); total += c
        if not c:
            break
    text, c = clean_block_comments(text); total += c
    text, c = clean_inline(text); total += c
    return text, total


def main(argv):
    if len(argv) < 2 or argv[1] not in ("theme", "convert", "check"):
        print(__doc__)
        return 2
    if argv[1] == "theme":
        print("THEME", detect_theme(argv[2] if len(argv) > 2 else ""))
        return 0
    path = argv[2]
    box_attr = "boxStyle"
    if "--box-attr" in argv:
        box_attr = argv[argv.index("--box-attr") + 1]
    src = open(path, encoding="utf-8").read()
    if argv[1] == "check":
        n, kinds = leftovers(src)
        print("LEFT", n, " ".join(kinds))
        return 0
    before_bad = balance(src)
    out, total = convert(src, box_attr)
    bad = balance(out) - before_bad
    if bad:
        print("BROKEN", " ".join(sorted(bad)), "(ファイルは書きかえていない)")
        return 1
    if out != src:
        open(path, "w", encoding="utf-8").write(out)
    n, kinds = leftovers(out)
    print("CONVERTED", total)
    print("LEFT", n, " ".join(kinds))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
