import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import time
import threading
from pow import WASM_PATH, DeepSeekHash

def test_independent_hasher_parallelism():
    config = {
        'algorithm': 'DeepSeekHashV1',
        'challenge': 'abcdef1234567890abcdef1234567890abcdef1234567890abcdef1234567890',
        'salt': 'salt_bench',
        'difficulty': 150000,
        'expire_at': 1700000000,
    }
    
    # 1. Serial test (shared instance with lock)
    hasher_shared = DeepSeekHash().init(WASM_PATH)
    lock = threading.Lock()
    def worker_serial(res_dict, idx):
        t0 = time.time()
        with lock:
            ans = hasher_shared.calculate_hash(
                config['algorithm'], config['challenge'], config['salt'], config['difficulty'], config['expire_at']
            )
        res_dict[idx] = time.time() - t0

    res_serial = {}
    threads = [threading.Thread(target=worker_serial, args=(res_serial, i)) for i in range(4)]
    t0 = time.time()
    for t in threads: t.start()
    for t in threads: t.join()
    t_serial_total = time.time() - t0

    # 2. Parallel test (isolated instance per thread)
    def worker_parallel(res_dict, idx):
        hasher_local = DeepSeekHash().init(WASM_PATH)
        t0 = time.time()
        ans = hasher_local.calculate_hash(
            config['algorithm'], config['challenge'], config['salt'], config['difficulty'], config['expire_at']
        )
        res_dict[idx] = time.time() - t0

    res_parallel = {}
    threads = [threading.Thread(target=worker_parallel, args=(res_parallel, i)) for i in range(4)]
    t0 = time.time()
    for t in threads: t.start()
    for t in threads: t.join()
    t_parallel_total = time.time() - t0

    print(f"Serial with single lock total wall time: {t_serial_total:.3f}s (Slot latencies: {[f'{v:.3f}s' for v in res_serial.values()]})")
    print(f"Parallel with thread-local hasher wall time: {t_parallel_total:.3f}s (Slot latencies: {[f'{v:.3f}s' for v in res_parallel.values()]})")

if __name__ == '__main__':
    test_independent_hasher_parallelism()
