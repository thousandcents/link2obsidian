# 批量处理图片常见陷阱与修复模式

## 1. MD5 命名替代 basename（用户强约束）

**问题**：早期用 `os.path.basename(url.split('?')[0])` 提取文件名，不同 URL 可能指向同一张图片但 basename 不同（如 `mmbiz.qpic.cn/xxx?wx_fmt=jpeg` vs `mmbiz.qpic.cn/xxx?wx_fmt=png`），导致重复下载和引用断裂。

**修复**：统一用 URL 的 MD5 哈希作为文件名：

```python
import hashlib
url_hash = hashlib.md5(img_url.encode()).hexdigest()
ext = '.jpg' if ('jpeg' in img_url or 'jpg' in img_url) else ('.png' if 'png' in img_url else ('.gif' if 'gif' in img_url else '.jpg'))
fname = f"{url_hash}{ext}"
```

**效果**：同一 URL 唯一对应一个文件，天然去重，引用稳定。

## 2. 保护-恢复模式（Protect-Restore Pattern）

**问题**：批量处理时，表格修复、`\n` 替换等文本变换可能破坏图片 alt 文本：
- 图片 alt 含 `<table>` 结构：`![<table><tr><td>...</td></tr></table>](url)` → 表格修复会误删 alt 中的 `<table>` 标签。
- 图片 alt 含 `[` 括号：复杂 alt 文本（如 `![[公式](url)]`）会让简单正则提前闭合。

**修复**：先提取图片标记，执行完文本变换后再恢复：

```python
import re

img_pattern = r'(!\\[.*?\\]\\()(https?://[^)]+)(\\))'
img_markers = []
counter = [0]

def protect_imgs(m):
    key = f"___IMG_{counter[0]}___"
    img_markers.append(m.group(0))
    counter[0] += 1
    return key

# 1. 保护：用占位符替换所有图片标记
protected = re.sub(img_pattern, protect_imgs, content, flags=re.DOTALL)

# 2. 变换：在 protected 上执行表格修复、\n 替换等
fixed = fix_tables(protected)
fixed = fixed.replace('\\n', '\n')  # 字面量换行

# 3. 恢复：把占位符替换回原始图片标记
for i, marker in enumerate(img_markers):
    fixed = fixed.replace(f"___IMG_{i}___", marker)

# 4. 替换：统一替换 URL 为本地路径
for marker in img_markers:
    url = extract_url_from_marker(marker)
    local_fname = download_and_get_fname(url)
    fixed = fixed.replace(f']({url})', f'](Clippings/images/{local_fname})')
```

**关键**：占位符 `___IMG_N___` 必须是原文中不可能出现的字符串，避免与正文内容冲突。

## 3. 伪图片跳过

**问题**：部分导出格式包含 `!(数字,数字,数字,数字)` 这类坐标标记，不是真实图片，会被误当作 markdown 图片处理。

**修复**：在图片匹配前过滤：

```python
pseudo_img_pattern = r'^!\\[\\]\\(\\d+,\\d+,\\d+,\\d+\\)$'
if re.match(pseudo_img_pattern, img_tag):
    continue  # 跳过伪图片
```

## 4. 字面量 `\n` 替换时机

**问题**：WeChat 导出文件在图片 alt 和正文中常出现 `\n` 字面量，需全局替换为真实换行。

**修复**：
- 必须在图片标记恢复后执行，否则会把 markdown 图片标记本身也改坏。
- 使用 `content.replace('\\n', '\n')` 而非 `re.sub(r'\\n', '\n', content)`（后者在含特殊字符时可能行为不一致）。

## 5. 复杂 alt 文本的正则匹配

**问题**：图片 alt 文本含 `[` 括号时，简单正则 `r'!\\[[^\\]]*\\]'` 会提前闭合，导致匹配失败或截断。

**修复**：使用分组捕获 + `re.DOTALL`：

```python
img_pattern = r'(!\\[.*?\\]\\()(https?://[^)]+)(\\))'
matches = re.findall(img_pattern, content, re.DOTALL)
# matches 返回 [(prefix, url, suffix), ...]，保留完整 alt 文本
```

## 6. 表格修复与图片 alt 的冲突

**问题**：全局 `<table>` 移除会破坏图片 alt 中的表格文本。

**修复**：
1. **保护-恢复模式**（推荐）：先提取图片标记占位，表格修复完成后再恢复。
2. **范围限制**：表格修复只作用于非图片区域（通过占位符划分边界）。

## 7. 验证要点

处理完成后，必须验证：

```python
# 1. 无远程链接
assert 'http://' not in content and 'https://' not in content

# 2. 无字面量 \n
assert '\\n' not in content

# 3. 图片引用与文件存在性一致
imgs = re.findall(r'!\\[.*?\\]\\(Clippings/images/([^\\)]+)\\)', content)
for f in imgs:
    assert (IMAGES_DIR / f).exists(), f"缺失: {f}"

# 4. 无伪图片残留
assert not re.search(r'^!\\[\\]\\(\\d+,\\d+,\\d+,\\d+\\)', content, re.MULTILINE)
```
