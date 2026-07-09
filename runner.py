#!/usr/bin/env python3
"""
link2obsidian 执行器（共享版本）
从 SKILL.md 动态加载代码并执行，支持多 profile。
"""
import sys
import re
import subprocess
import os
import hashlib
import html as html_mod
from datetime import datetime
import json
import tempfile
import yaml
import argparse
from pathlib import Path


def detect_profile():
    """自动检测当前 profile 名称。
    优先级: --profile 参数 > HERMES_HOME 环境变量 > 默认值
    """
    hermes_home = os.environ.get("HERMES_HOME", "")
    if hermes_home and "/profiles/" in hermes_home:
        return os.path.basename(hermes_home)
    return "ob_xianzi"  # 默认


def load_llm_config(profile="ob_xianzi"):
    """从指定 profile 的 Hermes 配置中读取 LLM 提供商信息。
    支持 config.yaml 中的 ${VAR} 引用，自动从 .env 展开。
    """
    profile_dir = os.path.expanduser(f"~/.hermes/profiles/{profile}")
    config_path = os.path.join(profile_dir, "config.yaml")
    env_path = os.path.join(profile_dir, ".env")

    llm_config = {
        "base_url": "https://opencode.ai/zen/go/v1",
        "model": "deepseek-v4-flash",
        "api_key": "",
    }

    # 1. 先读取 .env 到字典（供 ${VAR} 展开 + API key 查找）
    env_vars = {}
    try:
        with open(env_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                if '=' in line:
                    k, v = line.split('=', 1)
                    key_name = k.strip()
                    val = v.strip().strip('"').strip("'")
                    if val and val != '***':
                        env_vars[key_name] = val
    except Exception:
        pass

    def expand_var(value):
        """展开 ${VAR} 引用，优先 .env 字典，其次 os.environ，未找到则保留原样"""
        if not isinstance(value, str):
            return value
        def replacer(match):
            var_name = match.group(1)
            return env_vars.get(var_name, os.environ.get(var_name, match.group(0)))
        return re.sub(r'\$\{(\w+)\}', replacer, value)

    # 2. 从 config.yaml 读取（展开 ${VAR} 引用）
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            cfg = yaml.safe_load(f)
        model_cfg = cfg.get('model', {}) if cfg else {}
        provider = str(model_cfg.get('provider', ''))
        if provider and ':' in provider:
            parts = provider.split(':', 1)
            if len(parts) == 2:
                llm_config['model'] = parts[1].strip()
        if model_cfg.get('base_url'):
            expanded = expand_var(model_cfg['base_url'])
            if not expanded.startswith('${'):  # 展开成功
                llm_config['base_url'] = expanded.rstrip('/')
        if model_cfg.get('api_key'):
            expanded = expand_var(model_cfg['api_key'])
            if expanded and not expanded.startswith('${'):
                llm_config['api_key'] = expanded
    except Exception:
        pass

    # 3. 从 .env 读取 API key（如果 config.yaml 未提供或展开失败）
    #    优先级: SENSE_API_KEY > OPENCODE_GO_API_KEY > OPENAI_API_KEY
    if not llm_config['api_key']:
        for key_name in ['SENSE_API_KEY', 'OPENCODE_GO_API_KEY', 'OPENAI_API_KEY']:
            if key_name in env_vars:
                llm_config['api_key'] = env_vars[key_name]
                break

    # 4. OPENAI_BASE_URL 覆盖（如果 .env 中有且未被注释）
    if 'OPENAI_BASE_URL' in env_vars:
        llm_config['base_url'] = env_vars['OPENAI_BASE_URL'].rstrip('/')

    # 5. 如果用 xunfei/astron 端点，使用正确的模型名
    if 'xf-yun' in llm_config['base_url'] or 'maas-coding' in llm_config['base_url']:
        llm_config['model'] = 'astron-code-latest'

    return llm_config


def run_link2obsidian(url, profile="ob_xianzi", workdir=None):
    """从 SKILL.md 动态加载代码并执行"""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    skill_path = os.path.join(script_dir, "SKILL.md")
    with open(skill_path, 'r', encoding='utf-8') as f:
        content = f.read()

    # 支持 ```python 和 ~~~python 两种代码栅格
    code_match = re.search(r'```python\n(.*?)```', content, re.DOTALL)
    if not code_match:
        code_match = re.search(r'~~~python\n(.*?)~~~', content, re.DOTALL)
    if not code_match:
        print("错误: 未找到 Python 代码块")
        return False

    python_code = code_match.group(1)

    # 替换 URL 占位符
    python_code = python_code.replace(
        'ARTICLE_URL = "用户提供的链接"',
        f'ARTICLE_URL = {json.dumps(url)}'
    )

    # 替换工作目录（如果指定了自定义路径）
    if workdir:
        default_workdir = "/home/jack-lin-sparrow/Obsidian/Thousand"
        python_code = python_code.replace(
            f'WORKDIR = "{default_workdir}"',
            f'WORKDIR = {json.dumps(workdir)}'
        )

    # 加载 LLM 配置，注入到执行环境
    llm_config = load_llm_config(profile)

    # 编译并执行
    try:
        code_obj = compile(python_code.strip(), '<string>', 'exec')
        exec_globals = {
            'subprocess': subprocess,
            'shutil': __import__('shutil'),
            're': re,
            'os': os,
            'hashlib': hashlib,
            'datetime': datetime,
            'json': json,
            'html_mod': html_mod,
            'tempfile': tempfile,
            'Path': Path,
            'sys': sys,
            '_LLM_CONFIG': llm_config,
            '__name__': '__main__'
        }
        exec(code_obj, exec_globals)
        return True
    except Exception as e:
        print(f"执行错误: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="link2obsidian — 将网页链接转换为 Obsidian Markdown 文件"
    )
    parser.add_argument("url", help="网页链接 (微信公众号/知乎等)")
    parser.add_argument(
        "--profile", "-p",
        default=None,
        help="Hermes profile 名称 (默认: 自动检测 HERMES_HOME 或 ob_xianzi)"
    )
    parser.add_argument(
        "--workdir", "-w",
        default=None,
        help="Obsidian vault 路径 (默认: /home/jack-lin-sparrow/Obsidian/Thousand)"
    )
    args = parser.parse_args()

    profile = args.profile or detect_profile()
    print(f"🔧 使用 profile: {profile}")

    success = run_link2obsidian(args.url, profile=profile, workdir=args.workdir)
    sys.exit(0 if success else 1)
