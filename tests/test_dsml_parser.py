import unittest
import sys
import json
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import server


class TestDSMLParser(unittest.TestCase):
    def test_user_screenshot_repro(self):
        """Test exact failure from user screenshot where limit=330 was swallowed into file_path."""
        text = """<｜｜DSML｜｜invoke name="Read">
<｜｜DSML｜｜parameter name="file_path">c:/Users/buchh/projects/magazyn/o_tobie.md</｜｜DSML｜｜>
<｜｜DSML｜｜parameter name="limit" string="false">330</｜｜DSML｜｜>
</｜｜DSML｜｜invoke>"""
        calls = server._parse_tool_calls(text)
        self.assertEqual(len(calls), 1)
        name, raw_args = calls[0][2], calls[0][3]
        self.assertEqual(name, "Read")
        args = json.loads(raw_args)
        self.assertEqual(args["file_path"], "c:/Users/buchh/projects/magazyn/o_tobie.md")
        self.assertEqual(args["limit"], 330)

    def test_read_with_offset_and_limit(self):
        text = """<｜｜DSML｜｜invoke name="Read">
<｜｜DSML｜｜parameter name="file_path">c:/Users/buchh/projects/magazyn/o_tobie.md</｜｜DSML｜｜>
<｜｜DSML｜｜parameter name="offset" string="false">416</｜｜DSML｜｜>
<｜｜DSML｜｜parameter name="limit" string="false">330</｜｜DSML｜｜>
</｜｜DSML｜｜invoke>"""
        calls = server._parse_tool_calls(text)
        self.assertEqual(len(calls), 1)
        args = json.loads(calls[0][3])
        self.assertEqual(args["file_path"], "c:/Users/buchh/projects/magazyn/o_tobie.md")
        self.assertEqual(args["offset"], 416)
        self.assertEqual(args["limit"], 330)

    def test_grep_flags(self):
        text = """<｜｜DSML｜｜invoke name="Grep">
<｜｜DSML｜｜parameter name="path">c:/Users/buchh/projects/magazyn</｜｜DSML｜｜>
<｜｜DSML｜｜parameter name="glob" string="true">*.md</｜｜DSML｜｜>
<｜｜DSML｜｜parameter name="-n" string="true">true</｜｜DSML｜｜>
</｜｜DSML｜｜invoke>"""
        calls = server._parse_tool_calls(text)
        self.assertEqual(len(calls), 1)
        args = json.loads(calls[0][3])
        self.assertEqual(args["path"], "c:/Users/buchh/projects/magazyn")
        self.assertEqual(args["glob"], "*.md")
        self.assertEqual(args["-n"], True)

    def test_write_with_nested_dsml_in_content(self):
        """BUG-034: content containing nested DSML markup must not truncate or break tool parsing."""
        text = """<｜｜DSML｜｜invoke name="Write">
<｜｜DSML｜｜parameter name="file_path">c:/Users/buchh/projects/magazyn/rozmowa.md</｜｜DSML｜｜>
<｜｜DSML｜｜parameter name="content">Here is the log:
<｜｜DSML｜｜invoke name="Read">
<｜｜DSML｜｜parameter name="file_path">c:/foo.txt</｜｜DSML｜｜>
</｜｜DSML｜｜invoke>
End of log.</｜｜DSML｜｜>
</｜｜DSML｜｜invoke>"""
        calls = server._parse_tool_calls(text)
        self.assertEqual(len(calls), 1)
        args = json.loads(calls[0][3])
        self.assertEqual(args["file_path"], "c:/Users/buchh/projects/magazyn/rozmowa.md")
        self.assertIn('<｜｜DSML｜｜invoke name="Read">', args["content"])
        self.assertIn("End of log.", args["content"])

    def test_search_replace_multiline(self):
        text = """<｜｜DSML｜｜invoke name="SearchReplace">
<｜｜DSML｜｜parameter name="file_path">c:/Users/buchh/projects/magazyn/README.md</｜｜DSML｜｜>
<｜｜DSML｜｜parameter name="old_str">line 1
line 2</｜｜DSML｜｜>
<｜｜DSML｜｜parameter name="new_str">line 1 modified
line 2 modified</｜｜DSML｜｜>
</｜｜DSML｜｜invoke>"""
        calls = server._parse_tool_calls(text)
        self.assertEqual(len(calls), 1)
        args = json.loads(calls[0][3])
        self.assertEqual(args["file_path"], "c:/Users/buchh/projects/magazyn/README.md")
        self.assertEqual(args["old_str"], "line 1\nline 2")
        self.assertEqual(args["new_str"], "line 1 modified\nline 2 modified")

    def test_sequential_tools(self):
        text = """<｜｜DSML｜｜invoke name="LS">
<｜｜DSML｜｜parameter name="path">c:/Users/buchh/projects/magazyn</｜｜DSML｜｜>
</｜｜DSML｜｜invoke>
<｜｜DSML｜｜invoke name="Read">
<｜｜DSML｜｜parameter name="file_path">c:/Users/buchh/projects/magazyn/README.md</｜｜DSML｜｜>
</｜｜DSML｜｜invoke>"""
        calls = server._parse_tool_calls(text)
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0][2], "LS")
        self.assertEqual(calls[1][2], "Read")

    def test_unclosed_tool_call_detection(self):
        """Ensure _has_unclosed_tool_call does not falsely report closed calls as unclosed."""
        complete_call = """<｜｜DSML｜｜invoke name="Read">
<｜｜DSML｜｜parameter name="file_path">c:/Users/buchh/projects/magazyn/o_tobie.md</｜｜DSML｜｜>
<｜｜DSML｜｜parameter name="limit" string="false">330</｜｜DSML｜｜>
</｜｜DSML｜｜invoke>"""
        self.assertFalse(server._has_unclosed_tool_call(complete_call))

        incomplete_call = '<｜｜DSML｜｜invoke name="Read"><｜｜DSML｜｜parameter name="file_path">c:/foo'
        self.assertTrue(server._has_unclosed_tool_call(incomplete_call))


    def test_write_with_unclosed_content_parameter(self):
        """When content parameter has no explicit closing tag, it must still be captured."""
        text = """<invoke name="Write">
<parameter name="file_path">c:/Users/buchh/test.txt</parameter>
<parameter name="content">hello world without close tag
</invoke>"""
        calls = server._parse_tool_calls(text)
        self.assertEqual(len(calls), 1)
        args = json.loads(calls[0][3])
        self.assertEqual(args["file_path"], "c:/Users/buchh/test.txt")
        self.assertIn("hello world", args.get("content", ""))

    def test_run_command_with_unclosed_command(self):
        """When command parameter has no explicit closing tag, it must still be captured."""
        text = """<invoke name="RunCommand">
<parameter name="cwd">c:/Users/buchh/projects</parameter>
<parameter name="command">npm run build
</invoke>"""
        calls = server._parse_tool_calls(text)
        self.assertEqual(len(calls), 1)
        args = json.loads(calls[0][3])
        self.assertEqual(args["cwd"], "c:/Users/buchh/projects")
        self.assertEqual(args["command"], "npm run build")

    def test_bare_unclosed_invoke_not_returned_as_complete(self):
        """A bare unclosed <invoke name='Read'> with no parameters must NOT be returned as complete."""
        text = '<invoke name="Read">'
        calls = server._parse_tool_calls(text)
        self.assertEqual(len(calls), 0)
        self.assertTrue(server._has_unclosed_tool_call(text))

    def test_unclosed_write_missing_content_not_returned(self):
        """An unclosed Write missing the required content field must NOT be returned as complete."""
        text = '<invoke name="Write"><parameter name="file_path">c:/foo.txt</parameter>'
        calls = server._parse_tool_calls(text)
        self.assertEqual(len(calls), 0)
        self.assertTrue(server._has_unclosed_tool_call(text))

    def test_dsml_open_without_invoke_keyword(self):
        """DSML opening tag without 'invoke' keyword like <｜｜DSML｜｜ name='Read'> must be recognized."""
        text = """<｜｜DSML｜｜ name="Read">
<｜｜DSML｜｜parameter name="file_path">c:/test.md</｜｜DSML｜｜>
</｜｜DSML｜｜invoke>"""
        calls = server._parse_tool_calls(text)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][2], "Read")
        args = json.loads(calls[0][3])
        self.assertEqual(args["file_path"], "c:/test.md")

    def test_multiple_consecutive_tools_second_unclosed(self):
        """First tool closed, second tool unclosed: classifier must see unclosed tool in tail."""
        text = """<｜｜DSML｜｜invoke name="LS">
<｜｜DSML｜｜parameter name="path">c:/Users/buchh</｜｜DSML｜｜>
</｜｜DSML｜｜invoke>
<｜｜DSML｜｜invoke name="Read">
<｜｜DSML｜｜parameter name="file_path">c:/Users/buchh/projects"""
        calls = server._parse_tool_calls(text)
        # LS is closed and valid
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][2], "LS")
        # Tail after LS must be detected as unclosed tool call
        tail = text[calls[-1][1]:]
        self.assertTrue(server._has_unclosed_tool_call(tail))

    def test_simulated_sse_stream_chunks(self):
        """Simulate chunked token delivery character by character and verify streaming invariants."""
        payload = """<｜｜DSML｜｜invoke name="Read">
<｜｜DSML｜｜parameter name="file_path">c:/Users/buchh/projects/magazyn/o_tobie.md</｜｜DSML｜｜>
<｜｜DSML｜｜parameter name="limit" string="false">330</｜｜DSML｜｜>
</｜｜DSML｜｜invoke>"""
        # While stream is arriving before </｜｜DSML｜｜invoke>, it must report unclosed
        for i in range(len('<｜｜DSML｜｜invoke name="Read">'), len(payload) - len('</｜｜DSML｜｜invoke>') - 5, 10):
            partial = payload[:i]
            self.assertTrue(server._has_unclosed_tool_call(partial))

        # Once the final closing tag arrives:
        self.assertFalse(server._has_unclosed_tool_call(payload))
        calls = server._parse_tool_calls(payload)
        self.assertEqual(len(calls), 1)
        args = json.loads(calls[0][3])
        self.assertEqual(args["file_path"], "c:/Users/buchh/projects/magazyn/o_tobie.md")
        self.assertEqual(args["limit"], 330)

    def test_chinese_param_tags(self):
        """DeepSeek Chinese parameter tags <参数 name="...">...</参数> must be parsed cleanly."""
        text = """<｜｜DSML｜｜invoke name="Read">
<参数 name="file_path">c:/test.txt</参数>
</｜｜DSML｜｜invoke>"""
        calls = server._parse_tool_calls(text)
        self.assertEqual(len(calls), 1)
        args = json.loads(calls[0][3])
        self.assertEqual(args["file_path"], "c:/test.txt")

    def test_param_tag_not_treated_as_invoke_open(self):
        """BUG-035: <｜｜DSML｜｜ parameter ...> must NOT be matched as a nested invoke opening tag.

        Regression: _INVOKE_OPEN_RE with an optional invoke keyword also matched the
        parameter tags, driving nesting depth to 7 and leaving count=0 (Trae hang).
        """
        text = """<｜｜DSML｜｜invoke name="Read">
<｜｜DSML｜｜parameter name="file_path">c:/x.md</｜｜DSML｜｜parameter>
<｜｜DSML｜｜parameter name="limit" string="false">200</｜｜DSML｜｜parameter>
</｜｜DSML｜｜invoke>"""
        self.assertEqual(len(server._INVOKE_OPEN_RE.findall(text)), 1)
        calls = server._parse_tool_calls(text, allow_unclosed=True)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][2], "Read")
        args = json.loads(calls[0][3])
        self.assertEqual(args["file_path"], "c:/x.md")
        self.assertEqual(args["limit"], 200)

    def test_malformed_slash_lead_param_tag(self):
        """BUG-035: malformed '</｜｜DSML｜｜ parameter name="command">' must still be recognized.

        DeepSeek sometimes emits a close-slash-prefixed parameter tag instead of an
        opening one, losing critical fields such as RunCommand.command.
        """
        text = """<｜｜DSML｜｜invoke name="RunCommand">
<｜｜DSML｜｜parameter name="blocking" string="false">true</｜｜DSML｜｜parameter>
</｜｜DSML｜｜parameter name="command" string="true">Get-ChildItem -Force</｜｜DSML｜｜parameter>
</｜｜ invoke>"""
        calls = server._parse_tool_calls(text, allow_unclosed=True)
        self.assertEqual(len(calls), 1)
        args = json.loads(calls[0][3])
        self.assertEqual(args["blocking"], True)
        self.assertEqual(args["command"], "Get-ChildItem -Force")

    def test_msys_path_normalized(self):
        """BUG-036: MSYS-style paths (/c:/... or /c/...) must be normalized to c:/..."""
        for raw in ("/c:/Users/x/proj/a.md", "/c/Users/x/proj/a.md"):
            text = f"""<｜｜DSML｜｜invoke name="Read">
<｜｜DSML｜｜parameter name="file_path">{raw}</｜｜DSML｜｜parameter>
</｜｜ invoke>"""
            calls = server._parse_tool_calls(text, allow_unclosed=True)
            self.assertEqual(len(calls), 1)
            args = json.loads(calls[0][3])
            self.assertEqual(args["file_path"], "c:/Users/x/proj/a.md")

    def test_absolute_path_in_glob_pattern_split(self):
        """BUG-036b: absolute path wrongly placed in Glob.pattern -> path + relative pattern."""
        text = """<｜｜DSML｜｜invoke name="Glob">
<｜｜DSML｜｜parameter name="pattern">c:/Users/x/proj/**/*.md</｜｜DSML｜｜parameter>
</｜｜ invoke>"""
        calls = server._parse_tool_calls(text, allow_unclosed=True)
        self.assertEqual(len(calls), 1)
        args = json.loads(calls[0][3])
        self.assertEqual(args["pattern"], "**/*.md")
        self.assertEqual(args["path"], "c:/Users/x/proj")

    def test_annotate_ls_missing_dirs_detected(self):
        """Test wykrywania uciętych katalogów na dysku przez _annotate_ls_tool_result."""
        import os, tempfile, shutil
        tmp = tempfile.mkdtemp()
        try:
            os.makedirs(os.path.join(tmp, "badania"))
            os.makedirs(os.path.join(tmp, "docs"))
            os.makedirs(os.path.join(tmp, "kod"))
            # Symulujemy ucięty listing, który zawiera tylko 'badania'
            truncated_ls = f"{tmp}/badania/file1.txt\n{tmp}/badania/file2.txt"
            annotated = server._annotate_ls_tool_result(truncated_ls, dir_path=tmp)
            self.assertIn("[DIRECTORY LISTING ALERT: TRUNCATED / INCOMPLETE]", annotated)
            self.assertIn("docs", annotated)
            self.assertIn("kod", annotated)
            self.assertIn("Get-ChildItem -Directory", annotated)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_compress_tool_results_tree_warning(self):
        """Test kompresji zbyt długiego wyniku drzewa/listingu katalogu."""
        tree_lines = [f"├── folder_{i}/" for i in range(1000)]
        big_tree = "\n".join(tree_lines)
        msgs = [{"role": "tool", "content": big_tree, "tool_call_id": "call_1"}]
        compressed = server._compress_tool_results(msgs, threshold=1000)
        content = compressed[0]["content"]
        self.assertIn("[DIRECTORY LISTING TRUNCATED", content)
        self.assertIn("Get-ChildItem -Directory", content)


if __name__ == "__main__":
    unittest.main()

