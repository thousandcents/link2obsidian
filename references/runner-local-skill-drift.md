# Runner 本地 SKILL.md 漂移修复

## 症状

`runner.py` 执行时输出：

```
🔧 使用 profile: ob_xianzi
错误: 未找到 Python 代码块
```

此时 `runner.py` 无法提取抓取代码，不会生成任何 `.md` 文件。

## 根因

profile 本地的 `SKILL.md` 与全局技能仓库不同步，常见表现：
- `~~~python` 代码块缺失闭合标记 `~~~`
- 代码块后半部分（HTML→Markdown 转换、保存逻辑）丢失
- 文件仅保留开头的 LLM 摘要 helper 函数

## 快速修复

```bash
cp ~/.hermes/skills/note-taking/link2obsidian/SKILL.md \
   ~/.hermes/profiles/ob_xianzi/skills/note-taking/link2obsidian/SKILL.md
```

然后重新执行：

```bash
python3 ~/.hermes/profiles/ob_xianzi/skills/note-taking/link2obsidian/runner.py "https://mp.weixin.qq.com/s/..."
```

## 验证

修复后应看到正常的抓取输出（下载图片、生成摘要、保存文件），而非「未找到 Python 代码块」。

## 相关

- SKILL.md 已内置「SKILL.md 自检与修复」节，但若全局副本也不完整，需从 Hermes 上游或备份恢复。
- LLM 摘要网络不可达时（`[Errno 101] Network is unreachable`），runner 会跳过自动摘要，Agent 需手动补充 `> 📌 **文章要点**` 块。
