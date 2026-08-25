import re
import json

def test_full_sequence():
    full_text = '''
<user_input> <user_input> <user_input>c:/Users/Ksawier/Pictures/Screenshots/Projekty_zlecenia/OLX/recon/probe_car_brands.py</｜｜DSML｜｜parameter> </｜｜DSML｜｜invoke
Read 3 files
Sprawdzę na żywo. Najpierw zobaczę implementację klasyfikatora i jak działa filtr aut, potem odpalę sondę na API.
<user_input> <user_input> <user_input>c:/Users/Ksawier/Pictures/Screenshots/Projekty_zlecenia/OLX/recon/monitor_20min.py</｜｜DSML｜｜parameter> </｜｜DSML｜｜invoke
Read 2 files
Sprawdzę to na żywo, żeby rozstrzygnąć sprzeczność między 09_mapa_kategorii_final.md (183 = wszystkie auta) a 13_wiedza_techniczna_olx.md (183 = tylko BMW). Odpalę sondę na API.
<user_input> <user_input> <user_input>c:/Users/Ksawier/Pictures/Screenshots/Projekty_zlecenia/OLX/recon/verify_cat_183.py</｜｜DSML｜｜parameter> <user_input># coding: utf-8\nprint('hello')</｜｜DSML｜｜parameter> </｜｜DSML｜｜invoke
Created 1 file
<user_input> <user_input> <user_input>python verify_cat_183.py</｜｜DSML｜｜parameter> <user_input>c:/Users/Ksawier/Pictures/Screenshots/Projekty_zlecenia/OLX/recon</｜｜DSML｜｜parameter> <user_input>true</｜｜DSML｜｜parameter> <user_input>short_running_process</｜｜DSML｜｜parameter> <user_input>false</｜｜DSML｜｜parameter> </｜｜DSML｜｜invoke
'''

    # Block pattern for each corrupted DSML invocation
    invoke_block_pat = re.compile(
        r'''((?:<\s*user_input\s*>\s*)+[\s\S]*?</\s*(?:[|｜\uff5c\u2502\s]*DSML[|｜\uff5c\u2502\s]*)?invoke\s*>?)''',
        re.IGNORECASE
    )
    
    dsml_param_pat = re.compile(
        r'(?:<\s*(?:\w+)?\s*>)*\s*([\s\S]*?)</\s*(?:[|｜\uff5c\u2502\s]*DSML[|｜\uff5c\u2502\s]*)?(?:parameter|参数|參數)>',
        re.IGNORECASE
    )
    
    results = []
    for bm in invoke_block_pat.finditer(full_text):
        block = bm.group(1)
        matches = list(dsml_param_pat.finditer(block))
        vals = []
        for m in matches:
            v = m.group(1).strip()
            v = re.sub(r'<\s*user_input\s*>', '', v, flags=re.IGNORECASE).strip()
            v = re.sub(r'<\s*\w+\s*>', '', v).strip()
            vals.append(v)
            
        inferred = None
        args = {}
        if len(vals) == 1:
            if re.search(r'\.[a-zA-Z0-9_-]+$', vals[0]) or ':/' in vals[0] or ':\\' in vals[0]:
                inferred = "Read"
                args = {"file_path": vals[0]}
        elif len(vals) >= 2:
            first, second = vals[0], vals[1]
            if first.startswith('python ') or first.startswith('npm ') or first.startswith('pytest ') or first.startswith('git ') or first.startswith('pip ') or (' ' in first and not first.startswith('#') and not re.search(r'^[a-zA-Z]:[\\/]', first)):
                inferred = "RunCommand"
                args = {"command": first, "cwd": second}
            elif (re.search(r'\.[a-zA-Z0-9_-]+$', first) or ':/' in first or ':\\' in first) and ('\n' in second or '# coding' in second or 'import ' in second or len(second) > 50):
                inferred = "Write"
                args = {"file_path": first, "content": second}
            elif '**' in first or '*' in first or (not ('/' in first or '\\' in first) and ('/' in second or '\\' in second)):
                inferred = "Glob"
                args = {"pattern": first, "path": second}
            elif ':/' in second or ':\\' in second:
                inferred = "Grep" if len(first) > 0 else "Glob"
                args = {"pattern": first, "path": second}
                
        if inferred:
            results.append((bm.start(), bm.end(), inferred, args))
            
    print(f"Parsed {len(results)} tool calls:")
    for r in results:
        print(f"  {r[2]}: {r[3]}")
        
    assert len(results) == 4
    assert results[0][2] == "Read"
    assert results[1][2] == "Read"
    assert results[2][2] == "Write"
    assert results[3][2] == "RunCommand"
    print("Full sequence passed!")

if __name__ == '__main__':
    test_full_sequence()
