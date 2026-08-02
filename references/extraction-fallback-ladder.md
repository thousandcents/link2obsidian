# 微信文章提取降级阶梯（Extraction Fallback Ladder）

当 `runner.py` / `web_extract` / `browser` 依次失效时，按本阶梯降级提取正文。

## 触发信号

- `web_extract` 返回截断内容（正文中途截止，通常 < 3000 字）
- `browser_navigate` 进入「环境异常」验证页（CAPTCHA / 环境检测）
- `runner.py` 因代理 SSL 超时返回空文件
- `runner.py` 执行超时（Command timed out after 120s）——此时 runner 本身未产出文件，需手动接管提取

## 降级顺序

### 1. web_extract（默认）

最廉价，优先调用。若返回内容明显截断（对比文中已知结构如「1. 近亲变量」等小节缺失），立即放弃本方法。

### 2. browser_navigate（交互）

若 web_extract 截断，尝试 browser 渲染。**若命中 CAPTCHA / 「环境异常」页面，立即放弃**——继续 click/snapshot 只会浪费时间。

### 3. terminal Python requests（最可靠的兜底）

用 `requests.get` + 桌面 Chrome UA 直连，绕过代理 SSL 问题：

```python
import requests, re, html

url = "https://mp.weixin.qq.com/s/ARTICLE_ID"
headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}
resp = requests.get(url, headers=headers, timeout=30)
html_text = resp.text

# 提取 js_content（优先用 </div>\s*<script 锚定的非贪婪正则）
m = re.search(r'<div[^>]*id="js_content"[^>]*>(.*?)</div>\s*<script', html_text, re.S)
if m:
    raw = m.group(1)
    # 去标签 + unescape
    text = re.sub(r'<[^>]+>', '', raw)
    text = html.unescape(text)
    print(f"extracted {len(text)} chars")
```

**关键参数**：
- `timeout=30`：微信页面约 2-3MB，30 秒足够
- `Accept-Language: zh-CN`：避免跳转国际化版本
- 正则 `</div>\s*<script`：锚定正文真实结尾，比纯 `</div>` 更可靠

### 4. 代理直连（当 requests 也超时时）

若第 3 步也失败（环境异常 / SSL 错误），加 `--noproxy '*'` 或设置 `no_proxy` 环境变量绕过 Hermes 默认代理：

```bash
curl -sL --noproxy '*' \
  -A "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36" \
  "https://mp.weixin.qq.com/s/ARTICLE_ID" -o /tmp/page.html
```

## 已失效的方法

- `browser-act stealth-extract`：Chrome IPC 连接失败（Error 230322）时不可用
- `web_extract` 对微信文章存在 5000 字符截断上限，大文章必然丢失后半部分

## runner.py 超时后的手动接管提取

当 `runner.py` 因大文件/网络慢导致 **Command timed out** 时，可按以下顺序手动提取：

### 1. 用 curl 下载原始 HTML

```bash
curl -sL --noproxy '*' \
  -A "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36" \
  "https://mp.weixin.qq.com/s/ARTICLE_ID" -o /tmp/wechat_article.html
wc -c /tmp/wechat_article.html
```

若文件 < 500KB 或返回空白，说明下载失败，先解决网络/代理问题。

### 2. 用 execute_code 执行完整提取逻辑

将 `runner.py` 内的 Python 逻辑（元数据提取、图片下载、HTML→Markdown 转换）直接写入 `execute_code`：

```python
import re, os, hashlib, subprocess, html as html_mod
from datetime import datetime
from pathlib import Path

WORKDIR = Path("/home/jack-lin-sparrow/Obsidian/Thousand")
CLIPPINGS_DIR = WORKDIR / "Clippings"
IMAGES_DIR = CLIPPINGS_DIR / "images"
HTML_PATH = Path("/tmp/wechat_article.html")

# 读取 HTML
html = HTML_PATH.read_text(encoding="utf-8", errors="replace")

# 提取元数据
m = re.search(r'<meta[^>]*property="og:title"[^>]*content="([^"]*)"', html)
title = html_mod.unescape(m.group(1)).strip() if m else "未知标题"
# ... 其余逻辑同 runner.py
```

**关键点**：
- 图片下载时用 `no_proxy='mp.weixin.qq.com,mmbiz.qpic.cn'` 环境变量绕过代理
- 使用 `--noproxy '*'` curl 下载图片，避免 qpic.cn 防盗链 + 代理 SSL 双重失败
- 保存到 `Clippings/` 根目录，后续再由 Agent 执行 postprocess + 入库流程

### 3. 恢复标准流程

手动提取完成后，文件会出现在 `Clippings/<title>.md`，继续执行：
1. `postprocess.py` 后处理
2. 补全 `description` + LLM 摘要
3. 图片视觉确认（封面图删除、内容图保留）
4. `mv` 到 `raw/articles/` + 补 frontmatter 溯源字段
5. llm-wiki 入库决策

## 后续处理

提取到正文后，仍需执行：
1. 图片下载与分类（见 `wechat-image-triage.md`）
2. Markdown 清理（见 `wechat-markdown-manual-repair.md`）
3. NBSP 归一化：`content.replace('\xa0', ' ')`
