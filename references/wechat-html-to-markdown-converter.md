# WeChat Vue SPA HTML→Markdown Conversion Guide

## Background

WeChat Vue SPA pages' `content_noencode` field, after jsdecode, may contain two formats:
1. **Plain text** — directly usable
2. **HTML format** — contains `<p>`, `<img>`, `<strong>`, `<em>`, `<code>`, `<pre>`, `<a>`, `<table>` etc.

When `content_noencode` is HTML format, a custom HTML→Markdown converter is needed.

## Diagnosis

Check first 100 chars after jsdecode:
- Starts with `<p` → HTML format, needs HTML→Markdown conversion
- Starts with plain text (no tags) → plain text format, use directly

## HTML→Markdown Converter

```python
import re, html as html_mod

def js_decode(s):
    result = []
    i = 0
    while i < len(s):
        if s[i] == '\\' and i + 1 < len(s) and s[i+1] == 'x':
            hex_chars = s[i+2:i+4]
            if len(hex_chars) == 2:
                try:
                    val = int(hex_chars, 16)
                    result.append(chr(val))
                    i += 4
                    continue
                except ValueError:
                    pass
        result.append(s[i])
        i += 1
    return ''.join(result)

class WeChatHTMLToMarkdown:
    def __init__(self):
        self.output = []
        self.in_li = False
        self.in_code = False
        self.in_a = False
        self.link_url = ""
        self.in_table = False
        self.in_th = False
        self.in_td = False
        self.in_svg = False
        self.svg_depth = 0

    def process(self, html_str):
        i = 0
        while i < len(html_str):
            if html_str[i] == '<':
                tag_match = re.match(r'<\s*(/?)\s*([a-zA-Z][a-zA-Z0-9]*)', html_str[i:])
                if tag_match:
                    is_closing = tag_match.group(1) == '/'
                    tag = tag_match.group(2).lower()
                    tag_end = html_str.find('>', i)
                    if tag_end == -1:
                        tag_end = len(html_str)
                    tag_content = html_str[i+1:tag_end]
                    attrs = dict(re.findall(r'(\w+)\s*=\s*["\']([^"\']*)["\']', tag_content))
                    is_self_closing = html_str[tag_end-1] == '/'

                    # SVG 标签跳过（但 <img> 不跳过）
                    svg_skip = ('svg', 'g', 'path', 'rect', 'circle', 'line', 'text', 'polygon', 'ellipse', 'polyline')
                    if tag in svg_skip and not is_closing:
                        self.in_svg = True
                        self.svg_depth += 1
                        i = tag_end + 1
                        continue
                    if self.in_svg and not is_closing:
                        self.svg_depth += 1
                        i = tag_end + 1
                        continue
                    if self.in_svg and is_closing:
                        self.svg_depth -= 1
                        if self.svg_depth == 0:
                            self.in_svg = False
                        i = tag_end + 1
                        continue

                    if is_self_closing:
                        self._self_close(tag, attrs)
                    elif is_closing:
                        self._close(tag)
                    else:
                        self._open(tag, attrs)
                    i = tag_end + 1
                else:
                    i += 1
            else:
                text_end = html_str.find('<', i)
                if text_end == -1:
                    text_end = len(html_str)
                text = html_mod.unescape(html_str[i:text_end])
                self._text(text)
                i = text_end

    def _open(self, tag, attrs):
        if tag in ('strong', 'b'): self.output.append('**')
        elif tag in ('em', 'i'): self.output.append('*')
        elif tag == 'code': self.output.append('`'); self.in_code = True
        elif tag == 'pre': self.output.append('\n```'); self.in_pre = True
        elif tag in ('h1', 'h2', 'h3', 'h4', 'h5', 'h6'): self.output.append('\n' + '#' * int(tag[1]) + ' ')
        elif tag in ('ul', 'ol'): self.output.append('\n')
        elif tag == 'li': self.output.append('- '); self.in_li = True
        elif tag == 'a':
            href = attrs.get('href', '')
            if href: self.link_url = href; self.in_a = True
        elif tag == 'img':
            # mdnice 使用 data-src 而非 src
            src = attrs.get('data-src', attrs.get('src', ''))
            alt = attrs.get('alt', '')
            if src: self.output.append(f'\n![{alt}]({src})\n')
        elif tag == 'br': self.output.append('\n')
        elif tag == 'hr': self.output.append('\n---\n')
        elif tag == 'p': self.output.append('\n')
        elif tag == 'table': self.in_table = True; self.output.append('\n')
        elif tag == 'th': self.output.append('| **'); self.in_th = True
        elif tag == 'td': self.output.append('| '); self.in_td = True
        elif tag == 'div': self.output.append('\n')

    def _close(self, tag):
        if tag in ('strong', 'b'): self.output.append('**')
        elif tag in ('em', 'i'): self.output.append('*')
        elif tag == 'code': self.output.append('`'); self.in_code = False
        elif tag == 'pre': self.output.append('```\n')
        elif tag in ('h1', 'h2', 'h3', 'h4', 'h5', 'h6'): self.output.append('\n\n')
        elif tag == 'li': self.output.append('\n'); self.in_li = False
        elif tag == 'a': self.in_a = False; self.link_url = ""
        elif tag in ('td', 'th'): self.in_th = False; self.in_td = False
        elif tag == 'tr': self.output.append('\n')
        elif tag == 'table': self.in_table = False; self.output.append('\n')
        elif tag in ('ul', 'ol'): self.output.append('\n')
        elif tag == 'div': self.output.append('\n')
        elif tag == 'p': self.output.append('\n')

    def _self_close(self, tag, attrs):
        if tag == 'img':
            src = attrs.get('data-src', attrs.get('src', ''))
            alt = attrs.get('alt', '')
            if src: self.output.append(f'\n![{alt}]({src})\n')
        elif tag == 'br': self.output.append('\n')
        elif tag == 'hr': self.output.append('\n---\n')

    def _text(self, text):
        text = text.strip()
        if not text: return
        if self.in_a and self.link_url:
            self.output.append(f'[{text}]({self.link_url})')
        else:
            self.output.append(text)

# Usage
raw = re.search(r'content_noencode:\s*["\'](.+?)["\']', html, re.DOTALL).group(1)
decoded = js_decode(raw)
parser = WeChatHTMLToMarkdown()
parser.process(decoded)
md = ''.join(parser.output)
md = re.sub(r'\n{4,}', '\n\n', md)
```

## Complete Manual Extraction Flow

When runner.py times out or outputs an empty shell:

1. curl --noproxy '*' download HTML
2. grep 'content_noencode' → confirm it exists
3. Extract and js_decode
4. Check first 100 chars:
   - Plain text → output directly
   - HTML → use WeChatHTMLToMarkdown converter
5. Build frontmatter (title/description/created/url/author)
6. Insert summary section
7. postprocess.py for cleanup

## Pitfalls — mdnice 渲染器特异性

mdnice（微信 Markdown 编辑器）渲染的 HTML 与传统 WeChat 原生渲染器结构差异显著，原始转换器会漏掉大量图片并误解析 SVG 绘图内容。

### Pitfall 1: 图片嵌入 `<svg>` 容器内

mdnice 的文章结构中，图片嵌套在 `<svg>` 标签内，而非直接出现在 `<p>` 或 `<section>` 下。原始转换器的 SVG 跳过逻辑直接跳过所有 `<svg>` 标签，导致**所有图片的 img 计数为 0**。

**修复**：SVG 跳过逻辑只跳过绘图标签（`<svg>`、`<g>`、`<path>`、`<rect>` 等），但**不跳过** `<img>` 标签。即使 `<img>` 在 SVG 内部也应正常处理。

### Pitfall 2: 使用 `data-src` 而非 `src`

mdnice 渲染的图片将 URL 存储在 `data-src` 属性中，而非标准 `src`。原始转换器只查 `src`，导致 URL 为空。

```python
src = attrs.get('data-src', attrs.get('src', ''))
```

### Pitfall 3: 部分 `<img>` 标签是 `/>` 自关闭但末尾带属性

mdnice 生成的 `<img>` 可能有 `type="block"` 等属性。检查 `html_str[tag_end-1] == '/'` 可以正确检测自关闭形式。但若标签以 `>` 而非 `/>` 结尾，需通过 `attrs.get('data-src')` 判断是否为图片。

### Pitfall 4: 解码后 HTML 包含大量 SVG 数学公式绘图

解码后的 HTML 常包含大量 SVG 数学公式渲染（希腊字母的矢量图），这些 SVG 标签数量庞大（可达 600+ 个 `<g>`、300+ 个 `<path>`），必须跳过否则会严重膨胀输出。

**修复**：在标签解析中，遇到 `<svg>` 及其子标签时设置 `in_svg` 标记并跳过所有内容，直到遇到 `</svg>`。

### Pitfall 5: content_noencode 的正则提取

原始参考中的 `r'content_noencode:\s*["\'](.+?)["\']'` with `re.DOTALL` 在某些 WeChat 版本中不匹配（引号嵌套或转义导致）。替代方案是手动扫描第一个未被转义的结束引号：

```python
start_marker = "content_noencode: '"
idx = html.find(start_marker)
if idx != -1:
    i = idx + len(start_marker)
    while i < len(html):
        if html[i] == '\\' and i+1 < len(html):
            i += 2
            continue
        if html[i] == "'":
            encoded = html[idx+len(start_marker):i]
            break
        i += 1
```

## 图片 URL 提取的兜底方案

当转换器的图片计数为 0（或与实际数量不符）时，直接从解码后的 HTML 中用正则提取所有图片 URL：

```python
img_urls = re.findall(r'data-src="([^"]*?\.qpic\.cn[^"]*)"', decoded_html)
print(f"Found {len(img_urls)} images")
for i, url in enumerate(img_urls):
    print(f"  {i}: {url[:80]}")
```

然后在 Markdown 输出中按图片顺序插入 `![描述]({url})` 引用。图片插入位置建议：在包含"图"字或描述性文字（如"架构"、"对比"、"性能"）的段落附近插入。

## 代理失败后的兜底流程

runner.py 使用默认 `https_proxy` 连接 mp.weixin.qq.com，Clash 代理可能超时。当 runner.py 报 `TimeoutExpired`：

```
1. 不要重试 runner.py —— 它用的是同样的代理
2. 改用 curl --noproxy '*' 直连下载 HTML
   curl -sL --noproxy '*' -A "Mozilla/5.0 ..." "https://mp.weixin.qq.com/s/ARTICLE_ID" -o /tmp/page.html
3. 检查文件大小：如果 >500KB 且含 content_noencode，说明下载成功
4. 按上面"content_noencode 的正则提取方式"手动提取
```

**curl 失败判断标准**：
- 成功：`grep -c 'content_noencode' /tmp/page.html` 有结果（1），文件大小 > 500KB
- 代理失败：文件为空或 < 500 字节（SSL_ERROR_SYSCALL 或 ERR_CONNECTION_CLOSED）
- 如果 curl 也超时，等几秒后重试一次（有时是瞬时超时）