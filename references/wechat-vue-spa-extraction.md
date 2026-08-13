# Vue.js SPA 微信文章提取指南（2026年版）

## 背景

2026年起，部分微信公众号文章使用 Vue.js 动态渲染。传统基于 `<div id="js_content">` 的提取方式对这类页面无效——runner.py 生成的 Markdown 文件为空壳（< 500 字节），仅有 frontmatter 无正文。

## 诊断方法

runner.py 输出 `<500 字节` 文件后，用 curl 下载原始 HTML：

```bash
curl -s -L \
  -A "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36" \
  -H "Accept: text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8" \
  -H "Accept-Language: zh-CN,zh;q=0.9,en;q=0.8" \
  -H "Referer: https://mp.weixin.qq.com/" \
  "https://mp.weixin.qq.com/s/ARTICLE_ID"
```

检查 HTML 中是否存在 Vue.js SPA 特征：`grep -c 'content_noencode' page.html`（>0 即为 SPA）。

## ⚠️ SPA 页面 runner.py 也可能抓全：先做指纹比对，再决定是否重抓

**实战 2026-08-08（GenOffice 文章）**：页面含 `content_noencode`（SPA 签名），但 runner.py 的 `js_content` 正则**照样完整抓到了正文**（文件 1.8KB、正文齐全）。原因：部分 SPA 页面同时保留了 `js_content` div，runner 不需要 JsDecode 就能成功。

**因此：发现 SPA 签名 ≠ 必须走 JsDecode 重抓。** 当 runner 输出 >500 字节但偏小、疑似截断时，先解码 `content_noencode` 做**纯文本指纹比对**，确认覆盖度后再决定：

```python
import re, html as html_mod
# 1) JsDecode 解码 content_noencode（见下文 Step 2）得到 decoded HTML
text = re.sub(r'<[^>]+>', '', decoded)
text = html_mod.unescape(text).replace('&nbsp;', ' ')
text = re.sub(r'\s+', '', text)                    # 去全部空白 → 原文指纹

# 2) md 正文同样处理（去掉 frontmatter、LLM 摘要块、图片引用、格式符号）
body = md_content.split('---\n\n', 2)[-1]
body = re.sub(r'> 📌 \*\*文章要点\*\*\n(?:> - .*\n)+', '', body)
md_text = re.sub(r'!\[[^\]]*\]\([^)]*\)', '', body)
md_text = re.sub(r'[#*`|\->\s]', '', md_text)

# 3) 滑窗找原文中有而 md 中没有的片段
W = 30
missing = [text[i:i+W] for i in range(0, len(text)-W, 15) if text[i:i+W] not in md_text]
print(len(text), len(md_text), len(missing))
for s in missing[:10]: print("  缺失:", s)
```

**判定**：
- 长度差 ~1-2% 且缺失片段均可解释为格式噪声（URL 前后缀、表格单元格边界、全/半角标点、标题与正文的拼接顺序差异）→ **内容完整**，保留 runner 输出，只做语义修复（标题粘连、fence 等），**不要重抓**
- 大段连续缺失 → 真截断，走下方 JsDecode 提取流程

> 该比对同时适用于任何「怀疑正文不完整」的场景，不限于 SPA 页面。

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

## 提取流程

### Step 1: 找到 content_noencode

Vue.js 页面在 `<script>` 标签的 `cgiDataNew` 对象中存储文章数据：
- 标题: `title: JsDecode('...')` 或 `<title>` 或 `og:title`
- 正文: `content_noencode: JsDecode('...')`
- 作者: `nick_name: JsDecode('...')`
- 时间: `create_time: JsDecode('...')`
- 描述: `window.desc = "..."`（已部分解码）
- 全文仅含纯文本，无图片、格式、富文本

### Step 2: JsDecode 解码（推荐：正则统一解码）

旧版 jsdecode 使用 `val.replace('\\x5c', '\\')` 等逐个替换，只覆盖 `\\x5c / \\x0d / \\x22 / \\x26 / \\x27 / \\x3c / \\x3e / \\x0a` 等少量已知 hex 转义。遇到其他 `\xHH`（如 `\x30`~`\x39`、`\x41`~`\x5a`、`\x61`~`\x7a`）会漏解。

**推荐正则统一解码（覆盖全部 \xHH）：**

```python
import re

def jsdecode(val):
    if not val:
        return val
    # 先处理 \\x5c（即字符串中的字面 \ 字符，会被后续 hex 解码误用）
    val = val.replace('\\\\x5c', '\\\\')
    # 正则统一解码剩余的所有 \xHH hex 转义
    def repl(m):
        return chr(int(m.group(1), 16))
    val = re.sub(r'\\\\x([0-9a-fA-F]{2})', repl, val)
    return val
```

**两种模式的区别（易混淆点）：**

| 模式 | HTML 源码中的样子 | Python 字符串中的样子 | 正则匹配 |
|------|-------------------|----------------------|---------|
| 双反斜杠（旧） | `\\x22`（4字符） | `'\\\\x22'`（repr 显示 `\\\\x22`） | `r'\\\\x([0-9a-fA-F]{2})'` |
| 单反斜杠（新） | `\x22`（4字符） | `'\\x22'`（repr 显示 `\\x22`） | `r'\\x([0-9a-fA-F]{2})'` |

**实际诊断方法**：先 `print(repr(val[:100]))` 看 repr 输出。若输出含 `\\x`（两个反斜杠字母x），用双反斜杠正则；若只含 `\x`（一个反斜杠字母x），用单反斜杠正则。

### Step 3: 判断 content_noencode 是纯文本还是 HTML

不是所有 `content_noencode` 都是纯文本。先检查解码后的内容是否包含 HTML 标签：

```python
import re
if re.search(r'<[a-z]+[^>]*>', content):
    # 是 HTML，需要用 HTML→Markdown 转换器
    # 详见 references/wechat-html-to-markdown-converter.md
    pass
else:
    # 是纯文本，可直接作为 Markdown 正文
    pass
```

**典型 HTML 特征**：`<section`、`<blockquote`、`<strong`、`<code` 等标签。

### Step 4: HTML 变体 — 图片 URL 提取

当 `content_noencode` 为 HTML 时，图片 URL 可从中提取：

```python
img_urls = re.findall(r'src="([^"]+)"', decoded_content)
```

这些 URL 通常来自 `https://mmbiz.qpic.cn/...`。下载时参考"图片下载降级策略"。

**⚠️ Playwright 图片下载的 Vue SPA 陷阱**：

Vue.js SPA 的 `<img>` 标签是虚拟 DOM 渲染的，Playwright 的 `page.query_selector_all('img')` 返回空（虚拟 DOM 不会触发 `onload`，也不会注入 `<img>` 到真实 DOM）。

**解决方法**：从原始 HTML 源码（`page.content()`）中用正则提取 `<img src="...">`，然后对每个 URL 调用 `page.evaluate()` + `fetch()` 下载。

参考：SKILL.md "图片下载降级策略"章节。

## 注意事项

1. **文章可能真的很短** — content_noencode 提取的内容可能只有一两句话（推广帖/通知类）。这不代表提取失败。
2. **图片需额外处理** — content_noencode 可能为纯文本（无图片）或 HTML（含图片 src）。纯文本无图；HTML 变体需从标签中提取图片 URL 并手动下载。
3. **标题也需要解码** — 标题字段同样经过 JsDecode 编码。
4. **HTML 约 2MB+** — 大部分为 JS 代码，`curl` 下载时确保不截断。