import sys
sys.path.insert(0, '.')
import random
import re
import json
import scratch.test_gated_streaming as streamer

def run_chaos_fuzzing():
    """
    CHAOS & FUZZING TEST:
    Tests streaming resilience against extreme network packet fragmentation.
    Instead of neat multi-word chunks, we slice raw responses into random
    1-to-4 character chunks across 500 randomized runs.
    """
    raw_payloads = [
        # Payload 1: Chinese parameters
        (
            'Zaraz przeszukam pliki.\n'
            '<参数 name="description">Szukaj specyfikacji</参数> '
            '<参数 name="query">Czytaj c:/proj/doc.md</参数> '
            '<参数 name="subagent_type">search</参数>\n'
            'Koniec zadania.',
            ["<参数", "</参数", "Szukaj specyfikacji", "Czytaj c:/proj/doc.md", "search"],
            ["Task"]
        ),
        # Payload 2: Corrupted DSML user_input
        (
            'Sprawdzam kod.\n'
            '<user_input> <user_input> <user_input>c:/Users/proj/probe.py</｜｜DSML｜｜parameter> </｜｜DSML｜｜invoke\n'
            '<user_input> <user_input> <user_input>c:/Users/proj/test.py</｜｜DSML｜｜parameter> <user_input># coding: utf-8\nprint(123)</｜｜DSML｜｜parameter> </｜｜DSML｜｜invoke\n'
            'Zrobione.',
            ["<user_input>", "DSML", "probe.py", "test.py", "# coding: utf-8", "print(123)"],
            ["Read", "Write"]
        ),
        # Payload 3: Direct param tags
        (
            'Szukam regexem.\n'
            '<pattern>[ąćęłńóśźż]</pattern>\n<path>c:\\Users\\proj</path>\n'
            '<pattern>def test_</pattern>\n<path>c:\\Users\\proj\\tests</path>\n'
            'Gotowe.',
            ["<pattern>", "</pattern>", "<path>", "</path>", "[ąćęłńóśźż]", "def test_", "c:\\Users\\proj"],
            ["Grep", "Grep"]
        ),
        # Payload 4: Shorthand cascading tags
        (
            'Szukanie hurtowe.\n'
            '<glob> * c:/proj <grep> token c:/proj files_with_matches 50 <read> c:/proj/file.py 10 20 </glob></grep></read>\n'
            'Znaleziono.',
            ["<glob>", "</glob>", "<grep>", "</grep>", "<read>", "</read>", "token c:/proj", "c:/proj/file.py"],
            ["Glob", "Grep", "Read"]
        ),
        # Payload 5: Run command with flags
        (
            'Odpalam testy.\n'
            '<user_input> <user_input> <user_input>pytest -v --tb=short tests/test_core.py</｜｜DSML｜｜parameter> <user_input>c:/proj</｜｜DSML｜｜parameter> </｜｜DSML｜｜invoke\n'
            'Czekam.',
            ["<user_input>", "DSML", "pytest -v", "--tb=short", "test_core.py"],
            ["RunCommand"]
        )
    ]

    random.seed(42)  # Deterministic seed
    total_runs = 0
    total_leaks = 0
    total_tool_errors = 0

    print("=" * 70)
    print("STARTING 500-RUN CHAOS & FRAGMENTATION FUZZING TEST")
    print("=" * 70)

    for payload_idx, (text, forbidden_list, expected_tools) in enumerate(raw_payloads, 1):
        print(f"\n[PAYLOAD {payload_idx}] Testing 100 randomized chunk partitionings...")
        for run_idx in range(100):
            total_runs += 1
            # Generate random slice points (1 to 4 characters per chunk)
            chunks = []
            pos = 0
            while pos < len(text):
                step = random.randint(1, 4)
                chunks.append(text[pos:pos+step])
                pos += step
                
            content, tools = streamer.simulate_gated_stream(chunks)
            
            # Check leaks
            leaked = [f for f in forbidden_list if f in content]
            if leaked:
                total_leaks += 1
                print(f"  ❌ RUN {run_idx} LEAK: {leaked} in content: {repr(content)}")
                break
                
            # Check tools
            extracted = [t[0] for t in tools]
            if extracted != expected_tools:
                total_tool_errors += 1
                print(f"  ❌ RUN {run_idx} TOOL MISMATCH: Expected {expected_tools}, Got {extracted}")
                break

    print("\n" + "=" * 70)
    print(f"CHAOS FUZZING RESULTS:")
    print(f"  Total randomized streaming runs: {total_runs}")
    print(f"  Total content leaks detected:    {total_leaks}")
    print(f"  Total tool call mismatches:     {total_tool_errors}")
    print("=" * 70)

    assert total_leaks == 0, f"Found {total_leaks} leaks during chaos fuzzing!"
    assert total_tool_errors == 0, f"Found {total_tool_errors} tool mismatches during chaos fuzzing!"
    print("DETERMINISTIC PROOF: 0 LEAKS, 0 TOOL ERRORS ACROSS ALL 500 CHAOTIC RUNS!")

if __name__ == '__main__':
    run_chaos_fuzzing()
