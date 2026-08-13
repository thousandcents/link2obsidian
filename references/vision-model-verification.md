# Vision 模型能力核验与配置漂移诊断

当 `vision_analyze` 返回 `404 UnsupportedModel` / `does not support vision` 时，**不要直接落入「无 vision 兜底」路径**。先做两步诊断：① 确认配置的 vision 模型本身是否支持视觉；② 确认运行时实际用的模型是否与配置一致。

## 1. 直接用 curl 探测模型视觉能力（最关键、最快）

对自定义 provider（如火山方舟）直接发两个真实请求，验证配置模型是否支持图像输入：

```bash
# 文本请求（先确认模型在端点可用）
curl -s -X POST "${BASE_URL}/chat/completions" \
  -H "Authorization: Bearer ${API_KEY}" -H "Content-Type: application/json" \
  -d '{"model":"minimax-m3","messages":[{"role":"user","content":"hi"}],"max_tokens":10}' --max-time 40
```

```python
# 图像请求（Python，验证是否真支持图像输入）
import base64, json, urllib.request
png = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==')  # 1x1 PNG
b64 = base64.b64encode(png).decode()
payload = {
  'model':'<model>',
  'messages':[{'role':'user','content':[
      {'type':'text','text':'这张图是什么颜色？'},
      {'type':'image_url','image_url':{'url':'data:image/png;base64,'+b64}}]}],
  'max_tokens':30}
req = urllib.request.Request(BASE_URL+'/chat/completions', data=json.dumps(payload).encode(),
  headers={'Authorization':'Bearer '+API_KEY,'Content-Type':'application/json'})
r = urllib.request.urlopen(req, timeout=60)
print(r.status, r.read().decode()[:600])
```

- 图像请求返回 200 且能识别内容 → 模型视觉能力正常，问题在调用链。
- 返回 `UnsupportedModel` → 模型在端点不支持视觉（或纯文本模型）。

## 2. 配置漂移：配置 ≠ 运行时

实测案例（2026-08-09）：`config.yaml` 的 `auxiliary.vision` 正确配置了 `model: minimax-m3`（火山方舟，该模型确认支持视觉，图像请求返回 200），但 **vision_analyze 实际回落到 `qwen3.6-flash`**（火山端点的纯文本模型，报 `UnsupportedModel`）。

排查要点：
- 检查 `config.yaml` 里 `auxiliary.vision` 段的 `provider` / `model` / `base_url` / `api_key` 是否齐全。若 base_url + api_key 都设了，`_resolve_task_provider_model` 会走 `custom` 端点并带上配置的 model；若缺失则回落 `auto`。
- 对照 Hermes 运行时（`agent/auxiliary_client.py` 的 `resolve_vision_provider_client`）实际选用的 provider/model，与磁盘 config.yaml 比对——会话加载的配置可能与磁盘不一致。
- 排查时**保留两端证据**：配置模型可用（curl 200）+ 运行时用的模型报错（报错信息里的 model 名），两条证据并陈才能定位是「配置错」还是「运行时漂移」。

## 3. 修复前先确认

在改配置前先确认模型确实支持视觉（避免改一个更不支持的），再用 `hermes config set` 或直接编辑 `config.yaml` 的 `auxiliary.vision.model`，重启会话验证。
