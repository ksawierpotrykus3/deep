import sys
sys.path.insert(0, '.')
import re
import json
import server

def simulate_gated_stream(raw_chunks):
    full = ""
    sent_until = 0
    tools_yielded = 0
    yielded_content = []
    yielded_tools = []
    
    for chunk in raw_chunks:
        full += chunk
        tools = server._parse_tool_calls(full)
        if tools:
            cursor = sent_until
            for ts, te, tname, targs in tools:
                if te <= cursor:
                    continue
                if ts > cursor:
                    text = server._STRIP_TAGS.sub("", full[cursor:ts])
                    if text.strip():
                        yielded_content.append(text)
                yielded_tools.append((tname, json.loads(targs)))
                cursor = te
            sent_until = cursor
        else:
            if server._has_unclosed_tool_call(full):
                # Gated holdback!
                continue
            delta = full[sent_until:]
            lt = delta.find('<')
            lb = delta.find('[')
            ld = delta.find('|')
            cand_pos = [p for p in (lt, lb, ld) if p != -1]
            first_delim = min(cand_pos) if cand_pos else -1
            
            if first_delim != -1:
                safe = delta[:first_delim]
                clean = server._STRIP_TAGS.sub("", safe)
                if clean.strip():
                    yielded_content.append(clean)
                if first_delim > 0:
                    sent_until += first_delim
                else:
                    delim_char = delta[0]
                    if delim_char == '<':
                        gt = delta.find('>')
                        if gt != -1:
                            tag = delta[:gt+1]
                            clean_tag = server._STRIP_TAGS.sub("", tag)
                            if clean_tag.strip():
                                yielded_content.append(clean_tag)
                            sent_until += gt + 1
                    elif delim_char == '[':
                        rb = delta.find(']')
                        if rb != -1:
                            bracket_tag = delta[:rb+1]
                            clean_bracket = server._STRIP_TAGS.sub("", bracket_tag)
                            if clean_bracket.strip():
                                yielded_content.append(clean_bracket)
                            sent_until += rb + 1
                    elif delim_char == '|':
                        if re.match(r'^[|\uff5c\u2502\s]*DSML', delta):
                            pass
                        else:
                            yielded_content.append("|")
                            sent_until += 1
            else:
                clean = server._STRIP_TAGS.sub("", delta)
                if clean.strip():
                    yielded_content.append(clean)
                sent_until = len(full)

    # End of stream final check
    final_tools = server._parse_tool_calls(full)
    if final_tools:
        cursor = sent_until
        for ts, te, tname, targs in final_tools:
            if te <= cursor:
                continue
            if ts > cursor:
                text = server._STRIP_TAGS.sub("", full[cursor:ts])
                if text.strip():
                    yielded_content.append(text)
            yielded_tools.append((tname, json.loads(targs)))
            cursor = te
        sent_until = cursor
        
    if sent_until < len(full):
        remaining = full[sent_until:]
        if not server._has_unclosed_tool_call(full) and not re.search(r'<\s*(?:[|\uff5c\u2502\s]*DSML|tool_call|invoke|_call|user_input)', remaining, re.IGNORECASE):
            clean_rem = server._STRIP_TAGS.sub("", remaining)
            if clean_rem.strip():
                yielded_content.append(clean_rem)
        
    return "".join(yielded_content), yielded_tools


def test_corrupted_user_input_stream():
    raw_stream = [
        "Sprawdzę na żywo kod klasyfikatora.\n",
        "<user_input> <user_input> <user_input>",
        "c:/Users/Ksawier/Pictures/Screenshots/Projekty_zlecenia/OLX/recon/probe_car_brands.py",
        "</｜｜DSML｜｜parameter> </｜｜DSML｜｜invoke\n",
        "Następnie sprawdzę monitor.\n",
        "<user_input> <user_input> <user_input>",
        "c:/Users/Ksawier/Pictures/Screenshots/Projekty_zlecenia/OLX/recon/verify_cat_183.py",
        "</｜｜DSML｜｜parameter> <user_input>",
        "# coding: utf-8\nprint('running verification')",
        "</｜｜DSML｜｜parameter> </｜｜DSML｜｜invoke\n",
        "Odpalam weryfikację w tle."
    ]
    
    content, tools = simulate_gated_stream(raw_stream)
    print("=== YIELDED CONTENT ===")
    print(repr(content))
    print("=== YIELDED TOOLS ===")
    for t in tools:
        print(t)
        
    assert "user_input" not in content
    assert "DSML" not in content
    assert "probe_car_brands.py" not in content
    assert "running verification" not in content
    assert "Sprawdzę na żywo kod klasyfikatora." in content
    assert "Następnie sprawdzę monitor." in content
    assert "Odpalam weryfikację w tle." in content
    assert len(tools) == 2
    assert tools[0][0] == "Read"
    assert tools[1][0] == "Write"
    print("\nDeterministic Gated Stream Test PASSED with 0 leaks!")

if __name__ == '__main__':
    test_corrupted_user_input_stream()
