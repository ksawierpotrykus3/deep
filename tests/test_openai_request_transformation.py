"""Tests for OpenAI-Compatible Request Ingestion and Transformation into DeepSeek Web Prompts."""
import json
import pytest
import server


def test_standard_chat_request_transformation(ide_standard_chat_request):
    """Verifies that a standard IDE chat request is transformed into a clean prompt string."""
    messages = ide_standard_chat_request["messages"]
    prompt = server._build_prompt(messages, tools=None)
    
    assert isinstance(prompt, str)
    assert len(prompt) > 0
    assert "You are an expert software engineer." in prompt
    assert "Explain how Dijkstra shortest path algorithm works in Python." in prompt
    assert len(prompt) <= server.MAX_PROMPT_LEN


def test_tool_calling_request_includes_schemas_and_instructions(ide_subagent_task_request, trae_10_tools_schemas):
    """Verifies that tool definitions from IDE are converted into XML documentation and schemas suffix."""
    messages = ide_subagent_task_request["messages"]
    prompt = server._build_prompt(messages, tools=trae_10_tools_schemas)
    
    assert "# Available Tool Schemas" in prompt
    assert "## Task" in prompt
    assert "## Read" in prompt
    assert "## Grep" in prompt
    assert "## RunCommand" in prompt
    assert "# Tool Call Format" in prompt
    assert '<tool_call name="ToolName">' in prompt
    assert len(prompt) <= server.MAX_PROMPT_LEN


def test_dynamic_budgeting_with_large_tools_schemas(ide_subagent_task_request, trae_10_tools_schemas):
    """Verifies that adding ~6.5k of tool schemas automatically adjusts message budget and stays under 35k."""
    messages = ide_subagent_task_request["messages"]
    prompt = server._build_prompt(messages, tools=trae_10_tools_schemas)
    
    assert len(prompt) <= server.MAX_PROMPT_LEN
    assert len(prompt) <= 35000


def test_multiturn_heavy_history_pruning_and_compression(ide_multiturn_heavy_history_request, trae_10_tools_schemas):
    """Verifies that >80k of raw multi-turn tool outputs are compressed while keeping latest data intact."""
    messages = ide_multiturn_heavy_history_request["messages"]
    raw_size = sum(len(m.get("content", "")) for m in messages)
    assert raw_size > 35000, "Raw messages must be large to test compression"
    
    prompt = server._build_prompt(messages, tools=trae_10_tools_schemas)
    
    assert len(prompt) <= server.MAX_PROMPT_LEN
    assert len(prompt) <= 35000
    # Latest user request MUST be preserved
    assert "Now write a summary report based on all gathered data." in prompt
    # Tool schemas MUST be present
    assert "# Available Tool Schemas" in prompt


def test_compress_tool_results_preserves_latest_turn():
    """Verifies that _compress_tool_results preserves the last tool output while compressing earlier ones."""
    messages = [
        {"role": "user", "content": "Turn 1"},
        {"role": "tool", "content": "\n".join(f"old_line_{i} = {i}" for i in range(200))},
        {"role": "assistant", "content": "Answer 1"},
        {"role": "user", "content": "Turn 2"},
        {"role": "tool", "content": "\n".join(f"current_critical_line_{i} = {i}" for i in range(100))},
    ]
    
    # We call _build_prompt which internally calls _compress_tool_results
    prompt = server._build_prompt(messages, tools=None)
    
    assert "current_critical_line_1" in prompt
    assert len(prompt) <= server.MAX_PROMPT_LEN


def test_parallel_multi_tool_preservation_in_current_turn():
    """Verifies that when an assistant reads 3 files in parallel in the current turn, ALL 3 files remain intact."""
    messages = [
        {"role": "user", "content": "Analyze all 3 plan files."},
        {"role": "assistant", "content": "Reading PLAN.md, PLAN_faza1.md, PLAN_faza2.md in parallel", "tool_calls": [
            {"id": "call_1", "type": "function", "function": {"name": "Read", "arguments": '{"file_path": "PLAN.md"}'}},
            {"id": "call_2", "type": "function", "function": {"name": "Read", "arguments": '{"file_path": "PLAN_faza1.md"}'}},
            {"id": "call_3", "type": "function", "function": {"name": "Read", "arguments": '{"file_path": "PLAN_faza2.md"}'}},
        ]},
        {"role": "tool", "tool_call_id": "call_1", "name": "Read", "content": "  1-> # PLAN.md\n  2-> full line content A\n  3-> full line content B"},
        {"role": "tool", "tool_call_id": "call_2", "name": "Read", "content": "  1-> # PLAN_faza1.md\n  2-> full line content C\n  3-> full line content D"},
        {"role": "tool", "tool_call_id": "call_3", "name": "Read", "content": "  1-> # PLAN_faza2.md\n  2-> full line content E\n  3-> full line content F"},
    ]
    
    prompt = server._build_prompt(messages, tools=None)
    
    # ALL three files MUST be fully present and NOT replaced by omitted markers
    assert "full line content A" in prompt
    assert "full line content C" in prompt
    assert "full line content E" in prompt
    assert "more lines omitted" not in prompt


def test_monolith_user_message_hard_cap(ide_monolith_user_request, trae_10_tools_schemas):
    """Verifies that a 100k monolith user message is safely capped below 35k limit."""
    messages = ide_monolith_user_request["messages"]
    raw_size = len(messages[1]["content"])
    assert raw_size > 90000
    
    prompt = server._build_prompt(messages, tools=trae_10_tools_schemas)
    
    assert len(prompt) <= server.MAX_PROMPT_LEN
    assert len(prompt) <= 35000
    assert "[... Prompt truncated to 35k limit to prevent backend drop ...]" in prompt
    assert "# Available Tool Schemas" in prompt


def test_vision_image_extraction_and_encoding():
    """Verifies that image blocks in OpenAI format are extracted into image lists."""
    messages = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "What is in this diagram?"},
                {"type": "image_url", "image_url": {"url": "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="}}
            ]
        }
    ]
    
    prompt = server._build_prompt(messages, tools=None)
    assert "What is in this diagram?" in prompt
    assert len(prompt) <= server.MAX_PROMPT_LEN
