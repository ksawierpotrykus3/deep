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
    
    # Check if a tool call at index i is an orphaned parameter block that might still be growing
    # (i.e. it ends at the current stream edge and lacks an explicit closing </invoke> tag)
    def is_growing_orphaned_block(ts, te, full_text):
        snippet = full_text[ts:te].strip()
        # If it's wrapped in an explicit invoke/tool_call/DSML invoke, it's NOT an orphaned growing block
        if re.search(r'</\s*(?:[|｜\uff5c\u2502\s]*DSML[|｜\uff5c\u2502\s]*)?(?:invoke|tool_call|tool)s?>', snippet, re.IGNORECASE):
            return False
        if '<｜tool call end｜>' in snippet:
            return False
        # If it reaches the end of current text, it might still have more parameters coming in next chunks
        if te >= len(full_text.rstrip()):
            return True
        return False

    for chunk in raw_chunks:
        full += chunk
        
        # Check if the buffer has any unclosed tag or ends with a parameter tag
        if server._has_unclosed_tool_call(full):
            continue
            
        # Check if current tail looks like an active parameter block
        tail = full[-100:]
        if re.search(r'</\s*(?:parameter|参数|參數|pattern|path|file_path|command)>\s*$', tail, re.IGNORECASE):
            # Still in parameter sequence, hold back until boundary
            continue

        tools = server._parse_tool_calls(full)
        if tools:
            cursor = sent_until
            for ts, te, tname, targs in tools:
                if te <= cursor:
                    continue
                if is_growing_orphaned_block(ts, te, full):
                    # Hold back growing orphaned block until next boundary or end of stream
                    continue
                if ts > cursor:
                    text = server._STRIP_TAGS.sub("", full[cursor:ts])
                    if text.strip():
                        yielded_content.append(text)
                yielded_tools.append((tname, json.loads(targs)))
                cursor = te
            sent_until = cursor
        else:
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

    # End of stream final check: resolve all final tools exactly once
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
        if not server._has_unclosed_tool_call(full) and not re.search(r'<\s*(?:[|\uff5c\u2502\s]*DSML|tool_call|invoke|_call|user_input|parameter|参数|參數|pattern|path)', remaining, re.IGNORECASE):
            clean_rem = server._STRIP_TAGS.sub("", remaining)
            if clean_rem.strip():
                yielded_content.append(clean_rem)
        
    return "".join(yielded_content), yielded_tools
