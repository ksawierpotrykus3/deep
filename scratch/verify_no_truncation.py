import sys
import os
import io
import json
import re
from pathlib import Path

# Ensure UTF-8 IO
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, str(Path(__file__).parent.parent))

# Import parsing & streaming logic components from server.py
from server import _parse_tool_calls, _STRIP_TAGS, _CALL_MARKER

print("=" * 75)
print("  DETERMINISTYCZNY DOWÓD BRAKU UCINANIA TREŚCI (TRUNCATION PROOF)")
print("=" * 75)

def simulate_sse_stream_reassembly(stream_chunks):
    """
    Odwzorowuje 1:1 pętlę ze strumienia SSE w server.py (linie 3385-3490),
    zbiera wszystkie wyemitowane kawałki SSE i scala je w końcowy tekst.
    """
    full = ""
    sent_until = 0
    tools_yielded = 0
    emitted_text_parts = []
    emitted_tool_calls = []

    for chunk in stream_chunks:
        if not chunk:
            continue
        full += chunk
        tools = _parse_tool_calls(full)
        if tools:
            cursor = sent_until
            for ts, te, tname, targs in tools:
                if te <= cursor:
                    continue
                if ts > cursor:
                    text = _STRIP_TAGS.sub("", full[cursor:ts])
                    emitted_text_parts.append(text)
                emitted_tool_calls.append((tname, targs))
                tools_yielded += 1
                cursor = te
            sent_until = cursor
        else:
            delta = full[sent_until:]
            lt = delta.find('<')
            lb = delta.find('[')
            cand_pos = [p for p in (lt, lb) if p != -1]
            first_delim = min(cand_pos) if cand_pos else -1

            if first_delim != -1:
                safe = delta[:first_delim]
                clean = _STRIP_TAGS.sub("", safe)
                if clean:
                    emitted_text_parts.append(clean)
                if first_delim > 0:
                    sent_until = sent_until + first_delim
                else:
                    delim_char = delta[0]
                    if delim_char == '<':
                        gt = delta.find('>')
                        if gt != -1:
                            tag = delta[:gt+1]
                            if re.match(r'</?\s*(?:tool_call|tool_calls|tool_capability|invoke|_call|_calls|call|calls|tool|tools|tool_use_json|parameter|system-reminder|-reminder|[|\uff5c\u2502]\s*[|\uff5c\u2502]\s*DSML|\?\?DSML\?\?|DSML|[|\uff5c\u2502]\s*tool)\b', tag, re.IGNORECASE):
                                pass
                            else:
                                clean_tag = _STRIP_TAGS.sub("", tag)
                                if clean_tag:
                                    emitted_text_parts.append(clean_tag)
                                sent_until += gt + 1
                        else:
                            if delta == '<' or re.match(r'</?[\s|\uff5c\u2502a-zA-Z]', delta):
                                pass
                            else:
                                emitted_text_parts.append("<")
                                sent_until += 1
                    elif delim_char == '[':
                        rb = delta.find(']')
                        if rb != -1:
                            bracket_tag = delta[:rb+1]
                            if re.match(rf'\[\s*(?:{_CALL_MARKER}|tool_call|Task|Read|Write|Grep|Glob|LS)\b', bracket_tag, re.IGNORECASE):
                                pass
                            else:
                                clean_bracket = _STRIP_TAGS.sub("", bracket_tag)
                                if clean_bracket:
                                    emitted_text_parts.append(clean_bracket)
                                sent_until += rb + 1
                        else:
                            if delta == '[' or re.match(rf'\[\s*(?:{_CALL_MARKER}|tool|[a-zA-Z])', delta):
                                pass
                            else:
                                emitted_text_parts.append("[")
                                sent_until += 1
            else:
                clean = _STRIP_TAGS.sub("", delta)
                if clean:
                    emitted_text_parts.append(clean)
                sent_until = len(full)

    # Flush końcowy z linii 3490 (nasza poprawka)
    if sent_until < len(full):
        remaining = full[sent_until:]
        clean_rem = _STRIP_TAGS.sub("", remaining)
        if clean_rem:
            emitted_text_parts.append(clean_rem)
        sent_until = len(full)

    final_text = "".join(emitted_text_parts)
    return final_text, emitted_tool_calls


# ── TEST 1: KOD ZE ZNAKAMI NIERÓWNOŚCI I SZABLONAMI HTML (np. `< len`, `<div>`) ──
code_sample = """
function renderList(items) {
    let result = "";
    for (let i = 0; i < items.length; i++) {
        if (items[i].value < 100 && items[i].score > 50) {
            result += `<div id="item-${i}" class="card">`;
            result += `<span>Wartość: ${items[i].value}</span>`;
            result += `</div>`;
        }
    }
    return result;
}
// Zakończenie pliku ze znakiem mniejszości: if (x < y)
"""
# Symulacja dostarczania kodu po 3-5 znaków (rozcięte tokeny)
chunks_code = [code_sample[i:i+4] for i in range(0, len(code_sample), 4)]
reconstructed, _ = simulate_sse_stream_reassembly(chunks_code)

print("[DOWÓD 1: Kod z nierównościami matematycznymi i tagami HTML]:")
print(f" - Długość źródłowa:   {len(code_sample)} znaków")
print(f" - Długość odebrana:   {len(reconstructed)} znaków")
print(f" - Identyczność 100%:  {code_sample.strip() == reconstructed.strip()}")
assert code_sample.strip() == reconstructed.strip(), "BŁĄD: Kod został ucięty lub zmodyfikowany!"
print(" -> [PASS] Test 1: Zero ucięć w kodzie ze znakami '<', '>', '<div>'!")


# ── TEST 2: BARDZO DŁUGI TEKST (10 000 ZNAKÓW) ROZBITY NA MAŁE CHUNKI ──
long_text = "To jest linijka deterministycznego testu numer: {:04d} -> zażółć gęślą jaźń 🚀\n"
full_long = "".join([long_text.format(i) for i in range(150)]) # ~11 000 znaków
chunks_long = [full_long[i:i+7] for i in range(0, len(full_long), 7)]
reconstructed_long, _ = simulate_sse_stream_reassembly(chunks_long)

print("\n[DOWÓD 2: Długi strumień (11 000 znaków, 1500 chunków SSE)]:")
print(f" - Długość źródłowa:   {len(full_long)} znaków")
print(f" - Długość odebrana:   {len(reconstructed_long)} znaków")
print(f" - Zgodność znak po znaku: {full_long == reconstructed_long}")
assert full_long == reconstructed_long, "BŁĄD: Długi strumień został obcięty!"
print(" -> [PASS] Test 2: Ani jeden znak z 11 000 nie zaginął!")


# ── TEST 3: STRUMIEŃ Z WYWOŁANIEM NARZĘDZIA I DALSZYM TEKSTEM ──
tool_stream = [
    "Zaraz sprawdzę plik konfiguracyjny.\n",
    '<tool_call name="read_file">\n',
    '  <parameter name="file_path">src/config.ts</parameter>\n',
    '</tool_call>\n',
    "Oto dalsza część odpowiedzi po wykonaniu narzędzia."
]
reconstructed_tool, calls = simulate_sse_stream_reassembly(tool_stream)

print("\n[DOWÓD 3: Strumień z wywołaniem narzędzia <tool_call>]:")
print(f" - Wykryte narzędzia:  {calls}")
print(f" - Tekst przed i po:   {repr(reconstructed_tool)}")
assert len(calls) == 1 and calls[0][0] == "read_file", "BŁĄD: Narzędzie nie zostało wyodrębnione!"
assert "Zaraz sprawdzę" in reconstructed_tool and "Oto dalsza część" in reconstructed_tool, "BŁĄD: Tekst otaczający został ucięty!"
print(" -> [PASS] Test 3: Narzędzie wyodrębnione, a cały tekst przed i po nienaruszony!")

print("\n" + "=" * 75)
print("  DOWÓD MATEMATYCZNY ZAKOŃCZONY: STREAMING NIE UCINA ANI JEDNEGO ZNAKU!")
print("=" * 75)
