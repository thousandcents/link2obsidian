---
name: link2obsidian
description: Convert web page links to Obsidian Markdown files, auto-download images, add smart tags and LLM-generated summaries
---

# Link to Obsidian

## 功能

将网页链接内容抓取并转换为 Obsidian Markdown 文件，自动下载图片到本地，根据来源设置标签，**并在文件开头添加 LLM 生成的文章要点摘要**。

## 处理流程

1. **识别来源** — 根据 URL 判断来源类型
2. **抓取内容** — 使用 curl 模拟桌面浏览器抓取页面，保存 cookie jar
3. **提取正文** — 从 `<div id="js_content">` 提取（微信"环境异常"页面不影响）
4. **下载图片** — 带 cookie + Referer 下载至 `Clippings/images/`，含 token 过期自动重试
5. **清理 HTML** — 去除脚本样式，转 Markdown
6. **生成摘要** — 使用 LLM 生成 3~5 条核心要点，插入到文件开头 frontmatter 之后
7. **保存文件** — 存入 `Clippings/`，带 YAML frontmatter

## 来源与标签映射

| 来源域名 | 标签 |
|---------|------|
| mp.weixin.qq.com | 微信公众号 |
| zhuanlan.zhihu.com | 知乎 |
| 其他 | 网页收藏 |

## 目标目录 (相对于 OBSIDIAN_VAULT)

- 文章目录: `Clippings/`
- 图片目录: `Clippings/images/`

## Python 执行代码

~~~python
# ═══════════════════════════════════════════════════════════
# link2obsidian — WeChat Article Extractor
# ═══════════════════════════════════════════════════════════

import subprocess, re, os, hashlib, json, sys, tempfile
import html as html_mod
from datetime import datetime
from pathlib import Path
import urllib.request

ARTICLE_URL = "用户提供的链接"  # 由 runner.py 替换

# ─── 配置 ─────────────────────────────────────────────────
# OBSIDIAN_VAULT 环境变量：Obsidian vault 根目录
WORKDIR = os.environ.get("OBSIDIAN_VAULT", str(Path.home() / "Obsidian" / "Thousand"))
CLIPPINGS_DIR = Path(WORKDIR) / "Clippings"
IMAGES_DIR = CLIPPINGS_DIR / "images"
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)

# ─── LLM 总结功能 ──────────────────────────────────────────

def _call_llm(prompt_text):
    """调用 LLM 生成文本，返回响应字符串"""
    base_url = _LLM_CONFIG.get("base_url", "https://api.openai.com/v1")
    model = _LLM_CONFIG.get("model", "gpt-4o-mini")
    api_key = _LLM_CONFIG.get("api_key", "")

    if not api_key:
        print("  ℹ️ 未配置 API key，跳过 LLM 总结")
        return ""

    payload = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": prompt_text}],
        "max_tokens": 600,
        "temperature": 0.3,
    }).encode("utf-8")

    req = urllib.request.Request(
        f"{base_url}/chat/completions",
        data=payload,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        resp = urllib.request.urlopen(req, timeout=60)
        result = json.loads(resp.read())
        return result["choices"][0]["message"]["content"].strip()
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")
        if "QpsOverFlow" in body or "QPS" in body:
            print(f"  ⚠️ LLM 被限流，跳过摘要")
        elif e.code == 401:
            print(f"  ⚠️ LLM 认证失败，跳过摘要")
        else:
            print(f"  ⚠️ LLM 调用失败: HTTP {e.code}")
        return ""
    except Exception as e:
        print(f"  ⚠️ LLM 调用异常: {e}")
        return ""


def generate_summary(full_text):
    """读取文章全文，用 LLM 生成 3~5 条核心要点"""
    max_chars = 4000
    if len(full_text) > max_chars:
        full_text = full_text[:max_chars] + "\n……(省略)"

    prompt = f"""你是一个量化金融分析师。请用中文为以下文章提炼 3~5 条核心要点，每条一句话。
要求：
- 每条要点用「- 」开头
- 聚焦文章的核心论点、关键数据或结论
- 不写废话、不写标题、不加序号
- 不要使用 Markdown 格式，纯文本即可

文章内容：
{full_text}"""

    result = _call_llm(prompt)
    if result:
        lines = [line.strip().lstrip("- ") for line in result.split("\n") if line.strip()]
        lines = [l for l in lines if l and not l.startswith("```")]
        return lines[:6]
    return []


def format_summary_block(points):
    """将要点列表格式化为引用块"""
    if not points:
        return ""
    lines = ["> 📌 **文章要点**"]
    for p in points:
        lines.append(f"> - {p}")
    lines.append("")
    return "\n".join(lines)


# ─── 1. 抓取页面 + 保存 cookie ────────────────────────────

cookie_file = tempfile.NamedTemporaryFile(prefix="wc_", suffix=".txt", delete=False).name

result = subprocess.run([
    "curl", "-sL",
    "-A", UA,
    "-H", "Accept: text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "-H", "Accept-Language: zh-CN,zh;q=0.9,en;q=0.8",
    "-c", cookie_file,
    ARTICLE_URL
], capture_output=True, text=True, timeout=30)
html = result.stdout

# ─── 2. 提取元数据 ─────────────────────────────────────────

m = re.search(r'<meta[^>]*property="og:title"[^>]*content="([^"]*)"', html)
title = html_mod.unescape(m.group(1)).strip() if m else "未知标题"

m = re.search(r'<meta[^>]*property="og:description"[^>]*content="([^"]*)"', html)
description = html_mod.unescape(m.group(1)).strip() if m else ""

m = re.search(r'var\s+ct\s*=\s*"?"?(\d+)"?"?', html)
pub_time = ""
if m:
    pub_time = datetime.fromtimestamp(int(m.group(1))).strftime("%Y-%m-%d %H:%M:%S")

# ─── 3. 提取正文 (js_content div) ─────────────────────────

m = re.search(r'<div[^>]*id="js_content"[^>]*>(.*?)</div>\s*<script', html, re.DOTALL)
if not m:
    m = re.search(r'<div[^>]*id="js_content"[^>]*>(.*?)</div>', html, re.DOTALL)
raw_html = m.group(1) if m else ""

# ─── 4. 提取图片 URL ──────────────────────────────────────

img_urls = []
seen = set()
for attr in ["data-src", "src"]:
    for u in re.findall(rf'{attr}="([^"]+)"', raw_html):
        u_clean = u.replace("&amp;", "&")
        if u_clean not in seen and "qpic.cn" in u_clean:
            seen.add(u_clean)
            img_urls.append(u_clean)

# ─── 5. 下载图片 ───────────────────────────────────────────

IMAGES_DIR.mkdir(parents=True, exist_ok=True)
img_filenames = {}  # url -> 本地文件名
download_failed = False

for i, img_url in enumerate(img_urls):
    ext = "jpg" if "jpg" in img_url or "jpeg" in img_url else "png"
    fname = f"img_{i+1:02d}.{ext}"
    outpath = IMAGES_DIR / fname

    r = subprocess.run([
        "curl", "-sL", "-o", str(outpath),
        "-b", cookie_file,
        "-H", "Referer: https://mp.weixin.qq.com/",
        "-A", UA,
        img_url
    ], capture_output=True, timeout=30)

    ok = os.path.exists(outpath) and os.path.getsize(outpath) > 0
    if ok:
        print(f"  ✅ {fname}")
    else:
        print(f"  ❌ {fname} (0 bytes, URL 可能过期)")
        download_failed = True
    img_filenames[img_url] = fname

# ⚠️ Token 过期重试：重新抓取页面获取新鲜 URL
if download_failed:
    print(f"  🔄 重新抓取页面获取新鲜图片 URL...")
    r2 = subprocess.run([
        "curl", "-sL", "-A", UA,
        "-H", "Accept: text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "-H", "Accept-Language: zh-CN,zh;q=0.9,en;q=0.8",
        "-b", cookie_file,
        ARTICLE_URL
    ], capture_output=True, text=True, timeout=30)
    html2 = r2.stdout
    m2 = re.search(r'<div[^>]*id="js_content"[^>]*>(.*?)</div>\s*<script', html2, re.DOTALL)
    if m2:
        raw2 = m2.group(1)
        fresh_urls = []
        seen2 = set()
        for attr in ["data-src", "src"]:
            for u in re.findall(rf'{attr}="([^"]+)"', raw2):
                u2 = u.replace("&amp;", "&")
                if u2 not in seen2 and "qpic.cn" in u2:
                    seen2.add(u2)
                    fresh_urls.append(u2)

        for i in range(min(len(fresh_urls), len(img_urls))):
            ext = "jpg" if "jpg" in fresh_urls[i] or "jpeg" in fresh_urls[i] else "png"
            fname = f"img_{i+1:02d}.{ext}"
            outpath = IMAGES_DIR / fname
            r3 = subprocess.run([
                "curl", "-sL", "-o", str(outpath),
                "-b", cookie_file,
                "-H", "Referer: https://mp.weixin.qq.com/",
                "-A", UA,
                fresh_urls[i]
            ], capture_output=True, timeout=30)
            ok2 = os.path.exists(outpath) and os.path.getsize(outpath) > 0
            print(f"  {'✅' if ok2 else '❌'} {fname} (重试{'成功' if ok2 else '失败'})")

# ─── 6. HTML → Markdown ───────────────────────────────────

content = raw_html

# 替换图片标签
for attr in ["data-src", "src"]:
    for orig_url, local_name in img_filenames.items():
        for sa in ["data-src", "src"]:
            content = re.sub(
                rf'<img[^>]*{re.escape(sa)}="{re.escape(orig_url)}"[^>]*>',
                f"\n![{local_name}](images/{local_name})\n",
                content
            )

content = re.sub(r"<img[^>]*>", "", content)
content = re.sub(r"<script[^>]*>.*?</script>", "", content, flags=re.DOTALL)
content = re.sub(r"<style[^>]*>.*?</style>", "", content, flags=re.DOTALL)

# 块级元素
content = re.sub(r"<br\s*/?>", "\n", content)
content = re.sub(r"</p>", "\n\n", content)
for tag in ["section", "p", "div", "span"]:
    content = re.sub(rf"</?{tag}[^>]*>", "", content)

# 标题
for i in range(6, 0, -1):
    content = re.sub(rf"</h{i}>", "", content)
    content = re.sub(rf"<h{i}[^>]*>", "\n" + "#" * i + " ", content)

# 行内格式
content = re.sub(r"</?strong>", "**", content)
content = re.sub(r"</?b>", "**", content)
content = re.sub(r"</?em>", "*", content)
content = re.sub(r"</?i>", "*", content)
content = re.sub(r"<code[^>]*>", "`", content)
content = re.sub(r"</code>", "`", content)

# 代码块
content = re.sub(r"<pre[^>]*>", "\n```\n", content)
content = re.sub(r"</pre>", "\n```\n", content)

# 列表
content = re.sub(r"</?ul[^>]*>", "", content)
content = re.sub(r"</?ol[^>]*>", "", content)
content = re.sub(r"</li>", "\n", content)
content = re.sub(r"<li[^>]*>", "- ", content)

# 引用
content = re.sub(r"<blockquote[^>]*>", "\n> ", content)
content = re.sub(r"</blockquote>", "", content)

# 链接 / iframe
content = re.sub(r"<a[^>]*>", "", content)
content = re.sub(r"</a>", "", content)
content = re.sub(r'<iframe[^>]*data-src="([^"]+)"[^>]*></iframe>', r"\n[📺 点击观看视频](\1)\n", content)
content = content.replace("&amp;", "&")

# 移除残留标签
content = re.sub(r"<[^>]+>", "", content)

# 解义 & 清理
content = html_mod.unescape(content)
content = content.replace("&nbsp;", " ")
content = re.sub(r"[ \t]+", " ", content)
content = re.sub(r"\n{4,}", "\n\n\n", content)
content = content.strip()

# ─── 7. 确定标签 ──────────────────────────────────────────

if "mp.weixin.qq.com" in ARTICLE_URL:
    tag = "微信公众号"
elif "zhuanlan.zhihu.com" in ARTICLE_URL:
    tag = "知乎"
else:
    tag = "网页收藏"

# ─── 8. 生成 LLM 摘要 ──────────────────────────────────────

print("  🤖 正在生成文章要点摘要...")
summary_block = ""
try:
    points = generate_summary(content)
    if points:
        summary_block = format_summary_block(points)
        print(f"  ✅ 摘要生成完成 ({len(points)} 条)")
    else:
        print("  ℹ️ 未生成摘要（可能是 LLM 未配置）")
except Exception as e:
    print(f"  ⚠️ 摘要生成异常: {e}")

# ─── 9. 保存文件 ──────────────────────────────────────────

CLIPPINGS_DIR.mkdir(parents=True, exist_ok=True)

safe_title = re.sub(r'[\\/:*?"<>|]', "", title)
if len(safe_title) > 120:
    safe_title = safe_title[:120]

frontmatter = f"""---
source: {tag}
title: {title}
description: {description}
tags:
  - {tag}
created: {pub_time}
url: {ARTICLE_URL}
---

"""

# 拼接：frontmatter + 摘要 + 正文
full_output = frontmatter
if summary_block:
    full_output += summary_block + "\n"
full_output += content

output_path = CLIPPINGS_DIR / f"{safe_title}.md"
output_path.write_text(full_output, encoding="utf-8")
print(f"\n✅ 已保存: {output_path}")
~~~

## 注意事项

1. **环境异常页面** — 微信返回的验证页面中正文仍在 `<div id="js_content">`，正常提取
2. **qpic.cn 防盗链** — 图片下载必须带 cookie jar + `Referer: https://mp.weixin.qq.com/`，缺一不可
3. **Token 过期** — qpic.cn 图片 URL 有时效性 token，代码内置自动重试（重新抓取页面获取新鲜 URL）
4. **桌面 UA** — 必须使用桌面版 Chrome User-Agent，移动 UA 触发更严的验证
5. **LLM 摘要** — 需设置 `LLM_API_KEY` 环境变量。未设置时跳过摘要生成，不影响正文提取
6. **OBSIDIAN_VAULT** — 设置此环境变量指定 Obsidian vault 目录，默认 `~/Obsidian/Thousand`
