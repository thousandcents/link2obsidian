# link2obsidian 🔗→📝

**将网页链接转换为 Obsidian Markdown 文件** — 自动下载图片、智能标签、LLM 摘要、后处理格式清理。

全面支持微信公众号文章（含 Vue.js SPA 渲染）、知乎专栏、博客站点等。自包含设计：`runner.py` + `postprocess.py` + `SKILL.md` + 32 篇参考文档，无需外部依赖。

## ✨ Features

- 📱 **微信公众号文章** — 从 `<div id="js_content">` 提取，绕过"环境异常"验证页；支持 Vue.js SPA 渲染页面（`content_noencode` / `cgiDataNew` 方式）
- 🖼️ **Cookie 图片下载** — 使用 cookie jar + Referer 头下载 `qpic.cn` 图片，token 过期自动重试
- 🔄 **Token 过期重试** — 图片 URL token 失效时自动重新抓取页面获取新 URL
- 🤖 **LLM 摘要** — 自动生成 3~5 条核心要点，插入 frontmatter 之后。支持多种 LLM 配置优先级：SenseNova > OpenCode > OpenAI
- 🏷️ **智能标签** — 根据来源域名自动标签：微信公众号 / 知乎 / 网页收藏
- 📋 **YAML Frontmatter** — 标题、来源 URL、描述、标签、创建时间
- 🧹 **后处理清理** — `postprocess.py` 自动修复 Markdown 格式缺陷：代码围栏合并、表格修复、标题段落粘连分割、图片嵌入检测、em-dash 修复等
- 📖 **32 篇参考文档** — 涵盖微信公众号页面结构、Vue SPA 提取、图片处理、代码块模式、LLM 摘要配置等实战经验

## 📂 File Structure

```
link2obsidian/
├── SKILL.md              # 技能定义 + 内联 Python 代码（runner.py 动态提取执行）
├── runner.py             # 入口脚本 — 加载 SKILL.md 代码块、配置 LLM、执行抓取
├── postprocess.py        # 后处理脚本 — runner.py 执行后自动清理 Markdown 格式
├── references/           # 32 篇参考文档（坑点记录、提取策略、修复方案）
│   ├── wechat-page-structure.md
│   ├── wechat-vue-spa-extraction.md
│   ├── vue-spa-mdnice-extraction.md
│   ├── wechat-html-to-markdown-converter.md
│   ├── wechat-image-triage.md
│   ├── wechat-image-embedding-patterns.md
│   ├── wechat-codeblock-fence-patterns.md
│   ├── wechat-codeblock-newline-collapse.md
│   ├── wechat-boxdrawing-flowchart.md
│   ├── wechat-markdown-manual-repair.md
│   ├── wechat-session-patterns-20260701.md
│   ├── blog-site-extraction.md
│   ├── vue-spa-contentnoencode-fallback.md
│   ├── extraction-fallback-ladder.md
│   ├── markdown-table-repair.md
│   ├── postprocess-extension-pitfalls.md
│   ├── postprocess-residual-bugs.md
│   ├── llm-summary-config-and-403.md
│   ├── llm-summary-network-fallback.md
│   ├── llm-summary-thinking-artifact.md
│   ├── long-screenshot-image-extraction.md
│   ├── title-image-detection.md
│   ├── image-path-fix.md
│   ├── code-fence-lang-split-fix.md
│   ├── code-fence-merge-pitfall.md
│   ├── em-dash-patch-pitfall.md
│   ├── bold-label-orphan-patterns.md
│   ├── product-card-fields.md
│   ├── batch-article-splitting.md
│   ├── batch-processing-image-pitfalls.md
│   ├── supplemental-content-recovery.md
│   └── runner-local-skill-drift.md
├── README.md
├── LICENSE
└── 安装说明.txt
```

## 🚀 Quick Start

```bash
# Clone the repo
git clone https://github.com/thousandcents/link2obsidian.git
cd link2obsidian

# Set your Obsidian vault path
export OBSIDIAN_VAULT=/path/to/your/obsidian/vault

# Optional: set LLM API key for summary generation
export LLM_API_KEY=your-api-key
export LLM_BASE_URL=https://api.openai.com/v1
export LLM_MODEL=gpt-4o-mini

# Run it
python3 runner.py https://mp.weixin.qq.com/s/xxxxxx

# Or specify vault path and Hermes profile directly
python3 runner.py https://mp.weixin.qq.com/s/xxxxxx --workdir /path/to/vault --profile my_profile
```

## 🔧 CLI Options

```
python3 runner.py <url> [options]

Arguments:
  url                    网页链接 (微信公众号/知乎等)

Options:
  --profile, -p NAME     Hermes profile 名称 (默认: 自动检测 HERMES_HOME 或 ob_xianzi)
  --workdir, -w PATH     Obsidian vault 路径 (默认: ~/Obsidian/Thousand)
```

## 📡 LLM Summary Configuration

LLM 摘要功能支持多级配置优先级（runner.py 自动检测）：

| 优先级 | 配置方式 | 环境变量 |
|--------|---------|---------|
| 1 (最高) | SenseNova | `SENSE_API_KEY` + `SENSE_BASE_URL` |
| 2 | Hermes config.yaml | `model.provider` + `model.base_url` + `model.api_key` |
| 3 | OpenCode Go | `OPENCODE_GO_API_KEY` |
| 4 | OpenAI | `OPENAI_API_KEY` + `OPENAI_BASE_URL` |

不配置任何 LLM 时，脚本自动跳过摘要生成，不影响正文提取和保存。

### Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `OBSIDIAN_VAULT` | No | `~/Obsidian/Thousand` | Obsidian vault 根目录 |
| `SENSE_API_KEY` | No | — | SenseNova API key (国内直连，推荐) |
| `SENSE_BASE_URL` | No | — | SenseNova API endpoint |
| `LLM_API_KEY` | No | — | LLM API key (通用) |
| `LLM_BASE_URL` | No | `https://api.openai.com/v1` | LLM API endpoint |
| `LLM_MODEL` | No | `gpt-4o-mini` | LLM 模型名称 |

## 📝 Output

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
created: 2026-08-01 14:30:00
url: https://mp.weixin.qq.com/s/xxxxxx
---

> 📌 **文章要点**
> - 要点一
> - 要点二

正文内容...
```

## ⚙️ How It Works

1. **`runner.py`** 读取 `SKILL.md`，提取内联的 `~~~python` 代码块
2. 注入 LLM 配置（从环境变量 / Hermes config.yaml / .env 多级检测）
3. 替换 `ARTICLE_URL` / `WORKDIR` 占位符为目标值
4. 动态执行代码 — 抓取页面、提取正文、下载图片、生成摘要、保存文件
5. **`postprocess.py`** 自动执行后处理 — 修复代码围栏、表格、标题粘连、图片嵌入等格式问题

这种设计让代码与 `SKILL.md` 文档同步演进 — 代码始终匹配文档描述的工作流程。

## 🧹 Postprocess (`postprocess.py`)

runner.py 执行后自动调用的后处理脚本，负责所有确定性的格式清理：

- **代码围栏修复** — 合并被拆分的代码块、修复语言标签
- **表格修复** — 检测被压平的表格行并告警
- **标题段落分割** — 修复 `## N. xxx` 后缺少换行等粘连问题
- **图片嵌入检测** — 自动检测正文中的图片引用
- **Em-dash 修复** — 修复 Unicode 破折号渲染问题
- **Bold 标签孤立模式修复** — 修复 orphaned bold labels

也可独立运行：

```bash
python3 postprocess.py /path/to/Clippings/某文章.md
python3 postprocess.py /path/to/Clippings/某文章.md --dry-run
python3 postprocess.py /path/to/Clippings/某文章.md --verbose
```

## 📱 WeChat Article Handling

- 即使微信返回验证页面，文章正文仍在 `<div id="js_content">` 中
- `qpic.cn` 图片需要 cookie + `Referer: https://mp.weixin.qq.com/` 头
- 图片下载失败（token 过期）时，脚本自动重新抓取页面获取新 URL
- 必须使用桌面 Chrome User-Agent；移动端 UA 触发更严格验证
- 支持 Vue.js SPA 渲染页面（`content_noencode` JsDecode 方式）

## 🤖 As a Hermes Agent Skill

本项目设计为 [Hermes Agent](https://hermes-agent.nousresearch.com) 技能：

```yaml
# ~/.hermes/config.yaml
skills:
  link2obsidian:
    path: ~/.hermes/skills/link2obsidian/runner.py
```

在 Hermes `.env` 文件中设置 `OBSIDIAN_VAULT` 和 LLM 相关环境变量。

详细安装说明见 [`安装说明.txt`](安装说明.txt)。

## ⚠️ Pitfalls

- **IPv4 强制**：脚本内置 `socket.getaddrinfo` monkey-patch 强制 IPv4，避免无 IPv6 环境下的 `Network is unreachable` 错误
- **代理兼容**：LLM 调用默认直连，失败时自动回退走 `HTTP_PROXY` / `HTTPS_PROXY`
- **SenseNova 优先**：当同时配置了 SENSE 和 AGNES 时，SENSE 优先（国内直连更稳定）
- **SKILL.md 是唯一真身**：本目录自包含，不再依赖共享源技能或软链

## 📄 License

MIT
