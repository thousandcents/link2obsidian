# 批量多文章 Markdown 拆分参考

## 场景

用户从 ima 知识库「微信收藏」批量导出文章，得到一份包含多篇文章的合并 Markdown 文件。需要按文章拆分为独立文件，下载图片并改写为本地引用。

## 输入文件结构

典型输入（`option_articles_content.md`）：
- 开头：总说明（`# 期权相关文章正文导出（共 14 篇）` + 数据来源说明）
- 分隔：`---` 水平线
- 文章：`## 1. 标题` / `## 2. 标题` ... `## 14. 标题`
- 图片：`![](https://mmbiz.qpic.cn/...)` 或裸 URL
- 结尾：无总结束符

## 核心代码模板

```python
import re
import os
import urllib.request
from pathlib import Path

SOURCE_FILE = Path('/path/to/merged.md')
CLIPPINGS_DIR = Path('/home/jack-lin-sparrow/Obsidian/Thousand/Clippings')
IMAGES_DIR = CLIPPINGS_DIR / 'images'

content = SOURCE_FILE.read_text(encoding='utf-8')
parts = re.split(r'(?=^## \d+\. )', content, flags=re.MULTILINE)

articles = []
for part in parts:
    part = part.strip()
    if not part:
        continue
    if not re.match(r'^## \d+\. ', part):
        continue  # 跳过开头总说明
    
    title_match = re.match(r'^## \d+\. (.+?)$', part.split('\n')[0])
    if title_match:
        title = title_match.group(1).strip()
        safe_title = re.sub(r'[\\/:*?"<>|]', '', title)
        articles.append((safe_title, part))
```

## 图片处理（两种模式）

### 模式 1：标准 markdown `![](url)`

```python
img_pattern = r'!\\[([^\\]]*)\\]\\((https?://[^\\)]+)\\)'
images = re.findall(img_pattern, article_content)
for alt_text, img_url in images:
    # 下载并替换
    new_content = new_content.replace(f']({img_url})', f'](Clippings/images/{filename})')
```

### 模式 2：裸 URL（ima 导出常见）

```python
bare_url_pattern = r'https://mmbiz\\.qpic\\.cn/[^\\s\\)\\\"]+'
urls = re.findall(bare_url_pattern, content)
for url in urls:
    clean_url = url.rstrip(')')  # 清理尾部残留
    # 下载并替换
    new_content = new_content.replace(url, f'Clippings/images/{filename}')
```

## 图片命名（MD5 哈希，用户强约束）

为避免重名冲突和图片丢失，必须用 **URL 的 MD5 哈希** 作为文件名：

```python
import hashlib
url_hash = hashlib.md5(img_url.encode()).hexdigest()
ext = '.jpg' if ('jpeg' in img_url or 'jpg' in img_url) else ('.png' if 'png' in img_url else ('.gif' if 'gif' in img_url else '.jpg'))
fname = f"{url_hash}{ext}"
```

不要用 `os.path.basename(url.split('?')[0])` 提取文件名——不同 URL 可能指向同一张图片但 basename 不同，导致重复下载和引用断裂。

## 保护-恢复模式（避免文本变换破坏图片标记）

批量处理时，表格修复、`\n` 替换等文本变换可能破坏图片 alt 文本（如 `![<table>...</table>](url)` 中的 `<table>` 会被表格修复误删）。必须先提取图片标记，执行完文本变换后再恢复：

```python
# 1. 提取所有图片标记，用占位符替换
img_pattern = r'(!\\[.*?\\]\\()(https?://[^)]+)(\\))'
img_markers = []
counter = [0]

def protect_imgs(m):
    key = f"___IMG_{counter[0]}___"
    img_markers.append(m.group(0))
    counter[0] += 1
    return key

protected = re.sub(img_pattern, protect_imgs, content, flags=re.DOTALL)

# 2. 执行表格修复、\n 替换等文本变换（在 protected 上操作）
fixed = fix_tables(protected)
fixed = fixed.replace('\\\\n', '\n')  # 字面量换行

# 3. 恢复图片标记
for i, marker in enumerate(img_markers):
    fixed = fixed.replace(f"___IMG_{i}___", marker)

# 4. 统一替换 URL 为本地路径
for alt_text, img_url in img_markers_parsed:
    local_fname = download_and_get_fname(img_url)
    fixed = fixed.replace(f']({img_url})', f'](Clippings/images/{local_fname})')
```

## 伪图片跳过

部分导出格式包含 `!(数字,数字,数字,数字)` 这类坐标标记，不是真实图片，必须跳过：

```python
pseudo_img_pattern = r'^!\\[\\]\\(\\d+,\\d+,\\d+,\\d+\\)$'
if re.match(pseudo_img_pattern, img_tag):
    continue  # 跳过伪图片
```

## 表格修复与图片 alt 的冲突

WeChat 导出的图片 alt 文本可能包含 `<table>` 结构（如 `![<table><tr><td>...</td></tr></table>](url)`）。直接全局移除 `<table>` 标签会破坏图片 alt。解决方案：

1. **保护-恢复模式**（推荐）：先提取图片标记占位，表格修复完成后再恢复。
2. **范围限制**：表格修复只作用于非图片区域（通过占位符划分边界）。

## 字面量 `\n` 替换

WeChat 导出文件在图片 alt 和正文中常出现 `\n` 字面量，需全局替换为真实换行。注意：

- 必须在图片标记恢复后执行，否则会把 markdown 图片标记本身也改坏。
- 使用 `content.replace('\\n', '\n')` 而非 `re.sub(r'\\n', '\n', content)`（后者在含特殊字符时可能行为不一致）。

## 文件名生成

```python
url_path = img_url.split('?')[0]  # 去掉查询参数
filename = os.path.basename(url_path)
if not filename or '.' not in filename:
    filename = f'image_{idx+1}.png'

# 重名处理（MD5 模式下通常不需要，但保留兜底）
base, ext = os.path.splitext(filename)
counter = 1
while (IMAGES_DIR / filename).exists():
    filename = f"{base}_{counter}{ext}"
    counter += 1
```

## 常见问题

### Q: 为什么分割后只有 1 篇文章？

**A**: 正则 `^## \\d+\\. ` 必须匹配行首，若文件有 BOM 或前导空格会失败。用 `re.match(r'^## \\d+\\. ', part)` 验证每段标题。

### Q: 标题带日期后缀（如 `20200219`）怎么办？

**A**: 取整行作为标题即可，不要 strip 日期。日期是文章元数据，保留在文件名中可溯源。

### Q: 图片下载成功但 Markdown 仍显示远程链接？

**A**: 检查是否为裸 URL 模式（无 `![]()` 包裹）。标准模式的 `replace` 是 `f']({img_url})'`，裸 URL 直接用 `url` 文本替换。

### Q: 部分图片 URL 被截断怎么办？

**A**: ima 导出时 `mmbiz.qpic.cn` 链接可能丢失尾部字符。下载前 `url.rstrip(')')` 清理，若仍失败则跳过并记录。

### Q: 图片 alt 文本含 `[` 导致正则匹配失败？

**A**: 复杂 alt（如 `![[min(期末价格/期初价格,1)-1]x 杠杆倍数(如有)](url)`）会让简单 `r'!\\[[^\\]]*\\]'` 提前闭合。使用分组捕获 `r'(!\\[.*?\\]\\()(https?://[^)]+)(\\))'` + `re.DOTALL` 可保留完整 alt。

### Q: 表格修复后图片 alt 中的 `<table>` 被抹掉？

**A**: 未使用保护-恢复模式。先提取图片标记占位，表格修复完成后再恢复。详见上方「保护-恢复模式」。

### Q: 为什么用 MD5 命名而不是 URL basename？

**A**: 不同 URL 可能指向同一张图片但 basename 不同（如 `mmbiz.qpic.cn/xxx?wx_fmt=jpeg` vs `mmbiz.qpic.cn/xxx?wx_fmt=png`），用 basename 会导致重复下载和引用断裂。MD5 保证同一 URL 唯一对应一个文件。

## 验证清单

- [ ] 文章数量 = 用户声称数量（如 14）
- [ ] 每篇文章有独立 `.md` 文件
- [ ] 所有 `![](http://...)` 已替换为 `![](Clippings/images/xxx.png)`
- [ ] 无残留裸 URL（`grep -l 'mmbiz.qpic.cn' *.md` 应为空）
- [ ] 图片文件非空（`find images -empty -type f` 应为空）
- [ ] 无重复文件（如带日期和不带日期两个版本）
- [ ] 图片引用全部为本地路径（无 `http` 残留）
- [ ] 图片文件存在（引用数与实际文件数一致）
- [ ] 无字面量 `\n` 残留（正文和图片 alt 中）
- [ ] 表格格式正确（GFM pipe table，前后有空行）
