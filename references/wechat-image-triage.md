# 微信文章图片分类与清理（link2obsidian 实战）

runner + postprocess 默认把每张 qpic.cn 图都嵌入正文，且不做内容过滤，于是装饰图/表情包/引流二维码图/风险声明图也会被原样嵌进笔记。postprocess 报告「0 项需 AI 介入」**不意味着图片已妥当**——它只统计格式类修复，不判断图片是否内容相关。Agent **必须对每一张图片逐张使用 vision_analyze 进行视觉确认**。

## 判定协议（对每一张图 vision_analyze）

| 类别 | 判据 | 处理 |
|------|------|------|
| 内容图 | 数据图表/架构图/流程图/路线图/对比表/示意图；或**读者评论截图作为论据**（如「一喊拿住AI就跌」的调侃截图，服务于文章论点）；或软件界面/功能截图 | 保留 |
| 封面图 | 宽幅海报、品牌 logo、文章题图 | 删除 |
| 引流图 | 带二维码的活动海报/「扫码申请试听」「持有人集合」类私域转化图 | 删除 |
| 二维码 | 纯二维码图片、社群/公众号引流码 | 删除 |
| 装饰图 | 无信息量的装饰性图片、空白分隔符、纯色图 | 删除 |
| 表情包 | 反应梗图（"be like"、电影台词截图、表情包），无信息量，仅表达情绪 | 删除 |
| 风险说明 | 底部风险声明、投资提示、免责声明等模板化文本图 | 删除 |
| **文末互动引导图** | 卡通人物+「求分享」「求点赞」「在看也点下」等公众号互动话术的**表情包/插画**（常见于文章末尾，无正文信息量） | 删除 |
| **空白/无信息图** | 纯色（如纯白）、无文字、无图案、无数据点的图像（常见于装饰性 GIF/PNG，如空白分隔符） | 删除 | 视觉确认后删除，不保留无信息量图像 |

> **强制视觉筛查**：所有下载的图片都必须通过 `vision_analyze` 逐一分析，不能仅凭文件名或位置猜测。只有明确判定为「内容图」的才保留。
>
> 兜底（vision 不可用时）：纯工具/项目介绍无引流话术→图片大概率是软件截图**保留**；含「关注公众号/加群/扫码」→按引流图**删除**；不确定则保留并请用户确认。

## 删除后的连带清理
- **悬空句**：删图后若紧邻一句只是该图的说明/引子（如「但我的表情仍旧 be like」），同样删掉，否则读起来断裂。
- **引流尾巴**：文末「------------分割线------------」+「周四直播…」+「扫码申请试听」+ 海报图，整体属于推广，按分割线截断删除（见下）。

## 批量删除写法（execute_code）

```python
from pathlib import Path
import re
p = Path(".../Clippings/文章.md")
c = p.read_text(encoding="utf-8")
for img in ["2bf1....png", "48cd....png", "5ee1....jpg"]:   # 待删图文件名
    c = c.replace(f"![{img}](Clippings/images/{img})", "")
# 删引流尾巴（从分割线到文末）
div = "------------分割线------------"
if div in c:
    c = c.split(div)[0].rstrip() + "\n"
c = re.sub(r"\n{3,}", "\n\n", c)
p.write_text(c, encoding="utf-8")
```

⚠️ 图片路径用 vault-root 相对 `Clippings/images/xxx`，勿用 `../images/`。删除用整串 `replace` 而非 `replace(img+"\n\n\n", "\n")`，后者常因空白行数不匹配而静默无效。

## 批量二维码检测（OpenCV）

`vision_analyze` 逐张识别二维码效率低且可能 404。可用 OpenCV 的 `QRCodeDetector` 批量检测：

```python
import cv2
from pathlib import Path

detector = cv2.QRCodeDetector()
for img_path in Path("Clippings/images").iterdir():
    if img_path.suffix.lower() not in (".png", ".jpg", ".jpeg", ".webp"):
        continue
    img = cv2.imread(str(img_path))
    if img is None:
        continue
    data, bbox, _ = detector.detectAndDecode(img)
    if data:
        print(f"删除二维码: {img_path.name} (内容: {data[:50]})")
        img_path.unlink()
```

- 无需视觉模型，纯本地计算
- 即使图片有轻微变形/水印也能识别
- 适合在 `postprocess` 后、入库前做批量净化
