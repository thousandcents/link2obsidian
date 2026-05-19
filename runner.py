#!/usr/bin/env python3
"""
link2obsidian — 执行器
从 SKILL.md 动态加载 Python 代码并执行，注入 LLM 配置。

用法:
    python3 runner.py <URL>

环境变量:
    OBSIDIAN_VAULT       Obsidian 根目录（默认: ./Obsidian/Thousand）
    LLM_API_KEY          LLM API Key（可选，用于生成文章摘要）
    LLM_BASE_URL         LLM API 地址（可选，默认: https://api.openai.com/v1）
    LLM_MODEL            LLM 模型名（可选，默认: gpt-4o-mini）
"""

import sys
import re
import os
import json
import subprocess
import hashlib
import html as html_mod
import tempfile
from datetime import datetime
from pathlib import Path


def load_llm_config():
    """从环境变量读取 LLM 配置（用于文章摘要生成）。"""
    config = {
        "base_url": os.environ.get(
            "LLM_BASE_URL", "https://api.openai.com/v1"
        ).rstrip("/"),
        "model": os.environ.get("LLM_MODEL", "gpt-4o-mini"),
        "api_key": os.environ.get("LLM_API_KEY", ""),
    }
    return config


def run_link2obsidian(url):
    """从 SKILL.md 动态加载代码并执行。"""
    script_dir = Path(__file__).parent.resolve()
    skill_path = script_dir / "SKILL.md"
    with open(skill_path, "r", encoding="utf-8") as f:
        content = f.read()

    # 支持 ```python 和 ~~~python 两种代码栅格
    code_match = re.search(r"```python\n(.*?)```", content, re.DOTALL)
    if not code_match:
        code_match = re.search(r"~~~python\n(.*?)~~~", content, re.DOTALL)
    if not code_match:
        print("错误: 未找到 Python 代码块")
        return False

    python_code = code_match.group(1)

    # 替换 URL 占位符
    python_code = python_code.replace(
        'ARTICLE_URL = "用户提供的链接"',
        f"ARTICLE_URL = {json.dumps(url)}",
    )

    # 加载 LLM 配置，通过 _LLM_CONFIG 注入执行环境
    llm_config = load_llm_config()

    # 编译并执行
    try:
        code_obj = compile(python_code.strip(), "<string>", "exec")
        exec_globals = {
            "subprocess": subprocess,
            "re": re,
            "os": os,
            "hashlib": hashlib,
            "datetime": datetime,
            "json": json,
            "html_mod": html_mod,
            "tempfile": tempfile,
            "Path": Path,
            "_LLM_CONFIG": llm_config,
            "__name__": "__main__",
        }
        exec(code_obj, exec_globals)
        return True
    except Exception as e:
        print(f"执行错误: {e}")
        import traceback

        traceback.print_exc()
        return False


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法: python runner.py <URL>")
        sys.exit(1)

    url = sys.argv[1]
    success = run_link2obsidian(url)
    sys.exit(0 if success else 1)
