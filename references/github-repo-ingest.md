# GitHub 仓库链接入库（区别于网页文章）

当用户发送的是 **GitHub 仓库链接**（`github.com/<owner>/<repo>`）而非网页文章时，`runner.py` 的
微信 js_content 抽取逻辑不适用（会产出近空文件）。按以下工作流处理。

## 判定
- `github.com/<owner>/<repo>` → 走本流程
- 其余 URL（mp.weixin / zhihu / 博客）→ 走 link2obsidian 正常流程

## 工作流

1. **完整保存仓库到本地参考目录**（保留代码+文档，供日后参考）：
   ```bash
   cd /tmp && rm -rf <repo> && git clone --depth 1 https://github.com/<owner>/<repo>.git
   cp -r /tmp/<repo>/* "/home/jack-lin-sparrow/文档/<RepoName>/"
   rm -rf "/home/jack-lin-sparrow/文档/<RepoName>/.git"
   ```
   - 存到 `~/文档/<RepoName>/`，不是 vault 内。**不安装、不改动环境**（除非用户明确要求）。

2. **先读 README.md + 关键 spec**，理解仓库是什么再写笔记（不要只抄 README）。

3. **写原始文章**到 `Clippings/raw/articles/<RepoName>.md`：
   - frontmatter：`source: 网页收藏`、`title`、`description`、`tags: [网页收藏]`、`created: YYYY-MM-DD`、`url: <repo>`、`ingested`、`sha256`（对 frontmatter 之后正文计算）
   - body：把 README 提炼成结构化方法论笔记（模块构成表、核心机制、定位、生产证据），含要点摘要块
   - 中文撰写（用户偏好）

4. **建实体页** `Clippings/entities/<RepoName>.md`：
   - frontmatter：`type: entity`、`tags`、`sources: [raw/articles/...]`
   - body：构成表 + 定位 + 与同类项目的对照 + 相关页面出链
   - **出链前检查目标页面是否存在**——不存在的用 `[[...]]` 会成悬空链接，按「不建 stub」惯例删除（本次 `[[task-tracking-protocol]]` 即因此移除）

5. **更新 index.md**（实体区 +1，统计行重算：总页面/原始文章/覆盖率）+ **log.md** 追加日志。

6. **入库后校验**：用 execute_code 检查实体页全部出链可解析、Clippings 根目录无残留、统计行一致。

## 澄清
仓库链接意图可能多样（归档 / 安装 / 讲解 / 仅保存）。若不确定，用 clarify 问。
本次用户 10 分钟未回复，按「链接入库」默认工作流执行（归档 + 建实体页，不安装）——这是最不具破坏性的默认。
