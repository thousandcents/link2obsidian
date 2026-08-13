---
name: link2obsidian
description: 将网页链接转换为 Obsidian Markdown 文件，自动下载图片并设置来源标签
execution: python3 /home/jack-lin-sparrow/.hermes/profiles/ob_xianzi/skills/note-taking/link2obsidian/runner.py "{url}"
---

> ℹ️ **ob_xianzi 自包含版**：本目录即 link2obsidian 的唯一真身，`runner.py`、`postprocess.py`、本 `SKILL.md` 与 `references/` 都在此处，不再依赖共享源技能或软链。`runner.py` 抓取后会**自动调用 `postprocess.py`** 完成后处理。

# Link to Obsidian 技能

## 功能
将网页链接内容抓取并转换为 Obsidian Markdown 文件，自动下载图片到本地、嵌入正文（封面图除外），根据来源设置标签，**并在文件开头添加 LLM 生成的文章要点摘要**。

## 来源与标签映射

| 来源域名 | 标签 |
|---------|------|
| mp.weixin.qq.com | 微信公众号 |
| zhuanlan.zhihu.com | 知乎 |
| 其他 | 网页收藏 |

## 目标目录

- 文章目录: `Clippings/`
- 图片目录: `Clippings/images/`

## 执行方式

- Entry point: `runner.py` — loads scraper code and executes
- Scraper logic: 本 SKILL.md 内联的 `~~~python` 代码块（runner.py 提取并执行）
- Postprocess: `postprocess.py` — runner.py 执行后自动清理 Markdown 格式缺陷
- Reference: `references/wechat-page-structure.md` — Vue.js SPA details

## Python 执行代码

runner.py 从本 SKILL.md 提取以下代码块并执行（已替换 ARTICLE_URL / WORKDIR 占位符）：

~~~python
# ═══════════════════════════════════════════════════════════
# link2obsidian — WeChat Article Extractor
# ═══════════════════════════════════════════════════════════

import subprocess, re, os, hashlib, json, sys, tempfile
import html as html_mod
from datetime import datetime
from pathlib import Path
import urllib.request
import socket

# ─── 强制 IPv4 ─────────────────────────────────────────
# 系统无 IPv6 默认路由，apihub.agnes-ai.com 有 AAAA 记录，
# urllib 优先尝试 IPv6 导致 [Errno 101] Network is unreachable。
# monkey-patch socket.getaddrinfo 强制只返回 IPv4 地址。
_orig_getaddrinfo = socket.getaddrinfo
def _ipv4_only_getaddrinfo(host, port, family=0, *args, **kwargs):
    return _orig_getaddrinfo(host, port, socket.AF_INET, *args, **kwargs)
socket.getaddrinfo = _ipv4_only_getaddrinfo

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
    """调用 LLM 生成文本，返回响应字符串。

    默认直连（不使用代理）；若直连因网络/连接错误失败，自动回退到
    走代理（使用环境默认 HTTP_PROXY/HTTPS_PROXY）。
    """
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

    def _parse(resp):
        result = json.loads(resp.read())
        msg = result["choices"][0]["message"]
        # 兼容推理模型（SenseNova 用 reasoning + content）和标准模型（仅 content）
        text = msg.get("content") or msg.get("reasoning") or ""
        return text.strip()

    # 直连 opener（强制不走代理）；代理 opener（使用环境默认代理）
    no_proxy_opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    proxy_opener = urllib.request.build_opener(urllib.request.ProxyHandler(None))

    # 1) 优先走代理（本机 Clash 透明代理会拦截非代理出站连接，直连不可用）
    try:
        return _parse(proxy_opener.open(req, timeout=60))
    except urllib.error.HTTPError as e:
        # HTTP 错误（限流/认证/服务端）与代理无关，不回退
        body = e.read().decode(errors='replace')
        if "QpsOverFlow" in body or "QPS" in body:
            print(f"  ⚠️ LLM 被限流（QPS=1 被 Hermes 占用），摘要由 Agent 后续补充")
        elif e.code == 401:
            print(f"  ⚠️ LLM 认证失败，摘要由 Agent 后续补充")
        else:
            print(f"  ⚠️ LLM 调用失败: HTTP {e.code}")
        return ""
    except Exception as e_proxy:
        # 2) 代理失败（网络/连接/超时/SSL 等）→ 回退直连
        print(f"  ℹ️ LLM 走代理失败（{e_proxy}），回退直连重试...")
        try:
            return _parse(no_proxy_opener.open(req, timeout=60))
        except Exception as e_direct:
            print(f"  ⚠️ LLM 直连也失败: {e_direct}")
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

# ─── 6.1 表格：<table> → GFM（须在通用标签抹平之前，避免单元格粘连）───
def html_table_to_markdown(table_html):
    """将单个 <table>...</table> 转为 GFM pipe 表格。

    兼容 thead/tbody 包裹、<strong>/<em> 加粗斜体、<br> 换行、&nbsp;、
    以及单元格内已被替换为 ![..](..) 的图片。须在 <[^>]+> 通用抹平之前调用，
    否则 <td>/<tr> 被删、单元格内容粘连成一团的「**」分隔乱码。
    """
    def cell_text(cell_html):
        h = cell_html
        h = re.sub(r"<br\s*/?>", " ", h)                       # 单元格内换行 → 空格
        h = re.sub(r"</?strong[^>]*>|</?b[^>]*>", "**", h)     # 加粗（含带属性标签，如 <strong style=...>）
        h = re.sub(r"</?em[^>]*>|</?i[^>]*>", "*", h)          # 斜体（含带属性标签）
        h = re.sub(r"<[^>]+>", "", h)                          # 抹平其余标签（![]() 无 <>，保留）
        h = h.replace("&amp;", "&").replace("&nbsp;", " ")
        h = html_mod.unescape(h)
        h = re.sub(r"\s+", " ", h).strip()
        return h.replace("|", "\\|")                # 单元格内 | 转义

    rows = re.findall(r"<tr[^>]*>(.*?)</tr>", table_html, flags=re.DOTALL | re.IGNORECASE)
    if not rows:
        return ""
    grid = []
    for row in rows:
        cells = re.findall(r"<t(h|d)[^>]*>(.*?)</t\1>", row, flags=re.DOTALL | re.IGNORECASE)
        if not cells:
            # 退化兼容：个别 <td> 写法差异时按 <td> 切分
            cells = [("d", c) for c in re.findall(r"<td[^>]*>(.*?)</td>", row, flags=re.DOTALL | re.IGNORECASE)]
        grid.append([cell_text(c) for _, c in cells])
    if not grid:
        return ""
    ncol = max(len(r) for r in grid)
    out = []
    for i, r in enumerate(grid):
        while len(r) < ncol:
            r.append("")
        out.append("| " + " | ".join(r) + " |")
        if i == 0:
            out.append("|" + "|".join(["---"] * ncol) + "|")
    return "\n\n" + "\n".join(out) + "\n\n"

# 在 <img> 替换之后、通用标签抹平（<[^>]+> → ''）之前，转换所有 <table>
content = re.sub(
    r"<table[^>]*>.*?</table>",
    lambda m: html_table_to_markdown(m.group(0)),
    content,
    flags=re.DOTALL | re.IGNORECASE,
)

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

## Agent 后处理步骤（脚本执行后必做）

runner.py 执行完毕后，Agent 按以下顺序处理：

> ⚠️ **手动后处理的路径陷阱（高频踩坑）**：`runner.py` 保存文件用的 `safe_title` 会**剥离标题中的 Windows 非法字符**（如 `:` `*` `?` `"` `<` `>` `|`），因此**磁盘文件名 ≠ frontmatter 的 `title:`**，正文 `#` 标题也仍带这些符号。例：标题 `量化翻车现场：精心优化的模型，竟输给一个"拍脑袋"的常数？` 的磁盘文件名为 `量化翻车现场：精心优化的模型，竟输给一个拍脑袋的常数？.md`（无引号）。
> - **切勿**用正文标题（含引号/特殊字符）拼路径去 `open()`，会 `FileNotFoundError`。
> - **可靠重开方式**：用 `glob.glob('*拍脑袋*')` 或 `search_files(target='files')` 按稳定子串定位；execute_code 里用 `os.path.join(WORKDIR,'Clippings', f)` 且 `f` 取自 `glob` 结果。
> - execute_code 的工作目录是 Hermes 会话目录（非 vault），务必用**绝对路径** `WORKDIR`（即本技能 `runner.py` 的 `WORKDIR` 常量，默认 `/home/jack-lin-sparrow/Obsidian/Thousand`）。

> ⚠️ **中文弯引号文件名陷阱**：`safe_title` 剥离 ASCII 引号但不剥离**中文弯引号**（U+201C `"` U+201D `"`），后者会保留在磁盘文件名中，触发三个连锁问题：
> - **Shell `mv` 静默失败**：bash 将中文弯引号当作元字符，`mv "从"因子动物园"到..."` → `mv: 没有那个文件或目录`。**绕过**：用 Python `shutil.move()` 或 `os.rename()` 替代 shell mv。
> - **Python `execute_code` SyntaxError**：直接赋值 `f = "从"因子动物园"...md"` 时，中文引号终结字符串字面量，报 `SyntaxError: invalid syntax`。**绕过**：用 `glob.glob('/path/从*因子*')` 定位文件，或 Unicode 转义 `f = "从\\u201c因子动物园\\u201d...md"`。
> - **glob 碰撞错配**：相似前缀的文章命中多个 glob 结果（如 `从*因子*` 同时匹配「因子动物园」和「Agent 挖因子」），先取先返回的文件会算错 sha256 或错插溯源标记。**绕过**：glob 后用 frontmatter `title:` 字段核验目标，确认 `sha256` 的 `nSTXlHon` 等 URL 片段。

### 第 0 步：自动后处理（确定性清理）— 已由 runner.py 自动完成

`runner.py` 在抓取并生成 `.md` 文件后，**已自动调用 `postprocess.py` 完成所有可由正则/固定规则判定的清理工作**，无需 Agent 手动触发（这正是之前「postprocess 偶尔没运行」的根因：它原本是 Agent 的手动步骤，会被漏掉）。

runner.py 执行结束后，后处理报告会直接打印在终端。Agent 只需阅读报告即可知道哪些已自动修复、哪些仍需 AI 介入。

如需手动复核或重新运行（例如换了 .md 文件），可手动执行：

```bash
python3 ~/.hermes/profiles/ob_xianzi/skills/note-taking/link2obsidian/postprocess.py \
  "{生成的 .md 文件路径}" --url "{原 URL}" --verbose
```

可选参数：
- `--dry-run`：只报告修改项不写回，用于预检
- `--verbose` / `-v`：打印每条修复明细

**postprocess.py 自动覆盖以下需求**（原本以文字指挥 AI 完成的）：

1. **Frontmatter 清理**
   - `\x26quot;` → `"` 字面量解码
   - `\x0d` / `\x0a` CRLF 字面量 → 空格
   - `&quot;` / `&amp;` / `&lt;` / `&gt;` / `&nbsp;` / `&#x2B;` HTML 实体解码
   - 空 description 字段检测（仅提示，不自动填，由 Agent 用 LLM 生成）
2. **Markdown 字符级清理**
   - NBSP (U+00A0) → 空格
   - `\*\*xxx\*\*` 转义加粗 → `**xxx**`
   - 6+ 星号嵌套残留 → 去星保留纯文本
   - 4+ 星号 → `**` 标准化
   - `***text***` (strong+em 残差) → `**text**`
3. **孤儿 `**` 校正**（按段统计奇偶 + 常见模式批量修复）
   - `第N，...XXX**`（句末整段加粗）/ `第N，XXX**：/——/（` → `第N，**XXX**`
   - `X。** 空格` → `**X。** 空格`
   - `XXX**——` → `**XXX**——`
   - 引号包裹词后跟 `**`（中英文引号）
   - 公式/计算行末尾 `**` → 整行包裹
   - 列表项 `- TEXT**：/（/—— 会把/则` 系列 → `- **TEXT**...`
   - 冒号后加粗偏移 `- 原始回测：** 4 年...` → `- **原始回测：** 4 年...`
   - 整段加粗丢失（段末 `**` 开头无 `**`）→ 段首补 `**`
   - **兜底：连续 4+ 星号 → `**`（覆盖 overlapping fix 产生的 `****`）**
      - **AI 终扫（postprocess 后必做）**：对剩余仍未配对的孤儿 `**`，**直接删除**（勿猜原文加粗范围，避免引入错误强调），用精确字符串替换逐个删、保留已成对部分。脚本见 `references/batch-image-screening-and-orphan-sweep.md`。
   - **进阶清理（link2obsidian 实战沉淀，开发纪律见 `references/postprocess-extension-pitfalls.md`）**：
     - 标题孤立 `**` 包裹移除：`**### 2.1 标题粘连**` → `### 2.1 标题粘连`（仅去首尾 `**`，标题/正文粘连的语义拆分仍留给 AI）
     - 独立成行 `**` 删除（转换器残留的孤立加粗行）
     - 列表项孤儿 `**- ` → `- `（**仅限行内无闭合 `**` 的情形**；合法加粗 `**- 文本**` 不动，否则会残留孤儿 `**`）
     - 导语后孤儿 `**`：`通俗版**：` / `通俗理解**：` → `通俗版：` / `通俗理解：`
     - **被压平表格检测**：行内无 `|`、长度 > 40、含 ≥2 个 `%` 且存在 `**` 的表格行 → 输出 `⚠️ 需 AI` 提示按语义重建为 GFM pipe table（**不自动重建**，列边界需语义判定）
4. **标题修复**
   - 空标题 `# ` → `# {frontmatter title}`
   - 中文编号 `一、` `二、` 独立段落行 → `## 一、`（已带 `##` 或 `**加粗**` 的不动）
   - 数值编号 `01` `02` 独立段落行（排除 fence 内）→ `## 01`
   - 标题+正文粘连（`## N. xxx。正文` / `## 总结回顾全文` 等可明确判定的）→ 插入 `\n\n`
   - 标题+代码块 inline 粘连（`### 4.1 数据准备`from pathlib）→ 插入 `\n\n`
5. **列表/子弹修复**
   - 冗余子弹 `- • ` → `- `
   - 同行多子弹拆分（`。`/`；` 后紧跟 `•`/`- ` 处插入换行）
   - 空子弹行（仅 `- ` 无内容）→ 删除（不删段落分隔空行）
6. **加粗标签孤儿 `**` 缺开头**：列表项中 `XXX**：**`（标签**缺开头 `**`），需手工补全为 `**XXX**：**`。常见于「适合：/ 不适合：」类段落。详见 `references/bold-label-orphan-patterns.md`
7. **代码块/反引号修复**
   - 行首 `+Rust 关键字 → ````rust`
   - 行首 `+Python/C/Bash 关键字 → 对应语言 fence
   - 行首 `+中文字符 + 上下文含 ASCII 流程图字符（`│▼├└`）→ `````；否则删除行首反引号
   - 行首 `+URL 内联包装（`地址：https://...）→ 删 ` 后插 `\n\n`
   - 行首 `+` 起始符（`{`/`(`/`<`/`@`/`-`）→ ```` fence`
   - 行内代码闭包后缺空格（`` `xxx`text `` → `` `xxx` text ``）
   - 代码块闭合 ```` ``` `` 紧跟正文无换行 → 插入 `\\n\\n`
     - 内联代码行首（`+字母数字_ 且整行有配对反引号）→ **保留**，不动
     - **代码块 fence + 语言标识分离修复**（` ```\\n\\npython\\n ` → ` ```python\\n `）详见 `references/code-fence-lang-split-fix.md`
7. **空行/空白修复**
   - 4+ 连续空行 → 最多 2 空行
   - 行尾空白清理
8. **图片路径校正**
   - `](images/xxx.png` → `](Clippings/images/xxx.png`
   - 检查每条图片引用对应的本地文件是否存在；不存在则提示 Agent
9. **教程编号风格**
   - `1、xxx` → `1. xxx`（行首，不动 `## 一、` 标题）

postprocess.py 完成后会打印一份"📋 后处理报告"，列出已自动修复的项与仍需 AI 介入的项（带 `⚠️ 需 AI：` 前缀）。Agent 直接阅读报告即可知道下一步要做什么。

---

以下步骤 **无法用固定规则判定**，必须由 Agent 在 postprocess.py 之后人工介入完成。

### 第 1 步：文件大小检测与兜底抓取（仅当 postprocess 报告提示文件 < 500 字节时）

postprocess.py 已在报告里提示"文件仅 N 字节（< 500）"，此时 Agent 按以下优先级依次尝试：

**优先方案：提取 HTML 中嵌的数据**
- 用 `curl -s -L -A "Mozilla/5.0 ..."` 下载 HTML 源码，搜索 `content_noencode`
- 若找到 `content_noencode`，说明是 Vue.js SPA 页面，内容在 `cgiDataNew` 中，用 JsDecode 解码后手动构建 Markdown（JsDecode：`\x0a→换行`、`\x0d→回车`、`\x22→双引号`、`\x26→&` 等）

**备选方案：常规博客/静态 HTML 页面提取**
- 若 HTML 中无 `content_noencode`（非 WeChat SPA 页面），且页面是常规博客站点（博客园/cnblogs、CSDN 等），可直接从 HTML 提取正文：
  ```bash
  curl -s -L -A "Mozilla/5.0 ..." {url} > /tmp/article.html
  ```
- 站点标识符对照：cnblogs.com → `#post_detail`；CSDN → `#content_views`；普通 `<article>` 或 `<main>` 标签亦可
- 用 Python 解析 HTML，保留语义标签：`<h2/h3>` → `##/###`，`<strong/b>` → `**`，`<pre><code>` → fenced code block（注意保留缩进和语言标记 `class="language-xxx"`）
- `<table>` → pipe table（注意表头和数据行分离，分隔线列数匹配）
- HTML 实体（`&lt;` `&gt;` `&amp;` `&quot;` `&nbsp;`）全部解码
- 参考 `references/blog-site-extraction.md` 获取完整提取逻辑和 Python 代码模板

**兜底方案：用 browser-act 渲染抓取**
- 若 HTML 中也没有 `content_noencode`，使用 browser-act 的 `stealth-extract` 命令渲染页面后提取：
  ```bash
  browser-act stealth-extract "{url}" --content-type markdown
  ```
- browser-act 会启动真实浏览器引擎渲染 JavaScript，绕过反爬验证，返回 markdown 格式的内容
- 注意：browser-act 需要预先安装（`uv tool install browser-act-cli --python 3.12`）并配置 API key，否则此步骤会报错

**彻底失败**
- 若以上方法都无效，才判断为真正不可抓取的页面，删除文件并告知用户

### 第 2 步：description 校验与补全

postprocess.py 检测到 frontmatter 中 `description:` 为空时会输出 `⚠️ 需 AI`。

**注意三个不同故障模式**：
1. **空 description**（`description: `）—— 微信文章 OG meta 不含摘要，由 AI 根据标题和首段补 30~60 字描述。
2. **错 description**（`description:` 有值但与文章无关）—— 微信文章 OG meta description 有时来自发布者的公众号简介/签名语，与正文毫无关系（如某期货文章被填成佛教语录）。**此时同样需 Agent 手动重写**，不要用抓到的描述直接入库。
3. **截断 description**（有值且主题相关，但句子在半途被切断）—— 微信 OG meta 描述长度有限会被截断（实战 2026-08-08：`…包含文字处理、表格、演` 在「演示文稿」的「演」字处戛然而止）。**判定**：主题一致但结尾无终止标点、停在词/短语中间。**处理**：同样手动重写完整 30~60 字描述，不要留截断文本入库。

**判断标准**：读 description 是否和文章标题/首段主题一致。不一致即视为「错」，按以下格式重写：
```markdown
description: <30~60 字，概括文章核心论点>
```

### 第 3 步：复杂 Markdown 修复（postprocess 无法判定的语义型问题）

postprocess.py 已处理固定模式；以下场景需要 Agent 按上下文语义判断，参考对应 reference 文档：

- **表格数据重建**：WeChat HTML 表格转成 inline `**value**` 分隔文本行，需识别列结构重建为 GFM pipe table。**postprocess.py 现已自动检测此类被压平行并输出 `⚠️ 需 AI` 提示**（签名：行内无 `|`、长度 > 40、含 ≥2 个 `%` 且存在 `**`）；Agent 在报告中看到该提示即按语义重建为 GFM pipe table，列边界判定需结合上下文。详见 SKILL.md 原文表格节（保留在 git 历史）
- **无分隔符内联数据表修复**：纯文本行列表头/值直接拼接，需用后一列表头文字作为分隔锚点推断列边界
- **表格分隔线列数修正**：转换后 `|---|---|` 列数不匹配表头，逐一核对后重建分隔线
- **表格结尾粘连处理**：表格末行后接正文文字（`| +32.20%沪深300上的提升尤为显著`），需在表格行后补空行分离正文
- **表格末行单元格粘连变体**：`| 工作区工具 |命名上 Open Tag`（`|` 后无换行直接接文字）→ 插入 `\n\n`
- **商品卡片字段分隔符重建**：`field**value1**field2**value2` 扁平行文（** 用作字段分隔而非加粗），需按已知字段名（`项目详情`、`免费额度`、`代表模型`、`注册入口` 等）拆分。详见 `references/product-card-fields.md`
- **标题层级修复**：NBSP 占位的空 `#  ` 标题在 NBSP 清除后变成纯空格标题，需结合上下文判断正确层级（如应降为 `##` 而非 `#`）
- **编号内容标签升级**：`**技术版**` `**小白版**` 等步骤类标签跟在"下面正式开始"等转场句后 → 格式化为 `### 技术版`（保持层次，不用 `##`）
- **数学符号占位符残留**：部分 WeChat 量化/数学文章用 NBSP 代替希腊字母（β、λ、θ 等），NBSP 清除后正文中残留孤立空格（如 `把信号 拉长`）。**不要试图用空格位置推测原始符号**（容易猜错引入误导），在回复中告知用户"本文含数学公式符号，HTML→Markdown 转换中希腊字母等符号已丢失，建议对照原文"
- **公式整体被抹除的签名家族**（实战 2026-08-07，横截面 R² 文章）：公式若以 MathML/SVG/公式图片渲染，会被 `<[^>]+>` 通用抹平整段删掉，不只丢希腊字母，**数值也一起丢**。特征签名：
  - 句中空白 + 孤儿标点：`二者相乘得到 ，市场几乎完全解释`、`TSR = 0.48, RSR = 1.93, ；`（值丢失留下 `, ；`）
  - **图注尾部孤儿 `*`**：`获得最大 。*`、`跨越更高的  等值线。*`——图注原为斜体 `*图：…R²。*`，公式被删后开头 `*` 也随之丢失，只剩结尾孤儿 `*`。修复：直接删尾部 `*`（`。*` → `。`），不要试图补回斜体
  - **参考文献期刊斜体残骸**：`Working Paper*.`、`Journal of Financial Economics*, 96(2)`——期刊名原为 `*Journal*` 斜体，开头 `*` 丢失。修复：按引用格式补全为 `*Working Paper*.`、`*Journal of Financial Economics*, 96(2)`（期刊名/文献类型包进 `*...*`，这是安全修复，非臆测）
  - **纪律**：丢失的数值与符号一律不臆测补回，在回复中明确告知用户哪些位置丢公式；但「删孤儿 `*`」「补期刊斜体」属确定性清理，可以做
- **box-drawing 流程图（┌──┬──┐ 字符画）不是 GFM 表格**：部分微信文章把流程图/架构图渲染成 box-drawing 字符（`┌─┬─┐`/`│阶段│说明│`/`└─┴─┘`），既不是 HTML `<table>`（scraper 不转），也不含 `%`（postprocess 的「压平表格检测」也漏掉）。这种字符画在 Obsidian 里显示为乱码宽字符块，**必须手动按语义转为 pipe 表**（`| 阶段 | 说明 |` + `|---|---|` + 数据行，前后留空行）。可复用的转换函数与判定规则见 `references/wechat-boxdrawing-flowchart.md`。**通用 Markdown 表格修复（含 box-drawing / 空格对齐数据表 / 缩进 pipe 表三类 + 列 0 缩进修复 + 字符串替换实操要点）见 `references/markdown-table-repair.md`**。
- **Postprocess 报告"0 项需 AI"≠文件已可发布**：标题+正文粘连、跨段孤儿 `**`（段首有 `**` 但无段末闭合）、引流图片所在营销小节的连带删除等语义型残留，postprocess 无法覆盖。**实战残留样例（postprocess 报告 0 项需 AI 时仍出现）**：`## 功能特性- 手机遥控：浏览器扫码直连…`（标题直接粘连列表首项，须拆为 `## 功能特性\n\n- 手机遥控：…`）；`## 怎么用去 GitHub Releases 下最新版：`（标题粘连后续句子，须拆为 `## 怎么用\n\n去 GitHub Releases 下最新版：`）。**postprocess 跑完后仍须人工通读一遍**。详见 `references/postprocess-residual-bugs.md`。

⚠️ **批量正则编辑正文时严防图片引用损坏（`](path)` 被吞）**：对文章正文做整体正则替换（如给图片后补空行、调整标题前空行）时，若替换串里写了 `]` 但漏掉 `(Clippings/images/xxx.png)`，会静默把 `![hash.png](Clippings/images/hash.png)` 变成 `![hash.png]`，图片引用丢失但正文不报错。**实战（2026-08-06）**：`re.sub(r"\]\(Clippings/images/[^)]+\)\n(### \d\.\d )", r"]\n\n\1", content)` 意图在图片后补空行，实际吞掉 8 处 `](path)`，图片引用从 32 掉到 24。
> **修复**：用 `re.findall(r'!\[([a-f0-9]{32}\.(png|jpg|jpeg))\]\n', content)` 扫描 `![hash]` 后无 `(` 的损坏行，逐条 `replace(f"![{fn}]\n\n", f"![{fn}](Clippings/images/{fn})\n\n")` 补回路径。
> **预防**：任何整体正则编辑后，立刻 `re.findall(r'!\[[a-f0-9]{32}\.(png|jpg|jpeg)\]\(Clippings/images/', content)` 统计引用数并与编辑前对比；发现减少立即排查，不要假设替换只动了目标行。

⚠️ **`execute_code` + `patch` 中文破折号陷阱**：在 `execute_code` 沙箱中使用 `patch()` 工具时，若 `old_string` 参数包含中文破折号 `—`（U+2014 em-dash），Python 沙箱会报 `SyntaxError: invalid character '—' (U+2014)`。这是 Python 字节序列与源码 UTF-8 解析的边界问题。**绕过方法**：使用 `read_file` 获取内容后在 `execute_code` 内部用纯字符串替换（`content.replace(old, new)`），而非通过 `patch()` 工具的参数传递。例如：
```python
f = "Clippings/xxx.md"
with open(f, 'r') as fp:
    content = fp.read()
content = content.replace("形成背景—信息—风险的研究闭环。", "形成背景—信息—风险的研究闭环。\n\n![...]\n")
with open(f, 'w') as fp:
    fp.write(content)
```
⚠️ **批量替换涉及图片行时，替换串必须保留完整图片语法，否则 `(path)` 被静默丢弃（高频、严重）**：用正则处理"图片与标题间插空行""图注与标题拆分"时，若匹配串含 `](Clippings/images/...)` 而替换串只留 `]`（如 `re.sub(r"\]\(Clippings/images/[^)]+\)\n(### \d)", r"]\n\n\1", ...)`），所有命中图片会退化为裸 `![hash.png]`——路径丢失，Obsidian 中图片静默消失（实战事故 2026-08-06：一次损坏 8 张图，靠引用计数 32→24 才发现）。
> - **安全写法**：模式中对图片语法整体设捕获组并在替换串原样回引（`r"(!\[[^\]]+\]\(Clippings/images/[^)]+\))\n(### )" → r"\1\n\n\2"`）；或干脆不让匹配包含图片部分（按标题行定位插空行）。
> - **验证纪律**：对文章内容的**任何**批量编辑后，立即重数图片引用（`re.findall(r'!\[[a-f0-9]{32}\.(?:png|jpg|jpeg)\]\(Clippings/images/', content)` 计数应等于编辑前数量减去有意删除的图）；数量不符必有损坏。图注/标题粘连家族与安全替换写法详见 `references/postprocess-residual-bugs.md` §13–14。

⚠️ **代码块重度损坏（fence 逐行丢失、缩进全丢）** — 微信技术文代码块可能每个代码行都被 `` ` `` 包裹、fence 完全消失，postprocess 的行首修复覆盖不了。**修复：按稳定锚点整体重建代码块**（execute_code 定位起止标记 → 手工恢复缩进与 fence → 整体替换），勿逐行 patch。含验证脚本与伴生残留清理，详见 `references/code-block-heavy-reconstruction.md`。

⚠️ **代码块 fence 被拆分为多个独立 fence** — postprocess.py 有时会将同一个逻辑代码块在多个语言/章节标记处拆开，产生多个独立 fence。**修复**：人工检查相邻 fence 是否属于同一逻辑块，若是则手动合并。详见 `references/code-fence-merge-pitfall.md`。详见 `references/em-dash-patch-pitfall.md`。

⚠️ **代码块 fence 仅修 opening 不修 closing（高频）** — postprocess.py 只负责将行首 language marker（`+Python`/`+Rust`）修复为 ```` ```python` / ```` ```rust` opening fence，**不会自动为每个 opening fence 补 closing ```` ``` ````**。微信代码块常因 inline code 紧贴正文（`return spread`逐块拆解：`）导致 closing fence 缺失，生成"4 个 opening、0 个 closing"的 Markdown，Obsidian 中所有后续内容被当作代码。**修复顺序**：先合并 fence+language 分离 → 再补缺失的 closing fence → 最后合并重复 fence。**必做**：postprocess 完成后，用 `references/code-fence-unclosed-verification.md` 的 fence 配对验证脚本确认 fences 总数为偶数且每对间隔合理，**不要假设 postprocess 已处理好 closing**。

⚠️ **`content_noencode` 模板变量 `{1}` / `{{img_url}}` 字面量残留**：当微信文章 HTML 源码本身包含模板变量（如 `{img_url}`、`{1}`）时，经过 `\\xHH` hex 解码后这些变量会作为字面量 `{1}`、`{{img_url}}` 残留在 Markdown 正文中。常见于代码块内引用 URL 变量的文章（如"addr 就是一个公钥标识"中的 `{1}`）。**修复**：人工搜索 `{1}` 或 `{{img_url}}` 字面量，替换为正确语义（如 ``addr``、`https://...` 等）。

⚠️ **测试/改动 scraper 时严防"假截断"误报，且勿用 div 深度配对替换抽取正则**：
- 核对 js_content 抽取是否截断，必须测【抽取片段自身的纯文本长度】，不要拿它和【整篇 HTML 去标签后的纯文本】比较——`js_content` 之后还有评论/推荐/脚本，会使"仅捕获 0.2%"成为假警报，进而诱导去改本来正确的抽取逻辑（真实案例：某文 js_content 实际 115KB、正文仅 2179 字，全文去标签却有 1.2M 字）。
- 不要为"更稳健"把现有的 `</div>\s*<script` 非贪婪正则换成 `<div>/</div>` 深度配对解析器：微信正文 div 常不平衡（闭合多于开口），深度配对会返回空串 → **空文件**（比截断更糟）。现有正则锚定在正文真实结尾 `</div>` 前的 `<script>`，对两篇真实文章均正确捕获完整 js_content。
- 绕开代理直连测表格转换：`runner.py` 默认 curl 在代理 SSL 故障时 30s 超时（见下方"代理绕过"的 `--noproxy` 提示）。单独验证 `html_table_to_markdown` 时，用 `curl --noproxy '*' -sL -A "Mozilla/5.0 ..." <URL> -o /tmp/page.html` 拉 HTML，抽取所有 `<table>...</table>` 直接喂函数即可，无需跑完整管线。单元格加粗已修：`<strong style=...>` 带属性，正则须 `</?strong[^>]*>`（否则开头 `**` 丢失成孤儿 `**`）。

postprocess.py 完成后再人工排查时，**始终用 `open(path).read()` 获取原始内容**做字符串匹配，不要用 `read_file()` 的输出（带行号前缀 `N|` 与原文件不同），或直接用 `patch()` 工具的 `old_string` + `new_string`。

### 第 4 步：全量视觉筛查与图片嵌入

runner.py 下载的图片**默认全部写入正文**，但 **postprocess.py 不做内容过滤**。因此 Agent 必须对**每一张下载的图片**使用 `vision_analyze` 进行视觉分析，按以下规则分类处理。

> ⚠️ **预筛：统计引用次数分布（在 vision 之前做，可省掉大量冗余调用）**
>
> 微信长文常见一张装饰性分隔图被引用十几次到二十多次。若不加区分对 25 张唯一图逐张 vision，可能有 25+ 次在识别同一张图。
>
> **预筛方法**：先跑一次 `execute_code`，统计正文图片引用次数：
> ```python
> import re
> from collections import Counter
> c = Path("文章.md").read_text(encoding="utf-8")
> refs = re.findall(r'\[([a-f0-9]{32}\.(?:png|jpg|jpeg))\]\(Clippings/images/', c)
> for fname, n in Counter(refs).most_common():
>     print(f"  {n:3d}×  {fname}")
> ```
> - 某文件出现次数≥10 次且明显断层 → **装饰图，直接删除**（跳过 vision）
> - 文件数 ≪ 引用数 → 先删高频装饰图，再逐张 vision 剩余低频文件
- 文件数 ≈ 引用数 → 逐张 vision

> ⚠️ **孤立图片下载残留（2026-08-12 实战）**：runner.py 下载 14 张图片但正文仅嵌入 13 张——第 14 张（`cb50514c...jpg`）无任何 markdown 引用却静默留在 `Clippings/images/`。postprocess.py 的「图片引用统计」只计已嵌入的引用（报 13 处），不报已下载但未引用的孤立文件。**处理**：vision 批筛前，用 `execute_code` 扫描 `Clippings/images/`，比对已下载文件名与正文引用文件名集，差集中的文件即为孤立图——删除它们（`os.remove`），避免误判为"待 vision 的图片"。

详细判定规则与实战案例见 `references/wechat-image-triage.md#统计型预筛`。

**必做：全量视觉筛查**
- 对 `Clippings/images/` 中该文章对应的**所有图片**，逐一调用 `vision_analyze`
- **批量替代（推荐，省上下文）**：20+ 张图时用 `delegate_task` 委托一个子 agent（toolsets `["vision","file"]`）批量筛查，goal 里逐字写明全部绝对路径+判定标准+输出格式，返回紧凑判定表。详见 `references/batch-image-screening-and-orphan-sweep.md`。

> ⚠️ **delegate_task 批量视觉筛图超时陷阱（2026-08-06 实战）**：77 张图委托子 agent 批量 vision 筛查，600s 超时只完成 7 次 API 调用即被中断，未返回任何判定表。**超时原因**：vision_analyze 是慢调用（每张数秒~数十秒），77 张线性串行远超出子 agent 的 600s 时限。**不要对 40+ 张图整体委托一遍**，会白等 10 分钟颗粒无收。
>
> **结构性回退（对研究报告/论文类文章可靠）**：当文章类型决定了图片构成时，跳过全量 vision，只对**边界/可疑图片**做定向 vision，其余按文章结构上下文判定：
> - **正文中部图片**（公式图、回测净值曲线、相关系数热力图、架构图）→ 按文章结构判定为 CONTENT，保留——研究报告几乎不会在正文中部夹装饰图
> - **带图注的图片是最强结构信号**：图片行后紧跟 `图：`/`表：` 说明行的，几乎必为内容图，可直接保留、跳过 vision（实战 2026-08-07：8 张图中 7 张带图注全部命中）；只对**无图注**的文首/文末图片做定向 vision
> - **文首图片**（抓取后正文第一二张，位于摘要/投资要点后）→ 定向 vision，确认是封面图还是内容图
> - **文末图片**（位于"关注公众号/往期链接/风险提示"等促销文本之后）→ 定向 vision，通常为装饰横幅/二维码/风险声明页，判定后删除
> - 判定出 1~2 张可疑后，用 vision_analyze 定向确认即可，不必全部核验
> 此回退在"文章类型预测图片构成"的研报上可靠，且比全量委托快得多；对插图类型不可预测的普通文章仍需逐张/小批量 vision。
- 只有明确判定为「内容图」的图片才保留在正文中
- 以下 6 类图片必须**删除引用 + 删除磁盘文件**：
  1. **封面图**：宽幅海报、品牌 logo、文章题图
  2. **引流图**：带二维码的活动海报、「扫码申请试听」「持有人集合」类私域转化图
  3. **二维码**：纯二维码图片、社群/公众号引流码
  4. **装饰图**：无信息量的装饰性图片、空白分隔符、纯色图
  5. **表情包**：反应梗图（"be like"、电影台词截图、表情包），仅表达情绪无信息量
  6. **风险说明**：底部风险声明、投资提示、免责声明等模板化文本图

**稳健删除写法**（避免「`in` 为真却 `replace` 静默无效果」的假成功）：
```python
img = "![xxxx.jpg](Clippings/images/xxxx.jpg)"
content = content.replace(img, "")            # 整体删除，不依赖前后换行
content = re.sub(r"\n{3,}", "\n\n", content)  # 压缩多余空行
```
不要用 `content.replace(img + "\n\n\n", "\n")` 这类写法——`if img in content` 为真会误报「已移除」，但 `img + 换行序列` 与实际空白行数不匹配时 `replace` 不生效，图片残留。

#### 视觉分析判定标准

使用 `vision_analyze` 时，按以下标准提问：
```
vision_analyze(image_url, "请识别这张图片的类型：是封面图/题图、引流图、二维码、装饰图、表情包、风险说明，还是内容图（数据图表/架构图/流程图/示意图）？请详细描述图中内容。")
```

**保留条件**：只有明确属于「内容图」的才保留，包括：
- 数据图表、架构图、流程图、路线图、对比表、示意图
- 软件界面/功能截图（服务于文章论据）
- 读者评论截图（服务于文章论点）

**删除条件**：属于以下 6 类之一即删除：
- **封面图**：宽幅海报、品牌 logo、文章题图
- **引流图**：带二维码的活动海报、「扫码申请试听」「持有人集合」类私域转化图
- **二维码**：纯二维码图片、社群/公众号引流码
- **装饰图**：无信息量的装饰性图片、空白分隔符、纯色图
- **表情包**：反应梗图（"be like"、电影台词截图、表情包），仅表达情绪无信息量
- **风险说明**：底部风险声明、投资提示、免责声明等模板化文本图

⚠️ **vision_analyze 不可用时的兜底**：当前部分模型（如 sensenova 系列）不支持 image input，调用会返回 `404 - No endpoints found that support image input`，且不会回退到辅助视觉模型。此时无法视觉判定图片类型，按下述兜底处理，并在回复中**明确告知用户「未做视觉确认，请复核图片」**：
  - 基于文章内容判断：若是纯工具/项目介绍、无引流话术，图片大概率为软件截图 → **保留**；
  - 若内容含「关注公众号 / 加群 / 扫码」等引流特征，图片多为二维码/引流图 → **删除**；
  - 不确定时偏向保留，并请用户确认，不要凭空删除内容图。

#### ⚠️ vision 模型配置诊断（2026-08-09 实战，先于兜底判定执行）

当 `vision_analyze` 返回 `404 UnsupportedModel` / `does not support vision` 时，**不要立刻当作"当前模型不支持视觉"而走兜底**。先做两步诊断，常常能直接修好而无需兜底：

1. **直测配置的视觉模型**（绕过 auxiliary 工具，用 curl/API 发 base64 图片确认模型能力）。以火山方舟为例：
   ```bash
   # 从 config.yaml auxiliary.vision 读 provider/model/base_url/api_key
   curl -s -X POST "${VOLCANO_BASE_URL}/chat/completions" \
     -H "Authorization: Bearer ${VOLCANO_API_KEY}" -H "Content-Type: application/json" \
     -d '{"model":"minimax-m3","messages":[{"role":"user","content":[
       {"type":"text","text":"描述这张图"},
       {"type":"image_url","image_url":{"url":"data:image/png;base64,<b64>"}}]}],"max_tokens":100}'
   ```
   返回 200 且能描述内容 → 模型本身支持视觉，问题在调用链路。
2. **检查运行中的 gateway 是否持有旧配置**：磁盘 `config.yaml` 的 mtime 若晚于 gateway 启动时间，运行进程加载的是修改前的配置。`ps aux | grep "<profile> gateway"` 看启动时间，对比 `stat -c '%y' config.yaml`。config 缓存按文件 mtime 自动失效，但**进程启动时已展开/持有旧模型值**时需重启 gateway 才生效：
   ```bash
   systemctl --user restart hermes-gateway-<profile>.service
   ```
   ⚠️ 重启会中断当前会话（agent 运行在该 gateway 内），属需用户确认的操作，不要擅自执行。

**结论**：只有确认「配置的视觉模型本身确实不支持视觉」时，才走上面的结构性兜底判定。多数"vision 失败"其实是**运行中 gateway 的配置滞后**，重启后即恢复正常视觉筛查。

#### 嵌入规则

1. **匹配顺序**：runner 输出中的图片顺序 = 文章中的图片顺序（按文档顺序下载）
2. **定位锚点**：扫描正文中含"图"字的段落（图1、图2、架构图、对比图、示意图），或图片说明文字
3. **无显式图注时**：将图片插入到逻辑节标题之后、相关功能介绍之前
4. **格式**：`![描述文字](../images/文件名.png)`（相对路径）
5. **嵌入后验证**：用 `content.count('![](../images/')` 统计引用数，应与下载的非封面图片数一致

> ⚠️ **图片目录是共用库，严禁全局删除非本文图片**：`Clippings/images/` 是**整个 vault 所有文章共享的图片库**，不是每篇文章独立目录。vision_analyze 判定某图不属于本文（封面/引流/装饰）时，**只能删除正文中对该图的引用（`replace` 掉 markdown 行）+ 从磁盘删除该文件本身**。
>
> **错误做法**：遍历 `os.listdir(images_dir)`，对不在本文引用列表中的文件一律 `os.remove()`。这会删除其他文章的全部配图（真实事故：一次操作误删 3165 张共用图片，大量文章引用断裂）。
>
> **正确做法**：
> ```python
> # 1. 从本文 .md 中提取所有图片引用
> refs = re.findall(r'!\[([a-f0-9]{32}\.(?:png|jpg|jpeg))\]\(Clippings/images/', content)
>
> # 2. 仅对 vision_analyze 判定为"删除"的图片：先删引用再删文件
> for fname in deleted_set:
>     img_markdown = f"![{fname}](Clippings/images/{fname})"
>     content = content.replace(img_markdown, "")
>     if os.path.exists(f"Clippings/images/{fname}"):
>         os.remove(f"Clippings/images/{fname}")
> ```
>
> 视觉判断后如需删除图片，必须**逐张确认**该文件名只在本文被引用，且先移除正文引用再删除磁盘文件。**绝对不要**用 `os.listdir` + `if not in kept: os.remove()` 遍历整个 images/ 目录。

### 第 5 步：生成 LLM 摘要

postprocess.py 不生成摘要。runner.py 内置的 LLM 摘要**偶尔会超时（HTTP 403 或 read timeout）**，此时 Agent 需自行判断是否生成了摘要：

> LLM 调用网络策略：**默认直连（不使用代理）**；若直连因网络/连接/SSL 错误失败，自动回退到环境代理（HTTP_PROXY/HTTPS_PROXY）。认证类错误（401/限流）不会触发代理回退。
>
⚠️ **网络层故障（Network is unreachable）**：当终端同时出现 `LLM 直连失败（Network is unreachable）` 和 `LLM 走代理仍失败: Network is unreachable` 时，说明当前会话进程**完全无法出站访问 LLM API**。此时重跑 runner.py 无效，必须直接进入**手动补摘要**流程。详见 `references/llm-summary-network-fallback.md`。

**摘要处理的三种情况**（按优先级依次检查）：

**① 摘要已生成且干净**：文件中已有 `> 📌 **文章要点**` 段，且每条 `> - ` 开头的内容都是具体的文章要点（非元指令）→ 跳过

**② 摘要已生成但被思维链泄漏污染**（必须做）：文件中有 `> 📌 **文章要点**` 段，但 `> - **` 后面跟的是元指令（Role/Task/Format/Analyze/Thinking Process）而非具体要点。**此时不能跳过**。立即扫描并替换：
- 搜索 `> - **Analyze the Request`、`> - **Role`、`> - **Task`、`> - **Format`、`> - **1.`、`> - **2.`、`> - Thinking Process:`、`> - *   Role:`、`> - **Analyze the Request:**`、`> - *   Task:` 等模式，任一命中即判定为污染
- **关键特征**：`> - **` 后面是元指令关键词（Role/Task/Format/Analyze/Thinking Process）而非具体的文章要点内容
- **修复**：删除被污染的摘要区块，替换为人工生成的 3~5 条具体要点（每条 30~50 字），插入到 frontmatter 之后、正文之前
- 详见 `references/llm-summary-thinking-artifact.md`

**③ 摘要未生成**：文件中无 `> 📌` 段 → Agent 必须手动补摘要，**不要跳过**。插入到 frontmatter 之后、正文之前：

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

**手动摘要规范**：
- 每条 30~50 字，聚焦核心结论、关键数据或方法论
- 用 `> - ` 开头，保持与 runner.py 生成格式一致
- 3~5 条为宜，不超过 6 条
- 不写废话、不重复标题、不加序号

详见 `references/llm-summary-network-fallback.md`（网络不可达时的回退 SOP）与 `references/llm-summary-thinking-artifact.md`（思维链泄漏修复）。

⚠️ **注意**：某些 LLM 模型（如 xunfei/astron-code-latest）在生成摘要时可能把思维链元指令（Role/Task/Format 等）渗入摘要。生成摘要后务必检查 `> - **` 开头的是否为具体要点；发现元指令模式（Role/Task/Format/Analyze/Thinking Process）或 **原始 Prompt 头部泄漏**（`> - **文章要点**\n> - Thinking Process:` / `> - *   Role:` / `> - **Analyze the Request:**` 等提示词模板字段本身被当作要点输出），立即替换为人工要点，3~5 条，30~50 字，聚焦核心结论。

详见 `references/llm-summary-thinking-artifact.md`（思维链泄漏 + 原始 Prompt 头部泄漏两种模式的判定与修复）。

### 第 6 步：llm-wiki 入库（默认执行）

文章入库后**默认调用 llm-wiki skill**，将文中出现的实体和核心概念加入 Clippings wiki 库，无需询问。

执行方式：
1. 加载 `skill_view('llm-wiki')` 获取操作指引
2. 按 llm-wiki 的 Ingest 流程，将文章中的核心实体和概念提炼为 wiki 页面（entities/ concepts/）
3. 更新 index.md 和 log.md
4. 每条 wiki 页面用 `[[wikilinks]]` 与其他页面交叉引用

Wiki 路径：`Clippings/`（与文章目录一致，内含 `raw/articles/`、`entities/`、`concepts/`、`comparisons/`、`queries/`）

⚠️ **文章已自带 frontmatter，llm-wiki 溯源字段不要再加第二个 `---` 块**：link2obsidian 生成的文件头部已有完整 frontmatter（`source/title/description/tags/created/url`）。llm-wiki 的 Ingest 步骤要求补 `ingested/sha256` 溯源字段——**直接追加到现有 frontmatter 内**（如插在 `url:` 行之后），切勿在文件最前面再写一个 `--- ... ---` 块，否则 Obsidian 会把两份 YAML 拼在一起导致解析异常。
  - **正则陷阱**：用 `^---\n(.*?)\n---\n` 切分 frontmatter 时，捕获组末尾的 `url:` 行**没有尾随换行**，因此 `re.sub(r'(url: .*\n)', ...)` 会**静默不匹配**。应锚定 closing `---`，即匹配 `url: ...RuQ---\n` 替换为 `url: ...RuQ\ningested: 2026-07-12\nsha256: <hex>\n---\n`（注意 `ingested` 前**不要**加 `-`，否则 YAML 会把它解析成列表项而非 frontmatter 键值对，导致 Obsidian 解析异常）。
  - `sha256` 计算范围：frontmatter 之后的正文（body），不含 frontmatter 本身。
  - **`.replace('---', ..., 1)` 静默替换开头 `---` 的坑**：用 `re.match(r'^(---\n.*?\n---)\n', content)` 捕获 frontmatter 时，捕获组同时包含开头和结尾的 `---`。随后用 `fm.replace('---', ..., 1)` 注入字段会替换**开头的 `---`**（第一个出现的位置），导致 ingested/sha256 跑到 YAML 之外，而非插入在 url 行之后。正确写法：用正则**锚定结尾 `---`**，例如 `re.sub(r'(\nurl: .+)(\n---)', r'\1\ningested: 2026-08-05\nsha256: ...\n---', fm)`；或者用 `fm.rsplit('\n---', 1)` 分离结尾，插字段后拼接。

**跳过条件**：文章过短（<500 字节）或纯推广/无实质内容时跳过。

详见 `references/post-ingest-verification.md`（入库后文件整理检查清单）。

### 第 7 步：入库后文件整理检查（重要，防止残留）

**问题**：有时文件在 Clippings/ 根目录保留了一份，同时在 raw/articles/ 中另存了一个"英文缩写+日期"的文件名（如 `iroh-p2p-pubkey-20260709.md`）。这导致：
- Clippings/ 根目录残留旧文件（应清空）
- raw/articles/ 文件名与文章标题不一致
- wiki 页面引用路径断裂

**检查方法**：
```bash
cd Clippings
ls *.md  # 应只剩 index.md log.md SCHEMA.md
for f in *.md; do md5sum "$f" "raw/articles/$f" 2>/dev/null; done
grep -rn "英文缩写文件名" entities/ concepts/ comparisons/
```

**修复步骤**：
1. 将 Clippings/ 根目录文件 **移动** 到 raw/articles/（原名，不改名）
2. 删除 raw/articles/ 中旧的英文缩写文件
3. 修复 wiki 页面中的引用路径（更新为文章标题）
4. 删除 Clippings/ 根目录原文件（如果已移动）

### 第 7 步：入库后文件整理检查（重要，防止残留）

**问题**：有时文件在 Clippings/ 根目录保留了一份，同时在 raw/articles/ 中另存了一个"英文缩写+日期"的文件名（如 `iroh-p2p-pubkey-20260709.md`）。这导致：
- Clippings/ 根目录残留旧文件（应清空）
- raw/articles/ 文件名与文章标题不一致
- wiki 页面引用路径断裂

**检查方法**：
```bash
cd Clippings
ls *.md  # 应只剩 index.md log.md SCHEMA.md
for f in *.md; do md5sum "$f" "raw/articles/$f" 2>/dev/null; done
grep -rn "英文缩写文件名" entities/ concepts/ comparisons/
```

**修复步骤**：
1. 将 Clippings/ 根目录文件 **移动** 到 raw/articles/（原名，不改名）
2. 删除 raw/articles/ 中旧的英文缩写文件
3. 修复 wiki 页面中的引用路径（更新为文章标题）
4. 删除 Clippings/ 根目录原文件（如果已移动）

- See references/post-ingest-verification.md.

## References

- references/single-source-tool-workflow.md — 单篇文章引入工具+方法论文档
- references/wechat-title-and-heading-postprocessing.md — runner/postprocess 后常见的标题/正文粘连、标题内残留 `/Prototype` 等非语义斜杠、以及代码块 fence 语言标识分离残留。
- references/code-fence-unclosed-verification.md — postprocess 只修 opening fence 不修 closing 的配对验证脚本与修复 SOP
- references/code-fence-heading-swallow.md — URL 行尾反引号吞掉下一行 `## 02`/`## 03` 等章节标题的检测与修复
- references/vision-model-verification.md — vision_analyze 报 `404 UnsupportedModel` 时先 curl 探测配置模型视觉能力，并排查「配置模型 ≠ 运行时模型」的配置漂移
- references/wechat-inline-code-and-heading-artifacts.md — 行内代码首尾空格 + 全角标点前空格清理、`## 参考`/孤立「资料」标题残留、断言标点差异陷阱
- references/github-repo-ingest.md — GitHub 仓库链接入库流程（区别于网页文章）：clone → 存本地参考目录 → 提炼 README 成 raw article → 建实体页 → 更新 index/log。runner.py 的 js_content 抽取不适用仓库链接

## 代理绕过（重要）

Hermes 默认走 `https_proxy`（Clash 127.0.0.1:7897）连接外网。部分环境（尤其是 Clash 代理）连接 mp.weixin.qq.com 时会遇到 `SSL_ERROR_SYSCALL` 或 `net::ERR_CONNECTION_CLOSED`。

**curl 下载时加 `--noproxy '*'` 强制直连，可绕过代理失败：**

```bash
curl -sL --noproxy '*' \
  -A "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36" \
  "https://mp.weixin.qq.com/s/ARTICLE_ID" -o /tmp/page.html
```

**失败判断标准：**
- 代理正常时：`grep -c 'content_noencode' page.html` 应有结果
- 代理失败（SSL_ERROR_SYSCALL）：curl 返回空文件或非 HTML 错误页面
- browser 工具同样可能遇到 `ERR_CONNECTION_CLOSED`，此时应放弃 browser，改用 `--noproxy '*'` curl 直连

**建议策略：** 先用默认代理 curl；若 HTML 为空或 `<500 字节`，改用 `--noproxy '*'` 重试一次。

**运行 `runner.py` 本身也要绕代理**：`runner.py` 内部用 `curl` 拉 HTML + 下载图片，同样会撞代理 SSL 超时（返回空文件、30s 超时、图片全失败）。直接给 runner 进程注入 `no_proxy`/`NO_PROXY` 环境变量，让微信域名（含 `mmbiz.qpic.cn` 图片）直连，而 LLM API 仍走代理：

```bash
cd ~/.hermes/profiles/ob_xianzi/skills/note-taking/link2obsidian
no_proxy='mp.weixin.qq.com,mmbiz.qpic.cn' NO_PROXY='mp.weixin.qq.com,mmbiz.qpic.cn' \
  python3 runner.py "https://mp.weixin.qq.com/s/ARTICLE_ID"
```

⚠️ 图片下载走 `mmbiz.qpic.cn`，**务必把该域名也列入 `no_proxy`**，否则图片仍经代理 → SSL 失败导致 0 图下载。

## 注意事项

1. **环境异常页面** — 微信返回的验证页面中正文仍在 `<div id="js_content">`，正常提取
2. **Vue.js SPA 新版本** — 新版微信文章使用 Vue.js 动态渲染，正文不在 HTML 中。详见 `references/wechat-vue-spa-extraction.md`（含 JsDecode 解码函数和完整提取流程）
3. **代码块 fence 退化** — WeChat 文章的代码块 ``` 标记常退化为单 `。postprocess.py 已自动处理常见模式（Rust/Python/Bash/中文/ASCII 流程图），详细模式分类见 `references/wechat-codeblock-fence-patterns.md`，疑难场景由 Agent 手动排查
4. **SKILL.md 代码隔离** — Python 执行代码存储在 `scripts/wechat_scraper.py`，SKILL.md 只含文档。若 runner.py 报错"未找到 Python 代码块"，执行 `git checkout HEAD -- SKILL.md` 恢复
5. **qpic.cn 防盗链** — 图片下载必须带 cookie jar + `Referer: https://mp.weixin.qq.com/`，缺一不可
6. **Vue SPA HTML 内容格式** — 部分 Vue SPA 的 `content_noencode` 经 jsdecode 后是 HTML 标签文本（非纯文本），需要用 `WeChatHTMLToMarkdown` 转换器。详见 `references/wechat-html-to-markdown-converter.md`
6. **Token 过期** — qpic.cn 图片 URL 有时效性 token，代码内置自动重试
7. **桌面 UA** — 必须使用桌面版 Chrome User-Agent，移动 UA 触发更严的验证
8. **NBSP 残留** — postprocess.py 已自动清除 `\xa0`，复杂场景（数学符号占位）见第 3 步说明
9. **多重替换陷阱** — postprocess.py 在单次执行中按依赖顺序串行应用所有替换，避免多轮编辑中后续替换旧字符串失效。Agent 在 postprocess 之后手动排查时若发现替换匹配全部失效，用 `open(path).read()` 重新加载当前文件内容

## SKILL.md 自检与修复

若 `runner.py` 报错「未找到 Python 代码块」，说明本文件 `SKILL.md` 的 `~~~python` 代码块缺失闭合标记或内容被截断。此时按以下步骤恢复：

1. 用全局技能副本覆盖 profile 本地副本：
   ```bash
   cp ~/.hermes/skills/note-taking/link2obsidian/SKILL.md \
      ~/.hermes/profiles/ob_xianzi/skills/note-taking/link2obsidian/SKILL.md
   ```
2. 重新执行 `runner.py`

> 注意：若全局技能版本也不完整，需从 Hermes 上游或备份恢复完整代码块。

详见 `references/runner-local-skill-drift.md`（症状、根因、修复命令、验证方法）。

### 图片下载降级策略（微信文章）

qpic.cn 图片有严格反盗链，curl/wget 直连均返回 HTTP 400（`x-errno: -106`）。按以下优先级依次尝试：

**方案 1：browser-act（browser-act stealth-extract）**
- 启动 browser-act 浏览器后使用 `stealth-extract` 或 `navigate` 打开文章页面，然后提取页面内容
- browser-act 需要预先安装（`uv tool install browser-act-cli --python 3.12`），且 `chrome-direct` / `chrome` 模式可能因 Chrome IPC 连接失败而不可用（`Error 230322`）

**方案 2：Playwright（推荐，最可靠）**
- 当 browser-act 不可用时，用 Playwright 直接操作浏览器，通过 `page.evaluate()` + `fetch()` 复用浏览器 cookies 下载图片：
  ```python
  from playwright.sync_api import sync_playwright
  import base64, re

  with sync_playwright() as p:
      browser = p.chromium.launch()
      context = browser.new_context()
      page = context.new_page()
      page.goto(WECHAT_ARTICLE_URL, timeout=20000, wait_until="domcontentloaded")
      page.wait_for_timeout(3000)

      # 从 HTML 提取所有 mmbiz 图片 URL
      html = page.content()
      img_urls = re.findall(r'https?://mmbiz\.qpic\.cn/[^\"\'\s\)]+', html)
      # 去重（保留顺序）
      seen = set()
      unique = []
      for u in img_urls:
          u = u.strip()
          if u not in seen:
              seen.add(u)
              unique.append(u)

      # 逐张下载
      for i, img_url in enumerate(unique):
          b64 = page.evaluate(f'async () => {{ const r = await fetch("{img_url}"); const b = await r.arrayBuffer(); const bytes = new Uint8Array(b); let bin=""; for(let i=0;i<bytes.length;i++) bin+=String.fromCharCode(bytes[i]); return btoa(bin); }}').strip()
          img_data = base64.b64decode(b64)
          ext = '.jpg' if ('jpeg' in img_url or 'jpg' in img_url) else ('.png' if 'png' in img_url else ('.gif' if 'gif' in img_url else '.jpg'))
          fname = f"article_img_{i:03d}{ext}"
          with open(f"Clippings/images/{fname}", 'wb') as f:
              f.write(img_data)
          print(f"  ✅ {fname}: {len(img_data)} bytes")
  ```
- **原理**：`page.evaluate()` 中的 `fetch()` 运行在浏览器上下文中，自带页面 cookies 和 headers，不受 qpic.cn 反盗链限制
- **注意事项**：
  - `http://mmbiz.qpic.cn`（非 https）的图片可能会 `fetch` 失败，此时跳过即可，不影响正文图片
  - 正文图片通常都来自 `https://mmbiz.qpic.cn`，成功率接近 100%
  - GIF 动图也支持下载（文件较大，约 2MB）
  - Playwright 使用 `p.chromium.launch()` 即可，无需额外安装浏览器（自带 Chromium）
