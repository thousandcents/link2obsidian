# 题图识别与清理指南

当需要清理 Obsidian `Clippings/` 目录下文章的封面图（题图）时，按以下方法论操作。

## 什么是题图（封面图）

微信公众号文章首张图片通常是封面图/题图，用于公众号列表展示，并非文章内容的一部分。在 Obsidian 中阅读时，这张图通常不需要保留。

## 识别方法

### 位置判定
- 位于文章 YAML frontmatter 之后
- 位于 LLM 摘要（`> 📌 **文章要点**`）之后
- **图片之前没有实质性正文内容**

### 图像属性判定
- **引用次数**：在 Clippings/ 目录下只被 1 篇文章引用（专属图），而非多篇文章共享（如公众号底图）
- **alt 文本**：为空或仅为文件名（如 `![062dfd056bfc4f7b9deacf2ba63374fc](...)`）
- **图片尺寸**：通常为宽幅海报尺寸（如 900x500+）

### 共享底图识别
- 某些公众号使用统一的底部推广图，被多篇文章（如 30+ 篇）引用
- 这类图片不应被删除，因为它们对多篇文章有意义

## 自动化检测脚本

```python
import os, re
from collections import Counter

clippings_dir = '/home/jack-lin-sparrow/Obsidian/Thousand/Clippings/'

# 1. 统计每个图片被引用的次数
image_refs = Counter()
article_first_images = {}

for f in os.listdir(clippings_dir):
    if not f.endswith('.md'):
        continue
    path = os.path.join(clippings_dir, f)
    content = open(path, 'r', encoding='utf-8').read()
    
    refs = re.findall(r'!\[([^\]]*)\]\(([^)]+)\)', content)
    for alt, src in refs:
        img_name = os.path.basename(src)
        image_refs[img_name] += 1
    
    first_ref = re.search(r'!\[([^\]]*)\]\(([^)]+)\)', content)
    if first_ref:
        article_first_images[f] = (first_ref.group(2), first_ref.group(1))

# 2. 筛选可能的题图
for article, (src, alt) in article_first_images.items():
    img_name = os.path.basename(src)
    is_shared = image_refs[img_name] > 1
    has_alt = len(alt.strip()) > 5 and not re.match(r'^[0-9a-f]+$', alt.strip())
    
    if not is_shared and not has_alt:
        # 检查图片前是否有正文内容
        content = open(os.path.join(clippings_dir, article), 'r', encoding='utf-8').read()
        before_img = content.split(src)[0]
        lines = [l for l in before_img.strip().split('\n') if l.strip() and not l.startswith('---') and not l.startswith('>') and not l.startswith('tags:')]
        
        print(f"候选题图: {article}")
        print(f"  图片: {img_name} (引用{image_refs[img_name]}次)")
        print(f"  图片前行数: {len(lines)}")
```

## 删除操作

确认是题图后，删除步骤：

1. 从文章文件中删除图片引用行
2. 删除对应的本地图片文件
3. 清理多余空行（删除图片引用后可能留下连续空行）

```python
import os, re

article_path = '/path/to/article.md'
with open(article_path, 'r', encoding='utf-8') as f:
    content = f.read()

# 找到首张图片引用
first_img = re.search(r'!\[([^\]]*)\]\(([^)]+)\)', content)
if first_img:
    old_line = first_img.group(0)
    new_content = content.replace(old_line, '')
    new_content = re.sub(r'\n{4,}', '\n\n\n', new_content)
    new_content = re.sub(r'\n\*{3}\n', '\n', new_content)  # 清理 *** 分隔符
    
    with open(article_path, 'w', encoding='utf-8') as f:
        f.write(new_content)
    
    # 删除本地图片文件
    img_path = os.path.join(os.path.dirname(article_path), 'images', os.path.basename(first_img.group(2)))
    if os.path.exists(img_path):
        os.remove(img_path)
```

## 注意

- **务必先检查是否共享图**：被 30+ 文章引用的图片通常是公众号底图，不应删除
- **保留有语义化 alt 文本的图片**：如 `![MFS 架构图](...)` 可能是文章内容的一部分
- **批量操作前先列出来确认**：不要直接全部删除，先列出候选列表让用户确认