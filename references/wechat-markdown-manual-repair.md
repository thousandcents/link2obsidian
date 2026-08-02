# WeChat Markdown 手动修复实操（execute_code 可复用脚本）

link2obsidian 的 runner + postprocess 跑完后，以下残留用 `execute_code`（直接 `open().read()` 改写）修复最稳。
本文件是 `references/postprocess-residual-bugs.md` 的**实操补充**：那里列了「有哪些残留」，这里给「可直接跑的修复代码」。

## ⚠️ 头号坑：execute_code 传参的反斜杠二次转义

经工具链路（JSON）传代码时，**字面量反斜杠会被二次转义**。若 old_string 里写 `\\\n`（想表达「一个反斜杠 + 换行」），实际落到的字符串会变成「两个反斜杠」，与文件中真实的「一个反斜杠」不符，`replace` 静默返回原串、零命中。

**修复手法**：永远用 `chr(92)` 生成反斜杠，或把每行放进 list 用 `"\n".join(...)` 拼：

```python
bs = chr(92)  # 反斜杠，避免转义歧义
old = "\n".join([
    "```", "", "bash",
    "curl --proto '=https' --tlsv1.2 -LsSf " + bs,   # 行尾续行反斜杠
    "  https://github.com/tursodatabase/turso/releases/latest/download/turso_cli-installer.sh | sh",
])
new = "\n".join([
    "```bash",
    "curl --proto '=https' --tlsv1.2 -LsSf " + bs,
    "  https://github.com/tursodatabase/turso/releases/latest/download/turso_cli-installer.sh | sh",
    "```",
])
if old in c:
    c = c.replace(old, new, 1)
```

## 模式一：连续重复标题行

WeChat scraper 偶尔把同一章节标题输出两行（如 `它到底解决了什么问题` / `普通开发者怎么用` / `谁在用` 各出现两次）。
修复：逐行扫描，若某行等于下一行且属已知标题集合，删第二行。

```python
HEADINGS = {"它到底解决了什么问题", "普通开发者怎么用", "谁在用"}
lines = c.split("\n")
out, skip = [], False
for i, ln in enumerate(lines):
    if skip:
        skip = False
        continue
    if i + 1 < len(lines) and ln == lines[i + 1] and ln.strip() in HEADINGS:
        skip = True
        out.append(ln)
        continue
    out.append(ln)
c = "\n".join(out)
```

## 模式二：正文裸标题升级为 `##`

postprocess 只自动处理 `一、二、` 与数值编号 `01 02`；**纯中文章节标题（三面墙 / 值不值得关注 / 边界和风险）不会自动加 `#`**。
修复：先把重复行按模式一去重，再把已知裸标题行前缀 `## `。

```python
for t in ["三面墙", "它到底解决了什么问题", "普通开发者怎么用", "谁在用", "值不值得关注"]:
    c = c.replace(t + "\n", "## " + t + "\n", 1)
# 关键：边界和风险 经 postprocess 后常是裸文本「边界和风险」而非 **边界和风险**，
# 直接用 "**边界和风险**" 替换会静默不匹配——务必先 re-read 当前文本确认再 replace。
c = c.replace("边界和风险\n", "## 边界和风险\n", 1)
```

## 模式三：退化代码块重建（语言 token 落在块内 + 行尾反斜杠）

病态样例（fence 已开，但 `bash`/`python` 成了块内文本，续行反斜杠保留，后续正文漏进块内）：

```
```
bash
curl --proto '=https' --tlsv1.2 -LsSf \
  https://github.com/... | sh
启动交互式 Shell：      ← 本应在代码块外
```
修复：用模式一的 `bs = chr(92)` + list-join 拼出精确 old/new 整块替换，把语言 token 移出 fence、续行反斜杠保留、正文段落移回块外。多个相邻代码块各自独立围栏，切勿合并。

## 模式四：`**>` callout 残缺（与 postprocess-residual-bugs.md §1 配合）

真实变体多为 `**>\n**项目卡片`（**无结尾 `**`**）。朴素 `replace('**>\n**项目卡片**', ...)` 静默不匹配，会留下 `> **项目卡片****`。
正确写法：

```python
c = c.replace("**>\n**项目卡片", "> **项目卡片**")
c = c.replace("> **项目卡片****", "> **项目卡片**")  # 兜底去残留
```

## 模式五：标题+正文粘连（postprocess 漏修的语义融合）

postprocess 第 4 步只修「可明确判定」的标题粘连（`## N. xxx。正文`、`## 总结回顾全文`）。但 WeChat 转换常产生**无明确句边界**的融合标题，regex 判不出、会漏修，例如：

- `## 1. 这个项目在解决什么先说四个场景，看看你有没有遇到过。`
- `## 2. 核心架构：两层调用分层整个项目有一个设计决策贯穿始终：...`
- `### 需求澄清起点是`
- `### 规划与拆票需求澄清后，如果工作超出单个 session 的容量，走`
- `## 总结这套 skill 库的内核是工程纪律，不是 AI 技巧。`

修复流程：
1. 用 `search_files(pattern="^#{1,3} ", path=文件, output_mode="content")` 列出所有标题行；
2. 逐条核对：标题行若**标题之后直接接正文句子（无自然标题终止点）**即为粘连；
3. 用 `execute_code` 的 `content.replace` 按语义拆成 `标题\n\n正文`（标题保持原样，正文另起一段）。

```python
# 典型融合标题 → 拆开（old 必须是融合后的整行）
reps = [
    ("## 1. 这个项目在解决什么先说四个场景，看看你有没有遇到过。",
     "## 1. 这个项目在解决什么\n\n先说四个场景，看看你有没有遇到过。"),
    ("## 2. 核心架构：两层调用分层整个项目有一个设计决策贯穿始终：user-invoked 和 model-invoked 的分层。",
     "## 2. 核心架构：两层调用分层\n\n整个项目有一个设计决策贯穿始终：user-invoked 和 model-invoked 的分层。"),
    ("### 需求澄清起点是", "### 需求澄清\n\n起点是"),
    ("## 总结这套 skill 库的内核是工程纪律，不是 AI 技巧。",
     "## 总结\n\n这套 skill 库的内核是工程纪律，不是 AI 技巧。"),
]
missed = [o[:30] for o, n in reps if o not in c]
for o, n in reps:
    if o in c:
        c = c.replace(o, n, 1)
print("未命中:", missed)
```

⚠️ 拆分的边界（标题到哪、正文从哪开始）是**语义判断**，无法用正则一刀切；每篇融合点不同，必须人工读上下文定。replace 前先 `print` 命中情况，未命中的说明 old 串与实际有字符差（如 `.changeset/*.md` 是否被反引号包裹），按实际文本修正 old。

## 模式六：术语后游离 `**`（丢失 opener）

postprocess 的孤儿 `**` 校正主要补**缺失 opener**（`X。** 空格 → **X。**`、`XXX**—— → **XXX**——`）。但转换还会产生**缺失 closer / 完整包裹**的变体：术语后直接跟 `**` 且前面并无 `**`，例如：

- `Implementation-coupled**` / `Tautological**` / `Horizontal slicing**`（术语标签，应 `**术语**`）
- `并行**：` / `Negation**：` / `Negative Space**：`（术语 + 冒号，应 `**术语**：`）
- `做 X**` / `不要**`（句内游离 `**`，纯残留应去除）

修复：把「术语 + 后随 `**`」补成完整加粗 `**术语**`；若 `**` 纯属残留（如 `做 X**` 中 X 本非加粗），直接删除 `**`。

```python
c = c.replace("Implementation-coupled**", "**Implementation-coupled**")
c = c.replace("Tautological**", "**Tautological**")
c = c.replace("Horizontal slicing**", "**Horizontal slicing**")
c = c.replace("并行**：", "**并行**：")
c = c.replace("Negation**：", "**Negation**：")
c = c.replace("Negative Space**：", "**Negative Space**：")
c = c.replace("做 X**", "做 X")      # 纯残留，去 **
c = c.replace("不要**", "不要")      # 纯残留，去 **
```

⚠️ 修复后通读相关句子，确认加粗语义符合原文（术语标签 vs 普通强调），避免把本不需加粗的词误加 `**`。

### 模式六补充：冒号/句末丢失 opener、句中游离 opener

postprocess 的孤儿 `**` 校正主要修「句末词后 `**` → 包裹该词」「整段加粗丢失补开头 `**`」这类。但转换还会产生两类它漏掉的变体，需 Agent 手动补：

**① 冒号前丢失 opener**（closer `**` 在冒号前，但无 opener）：

- `这一步的重中之重是防止数据泄露**：` → `**防止数据泄露**：`（冒号前整词补 `**...**`）
- `一个诚实的代价**：` → `**一个诚实的代价**：`

**② 句末/句中孤立 closer**（只有 `**` 收尾、无 opener）：

- `绝不能当作未来必然盈利的保证**。` → `**保证**。`（把被收尾的词补成 `**词**`）
- `相对预测比绝对预测重要得多。**` → `**相对预测比绝对预测重要得多。**`

**③ 句中游离 opener**（术语后跟 `**` 但它是 opener 而非 closer，且无对应收尾）：

- `Sortino** 只惩罚下跌波动` → `**Sortino** 只惩罚下跌波动`
- `Calmar** 是「年化收益÷最大回撤」` → `**Calmar** 是...`
- `Kelly 公式** 则从数学上给出` → `**Kelly 公式** 则从...`

修复：`execute_code` 里逐条 `c.replace` 即可；修完用「逐行统计 `**` 奇偶」兜底校验（奇数行即仍有未闭合）：

```python
for i, l in enumerate(c.split("\n"), 1):
    if l.strip() and l.count("**") % 2 == 1:
        print(f"odd ** at line {i}: {l[:60]}")
```

注意：跨行的 `**...**` 配对若恰好在行尾/行首断开，会让单行计数为奇——此时需看完整配对而非单行之奇偶，别误删合法加粗。

## 模式七：全篇 `##` 标题化（每段落被转成 h2）

部分微信文章（尤其财经观点/「韭圈儿」「北落」类点评）源 HTML 把每个「观点句」都用 `<h2>` 包裹做视觉强调，scraper 的 `<h2>`→`##` 转换会把**每一行正文都变成二级标题**，且行与行之间夹着空 `##` 行。结果正文 70+ 行全是 `##`，Obsidian 里全是大标题，完全不可读。postprocess 的标题修复只处理「可明确判定」项，对这种「全篇标题化」会漏判（它不像粘连标题那样有句边界信号）。

**判定**：`search_files(pattern='^## ', output_mode='content')` 列出标题行，若发现大量**完整句子/段落**都是 `##`（而非真正的章节标题），即为该问题。

**修复（execute_code）**：逐行扫描，空 `##` 行删除，`## ` 开头行去掉前缀降级为正文段落。整篇统一降级即可——这类文章本就是流式随笔，没有值得保留的真标题：

```python
lines = c.split("\n")
out = []
for ln in lines:
    s = ln.strip()
    if s == "##":
        continue                      # 删空 ## 行
    if ln.startswith("## "):
        out.append(ln[3:].strip())    # 降级为正文
    else:
        out.append(ln)
c = "\n".join(out)
c = re.sub(r"\n{3,}", "\n\n", c)      # 压缩空行
```

⚠️ **前置保护**：frontmatter（`source:`/`title:` 等，不以 `## ` 开头）和摘要块（`> ` 开头）不会误伤。若文中有**确实想保留**的少数真标题（如「反应在股价上，会有几个特点：」），降级后可手动加回 `## `。
⚠️ **与 `**` 修复的顺序**：若同文还存在「游离 `**`」或「标题+正文粘连」，先按模式五/六修 `**`，再跑本模式降级 `##`，避免互相干扰。

## 模式八：标题冒号粘连（postprocess 漏修的「冒号无边界」融合）

postprocess 第 4 步的标题粘连修复依赖**句末标点边界**（如 `。` `：` 后接正文）。但 WeChat 转换常产生**标题本身以冒号/特定短语结尾、正文紧贴无标点**的融合，regex 判不出会漏修。典型样例：

- `### 感悟一：质量的关键是上下文在 Agentic SDLC 里，质量的天花板是由上下文决定的。`
- `# 结语Agentic SDLC 不是把 Agent 生硬地嵌入现有流程，而是用"驾驭工程"的方式...`
- `# 架构分层dev-kit 的技术架构自上而下分为五层：`

**判定**：`search_files(pattern='^#{1,3} ', output_mode='content')` 列出所有标题行；若标题行**以冒号/英文短语结尾且后面直接接正文句子**（无 `\n\n` 分隔），即为本模式。

**修复（execute_code）**：按语义把标题和正文拆开。标题保持原样，正文另起一段：

```python
reps = [
    ("### 感悟一：质量的关键是上下文在 Agentic SDLC 里，质量的天花板是由上下文决定的。",
     "### 感悟一：质量的关键是上下文\n\n在 Agentic SDLC 里，质量的天花板是由上下文决定的。"),
    ("# 结语Agentic SDLC 不是把 Agent 生硬地嵌入现有流程，而是用"驾驭工程"的方式对研发过程做彻底重塑，并以工程化手段探寻最佳实践。",
     "# 结语\n\nAgentic SDLC 不是把 Agent 生硬地嵌入现有流程，而是用"驾驭工程"的方式对研发过程做彻底重塑，并以工程化手段探寻最佳实践。"),
    ("# 架构分层dev-kit 的技术架构自上而下分为五层：",
     "# 架构分层\n\ndev-kit 的技术架构自上而下分为五层："),
]
missed = [o[:30] for o, n in reps if o not in c]
for o, n in reps:
    if o in c:
        c = c.replace(o, n, 1)
print("未命中:", missed)
```

⚠️ **弯引号陷阱**：若标题含中文弯引号 `\u201c` / `\u201d`（如 `"驾驭工程"`），直接在 `execute_code` 的字符串字面量中写会触发 `SyntaxError`。**绕过**：先把整行赋给变量，再用 `content.replace(var, new)`：
```python
old = '# 结语Agentic SDLC 不是把 Agent 生硬地嵌入现有流程，而是用"驾驭工程"的方式...'
new = '# 结语\n\nAgentic SDLC 不是把 Agent 生硬地嵌入现有流程，而是用"驾驭工程"的方式...'
c = c.replace(old, new)
```
不要写成 `c.replace("...\"驾驭工程\"...", "...")`——Python 会把弯引号当成字符串结束符。
⚠️ **拆分边界是语义判断**：每篇融合点不同，必须人工读上下文定。replace 前先 `print(repr(c[start:end]))` 确认真实字符，不要凭阅读猜测。

## 收尾校验

```python
print("fence 数:", c.count("```"))
print("残留单反引号开头行:", sum(1 for l in c.splitlines() if l.startswith("`") and not l.startswith("```")))
```

理想状态：fence 数为偶数（成对），残留单反引号行 = 0。