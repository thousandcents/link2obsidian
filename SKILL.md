---
name: link2obsidian
description: 将网页链接转换为 Obsidian Markdown 文件，自动下载图片并设置来源标签
---

# link2obsidian — Hermes Agent Skill

This is the Hermes Agent skill definition for the link2obsidian tool.

## Usage in Hermes

```yaml
# config.yaml
skills:
  link2obsidian:
    path: /path/to/link2obsidian/link2obsidian.py
```

The `OBSIDIAN_VAULT` environment variable must be set in Hermes `.env`:

```env
OBSIDIAN_VAULT=/path/to/your/obsidian/vault
```

## Trigger

When a user sends a URL, the agent can invoke:

```bash
python3 /path/to/link2obsidian/link2obsidian.py "{url}"
```
