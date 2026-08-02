# Vue.js SPA (mdnice) 文章 HTML→Markdown 提取

## 适用场景

微信文章使用 [mdnice](https://mdnice.com) 编辑器排版时，HTML 结构与传统 `#js_content` 文章不同：
- **不是** Vue 2 时代的 `content_noencode`（纯文本 + `\\xHH` 转义）
- **是** `cgiDataNew` 对象中的 `mdnice` HTML（含 `<div class="mdnice">`、内联 style、`<img>` 标签等）
- 正文不在 `<div id="js_content">` 中，或 js_content 为空

## 识别方法

```python
import re

with open('/tmp/page.html', 'r') as f:
    html = f.read()

if 'mdnice' in html or 'content_noencode' in html:
    print("疑似 mdnice/Vue SPA 页面")

m = re.search(r'<div[^>]*id="js_content"[^>]*>(.*?)</div>', html, re.DOTALL)
if not m or not m.group(1).strip():
    print("js_content 为空，确认为 mdnice/Vue SPA，需使用 content_noencode")
```

## 提取流程

### Step 1: 解码 content_noencode

`content_noencode` 有两种存放方式：

1. **var 赋值**：`var content_noencode = '...'`
2. **cgiDataNew JSON**：在 `window.cgiDataNew` 或 `<script>` 标签内的 JSON 字段

```python
import re, html as html_mod

# 方式 1: var 赋值
m = re.search(r'content_noencode\s*[:=]\s*([\'"])(.*?)[\'"]\s*[,\n}]', html, re.DOTALL)

# 方式 2: cgiDataNew JSON（尝试 JSON 解析）
if not m:
    m = re.search(r'window\.cgiDataNew\s*=\s*(\{.*?\})\s*;', html, re.DOTALL)
    if m:
        import json
        cgi = json.loads(m.group(1))
        raw = cgi.get('data', {}).get('content_noencode', '')
    else:
        raise ValueError("No content_noencode found")

def jsdecode(s):
    s = s.replace('\\\\x', '\\\\x')
    def hx(m):
        return chr(int(m.group(1), 16))
    s = re.sub(r'\\\\x([0-9a-fA-F]{2})', hx, s)
    s = re.sub(r'\\\\u([0-9a-fA-F]{4})', lambda m: chr(int(m.group(1), 16)), s)
    return html_mod.unescape(s)

decoded = jsdecode(raw)
```

### Step 2: 用 BeautifulSoup 解析 DOM

```python
from bs4 import BeautifulSoup

soup = BeautifulSoup(decoded, 'html.parser')

# 提取标题（H1）
h1_tag = soup.find('h1')
title = ''.join(c.strip() for c in h1_tag.find_all(string=True)) if h1_tag else "未知"
# 标题中常混入营销文案，取第一段
title_clean = re.split(r'\s{2,}', title)[0].strip()

# 提取图片 URL（data-src 优先）
img_urls = []
seen = set()
for img in soup.find_all('img'):
    url = img.get('data-src') or img.get('src')
    if url and url not in seen:
        seen.add(url)
        img_urls.append(url)
```

### Step 3: 文章正文转换（推荐：markdownify）

**`markdownify` 是处理 mdnice HTML 最干净的方法**，自动处理 `<p>`→段落、`<h1/h2/h3>`→`#` 标题、`<pre><code>`→fenced code blocks、`<table>`→pipe table、`<strong>`→`**`、`<code>`→行内代码。

```python
from markdownify import markdownify as md

# 移除营销/广告/二维码 section（按需调整 class 名）
for bad_class in ['marketing', 'advertisement', 'qrcode', 'poster', 'promotion']:
    for el in soup.find_all(attrs={'class': bad_class}):
        el.decompose()

# 只保留 .mdnice 主体
mdnice_div = soup.find('div', class_='mdnice')
source = mdnice_div if mdnice_div else soup

md_text = md(source)
md_text = re.sub(r'\n{4,}', '\n\n\n', md_text).replace('\xa0', ' ').strip()
```

### Step 4: 后处理修复

| 问题 | 修复方法 |
|------|---------|
| H1 内混入营销文案 | `re.split(r'\s{2,}', title)[0]` |
| `* ·` 列表项目 | `content.replace('* • ', '\n- ')` |
| 未配对的 `**`（strong+em 残差） | 逐段检查奇偶 `**` 数，补配或移除 |
| 段落粘连（无空行分隔） | `re.sub(r'(?<=[。！？])\s+([A-Z])', r'。\n\n\\1', text)` |

### 降级方案（markdownify 不可用时）

手写 BeautifulSoup DOM 遍历：

```python
from bs4 import BeautifulSoup, NavigableString, Tag

def process_element(tag):
    if not isinstance(tag, Tag):
        return str(tag)
    if tag.name == 'p':
        return ''.join(c for c in tag.find_all(string=True)) + '\n\n'
    elif tag.name in ('h1', 'h2', 'h3', 'h4', 'h5', 'h6'):
        level = int(tag.name[1])
        txt = ''.join(c for c in tag.find_all(string=True))
        return '#' * level + ' ' + txt + '\n\n'
    elif tag.name == 'pre':
        code = tag.find('code')
        return '```\n' + (code.get_text() if code else tag.get_text()) + '\n```\n\n'
    elif tag.name == 'img':
        url = tag.get('data-src') or tag.get('src') or ''
        return f'![img]({url})\n'
    else:
        return ''.join(c for c in tag.find_all(string=True))

md_text = ''.join(process_element(el) for el in soup.children)
```

## 依赖安装

```bash
pip3 install markdownify beautifulsoup4
```

## 注意事项

1. **markdownify 不处理 `<img>`**：需手动提取 `<img data-src>` 并替换为 `![](path)`
2. **mdnice 内联 style** 被忽略，可能引起文本粘连（正则修复）
3. **cgiDataNew JSON** 含 `data.content_noencode`，需先 `json.loads`
4. **JsDecode `\\xHH`**：微信编码用 `\\xHH` 字节，正则 `r'\\x([0-9a-fA-F]{2})'` 解码
5. **模板变量残留**：若文章含 `{1}`、`{{img_url}}`，JsDecode 后以字面量残留，需人工搜索修复
6. **mdnice `<div>` 嵌套**：部分版本用 `<div>` 模拟段落，markdownify 仍正确转换
7. **大文件**：cgiDataNew 可 >3MB，`json.loads` 无问题
