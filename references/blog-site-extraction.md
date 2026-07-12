# 博客园/常规博客站点 HTML 提取

## 触发条件

当 runner.py 输出 <500 字节空壳且文件名为「未知标题」时，说明该站点不在 WeChat SPA 抓取逻辑覆盖范围内。

## 通用提取流程

### 1. 下载 HTML

```bash
curl -s -L -A "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36" "{url}" > /tmp/article.html
```

### 2. 站点标识符对照

| 站点 | CSS 选择器 | 备注 |
|------|-----------|------|
| cnblogs.com（博客园） | `<div id="post_detail">` → `</div>\s*<div class="postDesc">` | 正文结束标记 |
| CSDN | `<div id="content_views" class="htmledit_views">` | |
| 通用 | `<article>` / `<main>` | 无专用选择器时的兜底 |

### 3. Python 提取核心逻辑

```python
import re

with open('/tmp/article.html', 'r', encoding='utf-8') as f:
    html = f.read()

# cnblogs.com 专用选择器
body_match = re.search(
    r'<div[^>]*id="post_detail"[^>]*>(.*?)</div>\s*<div[^>]*class="postDesc"',
    html, re.DOTALL
)
body = body_match.group(1)

# 保护代码块（预处理）
code_blocks = []
def save_code(m):
    code_blocks.append(m.group(0))
    return f'%%%CODE_BLOCK_{len(code_blocks)-1}%%%'

body = re.sub(r'<pre[^>]*>(.*?)</pre>', save_code, body, flags=re.DOTALL)

# 转换语义标签
body = re.sub(r'<h2[^>]*>(.*?)</h2>', r'## \1', body)
body = re.sub(r'<h3[^>]*>(.*?)</h3>', r'### \1', body)
body = re.sub(r'<strong[^>]*>(.*?)</strong>', r'**\1**', body)
body = re.sub(r'<b[^>]*>(.*?)</b>', r'**\1**', body)
body = re.sub(r'<em[^>]*>(.*?)</em>', r'*\1*', body)
body = re.sub(r'</?(?:p|div|li|br|tr|th|td|ul|ol)[^>]*>', '\n', body)

# 移除其余标签
body = re.sub(r'<[^>]+>', '', body)

# 恢复代码块
for i, cb in enumerate(code_blocks):
    code_text = re.sub(r'<[^>]+>', '', cb)
    code_text = code_text.replace('&lt;', '<').replace('&gt;', '>')
    code_text = code_text.replace('&amp;', '&').replace('&nbsp;', ' ')
    code_text = code_text.replace('&quot;', '"')
    lang = ''
    lang_m = re.search(r'class="[^"]*language-(\w+)', cb)
    if lang_m:
        lang = lang_m.group(1)
    fenced = f'```{lang}\n{code_text.strip()}\n```'
    body = body.replace(f'%%%CODE_BLOCK_{i}%%%', fenced)

# HTML 实体解码
body = body.replace('&nbsp;', ' ').replace('&lt;', '<').replace('&gt;', '>')
body = body.replace('&amp;', '&').replace('&quot;', '"').replace('&#x2B;', '+')
```

### 4. 提取标题

```python
title_match = re.search(r'<title>(.*?)</title>', html)
title = title_match.group(1).split(' - ')[0] if title_match else "文章标题"
```

### 5. 构建 Markdown 文件

- 拼接 frontmatter（source: 网页收藏, tags: [网页收藏]）
- 添加 LLM 摘要
- 写入 `Clippings/{title}.md`

## 常见陷阱

1. **代码块缩进丢失**：`<pre><code>` 内的 Python 缩进在 HTML tag 剥离后可能丢失（每行前的 4 空格被 trim）。修复方式：在恢复代码块后，对 Python 代码块检查缩进并手动修正
2. **表格结构丢失**：CNBLOGS 的 `<table>` 会完全展平为文字。检查提取结果中是否有成对出现的「优势」「说明」类文本行，重建为 pipe table
3. **标题+正文粘连**：`<h2>` 后直接跟 `<p>` 无换行时，两者会合并在一行。修复方式：用 regex 按短句模式分离（取 h2 行到第一个句号/冒号前）
4. **&lt; &gt; 残留**：代码中的比较运算符和泛型常被编码为 HTML 实体，务必做反向解码
