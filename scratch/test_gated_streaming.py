import sys
sys.path.insert(0, '.')
import re
import json
import server

def simulate_gated_stream(raw_chunks):
    full = ""
    sent_until = 0
    yielded_content = []
    yielded_tools = []
    
    # An orphaned block is any tool call that lacks an explicit closing tool wrapper tag.
    def is_orphaned_block(ts, te, full_text):
        snippet = full_text[ts:te].strip()
        if re.search(r'</\s*(?:[|｜\uff5c\u2502\s]*DSML[|｜\uff5c\u2502\s]*)?(?:invoke|tool_call|tool)s?>', snippet, re.IGNORECASE):
            return False
        if '<｜tool call end｜>' in snippet:
            return False
        if re.search(r'</\s*(?:glob|grep|read|write|task|skill)\s*>', snippet, re.IGNORECASE):
            return False
        # If it's pure <parameter...> or <参数...> or <pattern...> without outer wrapper, it is orphaned
        return True

    for chunk in raw_chunks:
        full += chunk
        
        # 1. Parse complete tools from full text
        tools = server._parse_tool_calls(full)
        if tools:
            cursor = sent_until
            all_resolved = True
            for ts, te, tname, targs in tools:
                if te <= cursor:
                    continue
                # If it's an orphaned block without explicit outer wrapper, hold it until stream end
                if is_orphaned_block(ts, te, full):
                    all_resolved = False
                    continue
                if ts > cursor:
                    text = server._STRIP_TAGS.sub("", full[cursor:ts])
                    if text.strip():
                        yielded_content.append(text)
                yielded_tools.append((tname, json.loads(targs)))
                cursor = te
            sent_until = cursor
            if not all_resolved:
                continue

        # 2. If any tool call or unclosed tag is active in remaining tail, DO NOT YIELD CONTENT
        if server._has_unclosed_tool_call(full):
            continue

        tail = full[sent_until:]
        if re.search(r'</?\s*(?:[|｜\uff5c\u2502\s]*DSML|tool_call|invoke|_call|user_input|parameter|参数|參數|pattern|path|file_path|command|glob|grep|read|write|task|skill)\b', tail, re.IGNORECASE):
            continue
            
        # 3. Only stream safe text before delimiters
        delta = full[sent_until:]
        lt = delta.find('<')
        lb = delta.find('[')
        ld = delta.find('|')
        cand_pos = [p for p in (lt, lb, ld) if p != -1]
        first_delim = min(cand_pos) if cand_pos else -1
        
        if first_delim != -1:
            if first_delim > 0:
                safe = delta[:first_delim]
                clean = server._STRIP_TAGS.sub("", safe)
                if clean.strip():
                    yielded_content.append(clean)
                sent_until += first_delim
        else:
            last_nl = delta.rfind('\n')
            if last_nl != -1:
                safe = delta[:last_nl+1]
                clean = server._STRIP_TAGS.sub("", safe)
                if clean.strip():
                    yielded_content.append(clean)
                sent_until += last_nl + 1

    # End of stream final resolution: resolve all remaining/orphaned tools exactly once
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
