# LLM 摘要网络不可达时的手动回退流程

## 触发条件

runner.py 摘要阶段同时满足以下两点时，进入手动回退：

1. 终端打印 `⚠️ LLM 走代理仍失败: <urlopen error [Errno 101] Network is unreachable>`
2. 生成的文件中**没有** `> 📌 **文章要点**` 段

## 不要误判为「LLM 未配置」

runner.py 的失败分支有三条，互不重叠：

| 终端提示 | 含义 | 处理 |
|----------|------|------|
| `ℹ️ 未配置 API key，跳过 LLM 总结` | `.env` / `config.yaml` 中无可用 key | 需用户配置密钥 |
| `⚠️ LLM 被限流` / `⚠️ LLM 认证失败` | 端点/key 有效但被网关拒绝 | 修正配置或等待 |
| `⚠️ LLM 走代理仍失败: Network is unreachable` | 网络层故障，直连和代理均不通 | **手动补摘要** |

最后一种才是本文件要处理的场景。特征是**直连先失败**（`urllib.error.URLError`），**代理回退也失败**（同样的 `Network is unreachable`），说明当前会话进程整体无法出站访问 LLM API。

## 手动回退 SOP

1. **确认无摘要**：`grep -n "📌 **文章要点**" <文章.md>`，无输出则继续
2. **读取全文**：用 `read_file` 或 `open(path).read()` 读取正文，注意不要用 `read_file` 的行号输出做正文分析
3. **提炼 3~5 条要点**：
   - 每条 30~50 字
   - 聚焦核心结论、关键数据、方法论
   - 不写废话、不重复标题、不加序号
4. **插入位置**：frontmatter 的 closing `---` 之后、正文第一个 `#` 标题之前
5. **格式模板**：

```markdown
> 📌 **文章要点**
> - 要点一
> - 要点二
> - 要点三

```

## 常见失败模式速查

- `HTTP 403` + body 含 `QpsOverFlow`：限流，等 60s 后重跑 runner.py 即可，无需手动补
- `HTTP 401`：认证失败，需检查 `.env` 的 `AGNES_API_KEY` 等配置
- `Network is unreachable`：网络层故障，直接走手动回退
- `read timeout`：偶发，可重跑 runner.py 一次；若仍失败则手动回退
