# -*- coding: utf-8 -*-
"""端到端集成测试:本地 mock OpenAI 兼容网关,验证 aicn test 完整链路。"""

import contextlib
import http.server
import io
import json
import sys
import threading
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from aicn import cli  # noqa: E402


class MockHandler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_POST(self):
        if self.path not in ("/chat/completions", "/responses"):
            self.send_response(404)
            self.end_headers()
            return
        length = int(self.headers.get("Content-Length", 0))
        self.rfile.read(length)
        payload = {"model": "mock-model",
                   "choices": [{"message": {"role": "assistant", "content": "ok"}}],
                   "usage": {"prompt_tokens": 10, "completion_tokens": 2}}
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(payload).encode("utf-8"))


class TestE2EMock(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), MockHandler)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def _run(self, argv):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = cli.main(argv)
        return rc, buf.getvalue()

    def test_test_command_chat(self):
        base = "http://127.0.0.1:%d" % self.port
        rc, out = self._run(["test", "-p", "deepseek", "-m", "deepseek-chat",
                             "-k", "sk-test", "--base-url", base, "--protocol", "chat"])
        self.assertEqual(rc, 0, out)
        self.assertIn("HTTP 200", out)
        self.assertIn("ok", out)

    def test_gen_codex_with_base_url(self):
        base = "http://127.0.0.1:9999/v1"
        rc, out = self._run(["gen", "-t", "codex", "-p", "gateway",
                             "-m", "deepseek-v4.1-flash", "--base-url", base])
        self.assertEqual(rc, 0, out)
        self.assertIn('base_url = "%s"' % base, out)
        self.assertIn('wire_api = "responses"', out)


if __name__ == "__main__":
    unittest.main()
