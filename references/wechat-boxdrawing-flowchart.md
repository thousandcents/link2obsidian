# WeChat box-drawing 流程图 → GFM pipe 表

## 问题

部分微信公众号文章把**流程图 / 架构图 / 阶段说明**渲染成 box-drawing 字符画，而不是 HTML `<table>`：

```
┌──────────┬──────────────────────────┐
│ 阶段     │ 说明                     │
├──────────┼──────────────────────────┤
│ 特征提取 │ 用 LLM 从原始数据抽取候选 │
│ 特征选择 │ 质量-多样性评估筛除冗余   │
│ 特征生成 │ 进化优化迭代生成新特征   │
└──────────┴──────────────────────────┘
```

这种字符画：
- **不是 HTML `<table>`** → scraper 的 `html_table_to_markdown()` 不会处理（它在 `<table>` 标签上触发）。
- **不含 `%`** → postprocess 的「被压平表格检测」（行内无 `|` + 长度>40 + ≥2 `%` + `**`）也漏掉。
- 在 Obsidian 里显示为乱码宽字符块，必须**手动按语义转为 pipe 表**。

## 判定规则

一行同时满足以下两点即属 box-drawing 表行：
- 含 `│`（U+2502 竖线）
- 含至少一个 box 字符：`┌ ┬ ┐ ├ ┼ ┤ └ ┴ ─`（U+250C/U+252C/U+2510/U+251C/U+253C/U+2524/U+2514/U+2534/U+2500）

连续多行 box 行组成一个块，整块转换。

## 转换规则（语义）

1. 用 `│` 切分每行的单元格（先剥掉外框 `┌┐├┤└┴┬┼─`）。
2. **第一行 = 表头**；紧接着的纯分隔行（全是 `─`/`┼`）**丢弃**。
3. 其余 `│` 行 = 数据行。
4. 输出：
   ```
   （前空行）
   | 表头1 | 表头2 |
   |---|---|
   | 数据1 | 数据2 |
   （后空行）
   ```
5. 列数取所有行最大值，数据行不足补空串。

## 可复用转换函数

```python
BOX_CHARS = set('┌┬┐├┼┤└┴┬┼─│')

def _is_box_row(line):
    return '│' in line and any(c in BOX_CHARS for c in line)

def _cells_of(line):
    # 剥外框后按 │ 切分
    s = line.strip()
    for b in '┌┐├┤└┴┬┼─':
        s = s.replace(b, '│')
    parts = s.split('│')
    if parts and parts[0].strip() == '':
        parts = parts[1:]
    if parts and parts[-1].strip() == '':
        parts = parts[:-1]
    return [p.strip() for p in parts]

def _is_sep_row(cells):
    return bool(cells) and all(set(c) <= set('─┼┬┴├┤┐┘┌└') for c in cells) and any('─' in c for c in cells)

def box_to_pipe(md_text):
    lines = md_text.split('\n')
    out, i = [], 0
    while i < len(lines):
        if _is_box_row(lines[i]):
            block = []
            while i < len(lines) and _is_box_row(lines[i]):
                block.append(lines[i]); i += 1
            grid = [_cells_of(b) for b in block]
            grid = [r for r in grid if r]
            if not grid:
                out.extend(block); continue
            ncol = max(len(r) for r in grid)
            header = grid[0]
            data = []
            for r in grid[1:]:
                if _is_sep_row(r):
                    continue
                while len(r) < ncol:
                    r.append('')
                data.append(r)
            pipe = ['| ' + ' | '.join(header) + ' |',
                    '|' + '|'.join(['---'] * ncol) + '|']
            for r in data:
                pipe.append('| ' + ' | '.join(r) + ' |')
            out.append('')
            out.extend(pipe)
            out.append('')
        else:
            out.append(lines[i]); i += 1
    return '\n'.join(out)
```

## 注意事项

- 转换后人工核对表头语义是否准确（字符画有时表头与数据混排，需结合上下文判断）。
- 转换后跑一次 postprocess 的「孤儿 `**` 校正」与「标题修复」，确保无残留孤立 `**`。
- 该函数只处理 `│` 分隔的矩形框；纯 ASCII 流程图（`+----+` / 普通 `|`）不在此列，按代码块或手动画图处理。
