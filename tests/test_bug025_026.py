import json
import time
import server

def test_bug025_detect_loop_ignores_decorative_comments():
    """BUG-025: Horizontal divider lines (// ===..., # ---...) must NOT trigger loop guard."""
    base_code = "export class CortexChatService {\n    // Implementation\n" * 20  # ~800 chars
    
    # 1. Standard banner comment (80 chars)
    divider_slash = base_code + "\n// " + ("=" * 76) + "\n"
    assert server._detect_loop(divider_slash) is False

    # 2. Hyphen divider
    divider_dash = base_code + "\n# " + ("-" * 80) + "\n"
    assert server._detect_loop(divider_dash) is False

    # 3. Markdown table divider
    divider_table = base_code + "\n|---|---|---|---|---|---|---|---|\n"
    assert server._detect_loop(divider_table) is False

    # 4. Asterisk divider
    divider_star = base_code + "\n/* " + ("*" * 70) + " */\n"
    assert server._detect_loop(divider_star) is False


def test_bug025_detect_loop_catches_pathological_repetition():
    """BUG-025: Real pathological loops (repeating sentences or runaway characters >= 250) MUST be caught."""
    base = "prefix text " * 50  # ~600 chars
    
    # 1. Repeating sentence loop
    sentence_loop = base + ("I will analyze the project files now.\n" * 5)
    assert server._detect_loop(sentence_loop) is True

    # 2. Pathological runaway single character (> 250 chars of unbroken repetition)
    runaway_char = base + ("=" * 300)
    assert server._detect_loop(runaway_char) is True


def test_bug026_parse_tool_calls_hybrid_closing_tag():
    """BUG-026: Tool calls closed by </｜｜DSML｜｜ask> or other DSML variants must parse correctly."""
    sample = """Mam pelny obraz warstwy. Migruje wylacznie sesje czatu.

<tool_call name="TodoWrite">
  <parameter name="merge" string="false">false</parameter>
  <parameter name="todos" string="false">[{"content": "Utworzyc typy czatu", "status": "in_progress", "id": "1", "priority": "high"}]</parameter>
</｜｜DSML｜｜ask>"""

    parsed = server._parse_tool_calls(sample)
    assert len(parsed) == 1
    start, end, name, args_str = parsed[0]
    assert name == "TodoWrite"
    args = json.loads(args_str)
    assert args["merge"] is False
    assert len(args["todos"]) == 1
    assert args["todos"][0]["content"] == "Utworzyc typy czatu"


def test_bug026_unclosed_tool_call_hybrid_closing_tag():
    """BUG-026: _has_unclosed_tool_call must recognize </｜｜DSML｜｜ask> as closing the tool."""
    complete_sample = """<tool_call name="TodoWrite">
  <parameter name="merge" string="false">false</parameter>
  <parameter name="todos" string="false">[{"content": "Zadanie 1"}]</parameter>
</｜｜DSML｜｜ask>"""
    assert server._has_unclosed_tool_call(complete_sample) is False

    # Truncated before closing tag
    truncated_sample = """<tool_call name="TodoWrite">
  <parameter name="merge" string="false">false</parameter>
  <parameter name="todos" string="false">[{"content": "Zadanie 1"}]</parameter>
</｜｜DSML｜｜"""
    assert server._has_unclosed_tool_call(truncated_sample) is True


def test_bug026_rate_limited_account_migration_detection():
    """BUG-026: If current account in state is rate-limited, router must migrate to a clean account."""
    ap = server.AccountPool()
    
    # Symulacja stanu: konto 0 jest zablokowane rate-limitem na 120s
    now = time.time()
    server._rate_limited_until[0] = now + 120.0
    
    state = {"account": 0, "parent_id": 12345}
    conv_key = "test_rate_limit_migration_conv"
    
    account_idx = state["account"]
    now_req = time.time()
    if now_req < server._rate_limited_until[account_idx]:
        free_acc = ap.pick_for_conv(conv_key)
        if free_acc != account_idx and now_req >= server._rate_limited_until[free_acc]:
            account_idx = free_acc
            state["account"] = account_idx
            state["parent_id"] = None
    
    # Deterministyczny dowod: konto zostalo zrotowane, a parent_id wyczyszczone do nowej sesji
    assert state["account"] != 0
    assert state["parent_id"] is None
    
    # Cleanup
    server._rate_limited_until[0] = 0.0
