# LLM 摘要配置解析 与 403 排查

## load_llm_config 配置解析优先级（runner.py）

按以下顺序决定 `base_url / model / api_key`：

1. 默认值：`base_url=https://opencode.ai/zen/go/v1`，`model=deepseek-v4-flash`，`api_key=''`。
2. `.env` 读入字典 `env_vars`（值为字面 `***` 的占位符会被跳过，不进入 `env_vars`）。
3. `config.yaml` 的 `model.base_url` / `model.api_key`（支持 `${VAR}` 展开）。
4. `.env` 的 `SENSE_API_KEY` > `OPENCODE_GO_API_KEY` > `OPENAI_API_KEY`（仅当 api_key 仍为空时取第一个）。
5. `.env` 的 `OPENAI_BASE_URL` 若存在则覆盖 `base_url`。
6. 若 `base_url` 含 `xf-yun` / `maas-coding` → `model=astron-code-latest`。
7. **（本 profile 当前生效）** 若 `env_vars` 同时存在 `AGNES_BASE_URL` 与 `AGNES_API_KEY` → 覆盖 `base_url`/`api_key` 且 `model=agnes-2.0-flash`。

⚠️ 坑：变量名严格匹配。`OPENCODE_GO_BASE_URL` 不会被识别（只认 `OPENAI_BASE_URL`）；`AGNES_*` 仅在第 7 步生效。改了 `.env` 变量名却没同步代码 → 静默回退默认值。

## 403 诊断配方（实测有效）

现象：runner.py 摘要总报 `HTTP 403`，body `error code: 1010`。

排查步骤：

1. 复刻 `runner.load_llm_config('ob_xianzi')` 打印返回，确认 `base_url/model/api_key` 是否符合预期。常见错配：`base_url` 变成默认 `opencode.ai/zen/go/v1`（说明真实模型配置没被读到）。
2. 用 `urllib` 分别**直连**（`ProxyHandler({})`）与**走代理**（`ProxyHandler(None)`）打 `{base_url}/chat/completions`：
   - 若**两者 body 完全相同** → 403 来自真实网关，**不是代理问题**（代理只是透传管道）。
   - `403` 属 `HTTPError`，`_call_llm` 内**不**触发代理回退（只有连接层异常才回退）。
3. 即便用 `.env` 真实 `OPENCODE_GO_BASE_URL` + `OPENCODE_GO_API_KEY` 直连仍 403 → 该 key 被网关拒绝（失效/过期/限流/QPS），与端点选择无关。

## 修复（本 profile 已落地，验证 HTTP 200）

在 `.env` 设：

```
AGNES_BASE_URL=https://apihub.agnes-ai.com/v1
AGNES_API_KEY=<真实 key>
```

`runner.py` `load_llm_config` 第 6 步自动采用，`model` 固定 `agnes-2.0-flash`，其他抓取/图片/后处理不变。验证：直连 `apihub.agnes-ai.com/v1/chat/completions` 返回 HTTP 200 与有效摘要。

## _call_llm 网络策略（被 runner.py 提取执行的内联代码）

- 默认直连 opener（`ProxyHandler({})`）；仅当**连接层异常**（非 `HTTPError`，如超时/SSL/连接拒绝）才回退代理 opener（`ProxyHandler(None)`）。
- `HTTPError`（401/403/限流）**不**回退，直接返回空摘要（由 Agent 后续补 `> 📌 文章要点`）。
- 因此：代理侧的 403/限流不会自愈，必须先修正 `load_llm_config` 的端点/key 配置。
