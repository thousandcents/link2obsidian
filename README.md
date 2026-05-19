# link2obsidian 🔗→📝

**Convert web page links to Obsidian Markdown files** — auto-download images, smart tagging, and LLM-generated summaries.

Fully supports WeChat public account articles with cookie-based image download and token expiry retry logic.

## Features

- 📱 **WeChat articles** — Extracts even from "environment异常" verification pages
- 🖼️ **Cookie-based image download** — Uses cookie jar + Referer header for WeChat qpic.cn images
- 🔄 **Token expiry retry** — Automatically re-fetches page when image tokens expire
- 🤖 **LLM summary** — Generates 3-5 key bullet points using any OpenAI-compatible API
- 🏷️ **Smart tagging** — Auto-tags: 微信公众号, 知乎, or 网页收藏
- 📋 **YAML frontmatter** — Title, source URL, description, tags, created time

## Requirements

- Python 3.7+
- `curl` (for fetching pages and downloading images)
- `pyyaml` (only needed if you want `runner.py` to read YAML-based configs)
- LLM API key (optional — for summary generation)

## Quick Start

```bash
# Clone the repo
git clone https://github.com/thousandcents/link2obsidian.git
cd link2obsidian

# Set your Obsidian vault
export OBSIDIAN_VAULT=/path/to/your/obsidian/vault

# Optional: set LLM API key for summary generation
export LLM_API_KEY=sk-your-key-here
export LLM_BASE_URL=https://api.openai.com/v1
export LLM_MODEL=gpt-4o-mini

# Run it
python3 runner.py https://mp.weixin.qq.com/s/xxxxxx
```

## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `OBSIDIAN_VAULT` | No | `~/Obsidian/Thousand` | Obsidian vault root directory |
| `LLM_API_KEY` | No | — | API key for LLM summary generation |
| `LLM_BASE_URL` | No | `https://api.openai.com/v1` | LLM API endpoint |
| `LLM_MODEL` | No | `gpt-4o-mini` | LLM model name |

## Output

```
/path/to/obsidian/vault/
├── Clippings/
│   └── 文章标题.md
└── Clippings/images/
    ├── img_01.jpg
    └── img_02.png
```

### Output Format

```markdown
---
source: 微信公众号
title: 文章标题
description: 文章描述
tags:
  - 微信公众号
created: 2026-05-19 14:30:00
url: https://mp.weixin.qq.com/s/xxxxxx
---

> 📌 **文章要点**
> - 要点一
> - 要点二

正文内容...
```

## How It Works

1. **runner.py** reads `SKILL.md`, extracts the embedded Python code
2. Injects LLM configuration from environment variables
3. Replaces the URL placeholder with the target URL
4. Executes the code dynamically

This design allows the code to evolve alongside the SKILL.md documentation — the code always matches the documented workflow.

## WeChat Article Handling

- Even when WeChat returns a verification page, the article body is still present in `<div id="js_content">`
- Images from `qpic.cn` require both cookie and `Referer: https://mp.weixin.qq.com/` headers
- If images fail to download (token expired), the script re-fetches the page to get fresh URLs
- Desktop Chrome User-Agent is required; mobile UA triggers stricter verification

## As a Hermes Agent Skill

This project is designed as a [Hermes Agent](https://hermes-agent.nousresearch.com) skill:

```yaml
# ~/.hermes/config.yaml
skills:
  link2obsidian:
    path: ~/.hermes/skills/link2obsidian/runner.py
```

Set `OBSIDIAN_VAULT` and `LLM_API_KEY` in your Hermes `.env` file.

## License

MIT
