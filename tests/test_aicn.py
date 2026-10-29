# -*- coding: utf-8 -*-
"""aicn 单元测试：python -m unittest discover -s tests -v"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import aicn  # noqa: E402


class TestProvidersData(unittest.TestCase):
    def setUp(self):
        self.data = aicn.load_providers()

    def test_required_fields(self):
        for pid, p in self.data["providers"].items():
            for field in ("name", "site", "base_url", "env_key", "models"):
                self.assertIn(field, p, "provider %s 缺少字段 %s" % (pid, field))
            self.assertIn(p.get("currency", "CNY"), ("CNY", "USD"))
            if pid != "gateway":
                self.assertTrue(p["models"], "provider %s 没有模型" % pid)

    def test_model_ids_unique(self):
        for pid, p in self.data["providers"].items():
            ids = [m["id"] for m in p["models"]]
            self.assertEqual(len(ids), len(set(ids)), "provider %s 模型 id 重复" % pid)

    def test_reserved_codex_ids_not_used(self):
        # Codex 内置 id 不可覆盖：openai / ollama / lmstudio
        self.assertNotIn("openai", set(self.data["providers"]) - {"openai"})
        self.assertNotIn("ollama", self.data["providers"])
        self.assertNotIn("lmstudio", self.data["providers"])


class TestCodexConfig(unittest.TestCase):
    def test_new_file(self):
        block = aicn.gen_codex_block("deepseek", {
            "name": "DeepSeek", "base_url": "https://api.deepseek.com",
            "env_key": "DEEPSEEK_API_KEY",
        }, "responses")
        out = aicn.apply_codex_update("", "deepseek", block)
        self.assertIn("[model_providers.deepseek]", out)
        self.assertIn('wire_api = "responses"', out)

    def test_append_preserves_existing(self):
        existing = '[model_provider]\nmodel = "gpt-5"\n\n[approval_policy]\nenabled = true\n'
        block = aicn.gen_codex_block("qwen", {
            "name": "Alibaba Cloud", "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
            "env_key": "DASHSCOPE_API_KEY",
        }, "responses")
        out = aicn.apply_codex_update(existing, "qwen", block)
        self.assertIn("[approval_policy]", out)
        self.assertIn("[model_providers.qwen]", out)
        self.assertIn('model = "gpt-5"', out)

    def test_replace_existing_section(self):
        existing = '[model_providers.qwen]\nname = "old"\nbase_url = "x"\n\n[other]\nx = 1\n'
        block = aicn.gen_codex_block("qwen", {
            "name": "Alibaba Cloud", "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
            "env_key": "DASHSCOPE_API_KEY",
        }, "responses")
        out = aicn.apply_codex_update(existing, "qwen", block)
        self.assertNotIn('name = "old"', out)
        self.assertIn('[other]', out)
        self.assertEqual(out.count("[model_providers.qwen]"), 1)

    def test_section_at_end_of_file(self):
        existing = "[model_providers.qwen]\nname = \"old\"\n"
        block = aicn.gen_codex_block("qwen", {
            "name": "Alibaba Cloud", "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
            "env_key": "DASHSCOPE_API_KEY",
        }, "responses")
        out = aicn.apply_codex_update(existing, "qwen", block)
        self.assertNotIn('name = "old"', out)
        self.assertEqual(out.count("[model_providers.qwen]"), 1)


class TestClaudeSettings(unittest.TestCase):
    def test_fresh(self):
        out = aicn.build_claude_settings(None, "https://api.moonshot.cn/anthropic",
                                         "kimi-latest", "sk-test")
        data = json.loads(out)
        self.assertEqual(data["env"]["ANTHROPIC_BASE_URL"], "https://api.moonshot.cn/anthropic")
        self.assertEqual(data["env"]["ANTHROPIC_AUTH_TOKEN"], "sk-test")
        self.assertEqual(data["env"]["ANTHROPIC_MODEL"], "kimi-latest")

    def test_merge_preserves_other_keys(self):
        existing = json.dumps({"permissions": {"allow": ["Read"]}, "env": {"X": "1"}},
                              ensure_ascii=False)
        out = aicn.build_claude_settings(existing, "https://x", "m", "k")
        data = json.loads(out)
        self.assertEqual(data["permissions"], {"allow": ["Read"]})
        self.assertEqual(data["env"]["X"], "1")
        self.assertEqual(data["env"]["ANTHROPIC_AUTH_TOKEN"], "k")

    def test_no_key_placeholder(self):
        out = aicn.build_claude_settings(None, "https://x", "m", None)
        self.assertIn("请替换为你的 API Key", out)


class TestHelpers(unittest.TestCase):
    def test_guide_base_url(self):
        self.assertEqual(aicn.guide_base_url({"base_url": "https://api.deepseek.com"}),
                         "https://api.deepseek.com/v1")
        self.assertEqual(aicn.guide_base_url({"base_url": "https://api.moonshot.cn/v1"}),
                         "https://api.moonshot.cn/v1")
        self.assertEqual(aicn.guide_base_url({"base_url": "https://open.bigmodel.cn/api/paas/v4"}),
                         "https://open.bigmodel.cn/api/paas/v4")

    def test_protocols(self):
        self.assertEqual(aicn.provider_protocols({"base_url": "x", "anthropic_base_url": None,
                                                  "responses_api": True}),
                         ["chat", "responses"])
        self.assertEqual(aicn.provider_protocols({"base_url": "x", "anthropic_base_url": "y",
                                                  "responses_api": None}),
                         ["chat", "anthropic", "responses?"])


class TestWriteWithBackup(unittest.TestCase):
    def test_backup_created(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.toml"
            path.write_text("old", encoding="utf-8")
            aicn.write_with_backup(path, "new")
            self.assertEqual(path.read_text(encoding="utf-8"), "new")
            backup = Path(tmp) / "config.toml.aicn.bak"
            self.assertTrue(backup.exists())
            self.assertEqual(backup.read_text(encoding="utf-8"), "old")


class TestCommands(unittest.TestCase):
    def test_list_json(self):
        out = aicn.cmd_list(argparse_namespace(provider=None, json=True))
        data = json.loads(out)
        self.assertIn("rows", data)
        self.assertTrue(any(r["provider"] == "deepseek" for r in data["rows"]))

    def test_list_filter(self):
        out = aicn.cmd_list(argparse_namespace(provider="deepseek", json=False))
        self.assertIn("deepseek-flash", out)

    def test_gen_claude_without_anthropic_endpoint(self):
        out = aicn.cmd_gen(argparse_namespace(
            tool="claude-code", provider="doubao", model=None, key=None,
            write=False, wire_api=None))
        self.assertIn("未收录 Anthropic 兼容端点", out)

    def test_gen_codex_dry_run(self):
        out = aicn.cmd_gen(argparse_namespace(
            tool="codex", provider="qwen", model="qwen-plus", key=None,
            write=False, wire_api=None))
        self.assertIn("[model_providers.qwen]", out)
        self.assertIn('wire_api = "responses"', out)
        self.assertIn("dry-run", out)

    def test_env(self):
        out = aicn.cmd_env(argparse_namespace(provider="deepseek"))
        self.assertIn("DEEPSEEK_API_KEY", out)


def argparse_namespace(**kwargs):
    return type("NS", (), kwargs)()


if __name__ == "__main__":
    unittest.main()



class TestWeb(unittest.TestCase):
    """web 面板基础可用性:页面与 /api/providers。"""

    def test_parser_has_web(self):
        from aicn import cli
        ns = cli.build_parser().parse_args(["web", "--port", "0", "--no-open"])
        self.assertEqual(ns.command, "web")
        self.assertEqual(ns.port, 0)

    def test_page_and_providers_api(self):
        import threading
        import urllib.request

        from aicn import webui
        webui.Handler.port = 0
        srv = webui.ThreadingHTTPServer(("127.0.0.1", 0), webui.Handler)
        port = srv.server_address[1]
        th = threading.Thread(target=srv.serve_forever, daemon=True)
        th.start()
        try:
            with urllib.request.urlopen("http://127.0.0.1:%d/" % port, timeout=5) as r:
                self.assertEqual(r.status, 200)
                self.assertIn("aicn", r.read().decode("utf-8"))
            with urllib.request.urlopen("http://127.0.0.1:%d/api/providers" % port, timeout=5) as r:
                data = json.loads(r.read().decode("utf-8"))
                self.assertTrue(data["ok"])
                self.assertIn("deepseek", data["providers"])
        finally:
            srv.shutdown()
            srv.server_close()


class TestCategoryData(unittest.TestCase):
    def test_category_field(self):
        data = aicn.load_providers()
        for pid, p in data["providers"].items():
            self.assertIn("category", p, "provider %s 缺少 category" % pid)


class TestWebSync(unittest.TestCase):
    """web 面板 /api/sync:临时数据文件 + mock /models 端点。"""

    def test_api_sync_merges_models(self):
        import http.server
        import threading

        from aicn import webui

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                body = json.dumps({"data": [{"id": "mock-model"}]}).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            with tempfile.TemporaryDirectory() as td:
                df = Path(td) / "providers.json"
                df.write_text(json.dumps(aicn.load_providers(), ensure_ascii=False),
                              encoding="utf-8")
                res = webui.api_sync(
                    {"provider": "deepseek", "key": "k",
                     "base_url": "http://127.0.0.1:%d/v1" % srv.server_address[1]},
                    data_file=df)
                self.assertTrue(res["ok"], res)
                self.assertEqual(res["added"], ["mock-model"])
                merged = json.loads(df.read_text(encoding="utf-8"))
                self.assertEqual([m["id"] for m in merged["providers"]["deepseek"]["models"]],
                                 ["mock-model"])
        finally:
            srv.shutdown()
            srv.server_close()

    def test_api_sync_unknown_provider(self):
        from aicn import webui
        res = webui.api_sync({"provider": "no-such-provider"})
        self.assertFalse(res["ok"])

    def test_api_sync_write_failure_is_reported_not_raised(self):
        """写失败时面板应返回 ok=False + 可读错误，而不是抛异常 / 500。"""
        import http.server
        import threading

        from aicn import webui

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                body = json.dumps({"data": [{"id": "mock-model"}]}).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        original = Path.write_text

        def boom(self, *a, **k):
            raise PermissionError(13, "Permission denied", str(self))

        Path.write_text = boom
        try:
            with tempfile.TemporaryDirectory() as td:
                df = Path(td) / "providers.json"
                res = webui.api_sync(
                    {"provider": "gateway", "key": "k",
                     "base_url": "http://127.0.0.1:%d/v1" % srv.server_address[1]},
                    data_file=df)
        finally:
            Path.write_text = original
            srv.shutdown()
            srv.server_close()
        self.assertFalse(res["ok"], res)
        self.assertIn("写入", res["error"])


class TestProtocolData(unittest.TestCase):
    """协议标注必须显式正确：Anthropic 官方不是 chat，且不再有过时的 responses?。"""

    def setUp(self):
        self.data = aicn.load_providers()

    def test_anthropic_official_is_not_chat(self):
        tags = aicn.provider_protocols(self.data["providers"]["anthropic"])
        self.assertIn("anthropic", tags)
        self.assertNotIn("chat", tags)

    def test_declared_protocols_used(self):
        for pid, p in self.data["providers"].items():
            self.assertIn("protocols", p, "provider %s 缺少 protocols 字段" % pid)
            for proto in p["protocols"]:
                self.assertIn(proto, ("chat", "responses", "anthropic"),
                              "provider %s 非法协议 %s" % (pid, proto))

    def test_no_stale_unconfirmed_protocols(self):
        """各家协议已由官方文档确认，不应再挂着未确认的 responses? 标记。"""
        for pid, p in self.data["providers"].items():
            self.assertNotIn("unconfirmed_protocols", p,
                             "provider %s 仍有过时的 unconfirmed_protocols" % pid)
            for tag in aicn.provider_protocols(p):
                self.assertNotIn("?", tag,
                                 "provider %s 的协议 %s 仍标记为未确认" % (pid, tag))

    def test_deepseek_supports_all_three(self):
        """DeepSeek 官方同时提供 chat / responses / anthropic 三种协议。"""
        tags = aicn.provider_protocols(self.data["providers"]["deepseek"])
        for proto in ("chat", "responses", "anthropic"):
            self.assertIn(proto, tags)

    def test_moonshot_supports_responses(self):
        """Moonshot 官方文档有 /v1/responses 端点。"""
        tags = aicn.provider_protocols(self.data["providers"]["moonshot"])
        self.assertIn("responses", tags)
        self.assertIn("anthropic", tags)

    def test_siliconflow_has_no_responses(self):
        """SiliconFlow 没有 /responses 端点（只有 chat 与 anthropic）。"""
        tags = aicn.provider_protocols(self.data["providers"]["siliconflow"])
        self.assertIn("chat", tags)
        self.assertIn("anthropic", tags)
        self.assertNotIn("responses", tags)
        self.assertNotIn("responses?", tags)

    def test_qwen_supports_responses(self):
        tags = aicn.provider_protocols(self.data["providers"]["qwen"])
        self.assertIn("responses", tags)
        self.assertNotIn("responses?", tags)

    def test_responses_api_field_consistent_with_protocols(self):
        """responses_api 与 protocols 不能互相矛盾。"""
        for pid, p in self.data["providers"].items():
            tags = aicn.provider_protocols(p)
            if p.get("responses_api") is True:
                self.assertIn("responses", tags,
                              "provider %s 声明 responses_api 但 protocols 里没有" % pid)
            if p.get("responses_api") is False:
                self.assertNotIn("responses", tags,
                                 "provider %s 声明不支持 responses 但 protocols 里有" % pid)


class TestProviderBaseUrl(unittest.TestCase):
    """不同协议的基址可能不同（智谱：chat=/api/paas/v4，responses=/api/v1）。"""

    def setUp(self):
        self.data = aicn.load_providers()

    def test_zhipu_responses_uses_api_v1(self):
        p = self.data["providers"]["zhipu"]
        self.assertEqual(aicn.provider_base_url(p, "responses"),
                         "https://open.bigmodel.cn/api/v1")
        self.assertEqual(aicn.provider_base_url(p, "chat"),
                         "https://open.bigmodel.cn/api/paas/v4")

    def test_default_falls_back_to_base_url(self):
        p = self.data["providers"]["deepseek"]
        self.assertEqual(aicn.provider_base_url(p, "responses"), p["base_url"])
        self.assertEqual(aicn.provider_base_url(p, "chat"), p["base_url"])

    def test_anthropic_base_url_points_at_v1_messages(self):
        """Claude Code 会往 base_url 后面拼 /v1/messages，基址不能自带 /v1/messages。"""
        for pid, p in self.data["providers"].items():
            base = p.get("anthropic_base_url")
            if not base:
                continue
            self.assertFalse(base.rstrip("/").endswith("/messages"),
                             "provider %s 的 anthropic_base_url 不应包含 /messages" % pid)

    def test_codex_block_uses_responses_base_url(self):
        p = dict(self.data["providers"]["zhipu"])
        p["base_url"] = "https://open.bigmodel.cn/api/paas/v4"
        block = aicn.gen_codex_block("zhipu", p, "responses")
        self.assertIn('base_url = "https://open.bigmodel.cn/api/v1"', block)


class TestExitCodes(unittest.TestCase):
    """失败必须返回非零退出码，CI 才能判断成败。"""

    def test_test_command_exit_code_on_failure(self):
        from aicn import cli
        ns = argparse_namespace(provider="deepseek", model="deepseek-flash",
                                key="bad-key", protocol="chat",
                                base_url="http://127.0.0.1:1/v1")
        out = cli.cmd_test(ns)
        self.assertEqual(out.exit_code, 1)
        self.assertIn("连通性测试失败", out)

    def test_main_returns_nonzero_on_failure(self):
        import contextlib
        import io

        from aicn import cli
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = cli.main(["test", "-p", "deepseek", "-m", "deepseek-flash",
                           "-k", "bad-key", "--base-url", "http://127.0.0.1:1/v1"])
        self.assertEqual(rc, 1)

    def test_main_unknown_provider_is_nonzero(self):
        import contextlib
        import io

        from aicn import cli
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(io.StringIO()):
            rc = cli.main(["env", "no-such-provider"])
        self.assertEqual(rc, 2)

    def test_main_always_returns_int_for_missing_env_provider(self):
        """env 缺供应商时 main() 必须返回 int，而不是抛 SystemExit。"""
        import contextlib
        import io

        from aicn import cli
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(io.StringIO()):
            rc = cli.main(["env"])
        self.assertIsInstance(rc, int)
        self.assertNotEqual(rc, 0)

    def test_http_200_with_error_body_is_failure(self):
        """部分网关用 200 返回错误体 —— 必须判失败并返回非零退出码。"""
        from aicn import cli
        original = cli.http_request
        cli.http_request = lambda *a, **k: (
            200, 5, json.dumps({"error": {"message": "invalid api key"}}))
        try:
            ns = argparse_namespace(provider="deepseek", model="deepseek-flash",
                                    key="bad-key", protocol="chat", base_url=None)
            out = cli.cmd_test(ns)
        finally:
            cli.http_request = original
        self.assertEqual(out.exit_code, 1)
        self.assertIn("连通性测试失败", out)
        self.assertIn("invalid api key", out)

    def test_http_200_with_non_json_body_is_failure(self):
        """200 但响应体不是 JSON —— 结论与退出码必须一致（都算失败）。"""
        from aicn import cli
        original = cli.http_request
        cli.http_request = lambda *a, **k: (200, 5, "<html>gateway error</html>")
        try:
            ns = argparse_namespace(provider="deepseek", model="deepseek-flash",
                                    key="k", protocol="chat", base_url=None)
            out = cli.cmd_test(ns)
        finally:
            cli.http_request = original
        self.assertEqual(out.exit_code, 1)
        self.assertIn("连通性测试失败", out)

    def test_http_200_success_returns_zero(self):
        from aicn import cli
        original = cli.http_request
        cli.http_request = lambda *a, **k: (
            200, 5, json.dumps({"model": "deepseek-flash",
                                "choices": [{"message": {"content": "ok"}}]}))
        try:
            ns = argparse_namespace(provider="deepseek", model="deepseek-flash",
                                    key="k", protocol="chat", base_url=None)
            out = cli.cmd_test(ns)
        finally:
            cli.http_request = original
        self.assertEqual(out.exit_code, 0)
        self.assertNotIn("连通性测试失败", out)

    def test_http_401_returns_nonzero_exit_code(self):
        """HTTP 401 必须返回非零退出码 —— 否则 CI 里 $? 恒为 0，无法判断成败。"""
        import contextlib
        import io

        from aicn import cli
        original = cli.http_request
        cli.http_request = lambda *a, **k: (
            401, 238, json.dumps({"error": {"message": "invalid api key"}}))
        try:
            ns = argparse_namespace(provider="deepseek", model="deepseek-flash",
                                    key="bad-key", protocol="chat", base_url=None)
            out = cli.cmd_test(ns)
        finally:
            cli.http_request = original
        self.assertEqual(out.exit_code, 1)
        self.assertIn("HTTP 401", out)

        # 经 main() 走一遍，退出码必须透传给 shell
        original = cli.http_request
        cli.http_request = lambda *a, **k: (
            401, 238, json.dumps({"error": {"message": "invalid api key"}}))
        try:
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc = cli.main(["test", "-p", "deepseek", "-m", "deepseek-flash",
                               "-k", "bad-key"])
        finally:
            cli.http_request = original
        self.assertEqual(rc, 1)

    def test_connection_failure_returns_nonzero_exit_code(self):
        """连接失败（网络不可达）同样必须返回非零退出码。"""
        import contextlib
        import io

        from aicn import cli
        original = cli.http_request
        cli.http_request = lambda *a, **k: (None, 12, "connection refused")
        try:
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc = cli.main(["test", "-p", "deepseek", "-m", "deepseek-flash",
                               "-k", "k"])
        finally:
            cli.http_request = original
        self.assertEqual(rc, 1)

    def test_main_returns_int_on_argparse_error(self):
        """argparse 报错（如缺少必填参数）时 main() 必须返回 int，不能抛 SystemExit。"""
        import contextlib
        import io

        from aicn import cli
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(io.StringIO()):
            rc = cli.main(["test"])          # 缺少必填的 --provider
        self.assertIsInstance(rc, int)
        self.assertNotEqual(rc, 0)
    def test_main_returns_int_on_missing_option_value(self):
        """`-p` 后面没跟值时同样必须返回 int（而不是 SystemExit）。"""
        import contextlib
        import io

        from aicn import cli
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(io.StringIO()):
            rc = cli.main(["env", "-p"])
        self.assertIsInstance(rc, int)
        self.assertNotEqual(rc, 0)

    def test_main_help_and_version_return_zero(self):
        """--help / --version 走 argparse 的 SystemExit(0) 路径，应被转成 0。"""
        import contextlib
        import io

        from aicn import cli
        for argv in (["--help"], ["--version"]):
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(io.StringIO()):
                rc = cli.main(argv)
            self.assertEqual(rc, 0, argv)


class TestEnvPositionalArg(unittest.TestCase):
    """README 写的是 `aicn env qwen`（位置参数），必须能用。"""

    def test_env_accepts_positional(self):
        from aicn import cli
        parser = cli.build_parser()
        args = parser.parse_args(["env", "deepseek"])
        self.assertEqual(args.provider_pos, "deepseek")

    def test_env_accepts_flag(self):
        from aicn import cli
        parser = cli.build_parser()
        args = parser.parse_args(["env", "-p", "deepseek"])
        self.assertEqual(args.provider_opt, "deepseek")

    def test_env_positional_end_to_end(self):
        import contextlib
        import io

        from aicn import cli
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = cli.main(["env", "deepseek"])
        self.assertEqual(rc, 0)
        self.assertIn("DEEPSEEK_API_KEY", buf.getvalue())

    def test_env_flag_end_to_end(self):
        import contextlib
        import io

        from aicn import cli
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = cli.main(["env", "-p", "qwen"])
        self.assertEqual(rc, 0)
        self.assertIn("DASHSCOPE_API_KEY", buf.getvalue())

    def test_env_flag_wins_over_positional(self):
        """两者都给出时以 --provider 为准。"""
        import contextlib
        import io

        from aicn import cli
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = cli.main(["env", "deepseek", "-p", "qwen"])
        self.assertEqual(rc, 0)
        self.assertIn("DASHSCOPE_API_KEY", buf.getvalue())
        self.assertNotIn("DEEPSEEK_API_KEY", buf.getvalue())

    def test_env_missing_provider_returns_nonzero(self):
        import contextlib
        import io

        from aicn import cli
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(io.StringIO()):
            rc = cli.main(["env"])
        self.assertNotEqual(rc, 0)

    def test_env_provider_is_not_required(self):
        """README 写的是 `aicn env qwen` —— 位置参数必须可用，--provider 不能是必填。"""
        from aicn import cli
        parser = cli.build_parser()
        # 不带任何 provider 参数时不应触发 argparse 的 required 错误
        args = parser.parse_args(["env"])
        self.assertIsNone(args.provider_opt)
        self.assertIsNone(args.provider_pos)
        # 位置参数形式
        args = parser.parse_args(["env", "qwen"])
        self.assertEqual(args.provider_pos, "qwen")

    def test_readme_examples_all_work(self):
        """README「快速开始」里的 env 命令必须都能跑通。"""
        import contextlib
        import io

        from aicn import cli
        for argv in (["env", "qwen"], ["env", "deepseek"], ["env", "-p", "qwen"]):
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc = cli.main(argv)
            self.assertEqual(rc, 0, argv)
            self.assertIn("API_KEY", buf.getvalue())


class TestClaudeCodeGeneration(unittest.TestCase):
    """Anthropic 官方可接 Claude Code；只讲 chat 的供应商不行。"""

    def test_anthropic_official_generates_config(self):
        out = aicn.cmd_gen(argparse_namespace(
            tool="claude-code", provider="anthropic", model=None, key=None,
            write=False, wire_api=None, base_url=None))
        self.assertIn("api.anthropic.com", out)
        self.assertNotIn("未收录 Anthropic 兼容端点", out)

    def test_chat_only_provider_rejected(self):
        """只讲 chat 的供应商（如豆包）不能接 Claude Code。"""
        out = aicn.cmd_gen(argparse_namespace(
            tool="claude-code", provider="doubao", model=None, key=None,
            write=False, wire_api=None, base_url=None))
        self.assertIn("未收录 Anthropic 兼容端点", out)

    def test_deepseek_can_now_generate_claude_code_config(self):
        """DeepSeek 官方提供 Anthropic 端点，应能生成 Claude Code 配置。"""
        out = aicn.cmd_gen(argparse_namespace(
            tool="claude-code", provider="deepseek", model=None, key=None,
            write=False, wire_api=None, base_url=None))
        self.assertIn("api.deepseek.com/anthropic", out)
        self.assertNotIn("未收录 Anthropic 兼容端点", out)

    def test_explicit_base_url_overrides(self):
        out = aicn.cmd_gen(argparse_namespace(
            tool="claude-code", provider="moonshot", model="kimi-latest", key=None,
            write=False, wire_api=None, base_url="http://127.0.0.1:9999/anthropic"))
        self.assertIn("http://127.0.0.1:9999/anthropic", out)
        self.assertNotIn("api.moonshot.cn", out)

    def test_preview_matches_written_content(self):
        """dry-run 预览必须与真正写入的内容一致（含已存在字段的合并）。"""
        import contextlib
        import io

        from aicn import cli
        with tempfile.TemporaryDirectory() as td:
            cfg = Path(td) / "settings.json"
            cfg.write_text(json.dumps({"permissions": {"allow": ["Read"]}}),
                           encoding="utf-8")
            original = cli.claude_config_path
            cli.claude_config_path = lambda: cfg
            try:
                buf = io.StringIO()
                with contextlib.redirect_stdout(buf):
                    cli.main(["gen", "-t", "claude-code", "-p", "moonshot",
                              "-m", "kimi-latest", "-k", "sk-x", "--write"])
                written = json.loads(cfg.read_text(encoding="utf-8"))
                self.assertIn("permissions", written)
                self.assertEqual(written["env"]["ANTHROPIC_BASE_URL"],
                                 "https://api.moonshot.cn/anthropic")
            finally:
                cli.claude_config_path = original


class TestCodexSectionMatching(unittest.TestCase):
    """Codex 小节匹配要容忍引号与空白，避免写出重复小节。"""

    def _block(self):
        return aicn.gen_codex_block("qwen", {
            "name": "Alibaba Cloud",
            "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
            "env_key": "DASHSCOPE_API_KEY",
        }, "responses")

    def test_quoted_header_is_matched(self):
        existing = '[model_providers."qwen"]\nname = "old"\n\n[other]\nx = 1\n'
        out = aicn.apply_codex_update(existing, "qwen", self._block())
        self.assertEqual(out.count("[model_providers."), 1)
        self.assertNotIn('name = "old"', out)
        self.assertIn("[other]", out)

    def test_whitespace_in_header_is_matched(self):
        existing = '[ model_providers.qwen ]\nname = "old"\n'
        out = aicn.apply_codex_update(existing, "qwen", self._block())
        self.assertNotIn('name = "old"', out)

    def test_similar_provider_not_confused(self):
        existing = '[model_providers.qwen-plus]\nname = "other"\n'
        out = aicn.apply_codex_update(existing, "qwen", self._block())
        self.assertIn('[model_providers.qwen-plus]', out)
        self.assertIn("[model_providers.qwen]", out)


class TestTableFormatting(unittest.TestCase):
    """表格列宽要按内容计算并截断，不能把后面的列推歪。"""

    def test_truncate_respects_display_width(self):
        self.assertEqual(aicn.truncate("abc", 10), "abc")
        self.assertEqual(aicn.display_width(aicn.truncate("中文测试", 5)), 5)
        self.assertTrue(aicn.truncate("中文测试", 5).endswith("…"))

    def test_pad_never_exceeds_width(self):
        out = aicn.pad("x" * 100, 10)
        self.assertLessEqual(aicn.display_width(out), 10)

    def test_column_widths_bounded(self):
        headers = ["A", "B"]
        rows = [["a" * 50, "b" * 5]]
        widths = aicn.column_widths(rows, headers, [3, 3], [10, 10])
        self.assertEqual(widths, [10, 5])

    def test_list_rows_aligned(self):
        """所有数据行的第二列必须起始于同一显示位置。"""
        out = aicn.cmd_list(argparse_namespace(provider=None, json=False))
        lines = out.splitlines()
        data_rows = [ln for ln in lines
                     if ln.startswith(("deepseek", "qwen", "zhipu", "moonshot"))]
        self.assertTrue(data_rows)
        offsets = set()
        for row in data_rows:
            pid = row.split()[0]
            rest = row[len(pid):]
            # 供应商列填充到固定宽度后接 2 空格分隔符
            offsets.add(len(pid) + (len(rest) - len(rest.lstrip(" "))))
        self.assertEqual(len(offsets), 1,
                         "数据行第二列起始位置不一致：%s" % sorted(offsets))


class TestSyncIsolation(unittest.TestCase):
    """同步结果写用户级文件，不污染包内 / 仓库里的 providers.json。"""

    def test_sync_writes_user_file_not_package(self):
        import http.server
        import threading

        from aicn import cli

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                body = json.dumps({"data": [{"id": "mock-model"}]}).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            with tempfile.TemporaryDirectory() as td:
                target = Path(td) / "user.json"
                res = cli.sync_models(
                    "gateway", "http://127.0.0.1:%d/v1" % srv.server_address[1],
                    "k", target=target)
                self.assertTrue(res["ok"], res)
                self.assertEqual(res["added"], ["mock-model"])
                self.assertEqual(res["path"], str(target))
                self.assertTrue(target.exists())
        finally:
            srv.shutdown()
            srv.server_close()

    def test_package_data_file_untouched_by_sync(self):
        """同步不应修改包内的 providers.json。"""
        before = aicn.DATA_FILE.read_text(encoding="utf-8")
        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / "user.json"
            from aicn import cli
            cli.sync_models("no-such-provider", None, None, target=target)
        after = aicn.DATA_FILE.read_text(encoding="utf-8")
        self.assertEqual(before, after)

    def test_sync_default_target_is_user_level_file(self):
        """不带 --data-file 时必须写用户级目录，不能写包内 DATA_FILE。"""
        from aicn import cli
        self.assertNotEqual(cli.USER_DATA_FILE, cli.DATA_FILE)
        self.assertIn(str(Path.home()), str(cli.USER_DATA_FILE))
        self.assertEqual(cli.USER_DATA_FILE.name, "providers.json")
        self.assertIn(".aicn", cli.USER_DATA_FILE.parts)

    def test_write_failure_raises_aicn_error_not_oserror(self):
        """写入失败应抛 AicnError（干净报错），而不是裸的 PermissionError。"""
        from aicn import cli
        original = Path.write_text

        def boom(self, *a, **k):
            raise PermissionError(13, "Permission denied", str(self))

        Path.write_text = boom
        try:
            with tempfile.TemporaryDirectory() as td:
                target = Path(td) / "providers.json"
                with self.assertRaises(cli.AicnError) as ctx:
                    cli.write_with_backup(target, "{}")
        finally:
            Path.write_text = original
        self.assertIn("写入", str(ctx.exception))
        self.assertNotIsInstance(ctx.exception, OSError)

    def test_sync_write_failure_exits_nonzero_without_traceback(self):
        """同步写失败时 CLI 应干净退出（非零码），不打印 traceback。"""
        import contextlib
        import http.server
        import io
        import threading

        from aicn import cli

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                body = json.dumps({"data": [{"id": "mock-model"}]}).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        original = Path.write_text

        def boom(self, *a, **k):
            raise PermissionError(13, "Permission denied", str(self))

        Path.write_text = boom
        err = io.StringIO()
        try:
            with tempfile.TemporaryDirectory() as td:
                target = Path(td) / "providers.json"
                with contextlib.redirect_stdout(io.StringIO()), \
                        contextlib.redirect_stderr(err):
                    rc = cli.main(["sync", "-p", "gateway", "--data-file", str(target),
                                   "--base-url",
                                   "http://127.0.0.1:%d/v1" % srv.server_address[1]])
        finally:
            Path.write_text = original
            srv.shutdown()
            srv.server_close()
        self.assertNotEqual(rc, 0)
        self.assertNotIn("Traceback", err.getvalue())
        self.assertIn("写入", err.getvalue())


class TestWebEscaping(unittest.TestCase):
    """面板渲染必须转义引号 —— /models 返回的模型 id 是不可信输入。"""

    def test_esc_function_escapes_quotes(self):
        from aicn import webui
        html = webui.HTML
        self.assertIn('&quot;', html, "esc() 必须转义双引号")
        self.assertIn('&#39;', html, "esc() 必须转义单引号")
        # 旧的实现只转义 & < >
        self.assertNotIn("replace(/[&<>]/g", html)

    def test_malicious_model_id_cannot_break_attribute(self):
        """恶意模型 id 渲染成 option 时不能逃逸出属性。"""
        import re

        from aicn import webui

        malicious = 'evil" onmouseover="alert(1)" x="'
        # 提取面板里的 esc() 规则并用等价 Python 实现验证
        self.assertIn("&quot;", webui.HTML)

        def esc(s):
            return re.sub(r'[&<>"\']',
                          lambda m: {'&': '&amp;', '<': '&lt;', '>': '&gt;',
                                     '"': '&quot;', "'": '&#39;'}[m.group()],
                          str(s if s is not None else ''))

        rendered = '<option value="%s">%s</option>' % (esc(malicious), esc(malicious))
        attr_value = rendered.split('value="')[1].split('"')[0]
        self.assertNotIn('"', attr_value, "属性值里出现裸引号，可逃逸属性")
        self.assertIn("&quot;", rendered)

    def test_esc_covers_ampersand_and_angle_brackets(self):
        """& < > 也必须转义，否则可注入标签。"""
        import re

        from aicn import webui

        self.assertIn("&amp;", webui.HTML)
        self.assertIn("&lt;", webui.HTML)
        self.assertIn("&gt;", webui.HTML)

        def esc(s):
            return re.sub(r'[&<>"\']',
                          lambda m: {'&': '&amp;', '<': '&lt;', '>': '&gt;',
                                     '"': '&quot;', "'": '&#39;'}[m.group()],
                          str(s if s is not None else ''))

        rendered = esc('<img src=x onerror=alert(1)>')
        self.assertNotIn("<", rendered)
        self.assertIn("&lt;img", rendered)

    def test_custom_model_input_is_bound(self):
        """「✏️ 自定义…」选项必须真的能显示自定义模型输入框。

        旧实现删掉了 bindModel 的调用，却保留了 hidden 初始 class，
        导致该选项永远不可用（选了也没地方填模型名）。
        """
        from aicn import webui
        html = webui.HTML
        self.assertIn("__custom__", html)
        self.assertIn("function bindModel", html)
        # 必须真的调用了 bindModel，而不是只定义不调用
        self.assertIn("bindModel('t-model','t-model-custom')", html)
        self.assertIn("bindModel('g-model','g-model-custom')", html)
        # 自定义输入框的 id 必须与 select 的 id 对得上（syncCustomInput 依赖 sel.id+'-custom'）
        self.assertIn("id=\"t-model-custom\"", html)
        self.assertIn("id=\"g-model-custom\"", html)


class TestWebConcurrency(unittest.TestCase):

    def test_concurrent_runs_are_isolated(self):
        """并发请求下，每个响应只应包含自己那份输出。

        旧实现用 contextlib.redirect_stdout 捕获输出，而 stdout 是进程级全局资源，
        并发时 A 的输出会串进 B 的响应。这里用带唯一标记的返回值验证隔离性。
        """
        import threading

        from aicn import webui

        results = []

        def worker(i):
            def fn(ns):
                return "RESULT-%d" % i

            results.append((i, webui._run(fn, None)["out"]))

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(len(results), 8)
        for i, out in results:
            self.assertEqual(out, "RESULT-%d" % i)
            for j in range(8):
                if j != i:
                    self.assertNotIn("RESULT-%d" % j, out)

    def test_run_does_not_capture_stdout(self):
        """_run 不应再劫持 sys.stdout —— 命令函数的返回值才是唯一输出通道。"""
        import contextlib
        import io

        from aicn import webui

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            res = webui._run(lambda ns: "VALUE", None)
        self.assertEqual(res["out"], "VALUE")
        self.assertEqual(buf.getvalue(), "")

    def test_run_reports_error_instead_of_raising(self):
        from aicn import webui

        def boom(ns):
            raise ValueError("boom")

        res = webui._run(boom, None)
        self.assertFalse(res["ok"])
        self.assertIn("boom", res["error"])

    def test_run_reports_aicn_error(self):
        from aicn import cli, webui

        def boom(ns):
            raise cli.AicnError("供应商不存在", code=2)

        res = webui._run(boom, None)
        self.assertFalse(res["ok"])
        self.assertEqual(res["exit"], 2)
        self.assertIn("供应商不存在", res["error"])

    def test_run_preserves_exit_code_of_empty_output(self):
        """空文本的 CommandOutput 不能因 `or ""` 被降级成普通 str 而丢掉退出码。"""
        from aicn import cli, webui

        res = webui._run(lambda ns: cli.CommandOutput("", 1), None)
        self.assertEqual(res["exit"], 1)
        self.assertFalse(res["ok"])

    def test_run_preserves_exit_code_of_success(self):
        from aicn import cli, webui

        res = webui._run(lambda ns: cli.CommandOutput("OK", 0), None)
        self.assertEqual(res["exit"], 0)
        self.assertTrue(res["ok"])

    def test_concurrent_http_requests_do_not_cross_contaminate(self):
        """真实 HTTP 并发下，每个响应只能含自己那条请求的内容。

        旧实现用 contextlib.redirect_stdout 捕获输出，而 stdout 是进程级全局资源，
        并发时 A 请求的输出会串进 B 的响应。这里起一个真实 mock 网关 + 真实
        HTTP 服务器，用唯一模型名验证隔离性。
        """
        import http.server
        import threading
        import urllib.request

        from aicn import webui

        class MockGateway(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_POST(self):
                length = int(self.headers.get("Content-Length", 0))
                request = json.loads(self.rfile.read(length) or b"{}")
                payload = json.dumps({
                    "model": request.get("model"),
                    "choices": [{"message": {"role": "assistant",
                                             "content": "reply-%s" % request.get("model")}}],
                }).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

        gateway = http.server.ThreadingHTTPServer(("127.0.0.1", 0), MockGateway)
        gateway_port = gateway.server_address[1]
        threading.Thread(target=gateway.serve_forever, daemon=True).start()

        results = []

        def worker(i):
            model = "model-marker-%d" % i
            body = json.dumps({"provider": "deepseek", "model": model,
                               "key": "sk-test", "protocol": "chat",
                               "base_url": "http://127.0.0.1:%d/v1" % gateway_port
                               }).encode("utf-8")
            req = urllib.request.Request("http://127.0.0.1:%d/api/test" % self.port,
                                         data=body,
                                         headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=30) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
            results.append((i, payload))

        webui.Handler.port = 0
        srv = webui.ThreadingHTTPServer(("127.0.0.1", 0), webui.Handler)
        self.port = srv.server_address[1]
        th = threading.Thread(target=srv.serve_forever, daemon=True)
        th.start()
        try:
            threads = [threading.Thread(target=worker, args=(i,)) for i in range(6)]
            for t in threads:
                t.start()
            for t in threads:
                t.join(timeout=60)
        finally:
            srv.shutdown()
            srv.server_close()
            gateway.shutdown()
            gateway.server_close()

        self.assertEqual(len(results), 6)
        for i, payload in results:
            out = payload.get("out", "")
            self.assertIn("model-marker-%d" % i, out)
            for j in range(6):
                if j != i:
                    self.assertNotIn("model-marker-%d" % j, out,
                                     "响应 %d 串入了请求 %d 的内容" % (i, j))
            self.assertEqual(payload.get("exit"), 0)
            self.assertTrue(payload.get("ok"))


class TestDoctorGrading(unittest.TestCase):
    """doctor 要按状态码分级，401/404 不该标成 OK。"""

    def test_probe_grades_auth_failure(self):
        from aicn import cli
        pid, label, ms, level = cli.probe_endpoint(
            "x", {"base_url": "http://127.0.0.1:1/v1", "env_key": "NOPE_KEY_X"})
        self.assertEqual(level, "down")

    def test_probe_grades_404_as_unsupported(self):
        from aicn import cli
        original = cli.http_request
        cli.http_request = lambda *a, **k: (404, 5, "")
        try:
            pid, label, ms, level = cli.probe_endpoint(
                "x", {"base_url": "https://example.invalid", "env_key": "K"})
            self.assertEqual(level, "unsupported")
            self.assertIn("404", label)
        finally:
            cli.http_request = original

    def test_probe_grades_401_as_auth(self):
        from aicn import cli
        original = cli.http_request
        cli.http_request = lambda *a, **k: (401, 5, "")
        try:
            pid, label, ms, level = cli.probe_endpoint(
                "x", {"base_url": "https://example.invalid", "env_key": "K"})
            self.assertEqual(level, "auth")
        finally:
            cli.http_request = original


class TestPackageExports(unittest.TestCase):
    """__init__ 不应把标准库名字泄进命名空间。"""

    def test_no_stdlib_leak(self):
        for name in ("json", "os", "re", "sys", "urllib", "time", "Path"):
            self.assertFalse(hasattr(aicn, name), "aicn.%s 不应被导出" % name)

    def test_public_api_exported(self):
        for name in ("load_providers", "cmd_list", "cmd_test", "cmd_gen",
                     "cmd_env", "cmd_doctor", "cmd_sync", "VERSION"):
            self.assertTrue(hasattr(aicn, name), "缺少导出 %s" % name)


class TestVersionSingleSource(unittest.TestCase):
    """版本号只能有一个来源：aicn/_version.py。"""

    def test_version_module_is_the_source(self):
        from aicn import _version
        self.assertRegex(_version.__version__, r"^\d+\.\d+\.\d+")

    def test_cli_version_matches_module(self):
        from aicn import _version, cli
        self.assertEqual(cli.FALLBACK_VERSION, _version.__version__)
        self.assertEqual(cli.VERSION, _version.__version__)

    def test_pyproject_uses_dynamic_version(self):
        """pyproject.toml 不应再硬编码 version=（会与 _version.py 脱节）。"""
        root = Path(__file__).resolve().parent.parent
        text = (root / "pyproject.toml").read_text(encoding="utf-8")
        self.assertIn('dynamic = ["version"]', text)
        self.assertNotIn('version = "', text.split("[tool.ruff]")[0].replace(
            'dynamic = ["version"]', ""))

    def test_webui_uses_cli_version(self):
        """Web 面板的 server_version 必须跟随 CLI 版本，不能写死。"""
        from aicn import cli, webui
        self.assertEqual(webui.Handler.server_version, "aicn-web/" + cli.VERSION)


class TestCliBaseUrlOverride(unittest.TestCase):
    """用户显式传的 --base-url 必须能覆盖供应商默认端点。"""

    def test_codex_base_url_override(self):
        out = aicn.cmd_gen(argparse_namespace(
            tool="codex", provider="qwen", model="qwen3.7-plus", key=None,
            write=False, wire_api=None, base_url="http://127.0.0.1:9999/v1"))
        self.assertIn('base_url = "http://127.0.0.1:9999/v1"', out)
        self.assertNotIn("dashscope.aliyuncs.com", out)

    def test_claude_code_base_url_override(self):
        out = aicn.cmd_gen(argparse_namespace(
            tool="claude-code", provider="moonshot", model="kimi-k3", key=None,
            write=False, wire_api=None, base_url="http://127.0.0.1:9999/anthropic"))
        self.assertIn("http://127.0.0.1:9999/anthropic", out)
        self.assertNotIn("api.moonshot.cn", out)

    def test_base_url_override_wins_over_responses_base_url(self):
        """--base-url 必须盖过供应商自带的 responses 基址（智谱是 /api/v1）。"""
        out = aicn.cmd_gen(argparse_namespace(
            tool="codex", provider="zhipu", model="glm-5.3", key=None,
            write=False, wire_api=None, base_url="http://127.0.0.1:9999/v1"))
        self.assertIn('base_url = "http://127.0.0.1:9999/v1"', out)
        self.assertNotIn("open.bigmodel.cn", out)
