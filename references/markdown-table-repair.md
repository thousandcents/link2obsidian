# Markdown 表格修复指南（通用）

当链接抓取、粘贴或手写的 Obsidian Markdown 文件中出现表格格式混乱时，按本指南修复。
适用于 `Clippings/` 抓取 article、`programming_file/` 工作记录、以及任何 vault 内文件。

## 三类"乱码"表格及识别

| 类别 | 识别特征 | 工具处理状态 |
|---|---|---|
| **A. box-drawing 字符表** | 含 `┌ ┬ ┐ └ ┴ ┘ ├ ┤ ┼ ─` | scraper **不转**；postprocess 压平检测**漏掉**（不含 `%`） |
| **B. 空格对齐数据表** | 行内无 `\|`、列用空格对齐，含数字/`%`/品种代码（如 `.CFE` `.DCE`） | scraper 不转；postprocess 部分检测（只报 `%`+加粗 行），不自动重建 |
| **C. 缩进的 pipe 表** | 行以 `  \|`（缩进）开头而非列 0 的 `\|` 开头 | Obsidian 视为普通文本段落，**不会渲染为表格** |

> 注：**流程树/调用链图**（`└─` `├─` `─►` `↓`）不属于表格，保留原样不动。

## 修复步骤（推荐脚本化）

### 1. 定位

用 `execute_code` 正则扫描文件：

```python
with open(path) as f:
    lines = f.readlines()
for i, ln in enumerate(lines):
    if re.search(r'[┌┬┐└┴┘├┤┼─]', ln):
        print(f"L{i+1}: {ln[:100]}")
    if re.search(r'\.(CFE|DCE|SHF|CZC|GFE|INE)\b', ln) and not ln.startswith('|') and len(ln) < 80:
        # 可能是空格对齐数据表
```

### 2. 用 `open(path).read()` 获取真实字符串

`read_file()` 输出的行号前缀 `N|` 与原文件不同，会导致字符串替换静默失败。**修复脚本必须 `open(path).read()` 直接读文件**。

### 3. 用文件中实际读出的文本做 `old`，不要用内存手写的版本

**高频踩坑**：box-drawing 字符和空格对齐的 `old` 字符串若凭记忆手写（尤其中文全角/半角、空格数量），极易字符不匹配导致 `replace` 不生效或 `assert` 失败。

**正确做法**：

```python
lines = content.split('\n')
old = '\n'.join(lines[start-1:end])   # start/end 是 1-indexed 行号
content = content.replace(old, new, 1)
```

### 4. box-drawing → pipe 表转换要点

- 拆表头行 + 数据行，合并跨行截断的单元格内容（如 `reverse_osc_tren`+`d()` → `reverse_osc_trend()`）
- 第二行 `| --- | --- |`，代码/文件/函数名用反引号包裹
- 可复用的 box-drawing 转换函数见 `references/wechat-boxdrawing-flowchart.md`

### 5. 空格对齐 → pipe 表转换要点

- 首行作表头，其余每行一个 pipe 行
- 保留语义注解（如 `← 收益最高`）

### 6. 修复缩进（关键，易遗漏）

新生成的 pipe 表若带缩进，**Obsidian 不会渲染为表格**。
找出所有以 `  |` 开头的连续块，对每行去掉前导空格，保证 pipe 在列 0：

```python
for b in block:
    new_lines.append(b[2:])
```

### 7. 验证

```python
box_chars = set(re.findall(r'[┌┬┐└┴┘├┤┼]', content))
# ② 确认每个 pipe 表前有空行（GFM 规范）
# ③ 核对原有原生 GFM 表未被破坏
```

## 工具选择

- **小文件/少量表**：`execute_code` 内 `content.replace()` + `open().write()`
- **大文件/多表**：先 `read_file()` 看上下文，再 `execute_code` 读取完整内容做批量替换
- 不要试图用 `patch()` 工具 `old_string` 传递含中文 em-dash（`—`）的字符串，会触发 `SyntaxError`；直接用 Python 字符串替换绕过

## 与 link2obsidian 管线的关系

- 本指南覆盖的是 **postprocess.py 之后、Agent 手动修复阶段** 的表格问题
- postprocess.py 已自动检测的"压平行"（`⚠️ 需 AI`）按本指南 B 类处理
- postprocess.py **未覆盖** box-drawing（A 类）和缩进问题（C 类）