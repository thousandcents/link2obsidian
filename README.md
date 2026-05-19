# link2obsidian 🔗→📝

Convert web page links to Obsidian Markdown files. Automatically fetches content, downloads images, and generates properly formatted Markdown with YAML frontmatter for your Obsidian vault.

## Features

- 🌐 **Universal web clipper** — Convert any webpage to an Obsidian note
- 📱 **WeChat articles** — Full support for WeChat public account articles (both legacy and 2026+ Vue.js structure)
- 🖼️ **Auto image download** — Downloads images to `Clippings/images/` with MD5-hashed filenames
- 🏷️ **Smart tagging** — Auto-tags based on source (微信公众号, 知乎, 网页收藏)
- 📋 **YAML frontmatter** — Title, source URL, date, and tags
- 🖥️ **Display mode** — Output to stdout instead of saving (useful for piping)

## Requirements

- Python 3.7+
- `curl` (for fetching pages and downloading images)

## Installation

```bash
# Clone the repo
git clone https://github.com/thousandcents/link2obsidian.git
cd link2obsidian

# Make it executable
chmod +x link2obsidian.py

# Optional: install as a system command
ln -s "$(pwd)/link2obsidian.py" ~/.local/bin/link2obsidian
```

## Usage

### Basic usage

```bash
# Set your Obsidian vault path
export OBSIDIAN_VAULT=/path/to/your/obsidian/vault

# Convert a webpage
python3 link2obsidian.py https://example.com/article

# Or specify vault directory inline
python3 link2obsidian.py https://example.com/article --dir /path/to/obsidian/vault
```

### Display mode (stdout only, no file saved)

```bash
python3 link2obsidian.py https://example.com/article --display
```

### WeChat article support

```bash
python3 link2obsidian.py https://mp.weixin.qq.com/s/xxxxxx
```

The script automatically detects WeChat articles and uses the appropriate extraction method (new Vue.js-based structure or legacy HTML structure).

## Output structure

```
/path/to/obsidian/vault/
├── Clippings/
│   ├── Article Title.md
│   └── Another Article.md
└── Clippings/images/
    ├── a1b2c3d4e5f6...jpg
    └── f6e5d4c3b2a1...png
```

### Output format

```markdown
---
title: Article Title
source: https://example.com/article
date: 2026-05-19
tags:
  - 网页收藏
---

# Article Title

> 作者：Author Name | 发布时间：2026-05-18

Article content in Markdown...

![[Clippings/images/a1b2c3d4e5f6...jpg]]
```

## As a Hermes Agent Skill

This project originated as a skill for [Hermes Agent](https://hermes-agent.nousresearch.com). To use it as a Hermes skill:

1. Copy `link2obsidian.py` to your skills directory
2. Configure the skill in `config.yaml` with appropriate execution command
3. Set `OBSIDIAN_VAULT` environment variable in your `.env`

## License

MIT
