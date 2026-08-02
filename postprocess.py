#!/usr/bin/env python3
"""
link2obsidian 后处理脚本（postprocess.py）

在 runner.py 执行完毕后，对生成的 Markdown 文件自动完成所有确定性的
格式清理工作。原本需要在 SKILL.md 中用长段文字指挥 AI 的后处理步骤，
凡是可以用正则/固定规则判定的修复，都搬到这里。

典型调用：
    python3 postprocess.py /path/to/Clippings/某文章.md
    python3 postprocess.py /path/to/Clippings/某文章.md --url https://...
    python3 postprocess.py /path/to/Clippings/某文章.md --dry-run
    python3 postprocess.py /path/to/Clippings/某文章.md --verbose

仍需要 AI 介入的步骤（脚本只负责检测并提示，不在本文件中尝试修复）：
  * 文件 < 500 字节时的兜底抓取（content_noencode JsDecode / cnblogs·CSDN
    静态页提取 / browser-act stealth-extract）— 需要 LLM 进行 JsDecode
    判断和上下文纠正，沿用 references 中既有模板。
  * 空 description 的填充文本 — 需要阅读全文后凝练 30~60 字。
  * 复杂表格（pipe table 列结构推断 / 无分隔内联数据表 / 商品卡片字段
    分隔）— 需要按语义推断列边界，规则化易引入错位。postprocess 现已能
    **自动检测**被压平的表格行（行内无 `|`、长度 > 40、含 ≥2 个 `%` 且
    存在 `**`）并提示 AI 按语义重建，将静默失败转为显式告警。
  * 正文标题与段落粘连的"语义型分割"——脚本会做最稳健的固定模式修复
    （`## N. xxx` 后插入换行、`## 总结合并` 类），余下判别留给 AI。
  * 图片按正文图注嵌入（Form A/B/C）— Agent 默认自动嵌入（封面图除外），
    图注匹配依赖人类判断图序与语义对应。
  * LLM 摘要生成 — runner.py 内置 LLM 基本不可用，仍由 Agent 自身生成。
"""

from __future__ import annotations

import argparse
import html as html_mod
import os
import re
import sys
from pathlib import Path
from typing import Callable, List, Tuple


# ══════════════════════════════════════════════════════════════
# 通用工具
# ══════════════════════════════════════════════════════════════


class Logger:
    """简易分级日志"""

    def __init__(self, verbose: bool = False, dry_run: bool = False):
        self.verbose = verbose
        self.dry_run = dry_run
        self.messages: List[str] = []
        self.ai_hints: List[str] = []  # 需要 AI 介入的提示

    def log(self, msg: str):
        self.messages.append(msg)
        if self.verbose:
            print(f"  • {msg}")

    def hint(self, msg: str):
        self.ai_hints.append(msg)

    def summary(self):
        print(
            f"\n📋 后处理报告：{len(self.messages)} 项自动修复，"
            f"{len(self.ai_hints)} 项需 AI 介入"
        )
        if self.verbose:
            for m in self.messages:
                print(f"  • {m}")
        for h in self.ai_hints:
            print(f"  ⚠️  需 AI：{h}")
        if self.dry_run:
            print("  （dry-run 模式：文件未写回）")


def split_frontmatter(content: str) -> Tuple[str, str]:
    """
    将 Markdown 拆为 (frontmatter, body)。
    frontmatter 以 `---\\n` 开头、`\\n---\\n` 结尾，含两端围栏行。
    """
    if content.startswith("---\n"):
        end = content.find("\n---\n", 4)
        if end != -1:
            fm_end = end + 5  # 含 `\\n---\\n`
            fm = content[:fm_end]
            body = content[fm_end:].lstrip("\n")
            return fm, body
    return "", content


# ══════════════════════════════════════════════════════════════
# 1. Frontmatter 清理
# ══════════════════════════════════════════════════════════════


def clean_frontmatter(fm: str, log: Logger) -> str:
    text = fm

    # \\x26quot; → "（HTML 实体 &quot; 经 JSON 序列化的字面量）
    if "\\x26quot;" in text:
        text = text.replace("\\x26quot;", '"')
        log.log("Frontmatter: \\x26quot; → \"")

    # \\x0d \\x0a CRLF 字面量
    if "\\x0d" in text or "\\x0a" in text:
        text = (
            text.replace("\\x0d\\x0a", " ")
            .replace("\\x0d", " ")
            .replace("\\x0a", " ")
        )
        log.log("Frontmatter: \\x0d / \\x0a CRLF 字面量 → 空格")

    # HTML 实体残留
    if any(e in text for e in ("&quot;", "&amp;", "&lt;", "&gt;", "&nbsp;", "&#x2B;")):
        text = html_mod.unescape(text).replace("\xa0", " ")
        text = text.replace("&#x2B;", "+")
        log.log("Frontmatter: HTML 实体解码")

    # 空 description 检测
    if re.search(r"(?m)^description:\s*$", text):
        log.hint(
            "Frontmatter: description 为空，请 Agent 依据标题与首段生成 "
            "30~60 字描述填入 frontmatter"
        )

    return text


# ══════════════════════════════════════════════════════════════
# 2. NBSP / 字符级清理
# ══════════════════════════════════════════════════════════════


def fix_nbsp(content: str, log: Logger) -> str:
    if "\xa0" in content:
        n = content.count("\xa0")
        content = content.replace("\xa0", " ")
        log.log(f"Body: 替换 {n} 个 NBSP (\\xa0) → 空格")
    return content


def fix_escaped_asterisks(content: str, log: Logger) -> str:
    """\\*\\* / \\* 形式的转义加粗 → **"""
    new, n = re.subn(r"\\\*\\\*(.+?)\\\*\\\*", r"**\1**", content, flags=re.DOTALL)
    if n:
        log.log(f"Body: 转义星号 \\*\\*xxx\\*\\*→ **xxx**：{n} 处")
    return new


# ══════════════════════════════════════════════════════════════
# 3. 加粗标记（星号）标准化
# ══════════════════════════════════════════════════════════════


def normalize_bold_markers(content: str, log: Logger) -> str:
    # 6+ 星号包裹文本 → 去星保留纯文本（HTML 多层嵌套失效产物）
    new = re.sub(r"\*{6,}(.+?)\*{6,}", r"\1", content, flags=re.DOTALL)
    if new != content:
        log.log("Body: 6+ 星号嵌套残留 → 去星保留纯文本")
        content = new

    # 4+ 星号 → **（标准加粗）
    new = re.sub(r"\*{4,}(?=[^*\n])", "**", content)
    new = re.sub(r"(?<=[^*\n])\*{4,}", "**", new)
    if new != content:
        log.log("Body: 4+ 星号 → ** 标准化")
        content = new

    # ***text*** (3 星，原 strong+em) → **text**
    new = re.sub(
        r"(?<!\*)\*\*\*(?!\*)(.+?)(?<!\*)\*\*\*(?!\*)",
        r"**\1**",
        content,
        flags=re.DOTALL,
    )
    if new != content:
        log.log("Body: ***text*** → **text**（统一加粗）")
        content = new

    return content


# 孤儿 ** 的常见模式（顺序敏感）
# 每个条目：(pattern, repl, 描述)
ORPHAN_BOLD_PATTERNS: List[Tuple[str, str, str]] = [
    # 第N，...XXX** —— 整句末尾的孤儿（整句加粗包裹）
    (
        r"(?m)^(第[一二三四五六七八九十百千万]+，[^\n*]+?)\*\*(?=\s*$)",
        r"**\1**",
        "第N，...XXX** → **...XXX**（整句末）",
    ),
    # 第N，*XXX*（XXX 后接 `：:` `——` `（(`）
    (
        r"(?m)^(第[一二三四五六七八九十百千万]+，)([^\n*]+?)\*\*(?=[：:——（(])",
        r"\1**\2**",
        "第N，XXX**：/——/（→ 第N，**XXX**",
    ),
    # 行末句号/感叹号/问号后跟 `** ` （段尾加粗错位）
    (
        r"(?m)^([^\n*]+?[。！？])\*\* ",
        r"**\1** ",
        "X。** 空格 → **X。** 空格",
    ),
    # XXX**—— → **XXX**——
    (
        r"(?m)^([^\n*]+?)\*\*——",
        r"**\1**——",
        "XXX**—— → **XXX**——",
    ),
    # 引号包裹词后跟 **
    (
        r'(["""\'])([^\n*"\'\n]+?)\1\*\*',
        r"\1**\2**\1",
        "\"xxx\"** → **\"xxx\"**（含中/英文引号）",
    ),
    # 公式/计算结果行：行末 ** 但无开头 **
    (
        r"(?m)^([^\n*=+\-]*?[=＝][^\n*]+?)\*\*(?=\s*$)",
        r"**\1**",
        "公式行末 **→ 整行包裹",
    ),
    # 列表项中：- TEXT**： / - TEXT**（ / - N. TEXT**：
    (
        r"(?m)^(- )(\d+\.\s+)?([^\n*]+?)\*\*(?=[：:（(])",
        r"\1\2**\3**",
        "- TEXT**：/（→ - **TEXT**：/（",
    ),
    # 列表项中：- TEXT**——
    (
        r"(?m)^(- )([^\n*]+?)\*\*(?=——)",
        r"\1**\2**",
        "- TEXT**—— → - **TEXT**——",
    ),
    # 描述性术语粗体：逻辑回归**则推断 → **逻辑回归**则推断
    # 形如 "XXXX**则" "XXXX**会" "XXXX**把" 等
    (
        r"(?m)^([^\n*\[\]]{2,12})\*\*(?=则|会|把|可以|应该|能够|需要|必须)",
        r"**\1**",
        "术语**动词 → **术语**动词",
    ),
    # 冒号后加粗偏移：- 原始回测：** 4 年... → - **原始回测：** 4 年...
    (
        r"(?m)^(- )([^\n*：:]+：)\*\* ",
        r"\1**\2** ",
        "冒号后加粗偏移 → 移至字段名",
    ),
]


def fix_orphan_bold(content: str, log: Logger) -> str:
    """逐条应用孤儿 ** 修复模式"""
    for pat, repl, desc in ORPHAN_BOLD_PATTERNS:
        new, n = re.subn(pat, repl, content)
        if n:
            log.log(f"{desc}（× {n}）")
            content = new

    # 整段加粗丢失：段落以 ** 结尾且开头非 ** 且段内仅一个 **（孤儿）
    paragraphs = content.split("\n\n")
    fixed = 0
    for i, para in enumerate(paragraphs):
        stripped = para.strip()
        if (
            stripped.endswith("**")
            and not stripped.startswith("**")
            and stripped.count("**") == 1
            and not re.match(r"^\*\*\*\*?$", stripped)  # 排除 *** 水平线
            and len(stripped) > 6
        ):
            paragraphs[i] = "**" + para
            fixed += 1
    if fixed:
        log.log(f"整段加粗丢失：{fixed} 段在开头补 **")
        content = "\n\n".join(paragraphs)

    # 句末词后粗体（保守，仅短行）：
    new, n = re.subn(
        r"(?m)^([^\n*]{4,60}?)\*\*(?=[\s。！？，；])",
        r"**\1**",
        content,
    )
    if n:
        log.log(f"句末词后 **→ 包裹该词：{n} 处（保守短句）")
        content = new

    # 兜底：连续 4+ 星号合并为 **（覆盖 overlapping fix）
    new = re.sub(r"\*{4,}", "**", content)
    if new != content:
        log.log("兜底：连续 4+ 星号 → **")
        content = new

    return content


# ══════════════════════════════════════════════════════════════
# 4. 标题修复
# ══════════════════════════════════════════════════════════════


def fix_empty_heading(content: str, fm: str, log: Logger) -> str:
    """# （孤立空 heading）→ # {frontmatter 中 title 的值}"""
    title = ""
    title_m = re.search(r"(?m)^title:\s*(.+?)\s*$", fm)
    if title_m:
        title = title_m.group(1).strip()
    new = re.sub(
        r"(?m)^#\s*$",
        f"# {title}" if title else "# 未命名文章",
        content,
        count=1,
    )
    if new != content:
        log.log(f"空标题补全 → # {title or '未命名文章'}")
    return new


def upgrade_chinese_numbered_headings(content: str, log: Logger) -> str:
    """一、二、三、... 独立段落行 → ## 一、...（已带 ## 或 **加粗** 的不动）"""
    nums = "一二三四五六七八九十"
    # 必须显式排除已经被 ## / ## ## 包裹的行
    pat = re.compile(
        r"(?m)^(?!#)(?!\*\*)([" + nums + r"](?:[" + nums + r"])?|百|千|万)、"
    )
    new, n = pat.subn(r"## \g<0>", content)
    if n:
        log.log(f"中文编号标题升级：{n} 处 → ## N、")
    return new


def upgrade_numeric_numbered_headings(content: str, log: Logger) -> str:
    """纯数字章节标记（01..09 等，独立成行且不在代码块/fence 区域）→ ## 01"""
    # 收集 ``` 围栏内行索引，跳过
    lines = content.split("\n")
    in_fence = False
    fence_lines = set()
    for i, line in enumerate(lines):
        if re.match(r"^```", line):
            in_fence = not in_fence
            continue
        if in_fence:
            fence_lines.add(i)
    fixed = 0
    for i, line in enumerate(lines):
        if i in fence_lines:
            continue
        # 必须是单一 2 位数字独立成行（前后只有空白）
        if re.match(r"^\s*\d{2}\s*$", line):
            lines[i] = f"## {line.strip()}"
            fixed += 1
    if fixed:
        log.log(f"数值编号标题升级：{fixed} 处 → ## NN")
    return "\n".join(lines)


def fix_heading_merged_with_body(content: str, log: Logger) -> str:
    """
    heading 与正文连在一起的常见可明确判定模式：
      * `## N. <短标题不超 60 字符><正文>`：在第一个句号/问号/感叹号后插入 \\n\\n
      * `## No.N 子标题——正文`：在 —— 后分割
      * `## 总结回顾全文`、`## 参考文章加入` 等：前 2 个汉字后做分割（仅当 body 较长）
    """

    def split_at_breaker(line: str) -> str | None:
        m = re.match(r"^(#{1,6})\s+(.+)$", line)
        if not m:
            return None
        prefix, body = m.group(1), m.group(2)
        if len(body) <= 30:
            return None

        # —— 模式：`## No.N 子标题——正文` → `## No.N 子标题` + 空行 + `——正文`
        # 仅当 —— 之后确有正文才拆分；若 —— 在行尾（标题自带破折号、无粘连
        # 正文），则不拆，保证幂等（否则每次都把同一行"拆"成相同结果 → 死循环）。
        # 同时把 —— 归入正文侧（标题只保留到 —— 之前），符合注释原意。
        if "——" in body:
            idx = body.index("——")
            rest = body[idx + 2 :]
            if rest.strip():
                title_part = body[:idx]
                return f"{prefix} {title_part}\n\n——{rest}"
            return None

        # 第一个句尾标点处分割
        m2 = re.search(r"[。！？!?]", body)
        if m2 and m2.start() < len(body) - 1:
            split = m2.start()
            title_part = body[: split + 1]
            rest = body[split + 1 :].lstrip()
            return f"{prefix} {title_part}\n\n{rest}"

        # 普通中文 2 字标题+长正文（`## 总结回顾全文`）
        if prefix in {"##", "###"} and len(body) >= 8 and re.match(
            r"^[\u4e00-\u9fff]{2,}", body
        ):
            # 若前 2 个汉字是常见标题词（总结/参考/导言/引言等），断开
            common_titles = {"总结", "参考", "导言", "引言", "背景", "概述", "前言", "结语", "附录"}
            head2 = body[:2]
            if head2 in common_titles:
                rest = body[2:]
                return f"{prefix} {head2}\n\n{rest}"

        return None

    lines = content.split("\n")
    new_lines = []
    fixed = 0
    for line in lines:
        if re.match(r"^#{1,6}\s+", line) and len(line) > 30:
            new = split_at_breaker(line)
            if new:
                fixed += 1
                new_lines.extend(new.split("\n"))
                continue
        new_lines.append(line)
    if fixed:
        log.log(f"标题+正文粘连修复：{fixed} 处")
        return "\n".join(new_lines)
    return content


def fix_heading_with_codeblock_inline(content: str, log: Logger) -> str:
    """### 4.1 数据准备`from pathlib ... → ### 4.1 数据准备\\n\\n`from pathlib..."""
    new, n = re.subn(
        r"(?m)^(#{1,6}\s+[^\n`]*?)`([a-zA-Z])",
        r"\1\n\n`\2",
        content,
    )
    if n:
        log.log(f"标题+代码块 inline 粘连修复：{n} 处")
    return new


# ══════════════════════════════════════════════════════════════
# 5. 列表/子弹修复
# ══════════════════════════════════════════════════════════════


def fix_redundant_bullets(content: str, log: Logger) -> str:
    """- • ... → - ..."""
    new, n = re.subn(r"(?m)^(- )• ", r"\1", content)
    if n:
        log.log(f"冗余子弹清理（- • → -）：{n} 处")
    return new


def split_inline_bullets(content: str, log: Logger) -> str:
    """同行多个 • 项: 在 。/；后紧跟 •/- 处插入换行"""
    new, n1 = re.subn(r"(?<=[。；])(?=•)", "\n", content)
    new, n2 = re.subn(r"(?<=[。；])(?=- )", "\n", new)
    if n1 + n2:
        log.log(f"同行多子弹拆分：{n1 + n2} 处")
    return new


def fix_empty_bullet_lines(content: str, log: Logger) -> str:
    """单独 `- ` 行（仅短横线+空格无内容）→ 删除"""
    new, n = re.subn(r"(?m)^ *- *$", "", content)
    if n:
        log.log(f"空子弹行清理：{n} 处")
    return new


# ══════════════════════════════════════════════════════════════
# 6. 代码块/反引号修复
# ══════════════════════════════════════════════════════════════


# (regex_pattern, language_label, 描述) — 行首反引号后紧跟编程语言特征
LANG_PATTERNS: List[Tuple[str, str, str]] = [
    (r"(?m)^`(fn|pub|struct|enum|static|let|impl|trait|use|mod)\b", "rust", "Rust 关键字"),
    (r"(?m)^`#include\b", "cpp", "C/C++ include"),
    (r"(?m)^`(import\s|from\s|def\s|class\s|#\s|if\s|for\s|while\s)", "python", "Python 关键字"),
    (r"(?m)^`(curl\s|npx\s|npm\s|yarn\s|git\s|hermes\s|pip\s|uv\s|sudo\s|cd\s)", "bash", "Bash 命令"),
    (r"(?m)^`//\s", "", "JS 行首注释"),
    (r"(?m)^`\{\s*$", "", "JS 对象/类块"),
]

ASCII_FLOW_CHARS = "│├└┌─▼▲►→←↗↘"


def _collect_fence_lines(content: str) -> set:
    lines = content.split("\n")
    in_fence = False
    fence_idx = set()
    for i, line in enumerate(lines):
        if re.match(r"^```", line):
            in_fence = not in_fence
            fence_idx.add(i)
            continue
        if in_fence:
            fence_idx.add(i)
    return fence_idx


def fix_code_fence_degraded(content: str, log: Logger) -> str:
    """
    单反引号替代 ``` 的退化模式：
      1. 行首 `+LANG 关键字 → ```lang\\n+余下
      2. 行首 `+中文字符 + 上下文含 ASCII 流程图字符 → ```+余下
      3. 行首 `+中文/中文标点（无流程图字符）→ 删除行首 `
      4. URL 内联包装 `地址：https://... → 删 ` 后插 \\n\\n
      5. 内联代码（`+字母数字_+配对反引号）→ 保留
    """
    fence_idx = _collect_fence_lines(content)
    lines = content.split("\n")
    fixed = 0
    for i, line in enumerate(lines):
        if i in fence_idx:
            continue
        if not line.startswith("`") or line.startswith("```"):
            continue
        rest = line[1:]

        # 5) 内联代码（行首 `+alnum/_ 且行内存在配对反引号）→ 跳过
        if rest and re.match(r"[A-Za-z0-9_]", rest) and rest.count("`") >= 1:
            continue

        # 4) URL 内联包装
        if re.match(r"`?(地址|开源地址|链接|官网|项目地址)[：:]\s*https?://", line):
            lines[i] = rest + "\n\n"
            fixed += 1
            log.log("行首 URL 内联包装反引号清理")
            continue

        # 3) 行首 `+中文/中文标点
        if rest and re.match(r"[\u4e00-\u9fff，。？！：；]", rest):
            ctx = "\n".join(lines[i : i + 3])
            if any(c in ctx for c in ASCII_FLOW_CHARS):
                lines[i] = "```\n" + rest
                fixed += 1
                log.log("ASCII 流程图代码块 fence 修复")
            else:
                lines[i] = rest
                fixed += 1
                log.log("行首中文反引号清理")
            continue

        # 1/2/6) 各语言关键字模式
        matched_lang = None
        matched_desc = None
        for pat, lang, desc in LANG_PATTERNS:
            if re.match(pat, line):
                matched_lang = lang
                matched_desc = desc
                break

        if matched_lang is not None:
            replacement = f"```{matched_lang}\n" if matched_lang else "```\n"
            lines[i] = replacement + rest
            fixed += 1
            log.log(f"代码块 fence 退化修复：{matched_desc}")
            continue

        # 其它行首反引号 + 起始符
        if re.match(r"`[\(\{\[<>@\-]", line):
            lines[i] = "```\n" + rest
            fixed += 1
            log.log("行首反引号+起始符 → fenced 代码块")
            continue

    if fixed:
        log.log(f"代码块 fence 修复合计：{fixed} 处行首")
    return "\n".join(lines)


def fix_inline_code_missing_space(content: str, log: Logger) -> str:
    """`xxx`非空白 → `xxx` 非空白（反引号闭包后补空格）"""
    new, n = re.subn(r"`([^\`\n]+)`([^\s\n`])", r"`\1` \2", content)
    if n:
        log.log(f"行内代码 fence 缺失空格修复：{n} 处")
    return new


def fix_code_fence_close_attached_text(content: str, log: Logger) -> str:
    """代码块尾部 ``` 紧跟正文无换行 → 插入 \\n\\n"""
    new, n = re.subn(r"```([^\n`])", r"```\n\n\1", content)
    if n:
        log.log(f"代码块闭合 ``` 后粘连正文修复：{n} 处")
    return new


# ══════════════════════════════════════════════════════════════
# 7. 空行 / 空白修复
# ══════════════════════════════════════════════════════════════


def fix_extra_blank_lines(content: str, log: Logger) -> str:
    """4+ 连续空行 → 最多 2 空行（即 3 个连续 \\n）"""
    new, n = re.subn(r"\n{4,}", "\n\n\n", content)
    if n:
        log.log(f"多余空行合并：{n} 处")
    return new


def fix_trailing_whitespace(content: str, log: Logger) -> str:
    new, _ = re.subn(r"[ \t]+$", "", content, flags=re.MULTILINE)
    if new != content:
        log.log("行尾空白清理")
    return new


# ══════════════════════════════════════════════════════════════
# 8. 图片路径
# ══════════════════════════════════════════════════════════════


def fix_image_path(content: str, log: Logger) -> str:
    """](images/xxx.png → ](Clippings/images/xxx.png"""
    new, n = re.subn(r"\]\(images/", "](Clippings/images/", content)
    if n:
        log.log(f"图片路径修正：{n} 处 images/ → Clippings/images/")
    return new


def check_image_status(content: str, log: Logger, md_path: Path) -> None:
    """
    图片引用自检：仅校验正文引用的图片是否能在 images/ 目录找到对应文件，
    以及正文是否完全没有图片引用（需按图注嵌入到正文中）。
    不再与 images/ 目录总文件数对比（images/ 是所有 Clippings 共享的目录，
    没有文章级隔离，对比会误报）。
    """
    refs = re.findall(r"!\[([^\]]*)\]\(([^)]+)\)", content)
    log.log(f"图片引用统计：正文 {len(refs)} 处")

    if not refs:
        log.hint("正文未引用任何图片——默认自动按图注嵌入（封面图除外）")
        return

    # 检查每条引用对应的本地文件是否存在
    img_dir = md_path.parent / "images"
    broken: List[str] = []
    for alt, path_str in refs:
        # 取 path_str 的 basename
        name = path_str.rsplit("/", 1)[-1]
        local = img_dir / name
        if not local.exists():
            broken.append(path_str)
    if broken:
        log.hint(
            f"{len(broken)} 条图片引用在 images/ 目录找不到对应文件："
            f"{', '.join(broken[:3])}{'…' if len(broken) > 3 else ''}"
        )


# ══════════════════════════════════════════════════════════════
# 9. 教程/编号格式修复
# ══════════════════════════════════════════════════════════════


def fix_mixed_numbered_list(content: str, log: Logger) -> str:
    """
    行首数字顿号编号 `1、xxx` → `1. xxx`（仅作用于正文行首，不动 ## 一、 等标题）
    """
    new, n = re.subn(r"(?m)^(?!#)(\d+)、\s*", r"\1. ", content)
    if n:
        log.log(f"教程编号风格统一 (N、→N.)：{n} 处")
    return new


# ══════════════════════════════════════════════════════════════
# 9.5 加粗包裹 / 孤立标记进阶清理（link2obsidian 实战沉淀）
# 来源：对《CTA因子动物园》等微信文章后处理，发现以下模式可确定性修复
# ══════════════════════════════════════════════════════════════


def unwrap_header_bold(content: str, log: Logger) -> str:
    """
    去掉包裹在 Markdown 标题行上的孤立 **：
      **### 2.1 标题正文粘连**  →  ### 2.1 标题正文粘连
    仅移除紧贴标题行首尾的 **（转换器把标题误当加粗），不做粘连拆分
    （粘连的语义化拆分见 fix_heading_merged_with_body，余下留给 AI）。
    """
    new, n = re.subn(r"(?m)^\*\*(#{1,6}[^\n]*?)\*\*", r"\1", content)
    if n:
        log.log(f"标题孤立加粗 ** 包裹移除：{n} 处")
    return new


def fix_standalone_bold_lines(content: str, log: Logger) -> str:
    """
    删除独立成行的 **（转换器残留的孤立加粗行）：
      ...\\n\\n**\\n\\n...  →  ...\\n\\n...
    """
    new, n = re.subn(r"(?<=\n)\*\*(?=\n)", "", content)
    if n:
        log.log(f"独立成行 ** 清理：{n} 处")
    return new


def fix_bold_list_prefix(content: str, log: Logger) -> str:
    """
    列表项被误加前置 **（行内无对应闭合 ** 的孤儿情形）：
      **- OLS（基准）  →  - OLS（基准）
    注意：若行内存在闭合 **（即正经的「**- 文本**」加粗列表项），则不动，
    避免把合法加粗拆成「- 文本**」残留孤儿星号。
    """
    # 仅匹配「**- 」后整行不再出现另一个 ** 的情形（孤儿）；
    # 合法加粗「**- 文本**」因行内有闭合 ** 而被负向先行断言排除。
    new, n = re.subn(r"(?m)^\*\*- (?=(?:(?!\*\*).)*$)", "- ", content)
    if n:
        log.log(f"列表项误加粗 **-  → - （仅孤儿情形）：{n} 处")
    return new


def fix_callout_orphan_bold(content: str, log: Logger) -> str:
    """
    微信常见「通俗版 / 通俗理解」导语后残留孤立 **：
      通俗版**：你以为...  →  通俗版：你以为...
    这类 ** 转换器误加，去掉后更干净。
    """
    new, n = re.subn(r"(通俗版|通俗理解)\*\*：", r"\1：", content)
    if n:
        log.log(f"导语后孤立 ** 清理（通俗版/通俗理解）：{n} 处")
    return new


def detect_scrambled_tables(content: str, log: Logger) -> None:
    """
    检测疑似被压平的表格行（转换器把 <table> 抹平后，单元格粘连成一行，
    用 ** 做分隔，丢失所有换行与 | 分隔符）。这类无法靠正则可靠重建
    （需按语义推断列边界），仅检测并提示 Agent 人工/LLM 重建，将静默
    失败转为显式告警。

    签名：行内无 |、长度 > 40、含 ≥2 个 % 且存在 **（数字单元格粘连特征）。
    """
    candidates = 0
    for line in content.split("\n"):
        if "|" in line or len(line) < 40:
            continue
        if line.count("%") >= 2 and "**" in line:
            candidates += 1
    if candidates:
        log.hint(
            f"检测到 {candidates} 行疑似被压平的表格（含 % 与 ** 但无 | 分隔符），"
            f"请按语义重建为 GFM pipe 表格（列边界需人工/LLM 判定）"
        )


# ══════════════════════════════════════════════════════════════
# 入口：组合所有修复
# ══════════════════════════════════════════════════════════════


def process(md_path: Path, url: str | None, dry_run: bool, verbose: bool) -> int:
    if not md_path.exists():
        print(f"❌ 文件不存在: {md_path}")
        return 2

    raw = md_path.read_text(encoding="utf-8")
    log = Logger(verbose=verbose, dry_run=dry_run)
    log.log(f"读取文件：{md_path}（{len(raw)} 字节）")

    if len(raw) < 500:
        log.hint(
            f"文件仅 {len(raw)} 字节（< 500），很可能 runner.py 抓取失败，"
            "请按 SKILL.md 后处理步骤 1 自行尝试 curl+JsDecode / cnblogs·CSDN "
            "提取 / browser-act stealth-extract"
        )

    fm, body = split_frontmatter(raw)
    new_fm = clean_frontmatter(fm, log)

    # body 处理：顺序敏感，先字符级，再标签级，再结构级
    body = fix_nbsp(body, log)
    body = fix_escaped_asterisks(body, log)
    body = normalize_bold_markers(body, log)
    body = fix_orphan_bold(body, log)
    body = unwrap_header_bold(body, log)
    body = fix_standalone_bold_lines(body, log)
    body = fix_bold_list_prefix(body, log)
    body = fix_callout_orphan_bold(body, log)
    body = upgrade_chinese_numbered_headings(body, log)
    body = upgrade_numeric_numbered_headings(body, log)
    body = fix_empty_heading(body, new_fm, log)
    body = fix_heading_merged_with_body(body, log)
    body = fix_heading_with_codeblock_inline(body, log)
    body = fix_redundant_bullets(body, log)
    body = split_inline_bullets(body, log)
    body = fix_empty_bullet_lines(body, log)
    body = fix_code_fence_degraded(body, log)
    body = fix_inline_code_missing_space(body, log)
    body = fix_code_fence_close_attached_text(body, log)
    body = fix_image_path(body, log)
    body = fix_mixed_numbered_list(body, log)
    body = fix_trailing_whitespace(body, log)
    # 空行合并放最后，确保捕获前序步骤（heading 拆分、空子弹清理等）产生的 4+ 空行
    body = fix_extra_blank_lines(body, log)

    # 图片状态检查（仅报告）
    check_image_status(body, log, md_path)
    # 被压平表格检测（仅报告，需 AI 按语义重建）
    detect_scrambled_tables(body, log)

    new_content = (new_fm + "\n" + body) if new_fm else body
    new_content = new_content.rstrip() + "\n"

    changed = new_content != raw
    if changed and not dry_run:
        md_path.write_text(new_content, encoding="utf-8")
        print(f"✅ 后处理完成，已写回：{md_path}")
    elif dry_run:
        print(f"💧 Dry-run 模式，未写回（{len(log.messages)} 项变更）")
    else:
        print("ℹ️  未发现需要修改的内容")

    log.summary()
    return 0


def parse_args(argv=None):
    p = argparse.ArgumentParser(
        description="link2obsidian 后处理：自动清理 runner.py 输出的 Markdown 文件"
    )
    p.add_argument("md_path", help="runner.py 生成的 Markdown 文件路径")
    p.add_argument("--url", default=None, help="原文 URL（仅用于 AI 提示，不自动抓取）")
    p.add_argument("--dry-run", action="store_true", help="只报告不写回")
    p.add_argument("--verbose", "-v", action="store_true", help="打印详细修复日志")
    return p.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    return process(
        Path(args.md_path).expanduser(), args.url, args.dry_run, args.verbose
    )


if __name__ == "__main__":
    sys.exit(main())