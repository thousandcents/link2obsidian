# 重度代码块损坏重建（fence 逐行丢失）

## 触发场景

微信量化/技术类文章的 Python 代码块在 HTML→Markdown 转换中严重损坏，特征：
- **每个代码行都被 `` ` `` 包裹**（` ``def foo():`` ``  ` 开头、行间用 ` `` ` 连接）
- 行内 ` `` ` 标记分散在各处，缩进全部丢失
- 原始 fence（```` ``` ````）完全消失，变成一团 ` `` ` 分隔的扁平行
- 代码块前后与正文粘连（如 `return sell` 激进版本每天…`、```` ``` `` 因子计算出来后…`）

postprocess.py 的行首 fence 修复只处理"单行以 ` 开头"的简单退化，**覆盖不了**这种逐行 ` `` ` 散落、缩进丢失的重度损坏。

## 判定

用脚本定位：读取文件，找出所有含 `` ` `` 且非 fence 起始符的行；若一行内出现多个 ` `` ` 且是代码关键字（`def`、`import`、`self.`、`return`、`pd.`），即为重度损坏代码块。

```python
import re
content = open(path, encoding="utf-8").read()
for i,l in enumerate(content.split("\n"),1):
    if "`" in l and not l.strip().startswith("```"):
        print(i, repr(l[:70]))   # 多行命中 → 重度损坏
```

## 修复：整体重建（不要逐行 patch）

代码结构在损坏文本中仍然可读（关键字、注释、调用都在，只是丢了缩进和 fence）。正确做法是**用 execute_code 整体重建**：

1. **定边界**：用文章中的稳定锚点串定位损坏区起止。例如
   `start_marker = "`1. 所属主题排名"`（代码块前的列表首项）→ `end_marker = "return sell` 激进版本"`。
   ```python
   i_start = content.index(start_marker)
   i_end = content.index(end_marker) + len("return sell`")
   ```
2. **写干净代码**：手工按原始结构恢复缩进与 ` ```python `/` ``` ` fence，存入字符串变量。
3. **替换**：`content = content[:i_start] + replacement + content[i_end:]`。
4. **写回**：`open(path,"w",encoding="utf-8").write(content)`。

注意：重建时**不要**用 f-string 拼含 `{`/`}` 的代码（会触发 `ValueError: Invalid format specifier`）——用普通字符串。

## 修复后的验证（必做）

```python
# 1. fence 配对：总数必须为偶数
fences = [content[:m.start()].count("\n")+1 for m in re.finditer(r'^```', content, re.MULTILINE)]
print("fence 行:", fences, "总数应偶数")

# 2. 代码区外不得残留行内反引号
in_fence=False
for i,l in enumerate(content.split("\n"),1):
    if l.strip().startswith("```"): in_fence=not in_fence; continue
    if not in_fence and "`" in l:
        print("残留反引号", i, repr(l))

# 3. 公式行/正文中偶发残留的 `` ` `` 也要清理（用精确 replace）
```

## 常见伴生残留（一次修完）

- **代码块闭合 fence 与正文粘连**：` ``` 因子计算出来后…` → 拆为 ` ```\n\n因子计算出来后…`
- **图片与正文粘连**：`个股为基础条件。\n![...]` → 图行前后补空行
- **正文公式行的 `` ` `` 残留**：`主题强度 =``0.30 × …``+ …` → 去反引号保留纯文本公式
- **文末推广/引流文本**（"扫码加学习群"、"加微信"、"下期再见"）与引流图 → 整段删除，引用+磁盘文件都删
- **列表项加粗**：`- 从单因子到多因子**：` → `- **从单因子到多因子**：`

## 实战验证

2026-08-08《形态选股策略：事件驱动 + 趋势过滤 + 热点轮动》：两个 Python 代码块（~60 行 ThemeLeaderStrategy 类 + ~40 行振幅切割因子）全部逐行 ` `` ` 损坏、缩进丢失。按上述整体重建法一次替换修复，fence 恢复 2 对（4 个）、代码区外零残留反引号、零孤儿 `**`。图片引用 5 张与磁盘一致。
