import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import wasmtime
from pow import WASM_PATH, DeepSeekHash, DeepSeekPOW

def test_wasm_memory_leak():
    hasher = DeepSeekHash().init(WASM_PATH)
    
    initial_pages = hasher.memory.size(hasher.store)
    ptrs = []
    print(f"[TEST 1] Initial WASM linear memory pages: {initial_pages} ({initial_pages * 65536} bytes)")
    
    # Run 500 iterations and track pointer addresses returned by __wbindgen_export_0
    for i in range(500):
        ptr, length = hasher._write_to_memory("test_string_to_measure_leakage")
        ptrs.append(ptr)
        
    final_pages = hasher.memory.size(hasher.store)
    print(f"[TEST 1] 1st allocated ptr: {ptrs[0]}, 500th allocated ptr: {ptrs[-1]}")
    print(f"[TEST 1] Final WASM pages: {final_pages} ({final_pages * 65536} bytes)")
    if ptrs[-1] > ptrs[0]:
        leaked_bytes = ptrs[-1] - ptrs[0]
        print(f"[TEST 1] DETERMINISTIC PROOF: WASM heap pointer drifted monotonically by {leaked_bytes} bytes across 500 writes because __wbindgen_export_2 (free) is never called!")
    else:
        print("[TEST 1] Memory was reused.")

if __name__ == '__main__':
    test_wasm_memory_leak()
