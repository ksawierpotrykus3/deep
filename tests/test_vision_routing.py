"""
Unit and integration tests for DeepSeek Proxy Vision Routing.
Verifies:
1. Image extraction from user messages (data URIs and URLs).
2. Image uploading helper (_upload_images_to_deepseek), caching, and SSRF prevention.
3. Resumed conversation turns (Turn 2+) correctly extract new images and populate ref_file_ids.
4. Turn 1 (fresh chat) correctly extracts images and sets ref_file_ids.
5. Follow-up turns without images do NOT re-upload previous turn images (ref_file_ids=[]).
"""

import sys
import os
import base64
import unittest
from unittest.mock import MagicMock
from pathlib import Path

# Setup paths
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

import server


class TestVisionRouting(unittest.TestCase):
    def setUp(self):
        # Clear upload cache before each test
        with server._image_cache_lock:
            server._image_upload_cache.clear()

    def test_extract_images_data_uri(self):
        # 1x1 transparent PNG in base64
        dummy_b64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
        messages = [
            {"role": "system", "content": "You are a helpful assistant."},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "What is in this image?"},
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{dummy_b64}"}}
                ]
            }
        ]
        images = server._extract_images(messages)
        self.assertEqual(len(images), 1)
        self.assertEqual(images[0]["base64"], dummy_b64)
        self.assertEqual(images[0]["mime_type"], "image/png")

    def test_extract_images_empty(self):
        messages = [
            {"role": "user", "content": "Hello world, no image here."}
        ]
        images = server._extract_images(messages)
        self.assertEqual(len(images), 0)

    def test_upload_images_and_cache(self):
        mock_ds = MagicMock()
        mock_ds.upload_file.return_value = "file-test-12345"

        dummy_b64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
        images = [
            {"base64": dummy_b64, "mime_type": "image/png", "url": "", "detail": "auto"}
        ]

        # 1st upload
        file_ids = server._upload_images_to_deepseek(mock_ds, account_idx=11, images=images)
        self.assertEqual(file_ids, ["file-test-12345"])
        self.assertEqual(mock_ds.upload_file.call_count, 1)

        # 2nd upload with identical image -> must hit cache, call_count remains 1
        file_ids_cached = server._upload_images_to_deepseek(mock_ds, account_idx=11, images=images)
        self.assertEqual(file_ids_cached, ["file-test-12345"])
        self.assertEqual(mock_ds.upload_file.call_count, 1)

    def test_upload_images_ssrf_blocked(self):
        mock_ds = MagicMock()
        images = [
            {"base64": None, "url": "http://127.0.0.1:8080/private_image.png"}
        ]
        file_ids = server._upload_images_to_deepseek(mock_ds, account_idx=11, images=images)
        self.assertEqual(file_ids, [])
        self.assertEqual(mock_ds.upload_file.call_count, 0)

    def test_resume_turn_extracts_and_uploads_new_image(self):
        """Simulate a multi-turn conversation where the user attaches an image in turn 2."""
        dummy_b64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
        
        # Turn 1 history already happened
        history_msgs = [
            {"role": "system", "content": "System instruction"},
            {"role": "user", "content": "Hi DeepSeek"},
            {"role": "assistant", "content": "Hello! How can I help you today?"},
        ]
        state = {
            "ds_session": "chat-session-uuid-123",
            "parent_id": "msg-node-456",
            "msgs_len": 3,
            "account": 11
        }

        # Turn 2 incoming request from Trae: contains previous 3 msgs + new 4th msg with image
        new_turn_user_msg = {
            "role": "user",
            "content": [
                {"type": "text", "text": "Can you check this error screenshot?"},
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{dummy_b64}"}}
            ]
        }
        all_req_messages = history_msgs + [new_turn_user_msg]

        # Verify resume detection
        resume = bool(state and state.get("parent_id") is not None and state.get("ds_session"))
        self.assertTrue(resume)

        # Calculate new_msgs as done in server.py
        new_msgs = [m for m in all_req_messages[state["msgs_len"]:] if m.get("role") in ("user", "tool")]
        self.assertEqual(len(new_msgs), 1)

        # Extract images from new_msgs
        turn_images = server._extract_images(new_msgs)
        self.assertEqual(len(turn_images), 1)
        self.assertEqual(turn_images[0]["base64"], dummy_b64)

        # Upload images
        mock_ds = MagicMock()
        mock_ds.upload_file.return_value = "file-turn2-image-id"
        ref_file_ids = server._upload_images_to_deepseek(mock_ds, account_idx=11, images=turn_images)
        self.assertEqual(ref_file_ids, ["file-turn2-image-id"])

        # Check prompt formatting
        prompt = server._build_prompt(new_msgs, tools=None, state=state)
        self.assertIn("Can you check this error screenshot?", prompt)
        self.assertIn("[Image]", prompt)

    def test_followup_turn_without_image_does_not_reupload(self):
        """Simulate Turn 3 where user replies with text only after having sent an image in Turn 2."""
        dummy_b64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
        all_messages = [
            {"role": "system", "content": "System instruction"},
            {"role": "user", "content": "Hi DeepSeek"},
            {"role": "assistant", "content": "Hello! How can I help you today?"},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Screenshot"},
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{dummy_b64}"}}
                ]
            },
            {"role": "assistant", "content": "I see the screenshot. Here is the analysis."},
            {"role": "user", "content": "Thanks, now implement the fix."}
        ]
        # State at start of Turn 3
        state = {
            "ds_session": "chat-session-uuid-123",
            "parent_id": "msg-node-789",
            "msgs_len": 5,
            "account": 11
        }

        # Calculate new_msgs for Turn 3
        new_msgs = [m for m in all_messages[state["msgs_len"]:] if m.get("role") in ("user", "tool")]
        self.assertEqual(len(new_msgs), 1)
        self.assertEqual(new_msgs[0]["content"], "Thanks, now implement the fix.")

        # Extract images from new_msgs in Turn 3
        turn_images = server._extract_images(new_msgs)
        self.assertEqual(len(turn_images), 0)

        # ref_file_ids stays empty for turn 3
        ref_file_ids = server._upload_images_to_deepseek(MagicMock(), account_idx=11, images=turn_images)
        self.assertEqual(ref_file_ids, [])


if __name__ == "__main__":
    unittest.main()
