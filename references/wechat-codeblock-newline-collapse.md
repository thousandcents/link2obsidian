# WeChat 代码块换行坍缩修复（newline-collapse）

比 fence 退化更隐蔽的损坏：**fence 还在，但代码块内的换行被转换器压成空格**，导致相邻顶层语句粘连成一行，Python 直接 `SyntaxError`、无法运行。postprocess 的「fence 退化修复」只处理 ``` 标记缺失/错位，对**块内换行坍缩**无能为力——本文件补这个缺口。

## 典型病状

```
`import pandas as pdimport numpy as np# 假设 df 是...tech_rets = df.pct_change()# 查看偏度...`
```

注意：原 Python 的每条语句（`import`、`# 注释`、`tech_rets = ...`）之间本应有换行，转换后全挤成单行，注释 `#` 直接贴在上一句末尾变成「`pdimport`」「`np# 假设`」这类非法标识符拼接。

其他变体：
- `from keras.models import Sequentialfrom keras.layers import Dense, LSTM`（import 粘连）
- `def create_dataset(data, lookback=6):    """docstring"""    X, y = [], []` —— 函数体缩进保留，但语句间换行没了
- 中文注释紧贴代码：`train_scaled = scaler.fit_transform(train_data)test_scaled = scaler.transform(test_data)`

**判定信号**：fenced 代码块（或 `` ` `` 内联包裹）里出现 `import Ximport Y`、`# ` 注释前无换行直接接字母、`def`/`for`/`model.add(` 等关键字紧跟上一句无空格断点。

## 修复方法

逐块重建：把粘连行按 Python 语法断点拆回多行，补换行、补空行、恢复缩进。indentation（如函数体 4 空格、链式 `model.add` 续行空格）需从原文上下文推断还原。

```python
# 在 execute_code 中，open().read() 取原文后整块替换
old = ("`import pandas as pdimport numpy as np# 假设 df 是...tech_rets = df.pct_change()"
       "# 查看偏度...skewness = tech_rets.skew()...`")
new = ("```python\n"
       "import pandas as pd\n"
       "import numpy as np\n"
       "\n"
       "# 假设 df 是...\n"
       "tech_rets = df.pct_change()\n"
       "\n"
       "# 查看偏度...\n"
       "skewness = tech_rets.skew()\n"
       "...\n"
       "```")
assert old in c, "block not matched"
c = c.replace(old, new)
```

用 `assert old in c` 验证命中；若未命中，先 `repr()` 看实际空白/反引号数量（转换器有时在粘连处塞了 2+ 空格），再修正 old。

## 强制校验（不可替代）

重建后**必须**用 `compile()` 验证块内 Python 语法，而非肉眼检查：

```python
import re
blocks = re.findall(r"```python\n(.*?)```", c, re.DOTALL)
for i, b in enumerate(blocks, 1):
    try:
        compile(b, f"<block{i}>", "exec")
        print(f"  block {i}: OK ({b.count(chr(10))} lines)")
    except SyntaxError as e:
        print(f"  block {i}: SYNTAX ERROR line {e.lineno}: {e.msg}")
```

任何 `SyntaxError` 都必须回到对应块重修——尤其链式调用 `model.add(LSTM(128, return_sequences=True,\n               input_shape=...))` 的续行缩进、以及 f-string 里的 `{asset}_Predictions` 等花括号。

## 收尾

- 全篇 fence 数应为偶数（`c.count("```")` % 2 == 0）
- 无残留 `` ` `` 开头的行（`l.startswith("`") and not l.startswith("```")` 应为 0）
- 若原文无语言标记，统一用 `python`（量化文章代码多为 Python）
