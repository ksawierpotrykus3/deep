import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import wasmtime
from pow import WASM_PATH, DeepSeekHash

def test_wasm_free_fix():
    hasher = DeepSeekHash().init(WASM_PATH)
    free_func = hasher.instance.exports(hasher.store)["__wbindgen_export_2"]
    
    ptrs = []
    for i in range(500):
        ptr, length = hasher._write_to_memory("test_string_to_measure_leakage")
        ptrs.append(ptr)
        # Free the allocated block: free(ptr, size, align)
        free_func(hasher.store, ptr, length, 1)
        
    print(f"[TEST FREE FIX] 1st allocated ptr: {ptrs[0]}, 500th allocated ptr: {ptrs[-1]}")
    if ptrs[-1] == ptrs[0]:
        print("[TEST FREE FIX] SUCCESS: With __wbindgen_export_2 called, memory is continuously reused at constant address (ZERO LEAK)!")
    else:
        print(f"[TEST FREE FIX] Pointer drifted: {ptrs[-1] - ptrs[0]}")

if __name__ == '__main__':
    test_wasm_free_fix()
