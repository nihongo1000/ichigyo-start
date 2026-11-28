#!/usr/bin/env python3
"""通常記事の品質検査と、検査したブロックHTMLの下書き保存。"""
import argparse
from collections import Counter
from contextlib import redirect_stdout
from html import unescape
from html.parser import HTMLParser
import io
import os
from pathlib import Path
import re
import subprocess
import sys
from urllib.parse import unquote, urlsplit


class Article(HTMLParser):
    def __init__(self, body):
        super().__init__()
        self.text = []
        self.links = []
        self.feed(body)

    def handle_data(self, data):
        self.text.append(data)

    def handle_starttag(self, tag, attrs):
        if tag == 'a':
            href = dict(attrs).get('href')
            if href:
                self.links.append(href)


HEAD = re.compile(r'<h([23])\b[^>]*>(.*?)</h\1>\s*<!--\s*/wp:heading\s*-->', re.S)
IMAGE = re.compile(r'<!--\s*wp:image\b[^\n]*?-->.*?<!--\s*/wp:image\s*-->', re.S)
LIST = re.compile(r'<!--\s*wp:list(?=\s|-->)[^>]*-->')
SKIP = ('まとめ', 'おわりに', 'さいごに', '最後に', 'よくある質問', 'FAQ', 'Q&A')


def check_layout(body):
    headings = list(HEAD.finditer(body))
    heading_images = {}
    expected_h3 = Counter()
    real_h3 = Counter()
    expected_h2 = []
    real_h2 = []
    parent_is_end = False
    h3_lists = 0
    for index, heading in enumerate(headings):
        end = headings[index + 1].start() if index + 1 < len(headings) else len(body)
        section = body[heading.end():end]
        label = unescape(re.sub(r'<[^>]+>', '', heading[2])).strip()
        if heading[1] == '2':
            parent_is_end = any(word in label for word in SKIP)
            if not parent_is_end and len(expected_h2) < 3:
                expected_h2.append(index)
        elif not parent_is_end:
            lists = min(len(LIST.findall(section)), 3 - h3_lists)
            if lists:
                expected_h3[index] = lists
                h3_lists += lists
        prefix = section.lstrip()
        for image in IMAGE.finditer(section):
            src = re.search(r'\bsrc="([^"]+)"', image[0])
            name = Path(unquote(urlsplit(unescape(src[1])).path)).name if src else ''
            if name.startswith(('h2_', 'h3_illust_')):
                if parent_is_end or not prefix.startswith(image[0]):
                    raise SystemExit('画像の位置が見出し直下の規則と一致しません。')
                prefix = prefix[len(image[0]):].lstrip()
                heading_images[image[0]] = heading_images.get(image[0], 0) + 1
                if name.startswith('h2_') and heading[1] == '2':
                    real_h2.append(index)
                elif name.startswith('h3_illust_') and heading[1] == '3':
                    real_h3[index] += 1
                else:
                    raise SystemExit('写真・図解と見出しの階層が一致しません。')
    if not expected_h2 or expected_h2 != real_h2 or expected_h3 != real_h3:
        raise SystemExit('H2写真またはH3図解の枚数・配置を確認してください。')
    if Counter(m[0] for m in IMAGE.finditer(body)) != Counter(heading_images):
        raise SystemExit('見出し直下の写真・図解以外の本文画像があります。')


def run_check(scripts, name, *args, directory):
    result = subprocess.run(
        [sys.executable, str(scripts / name), *map(str, args)], cwd=directory,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, check=False,
    )
    print(result.stdout, end='')
    if result.returncode:
        raise SystemExit(f'{name} が合格条件に達していません。')
    return result.stdout


def score_independently(scripts, args, title, reports):
    sys.path.insert(0, str(scripts))
    import strict_score

    original = strict_score.run_ai

    def request(task, command, *, input, **kwargs):
        instruction = (
            '甘くつけない。満点は例外的。くり返しは文末だけでなく、'
            '同じ動詞・同じ言い回し・同じ助言や結論も数える。'
        )
        return original(task, command, input=input + '\n\n' + instruction + '\n\n' + reports, **kwargs)

    strict_score.run_ai = request
    argv = sys.argv
    sys.argv = [argv[0], str(args.article), '--keyword', args.keyword, '--title', title,
                '--type', args.article_type, '--label', args.article_type, '--facts', str(args.facts)]
    if args.reader:
        sys.argv.extend(['--reader', args.reader])
    output = io.StringIO()
    try:
        with redirect_stdout(output):
            strict_score.main()
    finally:
        sys.argv = argv
        strict_score.run_ai = original
    text = output.getvalue()
    print(text, end='')
    score = re.search(r'^STRICT_SCORE (\d+)$', text, re.M)
    repetition = re.search(r'^[-・]\s*同じ形のくり返しが無い\s*[:：]\s*(\d{1,2})\s*/\s*15\b', text, re.M)
    if not score or not repetition or int(score[1]) < 80 or not 11 <= int(repetition[1]) <= 15:
        raise SystemExit('独立採点が80点以上、くり返しが11/15以上である必要があります。')


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('scripts', type=Path)
    p.add_argument('article', type=Path, help='先頭コメントにタイトルを含む最終ブロックHTML')
    p.add_argument('--keyword', required=True)
    p.add_argument('--type', dest='article_type', required=True)
    p.add_argument('--facts', type=Path, required=True)
    p.add_argument('--reader')
    p.add_argument('--research-log', type=Path, required=True)
    p.add_argument('--save', action='store_true', help='検査済み本文をWordPressに下書き保存する')
    p.add_argument('--featured-media', type=int)
    args = p.parse_args()
    if os.environ.get('ICHIGYO_AI') != 'gpt':
        p.error('ICHIGYO_AI=gpt が必要です。')
    scripts = args.scripts.resolve()
    for attr in ('article', 'facts', 'research_log'):
        setattr(args, attr, getattr(args, attr).resolve())
    original = args.article.read_text(encoding='utf-8')
    header = re.match(r'\s*<!--\s*([^\n<>]+?)\s*-->\s*', original)
    if not header or header[1].startswith('wp:'):
        p.error('先頭コメントにタイトルを入れてください。')
    title, body = header[1], original[header.end():]
    if '<!-- wp:' not in body:
        raise SystemExit('本文はWordPressのブロックHTMLで渡してください。')
    article = Article(body)
    size = len(re.sub(r'\s', '', ''.join(article.text)))
    if not 7600 <= size <= 8800:
        raise SystemExit(f'本文 {size}字。通常記事は8,000字前後（7,600〜8,800字）に整えてください。')
    host = urlsplit(os.environ.get('WP_SITE', '')).hostname
    for href in article.links:
        url = urlsplit(href.strip())
        if (url.hostname and url.hostname != host) or (url.scheme and url.scheme not in ('http', 'https')):
            raise SystemExit('本文に外部リンクがあります。')
    if re.search(r'参考リンク|(?:料金|数値)の出典', ''.join(article.text)):
        raise SystemExit('本文に出典欄があります。根拠は記事外の事実メモへ移してください。')
    if not args.facts.is_file() or not re.search(r'^- .+｜.+｜\s*https?://\S+', args.facts.read_text(encoding='utf-8'), re.M):
        raise SystemExit('出典URLを含む事実メモが必要です。')
    check_layout(body)
    directory = args.article.parent
    research = run_check(scripts, 'research_check.py', args.research_log, directory=directory)
    if not research.rstrip().endswith('RESEARCH_OK'):
        raise SystemExit('調査ログを確認してください。')
    style = run_check(scripts, 'style_check.py', args.article, directory=directory)
    if not re.search(r'^結果: FAIL 0件\b', style, re.M):
        raise SystemExit('文体検査のFAILを修正してください。')
    content = run_check(scripts, 'content_check.py', args.article, '--type', args.article_type,
                        '--keyword', args.keyword, directory=directory)
    machine = run_check(scripts, 'score_article.py', args.article, '--keyword', args.keyword,
                        '--images', 'h2', '--min-chars', 7600, directory=directory)
    if '同じ文末が' in machine:
        raise SystemExit('文末が続く箇所を自然な完結文に言い直してください。')
    reports = '\n\n'.join((style, content, machine, '==== 出典URL付き事実メモ ====\n' + args.facts.read_text(encoding='utf-8')))
    score_independently(scripts, args, title, reports)
    if args.save:
        if not args.featured_media or args.featured_media < 1:
            p.error('下書き保存には --featured-media が必要です。')
        if 'dryrun://' in body or '<!-- wp:' not in body:
            raise SystemExit('本体の画像を登録して最終ブロックHTMLに反映してください。')
        if args.article.read_text(encoding='utf-8') != original:
            raise SystemExit('検査中に本文ファイルが変更されました。')
        if not host or urlsplit(os.environ.get('WP_SITE', '')).scheme != 'https':
            raise SystemExit('WP_SITE に HTTPS の接続先が必要です。')
        import wp_post
        wp = wp_post.WP()
        wp.req('GET', f'/media/{args.featured_media}', query={'_fields': 'id'})
        candidates = wp.all('/posts', {'search': title, 'context': 'edit',
                                       'status': 'draft,pending,private,future,publish', '_fields': 'id,status,title'})
        if any(item['title']['raw'] == title for item in candidates):
            raise SystemExit('同じタイトルの投稿があります。二重保存を避けるため、その投稿を確認してください。')
        post = wp.req('POST', '/posts', data={
            'title': title, 'content': body, 'featured_media': args.featured_media, 'status': 'draft',
        })
        saved = wp.req('GET', f'/posts/{post["id"]}', query={'context': 'edit', '_fields': 'id,status,content,featured_media'})
        if (saved['status'] != 'draft' or saved['featured_media'] != args.featured_media
                or saved['content']['raw'].strip() != body.strip()):
            raise SystemExit(f'下書き #{saved["id"]} の保存結果を確認してください。')
        print(f'DRAFT_OK {saved["id"]}')
    else:
        print(f'ARTICLE_CHECK_OK chars={size}')


if __name__ == '__main__':
    main()
