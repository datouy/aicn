# -*- coding: utf-8 -*-
"""数据新鲜度检查。

两个维度：
  1. 价格：price_updated 超过 3 个月未更新 -> 开 Issue 提醒；
  2. 模型名：内置模型名与供应商 /models 实际返回的名单出现明显偏差
     （尤其是官方已下线的型号）-> 开 Issue 提醒。

模型名这一项才是主要腐化点：价格偶尔过期影响有限，型号一旦下线，
用户按 aicn 的推荐去接入就会直接 404。

需要密钥的供应商（/models 返回 401）跳过检查 —— 没有密钥比对不了。
"""
import datetime
import json
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_FILE = ROOT / "aicn" / "data" / "providers.json"

#: 只在这些供应商上比对模型名（其余 /models 需鉴权或无公开端点）。
CHECKABLE = ("openrouter",)

#: 命中多少比例的「已下线」模型才算真的过时，避免个别改名造成误报。
STALE_RATIO = 0.5


def open_issue(title: str, body: str) -> bool:
    """开 Issue；已有同类 Issue 则跳过。返回是否新开。"""
    try:
        listed = subprocess.run(
            ["gh", "issue", "list", "--state", "open", "--search", title,
             "--json", "number"],
            capture_output=True, text=True, timeout=60)
        if listed.returncode == 0 and json.loads(listed.stdout):
            print("已有同类 Issue，跳过：%s" % title)
            return False
    except Exception:
        pass
    try:
        proc = subprocess.run(
            ["gh", "issue", "create", "--title", title, "--body", body],
            capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError) as err:
        # 本地没装 gh / gh 未登录时不该让整个检查崩溃 —— 打印提示后继续。
        print("无法创建 Issue（%s）：%s" % (type(err).__name__, err))
        print("请手动检查：%s" % title)
        return False
    print(proc.stdout or proc.stderr)
    return proc.returncode == 0


def fetch_models(base_url: str, timeout: int = 15):
    """拉取 /models；返回 (模型名集合, 错误信息)。"""
    url = base_url.rstrip("/") + "/models"
    req = urllib.request.Request(url, headers={"User-Agent": "aicn-freshness"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status != 200:
                return None, "HTTP %s" % resp.status
            payload = json.loads(resp.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as err:
        return None, "HTTP %s" % err.code
    except Exception as err:
        return None, "%s: %s" % (type(err).__name__, err)
    ids = set()
    for m in payload.get("data") or []:
        if isinstance(m, dict) and m.get("id"):
            ids.add(str(m["id"]))
    return ids, None


def check_prices(data: dict) -> bool:
    """检查 price_updated 是否过期。返回是否需要开 Issue。"""
    updated = data.get("price_updated", "")
    try:
        year, month = (int(x) for x in updated.split("-")[:2])
        now = datetime.date.today()
        months = (now.year - year) * 12 + (now.month - month)
    except Exception:
        print("无法解析 price_updated，跳过价格检查。")
        return False
    if months <= 3:
        print("价格数据新鲜（%s，距今 %d 个月）。" % (updated, months))
        return False
    title = "提醒:模型价格数据超过 3 个月未更新"
    body = (
        "数据文件 `aicn/data/providers.json` 的 `price_updated` 为 `%s`，"
        "距今超过 3 个月。\n\n请检查各家官方定价页并更新价格。\n\n"
        "> 本 Issue 由 data-freshness 工作流自动创建。" % updated
    )
    return open_issue(title, body)


def check_model_names(data: dict) -> bool:
    """比对内置模型名与端点实际名单，找出可能已下线的型号。"""
    providers = data.get("providers") or {}
    stale_found = False
    for pid in CHECKABLE:
        provider = providers.get(pid)
        if not provider:
            continue
        base_url = provider.get("base_url")
        if not base_url:
            continue
        live, err = fetch_models(base_url)
        if live is None:
            print("跳过 %s：无法拉取 /models（%s）" % (pid, err))
            continue
        declared = [str(m.get("id")) for m in provider.get("models") or []
                    if m.get("id")]
        if not declared:
            continue
        missing = [m for m in declared if m not in live]
        if not missing:
            print("%s：%d 个内置模型名均仍在端点名单中。" % (pid, len(declared)))
            continue
        ratio = len(missing) / len(declared)
        if ratio < STALE_RATIO:
            print("%s：%d/%d 个模型名未出现在端点名单（占比 %.0f%%，低于阈值，暂不告警）。"
                  % (pid, len(missing), len(declared), ratio * 100))
            continue
        stale_found = True
        title = "提醒:%s 的内置模型名可能已过时" % pid
        body = (
            "供应商 `%s` 的 `/models` 端点当前已不返回以下内置模型：\n\n%s\n\n"
            "这些型号很可能已下线或改名，请对照官方文档更新 "
            "`aicn/data/providers.json` 中 `%s` 的模型列表。\n\n"
            "> 本 Issue 由 data-freshness 工作流自动创建。"
            % (pid, "\n".join("- `%s`" % m for m in missing), pid)
        )
        open_issue(title, body)
    return stale_found


def main() -> int:
    data = json.loads(DATA_FILE.read_text(encoding="utf-8"))
    price_stale = check_prices(data)
    model_stale = check_model_names(data)
    if not price_stale and not model_stale:
        print("数据新鲜度检查通过。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
