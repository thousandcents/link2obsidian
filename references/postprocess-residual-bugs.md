# postprocess.py 残余项（需 AI 兜底）

postprocess.py 处理了绝大多数固定模式的 Markdown 缺陷，
但以下模式未被覆盖，**需在 postprocess 报告 0 项需 AI 介入后手动检查**。

## 1. `**>` 残留

LLM 摘要区块结束后，有时会在正文开头残留 `**>` 行：

```markdown
> 📌 **文章要点**
> - 要点...

**>
**项目卡片**
```

表现为：摘要引用块结束后多了一行 `**>`，然后正文内容前有多余的 `**`。

**修复**：在摘要块与正文之间插入换行，删除孤立的 `**>`：

```python
content = content.replace('**>\n**项目卡片**', '**项目卡片**')
```

**识别方法**：在正文开头搜索 `**>` 或孤立的 `**` 行（紧跟摘要块之后，非代码块内部）。

## 2. 前端描述中的 `\x26#39;` HTML 实体

runner.py 在 frontmatter 的 `description` 字段中有时会生成形如 `\x26#39;` 的
十六进制转义字符，而不是 `&` 和 `'`：

```yaml
description: DeerFlow 2.0 让 AI 从\x26#39;聊天\x26#39;进化到\x26#39;真正干活\x26#39;。
```

解码对应关系：
- `\x26` → `&`
- `\x39` → `9`（所以 `\x26#39;` → `&#39;` → `'`）

**修复**：

```python
content = content.replace('\\x26#39;', "'")
content = content.replace('\\x26#34;', '"')  # &#34;
content = content.replace('\\x26amp;', '&')   # &amp;
```

**为什么 postprocess 没覆盖**：postprocess 处理的是 HTML 实体（`&quot;`、`&amp;` 等）
和 `\x0d`/`\x0a` CRLF，但不处理 `\x26#39;` 这种 `\xHH` 字节序列形式的 HTML 实体编码。

## 3. 检查点

postprocess 报告 "0 项需 AI 介入" **不意味着文件完全干净**。
建议每次 postprocess 后固定检查：

1. 搜索 `**>` — 确认摘要块与正文之间无残留
2. 搜索 `\\x` — 确认 frontmatter 中无未解码的十六进制转义
3. 搜索 `&#` — 确认无 HTML 实体字面量残留
