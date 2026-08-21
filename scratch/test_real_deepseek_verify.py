import time
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

import mcp_server

def test_live():
    print("=== TEST PRAWDZIWEJ ODPOWIEDZI DEEPSEEK R1 (BEZ POŚREDNIKÓW) ===")
    t0 = time.time()
    
    code_to_check = """
def calculate_hash(self, challenge, prefix):
    ptr1 = self._write_to_memory(challenge)
    ptr2 = self._write_to_memory(prefix)
    res = self.instance.exports(self.store)["calculate"](self.store, ptr1, ptr2)
    return res
"""
    
    res = mcp_server.deepseek_critical_verify(
        task_context="Weryfikacja alokacji i zwalniania pamieci w module pow.py (WASM)",
        proposed_solution_or_diff=code_to_check,
        focus_area="Czy wskazniki ptr1 i ptr2 sa zwalniane po obliczeniu hasha?"
    )
    
    print(f"\n[CZAS GENEROWANIA: {time.time()-t0:.2f}s]")
    print("=" * 60)
    print("SUROWA ODPOWIEDZ ZWROCONA PRZEZ DEEPSEEK:")
    print("=" * 60)
    sys.stdout.buffer.write(res.encode("utf-8"))
    print("\n" + "=" * 60)

if __name__ == "__main__":
    test_live()
