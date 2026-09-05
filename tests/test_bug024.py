import server, json

def test_dsml_asymmetric_open_close():
    raw_sample = """Wynik grep nie znalazł endpointów w tym fragmencie — szukam szerzej definicji tras HTTP.

<\uff5c\uff5cDSML\uff5c\uff5c name="Grep">
<parameter name="pattern">chat/completions|completions|@app\\.|add_api_route|APIRouter|def .*completion</parameter>
<parameter name="path">c:/Users/Ksawier/Pictures/Screenshots/Projekty_autorskie/deepseek-proxy-clean/server.py</parameter>
<parameter name="output_mode">content</parameter>
<parameter name="-n">true</parameter>
<parameter name="head_limit">80</parameter>
</invoke>"""
    tools = server._parse_tool_calls(raw_sample)
    assert len(tools) == 1
    start, end, name, args_str = tools[0]
    assert name == "Grep"
    args = json.loads(args_str)
    assert "chat/completions" in args["pattern"]
    assert args["path"] == "c:/Users/Ksawier/Pictures/Screenshots/Projekty_autorskie/deepseek-proxy-clean/server.py"

def test_resume_agent_directive_injected():
    msgs = [{"role": "user", "content": "kontynuuj"}]
    prompt = server._build_prompt(msgs, tools=None)
    assert "CRITICAL DIRECTIVE:" in prompt
    assert "<tool_call" in prompt
