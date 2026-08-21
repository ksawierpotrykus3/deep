import sys
sys.path.insert(0, ".")
from gemini_proxy.tool_parser import ToolStreamParser

parser = ToolStreamParser()
raw_stream = (
    'Checking code: <tool_call name="read_file">'
    '<parameter name="path">/app/main.py</parameter>'
    '</tool_call> Done.'
)

deltas = []
for ch in raw_stream:
    d_list = parser.process_chunk(ch)
    deltas.extend(d_list)
    print(f"Char: {repr(ch)} -> Buffer: {repr(parser.buffer)}, in_tool: {parser.in_tool_call}, deltas: {len(d_list)}")

deltas.extend(parser.finalize())

text_parts = [d.content for d in deltas if d.content]
full_text = "".join(text_parts)
print("FULL TEXT:", repr(full_text))
