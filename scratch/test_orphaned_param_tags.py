import re
import json

def test_orphaned_tags():
    text = (
        '\n<pattern>[ąćęłńóśźżĄĆĘŁŃÓŚŹŻ]</pattern>\n'
        '<path>c:\\Users\\Ksawier\\Pictures\\Screenshots\\Projekty_zlecenia\\Last_Z_BOT</path>\n\n'
        '<pattern>^\\s*(#|;|::|rem\\s)</pattern>\n'
        '<path>c:\\Users\\Ksawier\\Pictures\\Screenshots\\Projekty_zlecenia\\Last_Z_BOT</path>\n'
    )
    
    known_param_names = {'pattern', 'path', 'file_path', 'content', 'command', 'query', 'description', 'subagent_type', 'offset', 'limit', 'output_mode', 'glob'}
    param_pat_str = '|'.join(known_param_names)
    
    # 1c. Scan individual parameter tags and group them into tool calls
    matches = list(re.finditer(rf'<\s*({param_pat_str})\b[^>]*>([\s\S]*?)</\s*\1>', text, re.IGNORECASE))
    
    def infer_tool(params):
        if 'pattern' in params:
            return 'Grep'
        elif 'file_path' in params:
            return 'Write' if 'content' in params else 'Read'
        elif 'command' in params:
            return 'RunCommand'
        elif 'query' in params or 'description' in params:
            return 'Task'
        elif 'path' in params and 'glob' in params:
            return 'Glob'
        return None

    results = []
    cur_params = {}
    cur_start = None
    cur_end = None
    
    for m in matches:
        k = m.group(1).lower()
        v = m.group(2).strip()
        
        # If this key already exists in cur_params, flush the current tool call
        if k in cur_params:
            tname = infer_tool(cur_params)
            if tname:
                results.append((cur_start, cur_end, tname, json.dumps(cur_params)))
            cur_params = {}
            cur_start = None
        
        if cur_start is None:
            cur_start = m.start()
        cur_end = m.end()
        cur_params[k] = v

    if cur_params:
        tname = infer_tool(cur_params)
        if tname:
            results.append((cur_start, cur_end, tname, json.dumps(cur_params)))

    print(f'Parsed {len(results)} orphaned tool calls:')
    for r in results:
        print(r)
    assert len(results) == 2
    assert results[0][2] == 'Grep'
    assert json.loads(results[0][3])['pattern'] == '[ąćęłńóśźżĄĆĘŁŃÓŚŹŻ]'
    assert results[1][2] == 'Grep'
    assert json.loads(results[1][3])['pattern'] == '^\\s*(#|;|::|rem\\s)'
    print('Test passed!')

if __name__ == '__main__':
    test_orphaned_tags()
