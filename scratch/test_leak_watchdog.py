import sys
sys.path.insert(0, '.')
import os
import server

def test_leak_watchdog():
    # 1. Clean markdown should NOT trigger leak log
    initial_size = os.path.getsize(server.LEAKS_LOG_FILE)
    
    server._log_leak_if_any("Oto jest normalna odpowiedź z kodem python:\n```python\nif a < b:\n  pass\n```", conv_key="test_clean")
    after_clean_size = os.path.getsize(server.LEAKS_LOG_FILE)
    assert after_clean_size == initial_size, "Clean markdown falsely triggered leak log!"
    print("✅ Clean text test passed (no false positives)")

    # 2. Leaked tag should deterministically append to leaks.log
    server._log_leak_if_any("Sprawdzam kod <user_input> probe.py </｜｜DSML｜｜parameter>", conv_key="test_leak")
    after_leak_size = os.path.getsize(server.LEAKS_LOG_FILE)
    assert after_leak_size > initial_size, "Leak was NOT logged to leaks.log!"
    print("✅ Leaked tag test passed (leak was recorded in leaks.log)")

    # Read last line of leaks.log
    with open(server.LEAKS_LOG_FILE, "r", encoding="utf-8") as f:
        lines = f.readlines()
        last_line = lines[-1]
        assert "LEAK DETECTED" in last_line
        assert "test_leak" in last_line
        print(f"✅ Log entry verified: {last_line.strip()}")

if __name__ == '__main__':
    test_leak_watchdog()
