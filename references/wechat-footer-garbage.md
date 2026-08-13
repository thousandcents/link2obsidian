# 微信文章底部垃圾内容处理

postprocess.py 只覆盖固定规则，对微信文章正文末尾的引流话术和格式残留无能为力，必须在 postprocess 后人工介入清理。

## 两类垃圾

### 1. 引流话术（纯文字行）

微信文章底部常有标准化引流语，直接删除整行即可：

```python
content = content.replace("点击关注，共同进步\n", "")
```

常见变体：「关注了解更多」「关注公众号」「一起交流」等。

### 2. 代码块 fence 末尾断裂（格式噪音）

HTML 中多个相邻 `<pre>` / `<code>` 被 WeChat HTML → Markdown 转换器解析为孤立的 ``` fence + `*` 分隔行，产生如下形态：

```
#### 引用链接`[1]` https://...

[2]`https://github.com/karpathy/autoresearch
*

[3]`https://github.com/zjusharkyu/auto_optimization/
*
*
```

每个 `[N]`URL 前都有行首反引号，被误识别为代码 fence 起始符，后面跟着孤立的 `*` 行。

**修复方法**（按顺序）：

```python
import re

# ① 清理行首反引号 + [N] 格式：`[2]\`url → [2] url
content = re.sub(r'^`([^`]+)$', r'\1', content, flags=re.MULTILINE)

# ② 删除孤立 fence 行（``` 开头且无语言标识，且为连续 block 的一部分）
lines = content.split('\n')
new_lines = []
skip_fence = False
for i, ln in enumerate(lines):
    if ln.strip() == '```' and i + 1 < len(lines) and re.match(r'^\[[0-9]+\]`', lines[i+1]):
        skip_fence = True
        continue
    if skip_fence and ln.strip() == '```':
        skip_fence = False
        continue
    if skip_fence:
        continue
    new_lines.append(ln)
content = '\n'.join(new_lines)

# ③ 删除孤立 * 行
content = re.sub(r'\n\*\s*\n', '\n', content)
content = re.sub(r'\n\*\s*$', '\n', content)

# ④ 压缩多余空行
content = re.sub(r'\n{3,}', '\n\n', content)
```

**最终形态**：

```
#### 引用链接
[1] https://github.com/ajtulloch/quantcup-orderbook
[2] https://github.com/karpathy/autoresearch
[3] https://github.com/zjusharkyu/auto_optimization/
```

## 常见错误

- 不要只删 `*` 行而不处理反引号——反引号会留在 `[[N]]` 前面成为 orphan fence
- 不要误删 `#### 引用链接` 标题——这是合法引用区，不是噪音
- `skip_fence` 标记必须正确配对，否则会删错合法的代码块
