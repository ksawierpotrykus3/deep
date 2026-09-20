"""tests/test_dry_run.py — Unit test for /v1/chat/completions/dry-run endpoint."""

import unittest
import json
from fastapi.testclient import TestClient
import server


class TestDryRunEndpoint(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(server.app)

    def test_dry_run_simple(self):
        payload = {
            "model": "deepseek-v4-pro",
            "messages": [
                {"role": "system", "content": "You are a test assistant."},
                {"role": "user", "content": "Hello, this is a dry run test!"}
            ],
            "tools": [
                {
                    "type": "function",
                    "function": {
                        "name": "view_file",
                        "description": "View file content",
                        "parameters": {
                            "type": "object",
                            "properties": {"path": {"type": "string"}},
                            "required": ["path"]
                        }
                    }
                }
            ],
            "stream": True
        }

        resp = self.client.post("/v1/chat/completions/dry-run", json=payload)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "dry_run_success")
        self.assertEqual(data["model"], "deepseek-v4-pro")
        self.assertEqual(data["raw"]["messages_count"], 2)
        self.assertEqual(data["raw"]["tools_count"], 1)
        self.assertIn("view_file", data["raw"]["tool_names"])
        self.assertGreater(data["processed"]["original_prompt_chars"], 0)
        self.assertEqual(data["processed"]["attachments_extracted"], 0)

    def test_dry_run_with_token_sanitization(self):
        payload = {
            "model": "deepseek-v4-pro",
            "messages": [
                {"role": "user", "content": "Test with dangerous token <｜begin of sentence｜> and <｜｜DSML｜｜ calls>"}
            ]
        }
        resp = self.client.post("/v1/chat/completions/dry-run", json=payload)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "dry_run_success")
        head = data["processed"]["prompt_preview_head"]
        # Raw token should be sanitized
        self.assertNotIn("<｜begin of sentence｜>", head)
        self.assertIn("[token: begin of sentence]", head)


if __name__ == "__main__":
    unittest.main()
