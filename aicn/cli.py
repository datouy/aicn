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

try:
    from importlib.metadata import PackageNotFoundError
    from importlib.metadata import version as _pkg_version
except ImportError:  # pragma: no cover - Python < 3.8
    PackageNotFoundError, _pkg_version = Exception, None

from ._version import __version__

#: 源码树直接运行（未 pip 安装）时，importlib.metadata 查不到本包，
#: 回落到 aicn/_version.py 里的静态版本号（唯一来源）。
FALLBACK_VERSION = __version__
try:
    VERSION = _pkg_version("aicn") if _pkg_version else FALLBACK_VERSION
except PackageNotFoundError:
    VERSION = FALLBACK_VERSION

DATA_FILE = Path(__file__).resolve().parent / "data" / "providers.json"
#: 用户级数据文件：存放从 /models 同步来的模型列表。
#: 不直接写包内的 DATA_FILE —— pip 安装后那是 site-packages，多半无写权限，
#: 写坏了也会污染全局安装环境。
USER_DATA_FILE = Path.home() / ".aicn" / "providers.json"


class AicnError(Exception):
    """可预期的用户级错误：向 stderr 输出并以非零退出码结束。"""

    def __init__(self, message: str, code: int = 2):
        super().__init__(message)
        self.code = code


class CommandOutput(str):
    """命令输出文本，附带退出码。

    继承 str 以便调用方照常当普通字符串用（拼接、json.loads 等），
    同时让 main() 能把非零退出码透传给 shell / CI。
    """

    exit_code = 0

    def __new__(cls, text: str = "", exit_code: int = 0):
        obj = super().__new__(cls, text)
        obj.exit_code = exit_code
        return obj

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


def truncate(text: str, width: int) -> str:
    """按显示宽度截断，超长时以 … 结尾。"""
    if width <= 0:
        return ""
    if display_width(text) <= width:
        return text
    out = ""
    used = 0
    for ch in text:
        w = 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1
        if used + w > width - 1:
            break
        out += ch
        used += w
    return out + "…"


def pad(text: str, width: int) -> str:
    """截断到指定显示宽度并右侧补空格（结果宽度恰好等于 width）。"""
    text = truncate(text, width)
    return text + " " * max(0, width - display_width(text))


def column_widths(rows: list[list[str]], headers: list[str],
                   minimums: list[int], maximums: list[int]) -> list[int]:
    """按内容计算列宽：不超过 maximum，不小于 minimum。"""
    widths = []
    for i, header in enumerate(headers):
        widest = max([display_width(header)] + [display_width(r[i]) for r in rows]) if rows \
            else display_width(header)
        widths.append(max(minimums[i], min(maximums[i], widest)))
    return widths


def load_providers() -> dict:
    """加载供应商数据。

    以包内 DATA_FILE 为基线，再叠加用户级 USER_DATA_FILE（~/.aicn/providers.json）里
    同步来的模型列表。用户级文件只覆盖 model 条目，不改动价格等基线字段。
    """
    if not DATA_FILE.exists():
        raise AicnError("找不到数据文件 %s" % DATA_FILE)
    with open(DATA_FILE, encoding="utf-8") as fh:
        data = json.load(fh)
    overlay = load_user_overlay()
    if overlay:
        _apply_overlay(data, overlay)
    return data


def load_user_overlay() -> dict:
    """读取用户级数据文件（不存在或损坏时返回空 dict，不影响主流程）。"""
    if not USER_DATA_FILE.exists():
        return {}
    try:
        with open(USER_DATA_FILE, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, json.JSONDecodeError):
        return {}


def _apply_overlay(data: dict, overlay: dict) -> None:
    """把用户级数据里的模型列表合并进基线数据（按 id 覆盖）。"""
    for pid, user_provider in (overlay.get("providers") or {}).items():
        base_provider = data["providers"].get(pid)
        if not base_provider or not user_provider.get("models"):
            continue
        by_id = {m["id"]: m for m in base_provider.get("models", [])}
        for m in user_provider["models"]:
            if m.get("id"):
                by_id[m["id"]] = m
        base_provider["models"] = list(by_id.values())


def staleness_months(updated: str) -> int | None:
    """从 '2026-10' 计算距今月数;无法解析返回 None。"""
    try:
        year, month = (int(x) for x in updated.split("-")[:2])
        now = time.localtime()
        return (now.tm_year - year) * 12 + (now.tm_mon - month)
    except Exception:
        return None


def require_provider(data: dict, provider_id: str) -> dict:
    providers = data["providers"]
    if provider_id not in providers:
        raise AicnError("未知供应商 %r，可用：%s" % (provider_id, ", ".join(sorted(providers))))
    return providers[provider_id]


def pick_model(provider: dict, model_id: str | None) -> str:
    if model_id:
        return model_id
    models = provider.get("models") or []
    if not models:
        raise AicnError("供应商 %s 没有内置模型，请用 --model 指定" % provider.get("name"))
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
    """返回供应商支持的协议标签列表。

    优先使用 providers.json 里显式声明的 protocols / unconfirmed_protocols；
    缺失时回落到基于端点字段的推断（兼容旧数据文件）。
    """
    tags: list[str] = []
    declared = provider.get("protocols")
    if declared is None:
        # 兼容旧数据：按端点字段推断
        if provider.get("base_url"):
            tags.append("chat")
        if provider.get("anthropic_base_url"):
            tags.append("anthropic")
        if provider.get("responses_api") is True:
            tags.append("responses")
        elif provider.get("responses_api") is None:
            tags.append("responses?")
        return tags
    for proto in declared:
        tags.append(proto)
    for proto in provider.get("unconfirmed_protocols") or []:
        tags.append(proto + "?")
    return tags


def provider_base_url(provider: dict, protocol: str) -> str | None:
    """返回供应商在指定协议下的 base_url。

    不同协议的基址可能不同（智谱的对话补全是 /api/paas/v4，Responses 却是 /api/v1），
    所以按协议取基址，而不是所有协议共用一个 base_url。
    """
    if protocol == "anthropic":
        return provider.get("anthropic_base_url") or None
    if protocol == "responses":
        return provider.get("responses_base_url") or provider.get("base_url") or None
    return provider.get("base_url") or None


def provider_supports(provider: dict, protocol: str) -> bool:
    """供应商是否**已确认**支持某协议。

    '?' 标记的未确认协议（如 responses?）不算确认 —— 它们只是「值得一试」，
    不是「官方声明支持」。cmd_gen 用它来决定是否给出协议不支持的警告。
    """
    return protocol in provider_protocols(provider)


def provider_may_support(provider: dict, protocol: str) -> bool:
    """供应商是否可能支持某协议（含 '?' 标记的未确认协议）。"""
    return any(t.rstrip("?") == protocol for t in provider_protocols(provider))


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
        if not p.get("models"):
            rows.append({
                "provider": pid, "name": p.get("name", pid), "cn": p.get("cn", ""),
                "model": "(无内置模型)", "price": "—",
                "context": "-", "protocols": "/".join(provider_protocols(p)),
                "desc": "用 -m 指定模型名,或用 llmbench refresh 导入网关 /models",
            })
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
    minimums = [10, 16, 22, 6, 12, 20]
    maximums = [20, 40, 30, 10, 26, 52]
    cells = [[r["provider"], r["model"], r["price"], r["context"], r["protocols"], r["desc"]]
             for r in rows]
    widths = column_widths(cells, header, minimums, maximums)
    lines.append("  ".join(pad(h, w) for h, w in zip(header, widths)))
    lines.append("  ".join("-" * w for w in widths))
    for row in cells:
        lines.append("  ".join(pad(c, w) for c, w in zip(row, widths)))
    lines.append("")
    lines.append("协议说明：chat=OpenAI Chat 兼容 / anthropic=Anthropic 兼容 / responses=Responses 兼容（? 表示未官方确认）。")
    lines.append("价格更新于 %s，仅作参考，以官方定价页为准。" % data.get("price_updated", "未知"))
    months = staleness_months(data.get("price_updated", ""))
    if months is not None and months > 3:
        lines.append("⚠️ 价格数据已 %d 个月未更新，请 PR 更新 %s。" % (months, DATA_FILE))
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
    # Responses 的基址可能与对话补全不同（智谱：/api/v1 vs /api/paas/v4）
    base = (base_override or provider_base_url(provider, "responses") or "").rstrip("/")
    url = base + "/responses"
    body = {"model": model, "input": "请只回复 ok", "max_output_tokens": 16}
    headers = {"Content-Type": "application/json"}
    if key:
        headers["Authorization"] = "Bearer " + key
    status, ms, raw = http_request(url, "POST", headers, body)
    return status, ms, raw


def _test_anthropic(provider: dict, model: str, key: str, base_override: str | None):
    base = (base_override or provider_base_url(provider, "anthropic") or "").rstrip("/")
    url = base + "/v1/messages"
    body = {"model": model, "max_tokens": 16,
            "messages": [{"role": "user", "content": "请只回复 ok"}]}
    headers = {"Content-Type": "application/json", "anthropic-version": "2023-06-01"}
    if key:
        headers["x-api-key"] = key
    status, ms, raw = http_request(url, "POST", headers, body)
    return status, ms, raw


def cmd_test(args) -> CommandOutput:
    data = load_providers()
    provider = require_provider(data, args.provider)
    model = pick_model(provider, args.model)
    key = resolve_key(args, provider)
    lines = ["测试供应商 %s 模型 %s（协议 %s）..." % (provider["name"], model, args.protocol)]
    if not key:
        lines.append("提示：未提供 API Key（--key 或环境变量 %s），结果可能是 401。" % provider.get("env_key"))

    if args.protocol == "chat":
        status, ms, raw = _test_chat(provider, model, key, args.base_url)
    elif args.protocol == "responses":
        status, ms, raw = _test_responses(provider, model, key, args.base_url)
    else:
        status, ms, raw = _test_anthropic(provider, model, key, args.base_url)

    http_ok = bool(status) and status < 400
    lines.append("HTTP %s  耗时 %sms" % (status if status else "失败", ms))
    try:
        parsed = json.loads(raw)
    except (ValueError, TypeError):
        parsed = None
    if not isinstance(parsed, dict):
        parsed = None
    # 部分网关用 200 返回错误体（body 里带 error 字段），同样算失败
    has_body_error = parsed is not None and "error" in parsed \
        and parsed["error"] not in (None, {}, False, "")
    if not http_ok:
        reason = "HTTP %s" % status if status else "网络不可达"
    elif parsed is None:
        reason = "响应不是合法 JSON"
    elif has_body_error:
        reason = "接口返回错误"
    else:
        reason = ""
    ok = not reason

    if ok:
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
        err = parsed.get("error") if parsed else None
        if isinstance(err, dict):
            lines.append("错误信息：%s" % str(err.get("message", err))[:300])
        else:
            lines.append("原始响应：%s" % (raw or "")[:300])
        lines.append("")
        lines.append("结论：连通性测试失败（%s）。" % reason)
    return CommandOutput("\n".join(lines), 0 if ok else 1)


# --------------------------------------------------------------------------
# 命令：gen
# --------------------------------------------------------------------------

def gen_codex_block(provider_id: str, provider: dict, wire_api: str) -> str:
    # Codex 的 base_url 取决于 wire_api：responses 与 chat 的基址可能不同
    # （智谱的 chat 是 /api/paas/v4，responses 是 /api/v1）。
    base = provider_base_url(provider, wire_api) or provider["base_url"]
    block = [
        "[model_providers.%s]" % provider_id,
        'name = "%s"' % provider["name"],
        'base_url = "%s"' % base,
        'env_key = "%s"' % provider["env_key"],
        'wire_api = "%s"' % wire_api,
    ]
    return "\n".join(block) + "\n"


def apply_codex_update(text: str, provider_id: str, block: str) -> str:
    """在 config.toml 文本中新增或替换 [model_providers.<id>] 小节。

    匹配时容忍引号与空白：Codex 可能写成 [model_providers."qwen"] 或
    [model_providers.qwen ]，用精确字符串比较会漏判并追加出重复小节。
    """
    pattern = re.compile(r'^\s*\[\s*model_providers\.(?:"%s"|\'%s\'|%s)\s*\]\s*$'
                         % (re.escape(provider_id), re.escape(provider_id), re.escape(provider_id)))
    lines = text.splitlines()
    start = next((i for i, line in enumerate(lines) if pattern.match(line)), None)
    if start is not None:
        end = len(lines)
        for j in range(start + 1, len(lines)):
            if lines[j].strip().startswith("["):
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
            raise AicnError("现有 settings.json 不是合法 JSON（%s），请先手工修复后重试。" % err) from err
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


def write_with_backup(path: Path, content: str) -> str:
    """写入文件（先备份原文件），返回一条人类可读的状态消息。

    不直接 print —— Web 面板在多线程下调用本函数，直接 print 会与其它请求的
    输出交错（stdout 是进程级全局资源）。消息由调用方决定如何呈现。

    写入失败（目录无写权限、磁盘满、路径被占用）时抛 AicnError 而不是裸的
    OSError —— 否则 CLI 会打印一整屏 traceback，Web 面板也只能显示
    "PermissionError: ..." 这种没有上下文的文本。
    """
    message = ""
    try:
        if path.exists():
            backup = path.with_name(path.name + ".aicn.bak")
            backup.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
            message = "[备份] 原文件已备份到 %s" % backup
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    except OSError as err:
        raise AicnError("写入 %s 失败：%s\n请检查该目录的写权限。" % (path, err),
                        code=1) from err
    return message


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
    provider = dict(require_provider(data, args.provider))
    # 用户显式传入的 --base-url 覆盖所有协议的默认基址 —— 否则指向自建网关时
    # 供应商自己的端点（如智谱的 /api/v1）会盖过用户的选择。
    override = getattr(args, "base_url", None)
    if override:
        provider["base_url"] = override
        provider["anthropic_base_url"] = override
        provider["responses_base_url"] = override
    model = pick_model(provider, args.model)
    # Claude Code 写入配置时需要密钥；其余工具只用指引，不需要。
    # 注意：gen 只接受显式传入的密钥（--key / --key-stdin），不读环境变量 ——
    # 否则会把用户环境里的密钥悄悄写进 settings.json。
    if getattr(args, "tool", "") == "claude-code":
        key = read_key_from_stdin() if getattr(args, "key_stdin", False) \
            else getattr(args, "key", None)
    else:
        key = getattr(args, "key", None)
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
        if wire_api == "responses" and not provider_supports(provider, "responses"):
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
            note = write_with_backup(path, apply_codex_update(existing, args.provider, block))
            if note:
                lines.insert(0, note)
            lines.append("")
            lines.append("已写入 %s" % path)

    elif args.tool == "claude-code":
        # 优先级：用户显式 --base-url > 供应商的 anthropic 端点 > 声明支持 anthropic 协议的 base_url
        # （Anthropic 官方本身就是 Anthropic 协议，可直接接 Claude Code；
        #   但豆包等只讲 OpenAI chat 的供应商不能回落到 base_url）
        base = provider_base_url(provider, "anthropic")
        if not base and "anthropic" in provider_protocols(provider):
            base = provider.get("base_url")
        if not base:
            lines.append("%s 未收录 Anthropic 兼容端点，Claude Code 需要 Anthropic 协议。" % provider["name"])
            lines.append("可用替代方案：")
            lines.append("  - 换用带 anthropic 端点的供应商：deepseek / moonshot / zhipu(编码套餐) / qwen(百炼) / siliconflow / openrouter / anthropic")
            lines.append("  - 本机架设 claude-code-router 或 9router 做协议转换")
            lines.append("  - 或用 --base-url 指向自建的协议转换网关")
            return "\n".join(lines)
        path = claude_config_path()
        # 预览与真正写入使用同一份输入（合并现有文件），保证 dry-run 结果与实际一致
        existing = path.read_text(encoding="utf-8") if path.exists() else None
        content = build_claude_settings(existing, base, model, key)
        lines.append("将写入/更新 %s：" % path)
        lines.append("")
        lines.append(content.rstrip())
        lines.append("")
        lines.append("注意：模型名需与供应商端点接受的名称一致；新版 Claude Code 对模型名有校验，"
                     "如启动报错请对照供应商官方文档。")
        if args.write:
            note = write_with_backup(path, content)
            if note:
                lines.insert(0, note)
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
# 命令：sync
# --------------------------------------------------------------------------

def sync_models(provider_id: str, base_url: str | None = None, key: str | None = None,
                target: Path | None = None) -> dict:
    """从供应商 /models 拉取模型列表，合并后写入用户级数据文件。

    返回 {"ok", "url", "count", "added", "removed", "path", "error"}。
    写入的是用户级文件（默认 ~/.aicn/providers.json），不会改动包内或仓库里的数据文件。
    """
    data = load_providers()
    provider = data["providers"].get(provider_id)
    if not provider:
        return {"ok": False, "error": "未知供应商 %s（可用：%s）"
                                     % (provider_id, ", ".join(sorted(data["providers"])))}
    base = (base_url or provider.get("base_url") or "").rstrip("/")
    if not base:
        return {"ok": False, "error": "该供应商没有默认 base_url，请用 --base-url 指定"}
    url = base + "/models"
    headers = {"Authorization": "Bearer " + key} if key else {}
    status, ms, raw = http_request(url, "GET", headers, None, timeout=15)
    if status != 200:
        return {"ok": False, "error": "HTTP %s（%dms）：%s" % (status, ms, (raw or "")[:200])}
    try:
        ids = [str(m["id"]) for m in json.loads(raw).get("data", []) if m.get("id")]
    except Exception as exc:
        return {"ok": False, "error": "解析 /models 响应失败：%s" % exc}
    if not ids:
        return {"ok": False, "error": "端点未返回任何模型：%s" % url}

    old = {m["id"]: m for m in provider.get("models", [])}
    models = [old.get(mid) or {"id": mid, "input": None, "output": None,
                               "cache_hit_input": None, "context": None,
                               "desc": "从 /models 同步（价格待补充）"}
              for mid in ids]

    path = Path(target) if target else USER_DATA_FILE
    overlay = load_user_overlay()
    overlay.setdefault("providers", {}).setdefault(provider_id, {})["models"] = models
    note = write_with_backup(path, json.dumps(overlay, ensure_ascii=False, indent=2) + "\n")
    return {"ok": True, "url": url, "count": len(models), "path": str(path),
            "note": note,
            "added": [i for i in ids if i not in old],
            "removed": [i for i in old if i not in ids]}


def cmd_sync(args) -> CommandOutput:
    data = load_providers()
    provider = require_provider(data, args.provider)
    key = read_key(provider, getattr(args, "key", None))
    if not key:
        key = resolve_key(args, provider) if getattr(args, "key_stdin", False) else None
    try:
        res = sync_models(args.provider, getattr(args, "base_url", None), key,
                          Path(getattr(args, "data_file", None))
                          if getattr(args, "data_file", None) else None)
    except AicnError as err:
        # 写入失败（无权限等）时补一句可操作的提示
        raise AicnError("%s\n可用 --data-file 指定其它可写路径。" % err, code=err.code) from err
    if not res["ok"]:
        raise AicnError(res["error"], code=1)
    lines = ["已从 %s 同步 %d 个模型。" % (res["url"], res["count"])]
    if res.get("note"):
        lines.append(res["note"])
    lines.append("写入 %s" % res["path"])
    lines.append("新增：%s" % (", ".join(res["added"]) if res["added"] else "(无)"))
    lines.append("移除：%s" % (", ".join(res["removed"]) if res["removed"] else "(无)"))
    return CommandOutput("\n".join(lines))


# --------------------------------------------------------------------------
# 命令：doctor
# --------------------------------------------------------------------------

def probe_endpoint(pid: str, provider: dict) -> tuple:
    """探测供应商端点，返回 (pid, 标签, 耗时ms, 等级)。

    等级：ok=可用 / auth=需要密钥 / unsupported=端点不支持 / down=不可达或服务异常。
    Anthropic 官方等原生协议端点没有 /models，返回 404 属于正常，不算故障。
    """
    key = os.environ.get(provider.get("env_key") or "")
    url = provider["base_url"].rstrip("/") + "/models"
    headers = {"User-Agent": "aicn-doctor"}
    if key:
        headers["Authorization"] = "Bearer " + key
    status, ms, _ = http_request(url, "GET", headers, timeout=6)
    if status is None:
        return pid, "不可达", ms, "down"
    if status >= 500:
        return pid, "服务异常(%s)" % status, ms, "down"
    if status in (401, 403):
        return pid, "需密钥(%s)" % status, ms, "auth"
    if status == 404:
        return pid, "端点无 /models(%s)" % status, ms, "unsupported"
    if status >= 400:
        return pid, "异常(%s)" % status, ms, "unsupported"
    return pid, "可达(%s)" % status, ms, "ok"


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
            pid, label, ms, level = fut.result()
            results[pid] = (label, ms, level)
    marks = {"ok": "OK ", "auth": "!! ", "unsupported": "-- ", "down": "!! "}
    for pid in sorted(results):
        label, ms, level = results[pid]
        lines.append("%s %-14s %-20s %sms" % (marks.get(level, "?? "), pid, label, ms))
    lines.append("图例：OK=可用  !!=需处理(缺密钥/不可达)  --=端点不提供 /models（如 Anthropic 官方），属正常")

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
    p_test.add_argument("--key", "-k",
                        help="API Key（缺省读环境变量；命令行传参会进入 shell 历史，"
                             "推荐用环境变量或 --key-stdin）")
    p_test.add_argument("--key-stdin", action="store_true",
                        help="从标准输入读取 API Key（不进入 shell 历史，推荐）")
    p_test.add_argument("--protocol", choices=["chat", "responses", "anthropic"], default="chat",
                        help="协议（默认 chat）")
    p_test.add_argument("--base-url", help="覆盖 base URL（如指向本地网关）")

    p_gen = sub.add_parser("gen", help="生成工具接入配置")
    p_gen.add_argument("--tool", "-t", required=True,
                       choices=["codex", "claude-code", "cursor", "cline"])
    p_gen.add_argument("--provider", "-p", required=True)
    p_gen.add_argument("--model", "-m")
    p_gen.add_argument("--key", "-k",
                       help="API Key（仅 claude-code 会写入配置；命令行传参会进入 shell 历史，"
                            "推荐用环境变量或 --key-stdin）")
    p_gen.add_argument("--key-stdin", action="store_true",
                       help="从标准输入读取 API Key（不进入 shell 历史，推荐）")
    p_gen.add_argument("--write", action="store_true", help="真正写入配置文件（默认 dry-run）")
    p_gen.add_argument("--wire-api", choices=["responses", "chat"],
                       help="仅 codex：协议（默认 responses；chat 仅旧版）")
    p_gen.add_argument("--base-url", help="覆盖 base URL（如指向本地/自建网关）")

    p_env = sub.add_parser("env", help="查看密钥环境变量设置命令")
    p_env.add_argument("provider_pos", nargs="?", metavar="provider",
                       help="供应商 id（位置参数，等价于 --provider）")
    p_env.add_argument("--provider", "-p", dest="provider_opt", metavar="provider",
                       help="供应商 id（等价于位置参数）")

    p_sync = sub.add_parser("sync", help="从 /models 同步模型列表到用户数据文件")
    p_sync.add_argument("--provider", "-p", required=True, help="供应商 id")
    p_sync.add_argument("--base-url", help="覆盖 base URL（如指向本地网关）")
    p_sync.add_argument("--key", "-k", help="API Key（缺省读环境变量）")
    p_sync.add_argument("--key-stdin", action="store_true", help="从标准输入读取 API Key")
    p_sync.add_argument("--data-file", help="指定写入文件（默认 ~/.aicn/providers.json）")

    sub.add_parser("doctor", help="环境体检：网络/配置/密钥")
    p_web = sub.add_parser("web", help="启动本地 Web 面板（浏览器操作）")
    p_web.add_argument("--host", default="127.0.0.1",
                       help="监听地址（默认 127.0.0.1；改成 0.0.0.0 会把面板暴露到局域网，"
                            "面板无鉴权，请勿在公网使用）")
    p_web.add_argument("--port", type=int, default=8787, help="端口（默认 8787）")
    p_web.add_argument("--no-open", action="store_true", help="启动后不自动打开浏览器")
    return parser


def read_key_from_stdin() -> str | None:
    """从标准输入读取 API Key（避免进入 shell 历史 / 进程列表）。"""
    if sys.stdin is None or sys.stdin.isatty():
        raise AicnError("--key-stdin 需要通过管道提供密钥，例如：echo $KEY | aicn test -k-stdin ...")
    data = sys.stdin.read().strip()
    return data or None


def resolve_key(args, provider: dict) -> str | None:
    """按优先级解析密钥：--key > --key-stdin > 环境变量。"""
    if getattr(args, "key_stdin", False):
        return read_key_from_stdin()
    return read_key(provider, getattr(args, "key", None))


def main(argv: list | None = None) -> int:
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as err:
        # argparse 的错误处理会直接抛 SystemExit（如缺少必填参数）。
        # 这里转成返回码，保证 main() 的契约是「永远返回 int」——
        # 库调用方（Web 面板 / CI 脚本）不必再包一层 try/except。
        # --help / --version 本身也走这条路径，它们返回 0。
        code = err.code if isinstance(err.code, int) else 2
        return 0 if code == 0 else code
    if not args.command:
        parser.print_help()
        return 0
    try:
        if args.command == "env":
            # 位置参数与 --provider 等价，两者都给出时以 --provider 为准
            args.provider = getattr(args, "provider_opt", None) or args.provider_pos
            if not args.provider:
                # 用返回退出码代替 parser.error()（后者抛 SystemExit），
                # 保证 main() 的契约是「永远返回 int」。
                parser.print_usage(sys.stderr)
                sys.stderr.write("aicn: error: env 需要指定供应商："
                                 "aicn env <provider> 或 aicn env -p <provider>\n")
                return 2
        exit_code = 0
        if args.command == "list":
            print(cmd_list(args))
        elif args.command == "test":
            out = cmd_test(args)
            print(out)
            exit_code = getattr(out, "exit_code", 0)
        elif args.command == "gen":
            print(cmd_gen(args))
        elif args.command == "env":
            print(cmd_env(args))
        elif args.command == "sync":
            print(cmd_sync(args))
        elif args.command == "doctor":
            print(cmd_doctor(args))
        elif args.command == "web":
            from . import webui
            return webui.cmd_web(args)
        return exit_code
    except AicnError as err:
        sys.stderr.write("错误：%s\n" % err)
        return err.code
    except KeyboardInterrupt:
        print("\n已取消")
        return 130


if __name__ == "__main__":
    sys.exit(main())


