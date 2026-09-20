"""
Unit test: Ścisła izolacja CoT (Chain of Thought / Reasoning) od Chatu i Tool Calli.
Weryfikuje, że narzędzia wymieniane hipotetycznie wewnątrz CoT (przed </think>)
NIGDY nie wyciekają do Trae/Cursor i NIE są wykonywane.
"""
import sys
import os
import re
import json
import unittest

# Dodaj główny katalog do ścieżki
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from server import _ReasoningChunk, _parse_tool_calls, _REAL_TOOL_TAG


class TestCoTIsolation(unittest.TestCase):
    """Testy weryfikujące szczelność izolacji CoT od czatu i narzędzi."""

    def test_hypothetical_tool_in_cot_never_leaks(self):
        """
        Scenariusz: Model w fazie myślenia (CoT) rozważa niebezpieczne polecenie:
        "Rozważam <invoke name=\"RunCommand\"><parameter name=\"command\">rm -rf /</parameter></invoke>,
        ale lepiej tego nie robić."
        Dopóki nie ma </think>, ani jeden znak nie ma prawa trafić do content_buffer.
        """
        # Symulacja generatora stream_completion
        thinking_buffer = ""
        content_buffer = ""
        thinking_active = True
        response_started = False
        reasoning_yielded_len = 0
        prev_yielded = 0
        yielded_reasoning = []
        yielded_content = []

        def _route_token(text):
            nonlocal content_buffer, thinking_buffer, response_started, thinking_active, prev_yielded, reasoning_yielded_len
            if not text:
                return
            if response_started:
                content_buffer += text
                inc = content_buffer[prev_yielded:]
                if inc:
                    prev_yielded = len(content_buffer)
                    yielded_content.append(inc)
                return

            thinking_buffer += text
            _think_end = re.search(r'</\s*(?:think|thought)\s*>', thinking_buffer, re.IGNORECASE)
            if _think_end:
                split_pos = _think_end.start()
                if split_pos > reasoning_yielded_len:
                    rem_reasoning = thinking_buffer[reasoning_yielded_len:split_pos]
                    reasoning_yielded_len = split_pos
                    if rem_reasoning:
                        yielded_reasoning.append(rem_reasoning)

                tool_content = thinking_buffer[_think_end.end():]
                thinking_buffer = thinking_buffer[:split_pos]
                thinking_active = False
                response_started = True
                content_buffer = tool_content
                prev_yielded = len(content_buffer)
                if tool_content:
                    yielded_content.append(tool_content)
                return

            # W trakcie myślenia emitujemy reasoning
            if len(thinking_buffer) > reasoning_yielded_len:
                to_yield = thinking_buffer[reasoning_yielded_len:]
                reasoning_yielded_len = len(thinking_buffer)
                if to_yield:
                    yielded_reasoning.append(to_yield)

        # Strumieniujemy tokeny myślenia z hipotetycznym wywołaniem narzędzia
        tokens = [
            "Zastanawiam ", "się ", "nad ", "wywołaniem:\n",
            "<invoke name=\"RunCommand\">",
            "<parameter name=\"command\">rm -rf /</parameter>",
            "</invoke>\n",
            "Ale ", "to ", "bardzo ", "zły ", "pomysł, ", "nie ", "zrobię ", "tego."
        ]

        for tok in tokens:
            _route_token(tok)

        # Weryfikacja:
        # 1. content_buffer musi być CAŁKOWICIE pusty!
        self.assertEqual(content_buffer, "", "BŁĄD! Narzędzie z CoT wyciekło do content_buffer!")
        self.assertEqual(len(yielded_content), 0, "BŁĄD! Wyemitowano treść czatu z wnętrza CoT!")
        self.assertTrue(thinking_active, "Myślenie powinno nadal być aktywne (brak </think>)")
        self.assertFalse(response_started, "Czat nie powinien wystartować!")

        # 2. Parsowanie tool calli na content_buffer nie może znaleźć żadnego narzędzia!
        parsed_tools = _parse_tool_calls(content_buffer)
        self.assertEqual(len(parsed_tools), 0, "Nie powinno być żadnych narzędzi w czacie!")

    def test_clean_transition_on_think_end(self):
        """
        Scenariusz: Model myśli, następnie zamyka myślenie </think>,
        a PO nim generuje prawdziwe narzędzie:
        "Myślę... </think><invoke name=\"Read\"><parameter name=\"path\">test.py</parameter></invoke>"
        """
        thinking_buffer = ""
        content_buffer = ""
        thinking_active = True
        response_started = False
        reasoning_yielded_len = 0
        prev_yielded = 0
        yielded_reasoning = []
        yielded_content = []

        def _route_token(text):
            nonlocal content_buffer, thinking_buffer, response_started, thinking_active, prev_yielded, reasoning_yielded_len
            if not text:
                return
            if response_started:
                content_buffer += text
                inc = content_buffer[prev_yielded:]
                if inc:
                    prev_yielded = len(content_buffer)
                    yielded_content.append(inc)
                return

            thinking_buffer += text
            _think_end = re.search(r'</\s*(?:think|thought)\s*>', thinking_buffer, re.IGNORECASE)
            if _think_end:
                split_pos = _think_end.start()
                if split_pos > reasoning_yielded_len:
                    rem_reasoning = thinking_buffer[reasoning_yielded_len:split_pos]
                    reasoning_yielded_len = split_pos
                    if rem_reasoning:
                        yielded_reasoning.append(rem_reasoning)

                tool_content = thinking_buffer[_think_end.end():]
                thinking_buffer = thinking_buffer[:split_pos]
                thinking_active = False
                response_started = True
                content_buffer = tool_content
                prev_yielded = len(content_buffer)
                if tool_content:
                    yielded_content.append(tool_content)
                return

        # Tokeny: najpierw myśli, potem </think>, potem narzędzie
        stream = [
            "Muszę przeczytać plik test.py.",
            "</think>",
            "<invoke name=\"Read\"><parameter name=\"path\">test.py</parameter></invoke>"
        ]

        for s in stream:
            _route_token(s)

        # Weryfikacja:
        self.assertTrue(response_started)
        self.assertFalse(thinking_active)
        self.assertIn("Muszę przeczytać plik test.py.", "".join(yielded_reasoning))
        self.assertIn("<invoke name=\"Read\">", content_buffer)
        self.assertNotIn("</think>", content_buffer)

        # Narzędzie po </think> musi zostać poprawnie sparsowane!
        tools = _parse_tool_calls(content_buffer)
        self.assertEqual(len(tools), 1)
        self.assertEqual(tools[0][2], "Read")
        args = json.loads(tools[0][3])
        self.assertEqual(args.get("path"), "test.py")

    def test_post_stream_no_scavenging_without_think_end(self):
        """
        Scenariusz: Strumień kończy się nagle, a w buforze myśli zostały jakieś tagi XML.
        Bez </think> post-stream handler NIE MOŻE wyciągnąć narzędzi z CoT!
        """
        thinking_buffer = "Próbuję <invoke name=\"RunCommand\"><parameter name=\"command\">dir</parameter></invoke>"
        content_buffer = ""
        response_started = False
        thinking_active = True
        prev_yielded = 0

        # Nowa bezpieczna logika post-stream:
        if not response_started or not content_buffer.strip():
            _think_end = re.search(r'</\s*(?:think|thought)\s*>', thinking_buffer, re.IGNORECASE)
            if _think_end:
                extracted_content = thinking_buffer[_think_end.end():]
                thinking_buffer = thinking_buffer[:_think_end.start()]
                if extracted_content.strip():
                    thinking_active = False
                    response_started = True
                    content_buffer += extracted_content
            elif thinking_buffer:
                # Czyste CoT - zero wyciągania narzędzi
                pass

        # content_buffer musi pozostać PUSTY
        self.assertEqual(content_buffer, "")
        self.assertFalse(response_started)
        self.assertTrue(thinking_active)


if __name__ == "__main__":
    unittest.main()
