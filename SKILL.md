---
name: link2obsidian
description: 将网页链接转换为 Obsidian Markdown 文件，自动下载图片并设置来源标签
execution: python3 ~/.hermes/profiles/ob_xianzi/skills/link2obsidian/runner.py "{url}"
---

# Link to Obsidian 技能

## 功能
将网页链接内容抓取并转换为 Obsidian Markdown 文件，自动下载图片到本地，根据来源设置标签，**并在文件开头添加 LLM 生成的文章要点摘要**。

## 处理流程

1. **识别来源** - 根据URL判断来源类型
2. **抓取内容** - 使用 curl 模拟桌面浏览器抓取页面，保存 cookie jar
3. **提取正文** - 从 `<div id="js_content">` 提取（微信"环境异常"页面不影响）
4. **下载图片** - 带 cookie + Referer 下载至 `Clippings/images/`，含 token 过期自动重试
5. **清理 HTML** - 去除脚本样式，转 Markdown
6. **生成摘要** - （Agent 执行步骤）读取生成的 Markdown 全文，使用 LLM 生成 3~5 条核心要点，插入到文件开头 frontmatter 之后
7. **保存文件** - 存入 `Clippings/`，带 YAML frontmatter

## 来源与标签映射

| 来源域名 | 标签 |
|---------|------|
| mp.weixin.qq.com | 微信公众号 |
| zhuanlan.zhihu.com | 知乎 |
| 其他 | 网页收藏 |

## 目标目录

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
WORKDIR = "/home/jack-lin-sparrow/Obsidian/Thousand"
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
    base_url = _LLM_CONFIG.get("base_url", "https://opencode.ai/zen/go/v1")
    model = _LLM_CONFIG.get("model", "deepseek-v4-flash")
    api_key = _LLM_CONFIG.get("api_key", "")
    
    if not api_key:
        print("  ℹ️ 未配置 API key，跳过 LLM 总结")
        return ""

    payload = json.dumps({
        "model": model,
        "messages": [
            {"role": "system", "content": "直接输出结果，不要推理过程。"},
            {"role": "user", "content": prompt_text}
        ],
        "max_tokens": 3000,
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
        msg = result["choices"][0]["message"]
        # 兼容推理模型（SenseNova 用 reasoning + content）和标准模型（仅 content）
        text = msg.get("content") or msg.get("reasoning") or ""
        return text.strip()
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors='replace')
        if "QpsOverFlow" in body or "QPS" in body:
            print(f"  ⚠️ LLM 被限流（QPS=1 被 Hermes 占用），摘要由 Agent 后续补充")
        elif e.code == 401:
            print(f"  ⚠️ LLM 认证失败，摘要由 Agent 后续补充")
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

def is_valid_image(filepath):
    """检查文件是否为有效图片（通过 magic bytes）"""
    if not os.path.exists(filepath) or os.path.getsize(filepath) < 100:
        return False
    with open(filepath, 'rb') as f:
        header = f.read(8)
    return (
        header[:3] == b'\xff\xd8\xff' or  # JPEG
        header[:4] == b'\x89PNG' or        # PNG
        header[:4] == b'RIFF' or           # WEBP
        header[:4] == b'GIF8'              # GIF
    )

def download_with_playwright(failed_list):
    """使用 Playwright 浏览器下载 curl 失败的图片（绕过防盗链）"""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("  ⚠️ Playwright 未安装，无法使用浏览器备选方案")
        return {}

    results = {}
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.set_extra_http_headers({"Referer": "https://mp.weixin.qq.com/"})
        page.set_default_timeout(15000)

        for img_url, outpath in failed_list:
            try:
                resp = page.goto(img_url, wait_until='load', timeout=15000)
                if resp and resp.status == 200:
                    body = resp.body()
                    with open(str(outpath), 'wb') as f:
                        f.write(body)
                    ok = is_valid_image(str(outpath))
                    results[img_url] = ok
                    print(f"  🌐 {'✅' if ok else '❌'} {os.path.basename(str(outpath))} (Playwright, {len(body)} bytes)")
                else:
                    results[img_url] = False
                    print(f"  🌐 ❌ {os.path.basename(str(outpath))} (Playwright, HTTP {resp.status if resp else 'N/A'})")
            except Exception as e:
                results[img_url] = False
                print(f"  🌐 ❌ {os.path.basename(str(outpath))} (Playwright 异常: {e})")

        browser.close()
    return results

IMAGES_DIR.mkdir(parents=True, exist_ok=True)
img_filenames = {}  # url -> 本地文件名
failed_downloads = []  # [(url, outpath)] — 供 Playwright 备选

for img_url in img_urls:
    ext = "jpg" if "jpg" in img_url or "jpeg" in img_url else "png"
    url_hash = hashlib.md5(img_url.encode()).hexdigest()
    fname = f"{url_hash}.{ext}"
    outpath = IMAGES_DIR / fname

    # 如果文件已存在且为有效图片，跳过下载
    if is_valid_image(str(outpath)):
        print(f"  ⏭️ {fname} (已存在，跳过)")
        img_filenames[img_url] = fname
        continue

    r = subprocess.run([
        "curl", "-sL", "-o", str(outpath),
        "-b", cookie_file,
        "-H", "Referer: https://mp.weixin.qq.com/",
        "-A", UA,
        img_url
    ], capture_output=True, timeout=30)

    ok = is_valid_image(str(outpath))
    if ok:
        print(f"  ✅ {fname}")
    else:
        print(f"  ❌ {fname} (curl 失败，稍后用 Playwright 重试)")
        failed_downloads.append((img_url, outpath))
    img_filenames[img_url] = fname

# ⚠️ Token 过期重试：重新抓取页面获取新鲜 URL
if failed_downloads:
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

        # 用新鲜 URL 重试 curl
        still_failed = []
        for i in range(min(len(fresh_urls), len(failed_downloads))):
            fresh_url = fresh_urls[i]
            old_url, outpath = failed_downloads[i]
            ext = "jpg" if "jpg" in fresh_url or "jpeg" in fresh_url else "png"
            url_hash = hashlib.md5(fresh_url.encode()).hexdigest()
            fname = f"{url_hash}.{ext}"
            new_outpath = IMAGES_DIR / fname
            img_filenames[old_url] = fname
            r3 = subprocess.run([
                "curl", "-sL", "-o", str(new_outpath),
                "-b", cookie_file,
                "-H", "Referer: https://mp.weixin.qq.com/",
                "-A", UA,
                fresh_url
            ], capture_output=True, timeout=30)
            ok2 = is_valid_image(str(new_outpath))
            if ok2:
                print(f"  ✅ {fname} (curl 重试成功)")
            else:
                print(f"  ❌ {fname} (curl 重试仍失败)")
                still_failed.append((fresh_url, new_outpath))

        # curl 重试仍失败的图片，用 Playwright 浏览器下载
        if still_failed:
            print(f"  🌐 启动 Playwright 浏览器备选方案 ({len(still_failed)} 张图片)...")
            pw_results = download_with_playwright(still_failed)
            # 更新文件名映射
            for fresh_url, outpath in still_failed:
                if pw_results.get(fresh_url):
                    print(f"  🌐 ✅ {os.path.basename(str(outpath))} 浏览器下载成功")
                else:
                    print(f"  🌐 ❌ {os.path.basename(str(outpath))} 浏览器下载也失败")
    else:
        # 无法重新抓取页面，直接对原始 URL 用 Playwright
        print(f"  🌐 启动 Playwright 浏览器备选方案 ({len(failed_downloads)} 张图片)...")
        pw_results = download_with_playwright(failed_downloads)

# ─── 6. HTML → Markdown ───────────────────────────────────

content = raw_html

# 替换图片标签（就地按 <img> 标签替换，保证位置与原文一致，并兼容 &amp; 转义）
def _replace_img_tag(m):
    tag = m.group(0)
    url = None
    for sa in ("data-src", "src"):
        um = re.search(rf'{sa}="([^"]*)"', tag)
        if um:
            url = um.group(1).replace("&amp;", "&")
            break
    if url and url in img_filenames:
        name = img_filenames[url]
        return f"\n![{name}](images/{name})\n"
    return ""  # 未下载或提取不到的图片，直接移除

content = re.sub(r"<img[^>]*>", _replace_img_tag, content)
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
5. **首次使用** — 确保目标目录存在：`mkdir -p ~/Obsidian/Thousand/Clippings/images`
6. **摘要生成** — runner.py 不包含摘要功能。脚本执行后，Agent 需读取生成的 Markdown，用 LLM 提炼 3~5 条核心要点，插入到 frontmatter 与正文之间，格式：
   ```markdown
   ---
   （frontmatter...）
   ---

   > 📌 **文章要点**
   > - 要点一
   > - 要点二
   > - 要点三

   （正文开始...）
   ```
7. **图片验证 + Playwright 备选** — 下载的图片通过 magic bytes 验证（JPEG/PNG/WEBP/GIF），不仅检查文件大小。如果 curl 下载失败或文件非有效图片，自动触发三层重试：
   - **第一层**：curl + cookie + Referer（原有方式）
   - **第二层**：重新抓取页面获取新鲜 URL，再用 curl 重试
   - **第三层**：启动 Playwright headless 浏览器直接下载（绕过防盗链，需要 `pip install playwright && playwright install chromium`）
