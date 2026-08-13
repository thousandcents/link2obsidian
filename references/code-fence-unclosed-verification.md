# 代码块 Fence 未闭合验证

## 现象

postprocess.py 的 `fix_code_blocks()` 会识别行首 `+Python/C/Bash` 关键字，
在代码块起始处插入 ```` ```python` 标记，但**不会为每个 opening fence 自动补 closing fence**。

当微信原文代码块本身就没有 ```` ````（比如代码直接写在 inline code 行末，
或原文 HTML 的 `<pre>` 标签只开了不闭），postprocess 生成的 Markdown 会出现：
- 多个 ```` ```python` opening fence
- **0 个 ```` ``` 闭合**

Obsidian 中代码块不闭合 → 后面所有内容都被当代码，排版错乱。

## 典型案例

某文 4 个 Python 代码块（corwin_schultz_spread / parkinson_vol / 防御代码 / 滚动均值），
postprocess 修复后 fence 行如下（仅 opening，全部缺闭合）：

```
行56: ```python
行127: ```python
行167: ```python
行176: ```python
```

需手动在每个代码块末尾插入 ```` ``` ```` 闭合。

## 验证方法（必做）

postprocess 完成后，用以下脚本快速检测 fence 是否完全配对：

```python
import re
lines = open(path).read().split('\n')
fences = [i+1 for i, l in enumerate(lines) if l.strip().startswith('```')]
if len(fences) % 2 != 0:
    print(f'⚠️ 未配对 fence: {len(fences)} 个（奇数）')
else:
    pairs = [(fences[i], fences[i+1]) for i in range(0, len(fences), 2)]
    print(f'✅ 配对: {pairs}')
```

## 修复方法

逐个代码块，找到代码块结尾行（通常是某个 `return` 语句或最后一行缩进代码，
后紧跟 `text` 文本），在代码块结束处插入 ```` ``` ````：

```python
content = content.replace(
    "    return spread`逐块拆解：",
    "    return spread`\n```\n\n**逐块拆解：**",
    1
)
```

## 变体 A：backtick 退化的代码块（单反引号开/闭）

某些微信技术文代码块的 fence 会从 ```` ``` ```` **退化成单个反引号**（`` ` ``），
而不是完全消失。签名：
- 代码块首行以 `` ` `` 开头（如 `` `defensive_period = 126 ... ``），末行以 `` ` `` 结尾（如 `...fillna(0)`）。
- 与「缺 closing」的区别：这里有「假的闭合符」，但用的是单反引号而非三反引号。

**修复**：把首行与末行的单反引号各替换成 ```` ``` ````：
```python
c = c.replace("`defensive_period = 126   # 防御持有期（交易日）", "```\ndefensive_period = 126   # 防御持有期（交易日）")
c = c.replace("strategy_returns = (returns * signal.shift(1)).fillna(0)`", "strategy_returns = (returns * signal.shift(1)).fillna(0)\n```")
```

## 变体 B：全库代码块集体缺 closing + 正文被吞入（系统性重建）

量化/技术文常见：**每个**代码块都缺 closing fence，且代码块结束处紧跟的正文
被直接粘连在最后一行代码后面（同一行，代码末反引号后直接接中文正文）。
签名：fence 数 = 2×代码块数（全是 opening，全是「偶数个但每对都缺闭合」→ 实际
`len(fences)` 可能是偶数却是假象），逐块重建时正文都在代码行末粘连。

**系统性重建法**（一次 execute_code 搞定全部）：
1. 数 fence，若 `len % 2 != 0` 说明有不配对 opening（本案例 5 个 opening、0 个 closing）。
2. 逐块定位「代码末行 + 正文粘连」的边界：代码最后一行通常以反引号结尾再接正文
   （如 `...threshold)[0]`检测出的变点...` / `...均值！``shift(1)` 只能保证...`）。
3. 在反引号处切开，插入 `\n```\n\n`，让正文回到代码块外：
   ```python
   c = c.replace("change_points = np.where(cp_prob > threshold)[0]`检测出的变点",
                 "change_points = np.where(cp_prob > threshold)[0]\n```\n\n检测出的变点")
   ```
4. 若块内含 ` ``` ` + 空行 + `python` 的分离形式，`re.sub(r"```\n\npython\n", "```python\n", c)` 合并。
5. 全部重建后重跑 fence 配对验证，`len % 2 == 0` 且每对间隔合理。

**注意**：代码块内的 Python `**`（幂运算，如 `self.means) ** 2`）不是孤儿加粗，
配对验证时须跳过 fence 内部的行，只对 fence 外的正文行统计 `**` 奇偶。

## 触发条件

- 微信原文代码块使用 `<pre>` + `<code>` 标签但标签未配对
- 或代码块内容直接接在 inline `` ` `` 后（`return vol`要点：`），
  postprocess 只修了行首 language marker，没注意到后面缺 ```` ``` ````
- 或文章有多个短代码片段分散在不同段落

## 预防

postprocess.py 目前只负责 fence opening 修复。Agent 在 postprocess 报告之后
**必须主动跑一次 fence 配对验证**（见上），不要假设 postprocess 已经处理好了 closing。

## 修复顺序

- **fence + language 分离**（` ``` + python` 各一行）→ 先合并为 ```` ```python`
- **fence 未闭合**（只有 opening 没有 closing）→ 补 ```` ``` ````
- **同一代码块被拆开**（多个独立 fence）→ 合并，见 `code-fence-merge-pitfall.md`

Agent 处理顺序：分离修复 → 未闭合闭合 → 重复 fence 合并。postprocess 完成后必须跑一次 fence 配对验证，不要假设 closing 已被处理。

修复顺序：分离修复 → 未闭合闭合 → 重复 fence 合并
