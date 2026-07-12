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

    # 1) 默认直连
    try:
        return _parse(no_proxy_opener.open(req, timeout=60))
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
    except Exception as e_direct:
        # 2) 直连失败（网络/连接/超时/SSL 等）→ 回退走代理
        print(f"  ℹ️ LLM 直连失败（{e_direct}），回退走代理重试...")
        try:
            return _parse(proxy_opener.open(req, timeout=60))
        except Exception as e_proxy:
            print(f"  ⚠️ LLM 走代理仍失败: {e_proxy}")
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
   - 兜底：连续 4+ 星号 → `**`（覆盖 overlapping fix 产生的 `****`）
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
6. **代码块/反引号修复**
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

### 第 2 步：空 description 补全（仅当 postprocess 报告提示）

postprocess.py 检测到 frontmatter 中 `description:` 为空时会输出 `⚠️ 需 AI`。Agent 此时根据文章标题和首段内容生成 30~60 字的描述，写入 frontmatter `description:` 字段。

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
- **box-drawing 流程图（┌──┬──┐ 字符画）不是 GFM 表格**：部分微信文章把流程图/架构图渲染成 box-drawing 字符（`┌─┬─┐`/`│阶段│说明│`/`└─┴─┘`），既不是 HTML `<table>`（scraper 不转），也不含 `%`（postprocess 的「压平表格检测」也漏掉）。这种字符画在 Obsidian 里显示为乱码宽字符块，**必须手动按语义转为 pipe 表**（`| 阶段 | 说明 |` + `|---|---|` + 数据行，前后留空行）。可复用的转换函数与判定规则见 `references/wechat-boxdrawing-flowchart.md`。

⚠️ **`execute_code` + `patch` 中文破折号陷阱**：在 `execute_code` 沙箱中使用 `patch()` 工具时，若 `old_string` 参数包含中文破折号 `—`（U+2014 em-dash），Python 沙箱会报 `SyntaxError: invalid character '—' (U+2014)`。这是 Python 字节序列与源码 UTF-8 解析的边界问题。**绕过方法**：使用 `read_file` 获取内容后在 `execute_code` 内部用纯字符串替换（`content.replace(old, new)`），而非通过 `patch()` 工具的参数传递。例如：
```python
f = "Clippings/xxx.md"
with open(f, 'r') as fp:
    content = fp.read()
content = content.replace("形成背景—信息—风险的研究闭环。", "形成背景—信息—风险的研究闭环。\n\n![...]\n")
with open(f, 'w') as fp:
    fp.write(content)
```
⚠️ **代码块 fence 被拆分为多个独立 fence** — postprocess.py 有时会将同一个逻辑代码块在多个语言/章节标记处拆开，产生多个独立 fence。**修复**：人工检查相邻 fence 是否属于同一逻辑块，若是则手动合并。详见 `references/code-fence-merge-pitfall.md`。详见 `references/em-dash-patch-pitfall.md`。

⚠️ **`content_noencode` 模板变量 `{1}` / `{{img_url}}` 字面量残留**：当微信文章 HTML 源码本身包含模板变量（如 `{img_url}`、`{1}`）时，经过 `\\xHH` hex 解码后这些变量会作为字面量 `{1}`、`{{img_url}}` 残留在 Markdown 正文中。常见于代码块内引用 URL 变量的文章（如"addr 就是一个公钥标识"中的 `{1}`）。**修复**：人工搜索 `{1}` 或 `{{img_url}}` 字面量，替换为正确语义（如 ``addr``、`https://...` 等）。

⚠️ **测试/改动 scraper 时严防"假截断"误报，且勿用 div 深度配对替换抽取正则**：
- 核对 js_content 抽取是否截断，必须测【抽取片段自身的纯文本长度】，不要拿它和【整篇 HTML 去标签后的纯文本】比较——`js_content` 之后还有评论/推荐/脚本，会使"仅捕获 0.2%"成为假警报，进而诱导去改本来正确的抽取逻辑（真实案例：某文 js_content 实际 115KB、正文仅 2179 字，全文去标签却有 1.2M 字）。
- 不要为"更稳健"把现有的 `</div>\s*<script` 非贪婪正则换成 `<div>/</div>` 深度配对解析器：微信正文 div 常不平衡（闭合多于开口），深度配对会返回空串 → **空文件**（比截断更糟）。现有正则锚定在正文真实结尾 `</div>` 前的 `<script>`，对两篇真实文章均正确捕获完整 js_content。
- 绕开代理直连测表格转换：`runner.py` 默认 curl 在代理 SSL 故障时 30s 超时（见下方"代理绕过"的 `--noproxy` 提示）。单独验证 `html_table_to_markdown` 时，用 `curl --noproxy '*' -sL -A "Mozilla/5.0 ..." <URL> -o /tmp/page.html` 拉 HTML，抽取所有 `<table>...</table>` 直接喂函数即可，无需跑完整管线。单元格加粗已修：`<strong style=...>` 带属性，正则须 `</?strong[^>]*>`（否则开头 `**` 丢失成孤儿 `**`）。

postprocess.py 完成后再人工排查时，**始终用 `open(path).read()` 获取原始内容**做字符串匹配，不要用 `read_file()` 的输出（带行号前缀 `N|` 与原文件不同），或直接用 `patch()` 工具的 `old_string` + `new_string`。

### 第 4 步：嵌入图片（默认自动）

runner.py 下载的图片**默认全部嵌入正文**（封面图除外）。postprocess.py 仅负责**修正已存在图片引用的路径**（`images/` → `Clippings/images/`），不负责插入图片到正文。

**当 postprocess 报告出现 `⚠️ 需 AI：正文未引用任何图片——默认自动按图注嵌入` 时，Agent 必须手动嵌入图片。**

> ⚠️ **postprocess 会无差别嵌入所有图片（含引流二维码图）**：`runner.py` 默认把每张 qpic.cn 图都写入正文，`postprocess.py` 只修正路径、不做内容过滤。因此正文首图常是**知识星球/公众号引流二维码**——这不属于「内容图」，按下方封面图识别规则判定为二维码/装饰图后应**手动删除**，不要保留。
> **稳健删除写法**（避免「`in` 为真却 `replace` 静默无效果」的假成功）：
> ```python
> img = "![xxxx.jpg](Clippings/images/xxxx.jpg)"
> content = content.replace(img, "")            # 整体删除，不依赖前后换行
> content = re.sub(r"\n{3,}", "\n\n", content)  # 压缩多余空行
> ```
> 不要用 `content.replace(img + "\n\n\n", "\n")` 这类写法——`if img in content` 为真会误报「已移除」，但 `img + 换行序列` 与实际空白行数不匹配时 `replace` 不生效，图片残留。

#### 封面图识别（用 vision_analyze）

第一张图片通常是封面图，需通过视觉判断：
```
vision_analyze(image_url, "是封面图/题图（海报、无文字装饰图）还是文章中的架构图/流程图？如果是架构图/流程图，请描述图中展示的内容。")
```
- **封面图**：宽幅海报、品牌 logo、二维码、装饰性图片 → **跳过，不嵌入**
- **内容图**：架构图、流程图、对比表、示意图、数据图 → **嵌入**

⚠️ **vision_analyze 不可用时的兜底**：当前部分模型（如 sensenova 系列）不支持 image input，调用会返回 `404 - No endpoints found that support image input`，且不会回退到辅助视觉模型。此时无法视觉判定封面/二维码图，按下述兜底处理，并在回复中**明确告知用户「未做视觉确认，请复核图片」**：
  - 基于文章内容判断：若是纯工具/项目介绍、无引流话术，图片大概率为软件界面/功能截图 → **保留**；
  - 若内容含「关注公众号 / 加群 / 扫码」等引流特征，首图多为二维码/引流图 → 按下方稳健写法**删除**；
  - 不确定时偏向保留，并请用户确认，不要凭空删除内容图。

#### 嵌入规则

1. **匹配顺序**：runner 输出中的图片顺序 = 文章中的图片顺序（按文档顺序下载）
2. **定位锚点**：扫描正文中含"图"字的段落（图1、图2、架构图、对比图、示意图），或图片说明文字
3. **无显式图注时**：将图片插入到逻辑节标题之后、相关功能介绍之前
4. **格式**：`![描述文字](../images/文件名.png)`（相对路径）
5. **嵌入后验证**：用 `content.count('![](../images/')` 统计引用数，应与下载的非封面图片数一致

### 第 5 步：生成 LLM 摘要

postprocess.py 不生成摘要。runner.py 内置的 LLM 摘要**偶尔会超时（HTTP 403 或 read timeout）**，此时 Agent 需自行判断是否生成了摘要：

> LLM 调用网络策略：**默认直连（不使用代理）**；若直连因网络/连接/SSL 错误失败，自动回退到环境代理（HTTP_PROXY/HTTPS_PROXY）。认证类错误（401/限流）不会触发代理回退。

- **摘要已生成**：文件中已有 `> 📌 **文章要点**` 段 → 跳过
### 第 5 步：生成 LLM 摘要

postprocess.py 不生成摘要。runner.py 内置的 LLM 摘要**偶尔会超时（HTTP 403 或 read timeout）**，此时 Agent 需自行判断是否生成了摘要：

- **摘要已生成**：文件中已有 `> 📌 **文章要点**` 段 → 跳过
- **摘要未生成**：文件中无 `> 📌` 段 → Agent 自行生成 3~5 条核心要点摘要

- 生成方式：Agent 自身读取 Markdown 全文，用 LLM 能力生成要点，插入到 frontmatter 之后、正文之前：

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

每条要点 30~50 字，聚焦核心结论而非过程描述。

⚠️ **注意**：某些 LLM 模型（如 xunfei/astron-code-latest）在生成摘要时可能把思维链元指令（Role/Task/Format 等）渗入摘要。生成后务必检查 `> - **` 开头的是否为具体要点，发现元指令模式立即替换。详见 `references/llm-summary-thinking-artifact.md`。

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

详见 `references/post-ingest-verification.md`。

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
