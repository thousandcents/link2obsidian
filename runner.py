#!/usr/bin/env python3
"""
link2obsidian 执行器（共享版本）
从 SKILL.md 动态加载代码并执行，支持多 profile。

执行流程：
  1. 从同目录 SKILL.md 提取 Python 代码块（抓取 + 转 Markdown 逻辑）并执行，
     生成 Clippings/ 下的 .md 文件
  2. 自动调用 postprocess.py 完成后处理（正则/固定规则的格式清理），
     无需 Agent 手动触发 —— 解决「postprocess 偶尔没运行」的问题

postprocess.py 的位置会自动查找（同目录 / ../note-taking/link2obsidian/ /
~/.hermes 下搜索），找不到时仅告警并跳过，不影响已生成的 .md 文件。
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
import importlib.util
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
    """从 SKILL.md 动态加载代码并执行，返回生成的 .md 文件路径（Path）或 None"""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    skill_path = os.path.join(script_dir, "SKILL.md")
    with open(skill_path, 'r', encoding='utf-8') as f:
        content = f.read()

    # 支持 ~~~python 和 ```python 两种代码栅格。
    # 优先 ~~~python：本技能的抓取代码块用 ~~~python 包裹（代码内部含 ``` 反引号，
    # 不能用 ```python 否则会提前闭合）；文档里的 ```python 示例不干扰。
    code_match = re.search(r'~~~python\n(.*?)~~~', content, re.DOTALL)
    if not code_match:
        code_match = re.search(r'```python\n(.*?)```', content, re.DOTALL)
    if not code_match:
        print("错误: 未找到 Python 代码块")
        return None

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
        # 抓取代码会在执行结束时设置 output_path（Clippings/xxx.md）
        output_path = exec_globals.get("output_path")
        return output_path
    except Exception as e:
        print(f"执行错误: {e}")
        import traceback
        traceback.print_exc()
        return None


def locate_postprocess():
    """定位 postprocess.py。

    按以下顺序查找（覆盖 runner 经软链指向 source、以及 ob_xianzi 本地 fork 两种真实位置）：
      1. 与 runner.py 同目录
      2. ../note-taking/link2obsidian/postprocess.py
      3. ~/.hermes/profiles/ob_xianzi/skills/note-taking/link2obsidian/postprocess.py
      4. ~/.hermes/skills/note-taking/link2obsidian/postprocess.py
      5. ~/.hermes 下任意 link2obsidian 目录内的 postprocess.py（兜底搜索）
    """
    script_dir = os.path.dirname(os.path.abspath(__file__))
    home = os.path.expanduser("~")
    candidates = [
        os.path.join(script_dir, "postprocess.py"),
        os.path.join(script_dir, "..", "note-taking", "link2obsidian", "postprocess.py"),
        os.path.join(home, "profiles", "ob_xianzi", "skills", "note-taking", "link2obsidian", "postprocess.py"),
        os.path.join(home, "skills", "note-taking", "link2obsidian", "postprocess.py"),
    ]
    for c in candidates:
        p = os.path.abspath(c)
        if os.path.isfile(p):
            return p
    # 兜底：在 ~/.hermes 下搜索任意 link2obsidian 目录内的 postprocess.py
    import glob
    for p in glob.glob(os.path.join(home, ".hermes", "**", "link2obsidian", "postprocess.py"), recursive=True):
        return os.path.abspath(p)
    return None


def run_postprocess(md_path, url):
    """自动调用 postprocess.py 对生成的 .md 文件做确定性格式清理。

    失败仅告警，不影响已生成的文件；返回 True 表示后处理成功执行。
    """
    pp = locate_postprocess()
    if not pp:
        print("⚠️ 未找到 postprocess.py，跳过自动后处理（请手动运行 postprocess.py）")
        return False
    try:
        print(f"\n🔧 自动运行后处理: {pp}")
        spec = importlib.util.spec_from_file_location("link2obsidian_postprocess", pp)
        if spec is None or spec.loader is None:
            print("⚠️ 无法加载 postprocess.py（spec 为空），跳过自动后处理")
            return False
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        rc = mod.process(Path(md_path), url, dry_run=False, verbose=True)
        return rc == 0
    except Exception as e:
        print(f"⚠️ 后处理运行失败: {e}")
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

    output_path = run_link2obsidian(args.url, profile=profile, workdir=args.workdir)
    if not output_path:
        sys.exit(1)

    # 自动后处理（确定性格式清理），无需 Agent 手动触发
    run_postprocess(output_path, args.url)

    sys.exit(0)
