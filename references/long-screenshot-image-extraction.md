# 长截图图片提取实战（2026-07-20 创业股权文章 - 完整流程）

## 问题背景

用户提供了 4 张微信公众号长截图，要求将截图中的内容补充到文章中。后续用户反馈指出：
1. "你在文章里的插图是原始的3张图片，请只截取其中需要的部分图片即可，不要贴入全图"
2. "部分原始图片中的文字没有识别转化出来，请检查并补充"

## 完整图片处理流程

### 阶段 1：初步评估与分类

对每张截图进行 `vision_analyze`，识别：
- 是否为装饰图/引流图（封面、二维码、产品包装）→ **不嵌入**
- 是否包含内嵌内容图（信息图、表情包、示意图）→ **提取**

### 阶段 2：裁剪 UI 元素

长截图包含的 UI 元素：
- 顶部状态栏：时间、信号、电量图标（约 0-150px）
- 应用导航栏：返回按钮、更多选项（约 150-200px）
- 底部导航栏：返回键、Home 键等（约底部 150-200px）

裁剪方法：
```python
from PIL import Image
img = Image.open(path)
w, h = img.size
cropped = img.crop((0, 200, w, h-200))
```

### 阶段 3：内容图定位

对裁剪后的长图（仍可能 25000+ 像素），使用分段缩略图定位内容图：
```python
for y_start in range(0, h, 2000):
    crop = img.crop((0, y_start, w, y_start+2000))
    crop.thumbnail((540, 540))
    # 保存后用 vision_analyze 识别
```

### 阶段 4：独立图片提取

定位到内容图后，裁剪最小包围盒：
```python
# 示例：失败率信息图在 9500-10500px
failure_crop = img.crop((0, 9500, w, 10500))
failure_crop.save('startup-failure-rates.jpg')

# 示例：表情包在 24000-26000px
meme_crop = img.crop((0, 24000, w, 26000))
meme_crop.save('equity-meme.jpg')
```

### 阶段 5：OCR 文本识别

对每张提取的内容图调用 `vision_analyze` 识别文字：
```python
vision_analyze(image_url, "请识别这张图片中的所有文字内容")
```

记录 OCR 结果，用于补充到文章正文。

### 阶段 6：替换 Markdown 中的全图引用

1. 在 Markdown 中找到全图引用（如 `equity-screenshot-2.jpg`）
2. 用提取的独立图片引用替换
3. 删除全图引用行
4. 在对应文字段落后插入新图片引用

```python
# 删除全图引用
content = content.replace("![xxx](Clippings/images/equity-screenshot-2.jpg)\n\n", "")

# 插入独立图片引用
content = content.replace("相关文字", "相关文字\n\n![描述](Clippings/images/equity-failure-rates.jpg)\n")
```

### 阶段 7：清理与更新

1. **删除原始全图文件**：
```python
import os
os.remove('Clippings/images/equity-screenshot-2.jpg')
os.remove('Clippings/images/equity-screenshot-3.jpg')
```

2. **更新 frontmatter 的 sha256**：
```python
import hashlib
content = open(path).read()
parts = content.split('---\n', 2)
frontmatter, body = parts[1], parts[2]
new_sha = hashlib.sha256(body.encode()).hexdigest()
# 替换 frontmatter 中的 sha256
```

3. **验证图片引用**：
```python
import re
refs = re.findall(r'!\[.*?\]\(Clippings/images/', content)
print(f"图片引用数: {len(refs)}")
```

## 关键教训

### 1. 长截图不等于内容图
长截图是手机屏幕的完整照片，包含大量 UI 元素和已在 Markdown 中的文字。必须裁剪提取其中的独立内容图，不能直接嵌入整张截图。

### 2. 用户偏好：不要全图
用户明确反馈"不要贴入全图"，必须将长截图裁剪为独立的内容图。这是强偏好，应嵌入 skill。

### 3. 分段定位法
对 26000px 的长截图，按 2000px 分段生成缩略图，逐段 `vision_analyze` 定位内容图，比一次性分析整张图更高效准确。

### 4. UI 元素裁剪量
微信文章长截图通常需要裁剪顶部 200px 和底部 200px 以去除状态栏和导航栏。但某些截图顶部导航栏可能更高（200px+），需根据实际情况调整。

### 5. 表情包定位
网络表情包通常位于文章 humor 段落附近（如"你想的美"），在长截图中靠下位置（20000px+），需分段扫描才能找到。

### 6. OCR 文本与 Markdown 互补
OCR 识别的截图文字是对 Markdown 的补充，不是替换。两者合并后形成完整文章。对提取的每张内容图都应进行 OCR，检查是否有未识别的文字。

### 7. 必须删除原始全图
替换为独立内容图后，必须删除原始全图文件，避免磁盘残留。

### 8. SHA256 必须更新
图片引用变更后，必须重新计算 body 的 sha256 并更新 frontmatter，否则 lint 的 source-drift 检查会误报。

## 本次提取的内容图清单

| 文件名 | 类型 | 位置 (px) | OCR 文本 |
|--------|------|-----------|----------|
| startup-failure-rates.jpg | 信息图 | 9500-10500 | FAILURE RATES OF STARTUPS: 95% FALL SHORT, 80% FAIL TO SEE ROI, 40% LIQUIDATE, 99% LACK OF PLANNING |
| equity-meme.jpg | 表情包 | 24000-26000 | "你想的美" |
| equity-hourglass.jpg | 示意图 | 2400-2800 | "时间" |
| equity-drama.jpg | 剧照 | 12000-12400 | "现在我们回到关于股权分配原则" |
| equity-valuation.jpg | 示意图 | 15000-15400 | "一级市场风控模型"、"二级市场财务模型"、"10年财务预估"、"Year 1"、"Year 5" |

## 删除的原始全图

- `equity-screenshot-2.jpg`（26000+ px 长截图）
- `equity-screenshot-3.jpg`（26000+ px 长截图）
- `equity-screenshot-4.jpg`（不存在，已清理）
