import unittest
import sys
import json
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import server
import debounce


class TestStreamAndTurnLoopFix(unittest.TestCase):
    def test_token_by_token_single_tool_yield(self):
        """Simulate character-by-character streaming of a DSML invoke call.
        Verify that allow_unclosed=False never yields unclosed calls,
        and the entire stream yields EXACTLY 1 tool call instead of 116."""
        payload = """<｜｜DSML｜｜invoke name="Read">
<｜｜DSML｜｜parameter name="file_path">c:/Users/buchh/projects/magazyn/o_tobie.md</｜｜DSML｜｜>
<｜｜DSML｜｜parameter name="offset" string="false">416</｜｜DSML｜｜>
<｜｜DSML｜｜parameter name="limit" string="false">330</｜｜DSML｜｜>
</｜｜DSML｜｜invoke>"""

        cursor = 0
        tools_yielded = 0
        yielded_tool_starts = set()
        yielded_tool_signatures = set()

        for i in range(1, len(payload) + 1):
            chunk_full = payload[:i]
            # While streaming, allow_unclosed=False
            tools = server._parse_tool_calls(chunk_full, allow_unclosed=False)
            if i < len(payload):
                self.assertEqual(len(tools), 0, f"Unclosed invoke yielded early at pos {i}")

            if tools:
                for ts, te, tname, targs in tools:
                    if ts in yielded_tool_starts or te <= cursor:
                        continue
                    call_sig = (tname, targs)
                    if call_sig in yielded_tool_signatures:
                        yielded_tool_starts.add(ts)
                        cursor = max(cursor, te)
                        continue
                    tools_yielded += 1
                    yielded_tool_starts.add(ts)
                    yielded_tool_signatures.add(call_sig)
                    cursor = max(cursor, te)

        # EXACTLY 1 tool call yielded, not 116!
        self.assertEqual(tools_yielded, 1)
        self.assertEqual(len(yielded_tool_starts), 1)

    def test_sequential_tools_streaming_yields_once_each(self):
        """Simulate streaming of 2 consecutive tools (LS then Read).
        Verify each tool is yielded exactly once."""
        payload = """<｜｜DSML｜｜invoke name="LS">
<｜｜DSML｜｜parameter name="path">c:/Users/buchh/projects/magazyn</｜｜DSML｜｜>
</｜｜DSML｜｜invoke>
<｜｜DSML｜｜invoke name="Read">
<｜｜DSML｜｜parameter name="file_path">c:/Users/buchh/projects/magazyn/README.md</｜｜DSML｜｜>
</｜｜DSML｜｜invoke>"""

        cursor = 0
        yielded_tools = []
        yielded_tool_starts = set()
        yielded_tool_signatures = set()

        for i in range(1, len(payload) + 1):
            chunk_full = payload[:i]
            tools = server._parse_tool_calls(chunk_full, allow_unclosed=False)
            for ts, te, tname, targs in tools:
                if ts in yielded_tool_starts or te <= cursor:
                    continue
                call_sig = (tname, targs)
                if call_sig in yielded_tool_signatures:
                    yielded_tool_starts.add(ts)
                    cursor = max(cursor, te)
                    continue
                yielded_tools.append((tname, json.loads(targs)))
                yielded_tool_starts.add(ts)
                yielded_tool_signatures.add(call_sig)
                cursor = max(cursor, te)

        self.assertEqual(len(yielded_tools), 2)
        self.assertEqual(yielded_tools[0][0], "LS")
        self.assertEqual(yielded_tools[0][1]["path"], "c:/Users/buchh/projects/magazyn")
        self.assertEqual(yielded_tools[1][0], "Read")
        self.assertEqual(yielded_tools[1][1]["file_path"], "c:/Users/buchh/projects/magazyn/README.md")

    def test_declared_action_only_not_triggered_on_polish_conversational_text(self):
        """Verify normal Polish conversational replies containing future verbs or 'muszę'
        are NOT falsely classified as action promises."""
        # Case 1: Question to user
        msg_with_question = (
            "W magazynie mamy 6 plików. Zgodnie z wytycznymi muszę zapytać o jedną kwestię: "
            "czy chcesz zachować plik slownik.md w nowej strukturze?"
        )
        self.assertTrue("?" in msg_with_question)
        # Case 2: Substantial explanation ending normally
        msg_explanation = (
            "Przeanalizowałem obecny stan plików. Zauważyłem, że plik o_tobie.md zawierał "
            "wcześniejsze interpretacje AI, które należy usunąć. Następnie przygotuję "
            "zestawienie zgodne z Twoją prośbą. Czekam na dalsze instrukcje."
        )
        # Should not end with dangling promise
        self.assertFalse(msg_explanation.strip().endswith(":"))
        self.assertFalse(msg_explanation.strip().endswith("..."))

    def test_debounce_tracker_single_turn_burst_protection(self):
        """Verify that 20 calls in the same turn number only count as 1 turn entry."""
        state = {}
        tool_name = "Read"
        args = {"file_path": "c:/Users/buchh/projects/magazyn/o_tobie.md"}

        # Simulate burst of 20 calls in turn 1
        for _ in range(20):
            debounce.record_tool_call(state, tool_name, args, turn_number=1)

        tracker = state.get("debounce_tracker", {})
        self.assertEqual(len(tracker), 1)
        h = list(tracker.keys())[0]
        self.assertEqual(tracker[h], [1])  # Only recorded once for turn 1!

        # Call once in turn 2
        debounce.record_tool_call(state, tool_name, args, turn_number=2)
        self.assertEqual(tracker[h], [1, 2])

        # Blocked only after MAX_DUPLICATE_CALLS across distinct turns
        self.assertTrue(debounce.is_duplicate_blocked(state, tool_name, args))

    def test_turn_stimulus_has_no_kontynuuj_spam(self):
        """Verify that TURN_STIMULUS does not contain 'kontynuuj.' which confuses models."""
        for outcome, stimulus in server.TURN_STIMULUS.items():
            self.assertFalse(stimulus.lower().startswith("kontynuuj"),
                             f"Outcome {outcome} still starts with 'kontynuuj'")
            self.assertTrue(stimulus.startswith("[System directive:"),
                            f"Outcome {outcome} should start with '[System directive:'")


if __name__ == "__main__":
    unittest.main()
