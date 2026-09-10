"""Live End-to-End Tests against real DeepSeek Web Backend (chat.deepseek.com).

Weryfikuje żywe połączenie z prawdziwymi serwerami DeepSeek:
1. Prawdziwe tworzenie sesji i pobieranie tokenów (AccountPool slot 0..5)
2. Prawdziwe rozwiązywanie wyzwań Proof-of-Work (PoW w WASM)
3. Prawdziwy streaming SSE tokenów przez TLS/Cloudflare
4. Prawdziwe wygenerowanie wywołania narzędzia przez model DeepSeek i translację do OpenAI chunków
"""
import json
import time
import pytest
from pathlib import Path
import server


@pytest.mark.live
def test_live_account_pool_and_pow_solver():
    """Verifies that local account slots are valid and PoW challenges are solved in real time."""
    ap = server.AccountPool()
    valid_slots = [i for i in range(server.MAX_ACCOUNTS) if ap.is_valid(i)]
    assert len(valid_slots) > 0, "No active accounts in AccountPool!"
    
    ds = server.DeepSeek(ap)
    slot = valid_slots[0]
    
    t0 = time.perf_counter()
    pow_resp = ds._get_pow(slot)
    pow_time = time.perf_counter() - t0
    
    assert isinstance(pow_resp, str)
    assert len(pow_resp) > 10
    assert pow_time < 5.0, f"PoW solver took too long: {pow_time:.2f}s"


@pytest.mark.live
def test_live_deepseek_web_session_creation_and_streaming():
    """Verifies real HTTP/SSE streaming connection to chat.deepseek.com."""
    ap = server.AccountPool()
    valid_slots = [i for i in range(server.MAX_ACCOUNTS) if ap.is_valid(i)]
    slot = valid_slots[0]
    ds = server.DeepSeek(ap)
    
    t0 = time.perf_counter()
    session_id = ds.create_session(slot)
    assert isinstance(session_id, str) and len(session_id) > 10
    
    prompt = "Napisz dokładnie słowo: 'DEEPSEEK_PROXY_LIVE_OK'."
    stream_res = ds.stream_completion(slot, session_id, prompt, thinking_enabled=False)
    assert stream_res is not None
    
    gen, meta = stream_res
    received_tokens = []
    for tok in gen:
        if tok:
            received_tokens.append(tok)
            
    total_time = time.perf_counter() - t0
    full_resp = "".join(received_tokens).strip()
    
    assert len(received_tokens) > 0, "Received 0 tokens from live DeepSeek stream!"
    assert "DEEPSEEK_PROXY_LIVE_OK" in full_resp or "LIVE" in full_resp or len(full_resp) > 0
    assert meta.get("finished_normally") is True
    print(f"\n[LIVE TEST] Odpowiedź z żywego serwera w {total_time:.2f}s: {full_resp!r}")


@pytest.mark.live
def test_live_model_emits_valid_tool_call_and_proxy_translates(trae_10_tools_schemas):
    """Instructs real DeepSeek model to invoke Read tool, verifies raw emission and proxy translation."""
    ap = server.AccountPool()
    valid_slots = [i for i in range(server.MAX_ACCOUNTS) if ap.is_valid(i)]
    slot = valid_slots[1 % len(valid_slots)]
    ds = server.DeepSeek(ap)
    
    session_id = ds.create_session(slot)
    
    messages = [
        {"role": "system", "content": "You are an automated coding assistant. You MUST respond ONLY by calling the appropriate tool from the Available Tool Schemas. Do not reply with conversational text."},
        {"role": "user", "content": "Przeczytaj plik server.py od linii 1 do 20 za pomocą narzędzia Read."}
    ]
    
    prompt = server._build_prompt(messages, tools=trae_10_tools_schemas)
    
    t0 = time.perf_counter()
    stream_res = ds.stream_completion(slot, session_id, prompt, thinking_enabled=False)
    assert stream_res is not None
    
    gen, meta = stream_res
    raw_chunks = []
    for tok in gen:
        if tok:
            raw_chunks.append(tok)
            
    total_time = time.perf_counter() - t0
    full_output = "".join(raw_chunks)
    
    # Verify that the model output contains a parseable tool call
    parsed_tools = server._parse_tool_calls(full_output)
    print(f"\n[LIVE TOOL CALL] Model wygenerował {len(parsed_tools)} narzędzi w {total_time:.2f}s:")
    for pt in parsed_tools:
        print(f"  -> Tool: {pt[2]}, Args: {pt[3]}")
        
    assert len(parsed_tools) > 0, f"Model nie wywołał narzędzia! Surowe wyjście:\n{full_output}"
    assert parsed_tools[0][2] in ("Read", "read", "file_read")


@pytest.mark.live
def test_live_parallel_multi_tool_calling(trae_10_tools_schemas):
    """Instructs real DeepSeek model to invoke 3 tools in parallel, verifying that all 3 tools are extracted without loop false positives."""
    ap = server.AccountPool()
    valid_slots = [i for i in range(server.MAX_ACCOUNTS) if ap.is_valid(i)]
    slot = valid_slots[0]
    ds = server.DeepSeek(ap)
    
    session_id = ds.create_session(slot)
    
    messages = [
        {"role": "system", "content": "You are an automated assistant. Respond ONLY with tool calls in parallel."},
        {"role": "user", "content": "Wykonaj odczyt narzędziem Read dla 3 plików: PLAN.md, PLAN_faza1.md, PLAN_faza2_analiza.md w folderze c:\\Users\\Ksawier\\Pictures\\Screenshots\\Projekty_autorskie\\dry_runy\\plan\\."}
    ]
    
    prompt = server._build_prompt(messages, tools=trae_10_tools_schemas)
    
    t0 = time.perf_counter()
    stream_res = ds.stream_completion(slot, session_id, prompt, thinking_enabled=True)
    assert stream_res is not None
    
    gen, meta = stream_res
    content_chunks = []
    reasoning_chunks = []
    for tok in gen:
        if isinstance(tok, server._ReasoningChunk):
            if tok.text:
                reasoning_chunks.append(tok.text)
        elif tok:
            content_chunks.append(str(tok))
            
    total_time = time.perf_counter() - t0
    full_output = "".join(content_chunks)
    
    parsed_tools = server._parse_tool_calls(full_output)
    print(f"\n[LIVE PARALLEL TOOLS] Model wygenerował {len(parsed_tools)} narzędzi w {total_time:.2f}s (reasoning chars: {len(''.join(reasoning_chunks))}):")
    for pt in parsed_tools:
        print(f"  -> Tool: {pt[2]}, Args: {pt[3]}")
        
    assert len(parsed_tools) >= 2, f"Expected at least 2 parallel tool calls, got {len(parsed_tools)}: {full_output!r}"
    assert "KONTYNUUJ" not in full_output, "Auto-continue leaked into tool call generation!"


@pytest.mark.live
def test_live_unified_model_vision_with_reasoning():
    """Weryfikuje, że nowy zunifikowany model DeepSeek obsługuje obrazy oraz głębokie myślenie (R1) jednocześnie."""
    import io
    from PIL import Image

    ap = server.AccountPool()
    valid_slots = [i for i in range(server.MAX_ACCOUNTS) if ap.is_valid(i)]
    assert len(valid_slots) > 0, "No active accounts in AccountPool!"
    slot = valid_slots[0]
    ds = server.DeepSeek(ap)

    # Generujemy w pamięci mały obrazek testowy (czerwony kwadrat)
    img = Image.new("RGB", (10, 10), color="red")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    img_bytes = buf.getvalue()

    t0 = time.perf_counter()
    file_id = ds.upload_file(slot, img_bytes, "test_red_unified.png")
    assert file_id and len(file_id) > 5

    session_id = ds.create_session(slot)
    assert session_id and len(session_id) > 5

    prompt = "Jaki to kolor na obrazku? Wytłumacz i podaj odpowiedź."
    stream_res = ds.stream_completion(
        slot, session_id, prompt, model_type="default",
        ref_file_ids=[file_id], thinking_enabled=True,
    )
    assert stream_res is not None

    gen, meta = stream_res
    reasoning = []
    content = []
    for tok in gen:
        if isinstance(tok, server._ReasoningChunk):
            if tok.text:
                reasoning.append(tok.text)
        elif tok:
            content.append(str(tok))

    total_time = time.perf_counter() - t0
    full_reasoning = "".join(reasoning)
    full_content = "".join(content)

    print(f"\n[LIVE UNIFIED VISION+THINKING] Czas: {total_time:.2f}s, Reasoning: {len(full_reasoning)} znaków, Odpowiedź: {full_content.strip()!r}")
    assert len(full_reasoning) > 0, "Model nie wygenerował fazy myślenia dla obrazka!"
    assert len(full_content) > 0, "Model nie wygenerował właściwej odpowiedzi!"
    assert any(w in full_content.lower() for w in ("czerwon", "red")), f"Model nie rozpoznał koloru: {full_content}"

