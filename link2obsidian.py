#!/usr/bin/env python3
"""
link2obsidian - Convert web page links to Obsidian Markdown files.

Features:
- Fetch and clean web page content
- Auto-download images to local Clippings/images/ directory
- Support WeChat public account articles (two page structures)
- Generate Markdown with YAML frontmatter (title, source, date, tags)
- Display-mode (--display or -d): output to stdout instead of saving to file

Usage:
    python3 link2obsidian.py <URL> [--dir <obsidian_vault>] [--display]
    OBSIDIAN_VAULT=/path/to/vault python3 link2obsidian.py <URL>
"""

import os
import sys
import re
import hashlib
import json
import subprocess
import argparse
from datetime import datetime


def jsdecode(val):
    """Simulate WeChat's JsDecode function for decoding escape sequences."""
    if not val:
        return val
    val = val.replace('\\x5c', '\\\\')
    val = val.replace('\\x0d', '\\r')
    val = val.replace('\\x22', '"')
    val = val.replace('\\x26', '&')
    val = val.replace("\\x27", "'")
    val = val.replace('\\x3c', '<')
    val = val.replace('\\x3e', '>')
    val = val.replace('\\x0a', '\n')
    return val


def fetch_page(url):
    """Fetch page content using curl with appropriate User-Agent."""
    # Try with WeChat UA first (for WeChat articles)
    result = subprocess.run([
        'curl', '-s', '-L',
        '-H', 'User-Agent: Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 '
              '(KHTML, like Gecko) Chrome/114.0.0.0 Mobile Safari/537.36 '
              'MicroMessenger/8.0.38.2400',
        '-H', 'Accept: text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        '-H', 'Accept-Language: zh-CN,zh;q=0.9',
        url
    ], capture_output=True, text=True, timeout=60)
    return result.stdout


def extract_from_script_data(html):
    """New WeChat page (2026+): extract from cgiDataNew JSON in <script> tags."""
    script_pattern = re.compile(r'<script[^>]*>(.*?)</script>', re.DOTALL)
    scripts = script_pattern.findall(html)

    for script in scripts:
        if 'cgiDataNew' not in script and 'content_noencode' not in script:
            continue

        title_m = re.search(r"title:\s*JsDecode\('([^']*)'\)", script)
        title = jsdecode(title_m.group(1)) if title_m else None

        content_m = re.search(r"content_noencode:\s*JsDecode\('([^']*)'\)", script)
        content_html = jsdecode(content_m.group(1)) if content_m else ""

        author_m = re.search(r"nick_name:\s*JsDecode\('([^']*)'\)", script)
        author = jsdecode(author_m.group(1)) if author_m else ""

        time_m = re.search(r"create_time:\s*JsDecode\('([^']*)'\)", script)
        create_time = jsdecode(time_m.group(1)) if time_m else ""

        return title, content_html, author, create_time

    return None, "", "", ""


def extract_from_html_content(html):
    """Legacy WeChat page: extract from HTML div#js_content."""
    title_match = re.search(r'var msg_title = [\'"]([^\'"]+)[\'"]', html)
    if not title_match:
        title_match = re.search(r"msg_title = window\.title = '([^']+)'", html)
    title = (title_match.group(1).replace('\\x26', '&')
             .replace('\\x27', "'").strip()) if title_match else None

    content_match = re.search(
        r'id="js_content"[^>]*>(.*?)</div>\s*(?:<script|<div class="rich_media_tool")',
        html, re.DOTALL
    )
    content_html = content_match.group(1) if content_match else ""

    return title, content_html, "", ""


def html_to_markdown(html_content):
    """Convert HTML content to Markdown."""
    h = re.sub(r'<style[^>]*>.*?</style>', '', html_content, flags=re.DOTALL)

    # Convert tables
    def convert_table(match):
        table_html = match.group(0)
        rows = []
        for tr_match in re.finditer(r'<tr[^>]*>(.*?)</tr>', table_html, re.DOTALL):
            cells = []
            for cell_match in re.finditer(
                r'<t[hd][^>]*>(.*?)</t[hd]>', tr_match.group(1), re.DOTALL
            ):
                cell_content = cell_match.group(1)
                cell_content = re.sub(r'<br\s*/>', ' ', cell_content)
                cell_content = re.sub(r'<[^>]+>', '', cell_content)
                cell_content = cell_content.strip()
                cell_content = cell_content.replace('|', '\\|')
                cells.append(cell_content)
            if cells:
                rows.append(cells)

        if not rows:
            return ''
        max_cols = max(len(row) for row in rows)
        md_lines = []
        for i, row in enumerate(rows):
            while len(row) < max_cols:
                row.append('')
            md_lines.append('| ' + ' | '.join(row) + ' |')
            if i == 0:
                md_lines.append('| ' + ' | '.join(['---'] * max_cols) + ' |')
        return '\n' + '\n'.join(md_lines) + '\n'

    h = re.sub(r'<table[^>]*>.*?</table>', convert_table, h, flags=re.DOTALL)

    # Headings
    for i in range(1, 7):
        h = re.sub(
            f'<h{i}[^>]*>(.*?)</h{i}>',
            f'\n{"#" * i} \\1\n', h, flags=re.DOTALL
        )
    h = re.sub(r'<p[^>]*>(.*?)</p>', '\n\\1\n', h, flags=re.DOTALL)
    h = re.sub(r'<br\s*/>', '\n', h)
    h = re.sub(r'<strong[^>]*>(.*?)</strong>', '**\\1**', h, flags=re.DOTALL)
    h = re.sub(r'<[ou]l[^>]*>', '\n', h)
    h = re.sub(r'</[ou]l>', '\n', h)
    h = re.sub(r'<li[^>]*>(.*?)</li>', '- \\1\n', h, flags=re.DOTALL)
    h = re.sub(r'<blockquote[^>]*>(.*?)</blockquote>', '\n> \\1\n', h, flags=re.DOTALL)
    h = re.sub(r'</?section[^>]*>', '\n', h)
    h = re.sub(r'<[^>]+>', '', h)
    h = re.sub(r'\n{3,}', '\n\n', h)
    h = h.replace('&nbsp;', ' ').replace('&amp;', '&')
    h = h.replace('&lt;', '<').replace('&gt;', '>')
    return h.strip()


def download_images(html_content, images_dir, referer_url):
    """Download images from HTML and replace with Obsidian embed references."""
    if '<img' not in html_content:
        return html_content, []

    downloaded = []
    img_pattern = r'<img[^>]*>'
    all_imgs = list(re.finditer(img_pattern, html_content))

    for img_match in all_imgs:
        img_tag = img_match.group()
        src_match = re.search(r'(?:data-)?src=[\'"]([^\'"]+)[\'"]', img_tag)
        if not src_match:
            continue
        img_url = src_match.group(1)
        if not img_url.startswith('http'):
            continue

        ext = '.png' if '.png' in img_url.lower() else '.jpg'
        url_hash = hashlib.md5(img_url.encode()).hexdigest()
        filename = f"{url_hash}{ext}"
        filepath = os.path.join(images_dir, filename)

        if not os.path.exists(filepath):
            subprocess.run([
                'curl', '-s', '-L',
                '-o', filepath,
                '-H', 'User-Agent: Mozilla/5.0 (Linux; Android 10; K) '
                      'AppleWebKit/537.36 ... MicroMessenger/8.0.38.2400',
                '-H', f'Referer: {referer_url}',
                img_url
            ], capture_output=True, timeout=30)

        obsidian_ref = f'\n![[Clippings/images/{filename}]]\n'
        html_content = html_content.replace(img_tag, obsidian_ref, 1)
        downloaded.append(filename)

    return html_content, downloaded


def detect_tag(url):
    """Determine tag based on URL source."""
    if 'mp.weixin.qq.com' in url:
        return '微信公众号'
    elif 'zhuanlan.zhihu.com' in url:
        return '知乎'
    else:
        return '网页收藏'


def sanitize_filename(title):
    """Convert title to a safe filename."""
    title = title.replace('/', '-').replace('\\', '-')
    title = title.replace(':', '-').replace('*', '-')
    title = title.replace('?', '-').replace('"', '-')
    title = title.replace('<', '-').replace('>', '-').replace('|', '-')
    return title


def main():
    parser = argparse.ArgumentParser(
        description='Convert web page links to Obsidian Markdown files'
    )
    parser.add_argument('url', help='URL of the web page to convert')
    parser.add_argument(
        '--dir', '-d',
        help='Obsidian vault directory (default: $OBSIDIAN_VAULT env var)'
    )
    parser.add_argument(
        '--display', action='store_true',
        help='Print markdown to stdout instead of saving to file'
    )
    args = parser.parse_args()

    # Determine output directory
    workdir = args.dir or os.environ.get('OBSIDIAN_VAULT')
    if not workdir and not args.display:
        print("Error: OBSIDIAN_VAULT not set. Use --dir or --display.", file=sys.stderr)
        sys.exit(1)

    images_dir = os.path.join(workdir, "Clippings/images") if workdir else None
    url = args.url

    # Fetch page
    html = fetch_page(url)

    # Try new extraction method first, fall back to legacy
    title, content_html, author, create_time = extract_from_script_data(html)
    if not title or not content_html:
        title, content_html, _, _ = extract_from_html_content(html)
        author = ""
        create_time = ""

    if not title:
        print("Error: Could not extract title from page.", file=sys.stderr)
        sys.exit(1)

    # Download images (if we have a writable directory)
    if images_dir and not args.display:
        os.makedirs(images_dir, exist_ok=True)
        content_html, _ = download_images(content_html, images_dir, url)

    # Convert HTML to Markdown
    md_content = html_to_markdown(content_html) if content_html else ""

    # Build extra info line
    extra_info = ""
    if author:
        extra_info += f"作者：{author}"
    if create_time:
        if extra_info:
            extra_info += " | "
        extra_info += f"发布时间：{create_time}"
    if extra_info:
        extra_info = f"> {extra_info}\n>"

    # Build YAML frontmatter + content
    today = datetime.now().strftime('%Y-%m-%d')
    tag = detect_tag(url)

    parts = [
        "---",
        f"title: {title}",
        f"source: {url}",
        f"date: {today}",
        "tags:",
        f"  - {tag}",
        "---",
        "",
        f"# {title}",
        "",
    ]
    if extra_info:
        parts.append(extra_info)
        parts.append("")
    parts.append(md_content)

    full_content = "\n".join(parts)

    if args.display:
        print(full_content)
        return

    # Save to file
    safe_title = sanitize_filename(title)
    filepath = os.path.join(workdir, "Clippings", f"{safe_title}.md")
    os.makedirs(os.path.join(workdir, "Clippings"), exist_ok=True)
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(full_content)

    print(f"✅ Saved: {filepath}")


if __name__ == "__main__":
    main()
