# WeChat Article Title and Heading Postprocessing

> Session-specific detail for link2obsidian postprocess follow-up.

## 1. Title residual slash

`runner.py` uses `safe_title = re.sub(r'[\\/:*?"<>|]', '', title)`, which removes `/` from the saved filename but can leave the literal title/frontmatter/body heading intact. Some WeChat meta titles encode concepts as `/Prototype`, `/Spec`, `/Affine` etc.

Observed case:
- Saved/edited title displayed as: `别等 Spec 写完才发现不对：AI 编程时代，一文讲透如何用 /Prototype 直接看效果`
- The space before `/Prototype` came from the meta title encoding ` /Prototype`, not the Chinese punctuation slash.

Recommended Agent fix after runner/postprocess:
1. Inspect frontmatter `title:` and the first real body heading.
2. If the title contains an isolated English slash introducing a concept, e.g. ` /Prototype` or ` /Spec`, replace it with a normal space:
   ```python
   content = content.replace('如何用 /Prototype', '如何用 Prototype')
   ```
3. Keep `safe_title` filename-safe: `/` must not be saved in a filename or `open()` path.

## 2. Heading + body stickiness residuals

`postprocess.py` reports heading/body stickiness fixes, but can leave semantic misses when a heading ends at a non-obvious sentence boundary. After postprocess, inspect all `^#{1,6} ` lines by regex:

```python
import re
for m in re.finditer(r'^(#{1,6}\s+.+)$', content, re.MULTILINE):
    print(repr(m.group(1)))
```

Observed variants (2026-08-05 session, tinyplay article — postprocess reported "0 项需 AI" yet all three were present):
- Heading + body glued at a non-obvious sentence boundary (the cases in the replacements dict below).
- **Heading + list bullet glued with NO whitespace**: `## 功能特性- 手机遥控：浏览器扫码直连，不用下载东西` → split into `## 功能特性` + blank line + `- 手机遥控：...`. The `- ` marker glued directly to heading text is a reliable deterministic signal.
- **Heading + body glued with no delimiter, heading line ending in `：`**: `## 怎么用去 GitHub Releases 下最新版：` → `## 怎么用` + blank line + `去 GitHub Releases 下最新版：`. No punctuation marks the boundary; the semantic split point must be judged by the Agent.

Additional variants (2026-08-06 session, AlphaEval article — postprocess fixed 2 glues but left 8 of these):
- **Chinese-numbered heading glued to first bullet**: `## 一、背景- Alpha因子挖掘的意义：...` / `## 三、实验验证- 实验设置 使用Qlib平台...` → `## 一、背景` + blank line + `- Alpha因子挖掘的意义：...`. Note the bullet text may itself need a `：` inserted where a space stood in for the label separator (`实验设置 使用Qlib` → `实验设置：使用Qlib`).
- **Numbered `### N.` subsection heading glued to first bullet** (often with a parenthetical in the heading): `### 3. 消融实验（Ablation Study）- 单独使用某一维度...` / `### 4. 指标合理性验证- **RRE与换手率负相关**：...` / `### 5. 效率对比- AlphaEval比传统回测方法**快25%以上**...` → split after the heading's closing `）` or last heading word. The glued bullet may start with `**bold**` — that's fine, keep it in the bullet.
- **Chinese-numbered heading glued to plain prose**: `## 二、AlphaEval框架AlphaEval是一个无需回测...` (heading noun immediately repeated as prose subject) / `## 四、写在最后开源代码可看https://...` → split where the heading noun ends and the sentence (re)starts the same noun or begins a URL-bearing sentence.
- **Compound heading word split mid-word** (2026-08-07 session, 横截面 R² article): the heading `参考文献` landed as `## 参考` + body line starting `文献Balduzzi, P., ...` — a compound heading word broken across the heading/body boundary. Fix by deleting the orphaned leading word from the body (`文献Balduzzi` → `Balduzzi`) or rejoining it into the heading; scan for body lines that start with the tail half of the preceding heading.
- **High-volume glue in academic-popularization articles** (2026-08-07: 13 glues in one article): `## 一、…`/`### N.N …` headings whose text is a noun phrase ending in `的引入`/`的简化`/`的分析`/`的表现` glue directly to the following prose with NO punctuation at the boundary — postprocess can't detect these (its rule needs `。` at the boundary). After postprocess, scan every `^#{2,3} ` line longer than ~20 chars and judge whether the heading noun phrase ends mid-line.

**Key lesson**: postprocess reporting "标题+正文粘连修复：N 处" means it fixed N instances, NOT that none remain. The deterministic scan above (`^(#{1,6}\s+.+)$` + eyeball for `- ` or prose glued mid-line) is still mandatory.

Typical fix:

```python
replacements = {
    '一个真实的需求：给订单追踪页加搜索AI 编程圈': '一个真实的需求：给订单追踪页加搜索\n\nAI 编程圈',
    '为什么 AI 让"先做原型"变得划算传统开发里': '为什么 AI 让"先做原型"变得划算\n\n传统开发里',
    '### UI 分支：给设计问题跑个分触发信号': '### UI 分支：给设计问题跑个分\n\n触发信号',
}
for old, new in replacements.items():
    content = content.replace(old, new)
```

Use `open(path).read()` / `open(path).write()` in `execute_code`, not `read_file()` line-number output, for these exact string replacements.

## 3. Fenced code block language split residuals

WeChat-to-Markdown conversion can split a code fence from its language label:

```markdown
```

python
def foo():
```

Fix to:

```markdown
```python
def foo():
```

```

Reusable check/fix:

```python
import re
content = re.sub(r'```\n\npython\n', '```python\n', content)
content = re.sub(r'```\n\njavascript\n', '```javascript\n', content)
content = re.sub(r'```\n\nbash\n', '```bash\n', content)
content = re.sub(r'```\n\nshell\n', '```shell\n', content)
```

## 4. Unnumbered standalone section lines → promote to `##`

`postprocess.py` promotes **numbered** standalone lines to headings (`一、` Chinese-numbered, `01` numeric), but does NOT touch **unnumbered** short standalone lines. WeChat section headers rendered as styled `<section>`/`<div>` (bold/colored, no numbering) lose all formatting in conversion and land as bare prose lines:

```markdown
仓库里有什么
这不是一个 awesome-list 链接集合。每个模板都是自包含的完整项目：...

为什么值得关注

### 1. 能跑，不是摆设
```

**Detection**: short line (≤ ~15 chars), no punctuation, standing alone between blank lines, followed by content or `###` subsections. Deterministic scan:

```python
import re
for m in re.finditer(r'^([^\n#>\-\*|`!]{2,20})$', content, flags=re.M):
    line = m.group(1).strip()
    # 人工判定：是否为小节标题（后跟正文或 ### 子标题）
```

**Fix**: prepend `## ` to each confirmed section line. Anchor replacements with surrounding newlines (`\n仓库里有什么\n` → `\n## 仓库里有什么\n`) so you don't hit the same words inside prose sentences (e.g. `MCP 怎么用？` contains `怎么用` — only the standalone-line match should be promoted).

**实战来源**：2026-08-07 awesome-llm-apps 文章（`仓库里有什么`/`为什么值得关注`/`实际场景示例`/`边界和局限`/`怎么用` 共 5 处，postprocess 报告 0 项需 AI 但全部漏掉）。

## 5. Avoid relying on postprocess alone

Treat the postprocess report as a quality gate, not publication approval. Especially for WeChat methodology/tool articles, verify:
- headings no longer contain first paragraph body text;
- titles with `/` are cleaned;
- fenced code blocks have language labels attached;
- tables still render as pipe tables and are not flattened.
