# 微信公众号页面结构参考（2026年）

## 背景

2026年5月发现微信公众号页面结构已升级，使用 Vue.js 动态渲染。旧版 HTML 提取方式（`div#js_content`）对新版页面失效。

## 两种页面结构对比

### 旧版（传统 HTML）

- 标题在 `var msg_title = '...'` 或 `og:title` 中
- 正文在 `<div id="js_content" style="visibility: hidden;">...</div>` 中
- 图片使用 `<img data-src="...">` 标签
- 可通过 readability-lxml 等库提取

### 新版（Vue.js 动态渲染）

- 页面约 1.9MB，大部分为 JavaScript 代码
- 文章数据存储在 `<script>` 标签的 `cgiDataNew` 对象中
- 标题：`title: JsDecode('...')`
- 正文：`content_noencode: JsDecode('...')`（纯文本，非 HTML）
- 作者：`nick_name: JsDecode('...')`
- 时间：`create_time: JsDecode('...')`
- 封面图：`cdn_url_1_1: JsDecode('...')` 或 `cdn_url: JsDecode('...')`
- 需要模拟微信 JsDecode 函数解码转义序列

## JsDecode 函数

微信前端使用 `JsDecode` 函数解码转义字符：

```javascript
function JsDecode(str) {
    return str
        .replace(/\\x5c/g, '\\')    // 反斜杠
        .replace(/\\x0d/g, '\r')   // 回车
        .replace(/\\x22/g, '"')    // 双引号
        .replace(/\\x26/g, '&')    // & 符号
        .replace(/\\x27/g, "'")    // 单引号
        .replace(/\\x3c/g, '<')    // 小于号
        .replace(/\\x3e/g, '>')    // 大于号
        .replace(/\\x0a/g, '\n');  // 换行
}
```

Python 等效实现——注意 `\n` 必须替换为实际换行符（ASCII 10）而非字面 `\n`：

```python
def jsdecode(val):
    if not val:
        return val
    val = val.replace('\\x5c', '\\')
    val = val.replace('\\x0d', '\r')
    val = val.replace('\\x22', '"')
    val = val.replace('\\x26', '&')
    val = val.replace("\\x27", "'")
    val = val.replace('\\x3c', '<')
    val = val.replace('\\x3e', '>')
    val = val.replace('\\x0a', '\n')  # 注意：'\n' 是实际换行，不是字面 '\n'
    return val
```

## 诊断方法

检查页面是旧版还是新版：

```bash
# 检查是否有传统 HTML 内容区
grep -c 'id="js_content"' page.html

# 检查是否有新版脚本数据区
grep -c 'content_noencode' page.html
```

## 已知局限

- 新版正文是纯文本，不含图片链接和富文本格式
- 如果正文包含图片，需额外从 `cdn_url` 或 `sub_articles` 字段获取
- 多图文消息需检查 `sub_articles` 数组
