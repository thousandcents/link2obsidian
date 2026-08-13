# Code fence 行尾反引号吞掉章节标题

## 症状

WeChat 文章中若某个 `<code>` 标签出现在段末（如「开源地址：`https://github.com/...`」），HTML→Markdown 转换器会将 `<code>` 标签替换为单反引号 `` ` ``。当行末是关闭反引号、而下一行（原文本中的新段落）以编号标题 `02` / `03` 等开头时，反引号+编号的拼接被 Markdown 解析器当作行内代码，导致标题丢失。

**实战案例（2026-08-10）**：`gc-minimal-zine-poster` 开源地址行末反引号 ` 紧跟 `02`，生成后正文中：

```
开源地址：https://github.com/LiamGvchi/gc-minimal-zine-poster`02
```

而非期望的：

```
开源地址：https://github.com/LiamGvchi/gc-minimal-zine-poster

## 02
```

postprocess.py 的标题升级规则只处理「独立段落行」→ `## NN`，但此处 `02` 已在同一行、不是独立行，因此漏修复。

## 修复手法

用 `execute_code` 按精确字符串替换：

```python
content = content.replace(
    "开源地址：https://github.com/LiamGvchi/gc-minimal-zine-poster`02",
    "开源地址：https://github.com/LiamGvchi/gc-minimal-zine-poster\n\n## 02"
)
```

## 检测方式

postprocess 完成后搜索 `` `NN`（反引号+纯数字开头）模式，若命中即说明存在此残留：

```python
import re
m = re.findall(r'`(\d{2,3})', content)
# 若非空，则存在标题丢失
```

**注意**：不能盲目删除所有 `` `NN` 模式（合法行内代码也可能匹配），需人工确认上下文是否为章节编号。

## 根因

scraper 的 HTML→Markdown 阶段用 `</?code>` → `` ` `` 的替换是逐标签、不感知行边界的。WeChat 中「开源地址」常以 `<code>` 标签包裹 URL，URL 后紧跟新段落的标题，两者在原文中本就不在同一 HTML 标签内，但被统一替换后丢失了段落边界。

## 预防

目前无自动预防手段（scraper 层面修复可能误伤合法行内代码）。建议 postprocess 后增加一个扫描步骤，搜索 `` `NN` 模式并输出 `⚠️ 需 AI` 提示。