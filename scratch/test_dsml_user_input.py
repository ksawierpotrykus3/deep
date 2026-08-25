import re
import json

def test_dsml_user_input_leak():
    text = "<user_input> <user_input> <user_input>**/*</ | | DSML | | parameter> <user_input>c:/Users/Ksawier/Pictures/Screenshots/Projekty_zlecenia/OLX</ | | DSML | | parameter> </ | | DSML | | invoke"
    
    # Parser for DSML parameter blocks with corrupted opening tags (e.g. <user_input>val</ | | DSML | | parameter>)
    dsml_param_pat = re.compile(
        r'<(?:\w+)?>(.*?)</\s*(?:[|｜\uff5c\u2502\s]*DSML[|｜\uff5c\u2502\s]*)?parameter>',
        re.IGNORECASE
    )
    
    matches = list(dsml_param_pat.finditer(text))
    print(f"Found {len(matches)} DSML param matches:")
    params = []
    for m in matches:
        val = m.group(1).strip()
        # strip any residual leading tags like <user_input>
        val = re.sub(r'<[^>]*>', '', val).strip()
        params.append(val)
        print(f"  Param: {val}")
    
    # Infer Glob if one param is pattern and one is path
    if len(params) == 2:
        p1, p2 = params[0], params[1]
        is_path = lambda s: bool(re.search(r'^[a-zA-Z]:|^[\\/]|\.[\\/]', s)) or ('/' in s and '*' not in s)
        if is_path(p2) and not is_path(p1):
            tool_args = {"pattern": p1, "path": p2}
            print("Inferred Glob tool call:", tool_args)
            assert tool_args["pattern"] == "**/*"
            assert tool_args["path"] == "c:/Users/Ksawier/Pictures/Screenshots/Projekty_zlecenia/OLX"

if __name__ == "__main__":
    test_dsml_user_input_leak()
