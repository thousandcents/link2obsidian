# WeChat 行内代码空格与标题残留清理

postprocess.py 之后，人工复核时常见的两类语义型残留（postprocess.py 未覆盖，需 Agent 手动修）。

## 1. 行内代码首尾多余空格 + 全角标点前空格

WeChat HTML→MD 转换常把 `` `foo` `` 写成 `` ` foo` `` 或 `` `foo ` ``（反引号**内**首尾空格），
以及 `` `foo` ：`` / `` `foo` 。`` / `` `foo` ，``（反引号后接空格再跟全角标点）。
这在技术类微信文章（大量 inline code 如 `` `skills` ``、`` `implement` ``、`` `/to-spec` ``）中高频出现。

统一清理（execute_code 内用正则，勿走 patch 工具传参，避免中文破折号 U+2014 沙箱陷阱）：

```python
import re
c = open(path, encoding="utf-8").read()
# 行内代码内首尾空格：` foo` / `foo ` → `foo`
c = re.sub(r"`\s+([^`\n]+?)\s+`", r"`\1`", c)
# 反引号后接空格+全角标点 → 去空格：`foo` ：→ `foo`：
c = re.sub(r"`([^`\n]+)`\s+([：。，、；])", r"`\1`\2", c)
open(path, "w", encoding="utf-8").write(c)
```

⚠️ 只清理**反引号内**的首尾空格；反引号与中文之间的空格（`` `foo` 说明 ``）是正常中英混排空格，**不要动**。

## 2. `## 参考` 标题 + 孤立「资料」行

参考资料区常被拆成 `## 参考` 标题 + 下一行 `资料• GitHub...`（"资料"是标题残留的孤字，与 `•` 粘连）。
修复：标题统一为 `## 参考资料`，并去掉行首孤立「资料」，使 `资料• xxx` 变回 `• xxx`。

```python
c = c.replace("## 参考\n\n资料• GitHub 仓库", "## 参考资料\n\n• GitHub 仓库")
```

## 3. 断言字符串与原文标点差异陷阱

手动修复用 `assert old in c` 校验时，不要把行内空格想当然。真实案例：`17,715 Forks**。`
前是顿号 `、` 而非空格，按 `" 17,715 Forks**。"` 断言会失败。先从 `read_file`/`search_files`
确认原文精确字符（`、` vs 空格、全角 vs 半角）再写断言。