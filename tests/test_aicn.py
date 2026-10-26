# -*- coding: utf-8 -*-
"""aicn 单元测试：python -m unittest discover -s tests -v"""

import json
import os
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
        self.assertIn("deepseek-chat", out)

    def test_gen_claude_without_anthropic_endpoint(self):
        out = aicn.cmd_gen(argparse_namespace(
            tool="claude-code", provider="deepseek", model=None, key=None,
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
