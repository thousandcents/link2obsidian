# Vue SPA `content_noencode` Fallback

## Trigger

- `runner.py` 生成的文件 < 500 字节，且 postprocess 报告提示“很可能 runner.py 抓取失败”
- 用 curl 拉取 HTML 后，`<div id="js_content">` 为空或极短
- HTML 中存在 `content_noencode: '...'` 字段

## Extraction Pattern

```python
import re

with open('/tmp/article.html', 'r') as f:
    html = f.read()

m = re.search(r'content_noencode:\s*\'(.+?)\'', html, re.DOTALL)
if not m:
    raise SystemExit("No content_noencode found")
raw = m.group(1)
```

## JsDecode

微信 `content_noencode` 使用 JS 风格 hex 转义：

```python
def js_decode(s):
    s = re.sub(r'\\x([0-9a-fA-F]{2})', lambda m: chr(int(m.group(1), 16)), s)
    s = s.replace('\\n', '\n').replace('\\r', '\r').replace('\\t', '\t')
    s = s.replace('\\"', '"').replace("\\'", "'")
    return s
```

常见转义：
- `\x0a` → 换行
- `\x0d` → 回车
- `\x22` → 双引号 `"`
- `\x26` → `&`

## Markdown Reconstruction

解码后正文通常已经是纯文本段落，按 `\n\n` 分段即可：

```python
content = js_decode(raw)
paragraphs = [p.strip() for p in content.split('\n\n') if p.strip()]
md_body = '\n\n'.join(paragraphs)
```

若正文末尾有裸 URL（如 `https://github.com/...`），保留为普通段落或转为链接。

## Frontmatter

- `title`: 从 `<meta property="og:title">` 提取
- `description`: 从 `<meta property="og:description">` 提取（可能为空）
- `created`: Vue SPA 页面通常没有 `var ct = ...`，可留空或根据上下文补日期
- `url`: 原始文章 URL

## Pitfalls

- **Runner 不会自动走此 fallback**：当前 `runner.py` 仅依赖 `js_content` div，遇到 Vue SPA 会静默生成空文件。必须由 Agent 在 postprocess 报告 `< 500 字节` 后手动触发本流程。
- **content_noencode 可能重复出现**：HTML 中可能有多处 `content_noencode`，通常第一处即为正文。
- **模板变量残留**：若原文包含 `{1}`、`{{img_url}}` 等模板变量，解码后会作为字面量残留，需人工搜索替换。
- **图片 URL 提取**：Vue SPA 页面的图片 URL 仍在 HTML 中（`mmbiz.qpic.cn`），与正文提取无关，按常规流程下载即可。

## Session Example

2026-07-26：《给Cursor、Claude Code、Codex做了个踩坑本》
- runner.py 输出 189 字节空文件
- curl 直连 HTML（1.9MB），找到 `content_noencode`
- js_decode 后得到 471 字节正文
- 手动重建 frontmatter + 摘要 + 正文，写入 2228 字节 Markdown
- 2 张图片经 vision_analyze 判定为装饰图，删除磁盘文件
