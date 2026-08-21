import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import time
import threading
from pow import WASM_PATH, DeepSeekPOW, DeepSeekHash

def test_lock_contention():
    pow_solver = DeepSeekPOW()
    
    # Simulate 4 account slots requesting PoW at the same time
    # (using low difficulty 5000 so test runs in reasonable time, but creates measurable duration)
    config = {
        'algorithm': 'DeepSeekHashV1',
        'challenge': 'abcdef1234567890abcdef1234567890abcdef1234567890abcdef1234567890',
        'salt': 'salt_bench',
        'difficulty': 15000,
        'expire_at': 1700000000,
        'signature': 'test_sig',
        'target_path': '/api/v0/chat/completion'
    }
    
    times = {}
    threads = []
    
    def worker(slot_idx):
        start = time.time()
        res = pow_solver.solve_challenge(config)
        elapsed = time.time() - start
        times[slot_idx] = elapsed
        print(f"[CONCURRENCY TEST] Slot {slot_idx} completed in {elapsed:.3f}s")

    t0 = time.time()
    for i in range(4):
        t = threading.Thread(target=worker, args=(i,))
        threads.append(t)
        t.start()
        
    for t in threads:
        t.join()
        
    total_time = time.time() - t0
    sum_individual = sum(times.values())
    
    print(f"\n--- CONCURRENCY AUDIT METRICS ---")
    print(f"Total Wall Clock Time for 4 concurrent slots: {total_time:.3f}s")
    print(f"Individual thread wait+compute times: {[f'{times[i]:.3f}s' for i in range(4)]}")
    print(f"Serialization Factor: Total wall clock is ~{total_time / (sum_individual / 4):.1f}x single slot time")
    print(f"Head-of-line blocking observed: Last slot waited {max(times.values()):.3f}s!")

if __name__ == '__main__':
    test_lock_contention()
