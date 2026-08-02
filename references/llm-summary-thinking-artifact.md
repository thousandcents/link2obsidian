# LLM 摘要中的思维链泄漏

## 问题描述

runner.py 调用 LLM 生成文章要点摘要时，某些模型（如感知的 xunfei/astron-code-latest）
在 `**文章要点**` 区块里渗入了思维链（Chain-of-Thought）元指令，
表现为 `> - **Role:**`、`> - **Task:**`、`> - **Format:**` 等标签式内容，
而不是真正的要点列表。

## 诊断

在生成的 markdown 文件中搜索以下模式。任一模式出现即判定为思维链泄漏：

```
> - **Analyze the Request
> - **Role
> - **Task
> - **Format
> - **1.
> - **2.
> - Thinking Process:
> - *   Role:
> - *   Task:
> - *   Language:
> - *   Format:
```

关键特征：`> - **` 后面跟的是元指令关键词（Role/Task/Format/Analyze/Thinking Process），
而非具体的文章要点内容。

若 `> 📌 **文章要点**` 之后紧跟的是结构化的元指令而不是具体要点，
则为思维链泄漏。

## 修复方法

```python
p = "path/to/article.md"
with open(p, "r", encoding="utf-8") as f:
    content = f.read()

# 找到要点区块起止
start = content.find("> 📌 **文章要点**")
end = content.find("\n# ")  # 正文标题

# 重写为干净的 3~5 条要点
new_summary = "> 📌 **文章要点**\n"
# 根据文章实际内容人工生成 3~5 条 30~50 字的具体要点

content = content[:start] + new_summary + content[end:]
with open(p, "w", encoding="utf-8") as f:
    f.write(content)
```

## 根因

这是 LLM API 的行为差异：某些推理模型在输出结构化摘要时，
会把内部的规划步骤当成摘要内容返回。
这不是 runner.py 的 bug，但属于已知的 postprocess 盲区。

## 预防

第 5 步（生成 LLM 摘要）中增加检查：
生成摘要后立即扫描 `> - **` 开头的元指令模式，发现则替换。
详见 `references/llm-summary-thinking-artifact.md`。