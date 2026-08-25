import sys
sys.path.insert(0, '.')
import re
import json
import server

def replay_real_world_cases():
    test_cases = [
        {
            "id": "CASE_1_CHINESE_TAGS",
            "description": "DeepSeek emitting Chinese <参数> tags for Search subagent",
            "raw_stream": [
                "Zaraz przeszukam pliki projektu.\n",
                '<参数 name="description">Wyodrębnij specyfikację planu i zlecenia</参数> ',
                '<参数 name="query" string="true">Przeczytaj pliki c:/Users/Ksawier/project/doc.md</参数> ',
                '<参数 name="subagent_type" string="true">search</参数> ',
                '<参数 name="response_language" string="true">polski</参数>\n',
                "Czekam na wynik podagenta."
            ],
            "forbidden_in_content": ["<参数", "</参数", "Wyodrębnij", "Przeczytaj pliki", "search", "polski"],
            "expected_tools": ["Task"]
        },
        {
            "id": "CASE_2_CORRUPTED_DSML_USER_INPUT",
            "description": "DeepSeek emitting <user_input> instead of <DSML parameter>",
            "raw_stream": [
                "Sprawdzę na żywo. Najpierw zobaczę implementację klasyfikatora.\n",
                "<user_input> <user_input> <user_input>c:/Users/Ksawier/Pictures/Screenshots/Projekty_zlecenia/OLX/recon/probe_car_brands.py</｜｜DSML｜｜parameter> </｜｜DSML｜｜invoke\n",
                "Odpalę sondę na API.\n",
                "<user_input> <user_input> <user_input>c:/Users/Ksawier/Pictures/Screenshots/Projekty_zlecenia/OLX/recon/verify_cat_183.py</｜｜DSML｜｜parameter> <user_input># coding: utf-8\nimport requests\nprint('running')</｜｜DSML｜｜parameter> </｜｜DSML｜｜invoke\n",
                "Weryfikacja zakończona sukcesem."
            ],
            "forbidden_in_content": ["<user_input>", "DSML", "probe_car_brands.py", "verify_cat_183.py", "# coding: utf-8", "import requests"],
            "expected_tools": ["Read", "Write"]
        },
        {
            "id": "CASE_3_DIRECT_PARAM_TAGS",
            "description": "DeepSeek emitting direct <pattern> and <path> tags without invoke wrapper",
            "raw_stream": [
                "Szukam wystąpień polskich znaków w kodzie.\n",
                "<pattern>[ąćęłńóśźżĄĆĘŁŃÓŚŹŻ]</pattern>\n",
                "<path>c:\\Users\\Ksawier\\Pictures\\Screenshots\\Projekty_zlecenia\\Last_Z_BOT</path>\n\n",
                "<pattern>^\\s*(#|;|::|rem\\s)</pattern>\n",
                "<path>c:\\Users\\Ksawier\\Pictures\\Screenshots\\Projekty_zlecenia\\Last_Z_BOT</path>\n",
                "Analiza zakończona."
            ],
            "forbidden_in_content": ["<pattern>", "</pattern>", "<path>", "</path>", "[ąćęłńóśźżĄĆĘŁŃÓŚŹŻ]", "^\\s*(#|;|::|rem\\s)", "Last_Z_BOT"],
            "expected_tools": ["Grep", "Grep"]
        },
        {
            "id": "CASE_4_CASCADING_SHORTHAND",
            "description": "DeepSeek emitting stacked shorthand tags <glob> <grep> <read> </glob></grep></read>",
            "raw_stream": [
                "Przeszukuję katalogi:\n",
                "<glob> * c:/proj <grep> token c:/proj files_with_matches 50 <read> c:/proj/file.py 10 20 </glob></grep></read>\n",
                "Znaleziono pasujące pliki."
            ],
            "forbidden_in_content": ["<glob>", "</glob>", "<grep>", "</grep>", "<read>", "</read>", "token c:/proj", "c:/proj/file.py"],
            "expected_tools": ["Glob", "Grep", "Read"]
        },
        {
            "id": "CASE_5_PURE_MARKDOWN_CONVERSATION",
            "description": "Normal conversation with code snippets containing < and >",
            "raw_stream": [
                "Oto wyjaśnienie algorytmu:\n",
                "```python\n",
                "def check(a, b):\n",
                "    if a < 10 and b > 20:\n",
                "        return '<valid>'\n",
                "    return '<invalid>'\n",
                "```\n",
                "Mam nadzieję, że to jasne."
            ],
            "forbidden_in_content": [],
            "expected_tools": []
        },
        {
            "id": "CASE_6_LONG_PYTHON_WRITE",
            "description": "Writing large Python script via standard invoke",
            "raw_stream": [
                "Tworzę skrypt monitora.\n",
                '<invoke name="Write">\n',
                '<parameter name="file_path">c:/Users/Ksawier/project/monitor.py</parameter>\n',
                '<parameter name="content">\nimport time\nimport requests\n\ndef main():\n    for i in range(100):\n        print(f"Tick {i}")\n        time.sleep(1)\n\nif __name__ == "__main__":\n    main()\n</parameter>\n',
                '</invoke>\n',
                'Skrypt został utworzony i jest gotowy do uruchomienia.'
            ],
            "forbidden_in_content": ["<invoke", "</invoke", "<parameter", "</parameter", "import time", "import requests", "def main()", "Tick {i}"],
            "expected_tools": ["Write"]
        },
        {
            "id": "CASE_7_RUN_COMMAND_WITH_FLAGS",
            "description": "Running CLI command with multiple flags via shorthand DSML",
            "raw_stream": [
                "Uruchamiam testy regresyjne w terminalu:\n",
                "<user_input> <user_input> <user_input>pytest -v -s --tb=short tests/test_core.py</｜｜DSML｜｜parameter> <user_input>c:/Users/Ksawier/project</｜｜DSML｜｜parameter> </｜｜DSML｜｜invoke\n",
                "Czekam na zakończenie testów."
            ],
            "forbidden_in_content": ["<user_input>", "DSML", "pytest -v", "--tb=short", "test_core.py"],
            "expected_tools": ["RunCommand"]
        }
    ]

    import scratch.test_gated_streaming as streamer

    all_passed = True
    print("=" * 70)
    print("EMPIRICAL ENGINEERING AUDIT: REPLAYING ALL PRODUCTION FAILURE MODES")
    print("=" * 70)

    for tc in test_cases:
        cid = tc["id"]
        desc = tc["description"]
        print(f"\n[RUNNING] {cid}: {desc}")
        content, tools = streamer.simulate_gated_stream(tc["raw_stream"])
        
        # 1. Check for leaks in content
        leaks = []
        for forbidden in tc["forbidden_in_content"]:
            if forbidden in content:
                leaks.append(forbidden)
                
        # 2. Check tool extraction
        extracted_tools = [t[0] for t in tools]
        expected_tools = tc["expected_tools"]
        
        tool_mismatch = extracted_tools != expected_tools
        
        if leaks:
            print(f"  ❌ FAILED: Found {len(leaks)} leaked fragments in content: {leaks}")
            all_passed = False
        else:
            print(f"  ✅ CONTENT INTEGRITY: 0 leaks in streamed content.")
            
        if tool_mismatch:
            print(f"  ❌ TOOL MISMATCH: Expected {expected_tools}, Got {extracted_tools}")
            all_passed = False
        else:
            print(f"  ✅ TOOL EXTRACTION: 100% accurate ({extracted_tools}).")
            
        print(f"  --> Streamed Content Snippet: {repr(content[:60])}...")
        
    print("\n" + "=" * 70)
    if all_passed:
        print("ALL 7 EMPIRICAL TEST CASES PASSED WITH ZERO LEAKS AND 100% TOOL FIDELITY!")
    else:
        print("SOME TEST CASES FAILED!")
    print("=" * 70)
    return all_passed

if __name__ == '__main__':
    success = replay_real_world_cases()
    if not success:
        sys.exit(1)
