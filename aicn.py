#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""aicn —— 国内大模型一键接入 AI 编程工具（Codex / Claude Code / Cursor / Cline）

零依赖单文件 CLI：查看模型与价格、测试连通性、生成工具配置、环境体检。

用法示例：
    python aicn.py list                              # 查看供应商/模型/价格
    python aicn.py test -p deepseek -m deepseek-chat --key sk-xxx
    python aicn.py gen -t codex -p qwen -m qwen-plus --write
    python aicn.py doctor                            # 环境体检
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import re
import shutil
import sys
import time
import unicodedata
import urllib.error
import urllib.request
from pathlib import Path

VERSION = "0.1.0"
DATA_FILE = Path(__file__).resolve().parent / "data" / "providers.json"

if sys.platform == "win32":
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


# --------------------------------------------------------------------------
# 基础工具
# --------------------------------------------------------------------------

def display_width(text: str) -> int:
    """按终端显示宽度计算（中文按 2 列）。"""
    return sum(2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1 for ch in text)


def pad(text: str, width: int) -> str:
    return text + " " * max(1, width - display_width(text))


def load_providers() -> dict:
    if not DATA_FILE.exists():
        sys.stderr.write("错误：找不到数据文件 %s\n" % DATA_FILE)
        sys.exit(2)
    with open(DATA_FILE, encoding="utf-8") as fh:
        data = json.load(fh)
    return data


def require_provider(data: dict, provider_id: str) -> dict:
    providers = data["providers"]
    if provider_id not in providers:
        sys.stderr.write("未知供应商 %r，可用：%s\n" % (provider_id, ", ".join(sorted(providers))))
        sys.exit(2)
    return providers[provider_id]


def pick_model(provider: dict, model_id: str | None) -> str:
    if model_id:
        return model_id
    models = provider.get("models") or []
    if not models:
        sys.stderr.write("供应商 %s 没有内置模型，请用 --model 指定\n" % provider.get("name"))
        sys.exit(2)
    return models[0]["id"]


def http_request(url: str, method: str = "GET", headers: dict | None = None,
                 body: dict | None = None, timeout: int = 15):
    payload = None if body is None else json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=payload, headers=headers or {}, method=method)
    started = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, round((time.time() - started) * 1000), resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as err:
        return err.code, round((time.time() - started) * 1000), err.read().decode("utf-8", "replace")
    except Exception as err:  # URLError / 超时 / 连接失败
        return None, round((time.time() - started) * 1000), str(err)


def read_key(provider: dict, key_arg: str | None) -> str | None:
    if key_arg:
        return key_arg
    return os.environ.get(provider.get("env_key") or "")


def provider_protocols(provider: dict) -> list:
    """返回供应商支持的协议标签列表。"""
    tags = []
    if provider.get("base_url"):
        tags.append("chat")
    if provider.get("anthropic_base_url"):
        tags.append("anthropic")
    if provider.get("responses_api") is True:
        tags.append("responses")
    elif provider.get("responses_api") is None:
        tags.append("responses?")
    return tags


def format_price(value, currency: str) -> str:
    if value is None:
        return "见官网"
    if currency == "USD":
        return "$%.2f" % value
    return "¥%.2f" % value


# --------------------------------------------------------------------------
# 命令：list
# --------------------------------------------------------------------------

def cmd_list(args) -> str:
    data = load_providers()
    providers = data["providers"]
    lines = []
    if args.provider:
        require_provider(data, args.provider)
        providers = {args.provider: providers[args.provider]}

    rows = []
    for pid, p in providers.items():
        currency = p.get("currency", "CNY")
        for m in p.get("models", []):
            price_in = format_price(m.get("input"), currency)
            price_out = format_price(m.get("output"), currency)
            if m.get("cache_hit_input") is not None and currency == "CNY":
                price_in += "(命中¥%.1f)" % m["cache_hit_input"]
            rows.append({
                "provider": pid, "name": p.get("name", pid), "cn": p.get("cn", ""),
                "model": m["id"], "price": "%s / %s" % (price_in, price_out),
                "context": m.get("context") or "-", "protocols": "/".join(provider_protocols(p)),
                "desc": m.get("desc") or "",
            })

    if args.json:
        lines.append(json.dumps({"price_updated": data.get("price_updated"),
                                 "disclaimer": data.get("disclaimer"), "rows": rows},
                                ensure_ascii=False, indent=2))
        return "\n".join(lines)

    header = ["供应商", "模型", "输入/输出 (1M)", "上下文", "协议", "说明"]
    widths = [12, 30, 26, 10, 12, 40]
    lines.append("  ".join(pad(h, w) for h, w in zip(header, widths)))
    lines.append("  ".join("-" * w for w in widths))
    for r in rows:
        cells = [r["provider"], r["model"], r["price"], r["context"], r["protocols"], r["desc"]]
        lines.append("  ".join(pad(c, w) for c, w in zip(cells, widths)))
    lines.append("")
    lines.append("协议说明：chat=OpenAI Chat 兼容 / anthropic=Anthropic 兼容 / responses=Responses 兼容（? 表示未官方确认）。")
    lines.append("价格更新于 %s，仅作参考，以官方定价页为准。%s" % (
        data.get("price_updated", "未知"), ""))
    lines.append("模型价格可 PR 更新：%s" % DATA_FILE)
    return "\n".join(lines)


# --------------------------------------------------------------------------
# 命令：test
# --------------------------------------------------------------------------

def _test_chat(provider: dict, model: str, key: str, base_override: str | None):
    base = (base_override or provider["base_url"]).rstrip("/")
    url = base + "/chat/completions"
    body = {"model": model, "messages": [{"role": "user", "content": "请只回复 ok"}], "max_tokens": 16}
    headers = {"Content-Type": "application/json"}
    if key:
        headers["Authorization"] = "Bearer " + key
    status, ms, raw = http_request(url, "POST", headers, body)
    return status, ms, raw


def _test_responses(provider: dict, model: str, key: str, base_override: str | None):
    base = (base_override or provider["base_url"]).rstrip("/")
    url = base + "/responses"
    body = {"model": model, "input": "请只回复 ok", "max_output_tokens": 16}
    headers = {"Content-Type": "application/json"}
    if key:
        headers["Authorization"] = "Bearer " + key
    status, ms, raw = http_request(url, "POST", headers, body)
    return status, ms, raw


def _test_anthropic(provider: dict, model: str, key: str, base_override: str | None):
    base = (base_override or provider.get("anthropic_base_url") or provider["base_url"]).rstrip("/")
    url = base + "/v1/messages"
    body = {"model": model, "max_tokens": 16,
            "messages": [{"role": "user", "content": "请只回复 ok"}]}
    headers = {"Content-Type": "application/json", "anthropic-version": "2023-06-01"}
    if key:
        headers["x-api-key"] = key
    status, ms, raw = http_request(url, "POST", headers, body)
    return status, ms, raw


def cmd_test(args) -> str:
    data = load_providers()
    provider = require_provider(data, args.provider)
    model = pick_model(provider, args.model)
    key = read_key(provider, args.key)
    lines = ["测试供应商 %s 模型 %s（协议 %s）..." % (provider["name"], model, args.protocol)]
    if not key:
        lines.append("提示：未提供 API Key（--key 或环境变量 %s），结果可能是 401。" % provider.get("env_key"))

    if args.protocol == "chat":
        status, ms, raw = _test_chat(provider, model, key, args.base_url)
    elif args.protocol == "responses":
        status, ms, raw = _test_responses(provider, model, key, args.base_url)
    else:
        status, ms, raw = _test_anthropic(provider, model, key, args.base_url)

    lines.append("HTTP %s  耗时 %sms" % (status if status else "失败", ms))
    try:
        parsed = json.loads(raw)
    except (ValueError, TypeError):
        parsed = None
    if parsed and status and status < 400:
        lines.append("响应模型：%s" % parsed.get("model", "-"))
        if args.protocol == "chat":
            content = ""
            choices = parsed.get("choices") or []
            if choices and choices[0].get("message"):
                content = choices[0]["message"].get("content") or ""
            usage = parsed.get("usage") or {}
            if content:
                lines.append("回复内容：%s" % str(content)[:200])
            if usage:
                lines.append("用量：prompt %s / completion %s tokens" % (
                    usage.get("prompt_tokens"), usage.get("completion_tokens")))
        elif args.protocol == "responses":
            content = parsed.get("output_text") or ""
            usage = parsed.get("usage") or {}
            if content:
                lines.append("回复内容：%s" % str(content)[:200])
            if usage:
                lines.append("用量：input %s / output %s tokens" % (
                    usage.get("input_tokens"), usage.get("output_tokens")))
        else:
            content = ""
            for block in parsed.get("content") or []:
                if block.get("type") == "text":
                    content = block.get("text") or ""
            usage = parsed.get("usage") or {}
            if content:
                lines.append("回复内容：%s" % content[:200])
            if usage:
                lines.append("用量：input %s / output %s tokens" % (
                    usage.get("input_tokens"), usage.get("output_tokens")))
    else:
        err = parsed.get("error", {}) if parsed else None
        if isinstance(err, dict):
            lines.append("错误信息：%s" % str(err.get("message", err))[:300])
        else:
            lines.append("原始响应：%s" % raw[:300])
    return "\n".join(lines)


# --------------------------------------------------------------------------
# 命令：gen
# --------------------------------------------------------------------------

def gen_codex_block(provider_id: str, provider: dict, wire_api: str) -> str:
    block = [
        "[model_providers.%s]" % provider_id,
        'name = "%s"' % provider["name"],
        'base_url = "%s"' % provider["base_url"],
        'env_key = "%s"' % provider["env_key"],
        'wire_api = "%s"' % wire_api,
    ]
    return "\n".join(block) + "\n"


def apply_codex_update(text: str, provider_id: str, block: str) -> str:
    """在 config.toml 文本中新增或替换 [model_providers.<id>] 小节。"""
    header = "[model_providers.%s]" % provider_id
    lines = text.splitlines()
    start = next((i for i, line in enumerate(lines) if line.strip() == header), None)
    if start is not None:
        end = len(lines)
        for j in range(start + 1, len(lines)):
            if lines[j].startswith("["):
                end = j
                break
        new_lines = lines[:start] + block.strip().splitlines() + lines[end:]
        return "\n".join(new_lines).rstrip() + "\n"
    if text and not text.endswith("\n"):
        text += "\n"
    if text.strip():
        text = text.rstrip() + "\n\n"
    return text + block


def build_claude_settings(existing: str | None, base_url: str, model: str, key: str | None) -> str:
    data: dict = {}
    if existing:
        try:
            loaded = json.loads(existing)
        except json.JSONDecodeError as err:
            sys.stderr.write("错误：现有 settings.json 不是合法 JSON（%s），请先手工修复后重试。\n" % err)
            sys.exit(2)
        if isinstance(loaded, dict):
            data = loaded
    env = data.setdefault("env", {})
    if not isinstance(env, dict):
        env = {}
    env["ANTHROPIC_BASE_URL"] = base_url
    env["ANTHROPIC_AUTH_TOKEN"] = key or "请替换为你的 API Key"
    if model:
        env["ANTHROPIC_MODEL"] = model
    data["env"] = env
    return json.dumps(data, ensure_ascii=False, indent=2) + "\n"


def write_with_backup(path: Path, content: str) -> None:
    if path.exists():
        backup = path.with_name(path.name + ".aicn.bak")
        backup.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
        print("[备份] 原文件已备份到 %s" % backup)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def codex_config_path() -> Path:
    return Path.home() / ".codex" / "config.toml"


def claude_config_path() -> Path:
    return Path.home() / ".claude" / "settings.json"


def guide_base_url(provider: dict) -> str:
    base = provider["base_url"].rstrip("/")
    if re.search(r"/v[0-9]+$", base):
        return base
    return base + "/v1"


def cursor_guide(provider: dict, model: str) -> str:
    return "\n".join([
        "Cursor 通过界面接入 OpenAI 兼容端点，按以下步骤操作：",
        "  1. 打开 Cursor → Settings → Models",
        "  2. 勾选开启 “OpenAI API Key”",
        "  3. 填写：",
        "     OpenAI API Key : 你的 %s 密钥（%s）" % (provider["name"], provider["env_key"]),
        "     Base URL       : %s" % guide_base_url(provider),
        "     模型名称       : %s" % model,
        "  4. 保存后，在模型选择器中选择该模型",
        "提示：Cursor 会保存密钥到本机；如遇 404，请确认模型名与 Base URL 是否以官网为准。",
    ])


def cline_guide(provider: dict, model: str) -> str:
    return "\n".join([
        "Cline（VS Code 插件）通过 “OpenAI Compatible” 接入，按以下步骤操作：",
        "  1. 打开 Cline 设置 → API Provider 选择 “OpenAI Compatible”",
        "  2. 填写：",
        "     Base URL : %s" % guide_base_url(provider),
        "     API Key  : 你的 %s 密钥（%s）" % (provider["name"], provider["env_key"]),
        "     Model ID : %s" % model,
        "  3. 保存并重连",
    ])


def cmd_gen(args) -> str:
    data = load_providers()
    provider = require_provider(data, args.provider)
    model = pick_model(provider, args.model)
    lines = []

    if args.tool == "codex":
        wire_api = args.wire_api or "responses"
        block = gen_codex_block(args.provider, provider, wire_api)
        path = codex_config_path()
        lines.append("将写入/更新 %s：" % path)
        lines.append("")
        lines.append(block.rstrip())
        lines.append("")
        lines.append("使用方式：设置密钥后，用 `codex --model %s/%s` 选择该模型。" % (args.provider, model))
        if wire_api == "responses" and provider.get("responses_api") is not True:
            lines.append("")
            lines.append("注意：当前 Codex 官方仅支持 Responses 协议，%s 未官方确认支持。"
                         "请先运行 `aicn test --provider %s --model %s --protocol responses` 验证；"
                         "如不通过，可改用已确认支持的供应商（如 qwen），或在本机架设网关"
                         "（one-api / claude-code-router / 9router 等）再指向网关地址。" % (
                             provider["name"], args.provider, model))
        if wire_api == "chat":
            lines.append("")
            lines.append("注意：--wire-api chat 仅适用于旧版 Codex；当前版本只支持 responses。")
        if args.write:
            existing = path.read_text(encoding="utf-8") if path.exists() else ""
            write_with_backup(path, apply_codex_update(existing, args.provider, block))
            lines.append("")
            lines.append("已写入 %s" % path)

    elif args.tool == "claude-code":
        base = provider.get("anthropic_base_url")
        if not base:
            lines.append("%s 未收录 Anthropic 兼容端点，Claude Code 需要 Anthropic 协议。" % provider["name"])
            lines.append("可用替代方案：")
            lines.append("  - 换用带 anthropic 端点的供应商：moonshot / zhipu(编码套餐) / siliconflow")
            lines.append("  - 本机架设 claude-code-router 或 9router 做协议转换")
            return "\n".join(lines)
        content = build_claude_settings(None, base, model, args.key)
        path = claude_config_path()
        lines.append("将写入/更新 %s：" % path)
        lines.append("")
        lines.append(content.rstrip())
        lines.append("")
        lines.append("注意：模型名需与供应商端点接受的名称一致；新版 Claude Code 对模型名有校验，"
                     "如启动报错请对照供应商官方文档。")
        if args.write:
            existing = path.read_text(encoding="utf-8") if path.exists() else None
            write_with_backup(path, build_claude_settings(existing, base, model, args.key))
            lines.append("")
            lines.append("已写入 %s" % path)

    elif args.tool == "cursor":
        lines.append(cursor_guide(provider, model))
        if provider.get("currency") == "USD":
            lines.append("提示：%s 为美元计费海外服务，国内访问可能受限。" % provider["name"])

    elif args.tool == "cline":
        lines.append(cline_guide(provider, model))

    if args.tool not in ("cursor", "cline"):
        lines.append("")
        lines.append("设置密钥后运行：`aicn env %s` 查看环境变量设置命令。" % args.provider)
    if not args.write and args.tool in ("codex", "claude-code"):
        lines.append("")
        lines.append("以上为预览（dry-run）。确认无误后加 --write 真正写入配置文件。")
    return "\n".join(lines)


# --------------------------------------------------------------------------
# 命令：env
# --------------------------------------------------------------------------

def cmd_env(args) -> str:
    data = load_providers()
    provider = require_provider(data, args.provider)
    key = provider["env_key"]
    return "\n".join([
        "PowerShell（当前会话）：",
        '  $env:%s = "你的Key"' % key,
        "PowerShell（永久，当前用户）：",
        '  setx %s "你的Key"' % key,
        "",
        "bash / zsh：",
        '  export %s="你的Key"' % key,
        "  （持久化建议写入 ~/.bashrc 或 ~/.zshrc）",
        "",
        "密钥获取地址：%s" % provider["site"],
    ])


# --------------------------------------------------------------------------
# 命令：doctor
# --------------------------------------------------------------------------

def probe_endpoint(pid: str, provider: dict) -> tuple:
    key = os.environ.get(provider.get("env_key") or "")
    url = provider["base_url"].rstrip("/") + "/models"
    headers = {"User-Agent": "aicn-doctor"}
    if key:
        headers["Authorization"] = "Bearer " + key
    status, ms, _ = http_request(url, "GET", headers, timeout=6)
    if status is None:
        return pid, "不可达", ms
    if status >= 500:
        return pid, "服务异常(%s)" % status, ms
    return pid, "可达(%s)" % status, ms


def cmd_doctor(args) -> str:
    data = load_providers()
    lines = ["=== aicn 环境体检 (v%s) ===" % VERSION, ""]
    lines.append("Python：%s  平台：%s" % (sys.version.split()[0], sys.platform))
    lines.append("Git：%s   Node：%s" % (
        shutil.which("git") or "未安装", shutil.which("node") or "未安装"))

    lines.append("")
    lines.append("--- 网络连通性（%s 个供应商端点）---" % len(data["providers"]))
    results = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        futures = {pool.submit(probe_endpoint, pid, p): pid
                   for pid, p in data["providers"].items()}
        for fut in concurrent.futures.as_completed(futures):
            pid, label, ms = fut.result()
            results[pid] = (label, ms)
    for pid in sorted(results):
        label, ms = results[pid]
        mark = "OK " if label.startswith("可达") else "!! "
        lines.append("%s %-14s %-14s %sms" % (mark, pid, label, ms))

    lines.append("")
    lines.append("--- 本机配置文件 ---")
    for label, path in [("Codex", codex_config_path()), ("Claude Code", claude_config_path())]:
        if path.exists():
            size = path.stat().st_size
            lines.append("%-14s 存在  %s (%dB)" % (label, path, size))
        else:
            lines.append("%-14s 不存在  %s" % (label, path))

    lines.append("")
    lines.append("--- 环境变量中的密钥 ---")
    found = False
    for pid, p in data["providers"].items():
        env_key = p.get("env_key")
        if env_key and os.environ.get(env_key):
            lines.append("%-14s %s = 已设置(****)" % (pid, env_key))
            found = True
    if not found:
        lines.append("未检测到任何供应商密钥环境变量（可通过 `aicn env <provider>` 查看设置命令）")

    lines.append("")
    lines.append("下一步建议：")
    lines.append("  1. `aicn list` 查看模型与价格")
    lines.append("  2. `aicn test --provider <p> --model <m> --key <k>` 验证连通性")
    lines.append("  3. `aicn gen --tool codex --provider <p> --model <m> --write` 写入配置")
    return "\n".join(lines)


# --------------------------------------------------------------------------
# 入口
# --------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="aicn",
        description="国内大模型一键接入 AI 编程工具（Codex / Claude Code / Cursor / Cline）的零依赖 CLI",
    )
    parser.add_argument("--version", action="version", version="aicn " + VERSION)
    sub = parser.add_subparsers(dest="command")

    p_list = sub.add_parser("list", help="查看供应商/模型/价格")
    p_list.add_argument("--provider", "-p", help="只看某个供应商")
    p_list.add_argument("--json", action="store_true", help="输出 JSON")

    p_test = sub.add_parser("test", help="测试模型连通性")
    p_test.add_argument("--provider", "-p", required=True, help="供应商 id（如 deepseek）")
    p_test.add_argument("--model", "-m", help="模型名（缺省取该供应商第一个模型）")
    p_test.add_argument("--key", "-k", help="API Key（缺省读环境变量）")
    p_test.add_argument("--protocol", choices=["chat", "responses", "anthropic"], default="chat",
                        help="协议（默认 chat）")
    p_test.add_argument("--base-url", help="覆盖 base URL（如指向本地网关）")

    p_gen = sub.add_parser("gen", help="生成工具接入配置")
    p_gen.add_argument("--tool", "-t", required=True,
                       choices=["codex", "claude-code", "cursor", "cline"])
    p_gen.add_argument("--provider", "-p", required=True)
    p_gen.add_argument("--model", "-m")
    p_gen.add_argument("--key", "-k", help="API Key（仅 claude-code 会写入配置）")
    p_gen.add_argument("--write", action="store_true", help="真正写入配置文件（默认 dry-run）")
    p_gen.add_argument("--wire-api", choices=["responses", "chat"],
                       help="仅 codex：协议（默认 responses；chat 仅旧版）")

    p_env = sub.add_parser("env", help="查看密钥环境变量设置命令")
    p_env.add_argument("--provider", "-p", required=True)

    sub.add_parser("doctor", help="环境体检：网络/配置/密钥")
    return parser


def main(argv: list | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.command:
        parser.print_help()
        return 0
    try:
        if args.command == "list":
            print(cmd_list(args))
        elif args.command == "test":
            print(cmd_test(args))
        elif args.command == "gen":
            print(cmd_gen(args))
        elif args.command == "env":
            print(cmd_env(args))
        elif args.command == "doctor":
            print(cmd_doctor(args))
        return 0
    except KeyboardInterrupt:
        print("\n已取消")
        return 130


if __name__ == "__main__":
    sys.exit(main())
