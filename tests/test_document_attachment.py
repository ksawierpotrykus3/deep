"""tests/test_document_attachment.py — Tests for Document Attachment Strategy & Token Sanitizer."""

import unittest
from document_attachment_service import (
    extract_oversized_blocks_to_attachments,
    sanitize_system_tokens,
    format_history_to_markdown,
)


class TestDocumentAttachment(unittest.TestCase):
    def test_no_extraction_under_threshold(self):
        prompt = "Hello DeepSeek, write a simple Python script."
        lean_prompt, attachments = extract_oversized_blocks_to_attachments(prompt, threshold=35000)
        self.assertEqual(lean_prompt, prompt)
        self.assertEqual(len(attachments), 0)

    def test_extract_oversized_tool_result(self):
        big_content = "X" * 10000
        tool_block = f"<tool_result><id>call_read_123</id><content>{big_content}</content></tool_result>"
        # Make total prompt exceed threshold
        prompt = ("Preamble text... " * 2000) + tool_block
        self.assertGreater(len(prompt), 35000)

        lean_prompt, attachments = extract_oversized_blocks_to_attachments(prompt, threshold=35000)
        self.assertGreater(len(attachments), 0)
        self.assertEqual(attachments[0]["filename"], "tool_result_call_read_123.md")
        self.assertEqual(attachments[0]["mime_type"], "text/markdown")
        self.assertIn("[Full output provided in attached document(s): tool_result_call_read_123.md]", lean_prompt)
        self.assertNotIn(big_content, lean_prompt)

    def test_token_sanitization(self):
        # Raw DSML tag
        text = "Hello <｜｜DSML｜｜ calls> do something </｜｜DSML｜｜ calls>"
        cleaned = sanitize_system_tokens(text)
        self.assertIn("<tool_calls>", cleaned)
        self.assertIn("</tool_calls>", cleaned)
        self.assertNotIn("｜", cleaned)

        # Internal tokenizer token
        text_with_token = "Some prompt <｜begin of sentence｜> and <｜tool call begin｜>"
        cleaned_token = sanitize_system_tokens(text_with_token)
        self.assertNotIn("<｜begin of sentence｜>", cleaned_token)
        self.assertIn("[token: begin of sentence]", cleaned_token)
        self.assertIn("[token: tool call begin]", cleaned_token)

    def test_format_history_to_markdown(self):
        history = [
            {"role": "user", "content": "Create a file"},
            {"role": "assistant", "tool_calls": [{"id": "c1", "function": {"name": "Write", "arguments": '{"path":"test.txt"}'}}]},
            {"role": "tool", "name": "Write", "content": "File created successfully."},
        ]
        md = format_history_to_markdown(history)
        self.assertIn("## Turn 1 - User", md)
        self.assertIn("## Turn 2 - Assistant", md)
        self.assertIn("## Turn 3 - Tool", md)
        self.assertIn("Write", md)


if __name__ == "__main__":
    unittest.main()
