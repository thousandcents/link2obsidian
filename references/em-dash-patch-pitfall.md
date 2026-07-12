# execute_code 中的 Python 字符串编码陷阱

## 问题

在 `execute_code` 沙箱中，当 Python 字符串字面量包含某些 Unicode 字符时，会触发 `SyntaxError`：

- **中文破折号 `—`（U+2014 em-dash）**
- **中文引号 `""` `''`（U+201C/U+201D, U+2018/U+2019）** — 常见于 `"xxx"` 包裹的引用文字
- **中文书名号 `《》`、括号 `（）` 等特殊符号** 在特定位置

典型报错：
```
SyntaxError: invalid character '—' (U+2014)
SyntaxError: invalid syntax. Perhaps you forgot a comma?
```

## 根因

Python 沙箱对源码 UTF-8 解析存在边界行为。当多字节 Unicode 字符出现在 `patch()` 工具的参数传递路径中，或在复杂字符串字面量中，解析器可能在某些位置报错。

## 绕过方法

### 方法 1：直接文件操作（推荐）

```python
f = "Clippings/xxx.md"
with open(f, 'r') as fp:
    content = fp.read()

content = content.replace(
    "形成背景—信息—风险的研究闭环。",
    "形成背景—信息—风险的研究闭环。\n\n![...]\n"
)
with open(f, 'w') as fp:
    fp.write(content)
```

### 方法 2：用纯 ASCII 锚点

```python
patch(path, 
    old_string="The quick brown fox\n jumps over the lazy dog",  # 只 ASCII
    new_string="new content\n")
```

## 不要这样做

❌ 在 `patch()` 工具的 `old_string` 参数中包含 `—` `""` `《》` 等字符
❌ 在 `execute_code` 的 Python 源码中直接写含 `—` 的字符串字面量
❌ 期望 `read_file()` 的输出（带 `N|` 行号前缀）与文件原始内容一致

## 适用场景

- 任何需要修改含中文特殊字符的文件
- 任何 `patch()` + `execute_code` 组合
- WeChat 文章后处理（经常含 `—` `"` `《》`）
