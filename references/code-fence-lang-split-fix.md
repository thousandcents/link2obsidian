# 代码块 fence + 语言标识分离修复

## 问题描述

从 WeChat SPA 内容（`content_noencode` JsDecode 后）手动构建 Markdown 时，代码块的 fence 标记和语言标识（python/rust/bash 等）被拆成独立行：

```markdown
```

python
def run():
    pass
```
```

正确格式应为：

```markdown
```python
def run():
    pass
```
```

## 修复方法

在 `postprocess.py` 的 `fix_code_blocks()` 函数末尾追加以下逻辑：

```python
    # 代码块 fence + 语言标识分离修复：
    # ``` 与语言标识被拆成独立行：
    # ```\n\npython\n  → ```python\n
    fixed_lang = 0
    pattern = re.compile(
        r"```\n+([a-zA-Z0-9_-]+)\n+(?!```)",
        re.MULTILINE,
    )
    new_text = pattern.sub(r"```\1\n", text)
    fixed_lang = len(pattern.findall(text))
    if fixed_lang:
        text = new_text
        report.append(f"  • 代码块 fence + 语言标识分离修复：{fixed_lang} 处")
```

## 根因

WeChat 文章 HTML 中 `<pre class="codeblock codeblock-prism" data-lang="python">` 的 `data-lang` 属性在 HTML→Markdown 转换时未与 ``` 标记合并，而是被解析为独立行。

## 已知受影响文件

- `Clippings/新手做量化交易，什么策略最可行？.md`（2026-07-05，2 处修复）

## 注意

- 正则要求语言标识行后紧跟非 ``` 的任意内容，避免误匹配空代码块
- 语言标识匹配范围：`[a-zA-Z0-9_-]`，覆盖常见语言名（python/rust/bash/sql/makefile/ini 等）
- 此修复应放在 `fix_code_blocks()` 末尾，紧接"代码块闭合 ``` 后粘连正文修复"之后
