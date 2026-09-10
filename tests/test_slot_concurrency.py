import time
import threading
import pytest
import server
from server import AccountPool, Session, MAX_ACCOUNTS


def setup_function():
    for i in range(MAX_ACCOUNTS):
        server._slot_busy[i] = False
        server._rate_limited_until[i] = 0.0


def test_concurrent_subagents_get_unique_slots():
    ap = AccountPool()
    results = []
    barrier = threading.Barrier(5)

    def worker(worker_id):
        barrier.wait()
        slot = ap.acquire_slot(preferred_slot=None, timeout=5.0)
        results.append((worker_id, slot))
        time.sleep(0.05)
        ap.release_slot(slot)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(results) == 5
    assigned_slots = [slot for _, slot in results]
    unique_slots = set(assigned_slots)
    
    assert len(unique_slots) == 5, f"Wykryto kolizje slotow! Przydzielono: {assigned_slots}"
    assert not any(server._slot_busy[s] for s in assigned_slots)


def test_all_eight_slots_parallel_allocation():
    ap = AccountPool()
    num_workers = 8
    results = []
    barrier = threading.Barrier(num_workers)

    def worker(worker_id):
        barrier.wait()
        slot = ap.acquire_slot(preferred_slot=None, timeout=5.0)
        results.append((worker_id, slot))
        time.sleep(0.05)
        ap.release_slot(slot)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(num_workers)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(results) == num_workers
    assigned_slots = [slot for _, slot in results]
    assert len(set(assigned_slots)) == num_workers, f"Oczekiwano 8 unikalnych slotow, otrzymano: {assigned_slots}"


def test_queueing_when_more_workers_than_slots():
    ap = AccountPool()
    num_workers = 10
    results = []

    def worker(worker_id):
        slot = ap.acquire_slot(preferred_slot=None, timeout=10.0)
        results.append((worker_id, slot, time.time()))
        time.sleep(0.1)
        ap.release_slot(slot)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(num_workers)]
    start_time = time.time()
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    total_time = time.time() - start_time
    assert len(results) == num_workers
    assert total_time >= 0.15, f"Kolejkowanie nie zadzialalo poprawnie (czas: {total_time:.2f}s)"
    for i in range(8):
        assert server._slot_busy[i] is False


def test_preferred_slot_waiting_and_release():
    ap = AccountPool()
    server._slot_busy[3] = True

    def unlock_later():
        time.sleep(0.1)
        ap.release_slot(3)

    t = threading.Thread(target=unlock_later)
    t.start()

    acquired = ap.acquire_slot(preferred_slot=3, timeout=5.0)
    t.join()

    assert acquired == 3
    assert server._slot_busy[3] is True
    ap.release_slot(3)
    assert server._slot_busy[3] is False


def test_preferred_slot_fallback_on_rate_limit():
    ap = AccountPool()
    server._rate_limited_until[3] = time.time() + 120.0

    t0 = time.time()
    acquired = ap.acquire_slot(preferred_slot=3, timeout=5.0)
    elapsed = time.time() - t0

    assert elapsed < 0.2
    assert acquired != 3
    assert server._slot_busy[acquired] is True
    ap.release_slot(acquired)


def test_round_robin_fairness():
    ap = AccountPool()
    picks = []
    for _ in range(8):
        slot = ap.acquire_slot()
        picks.append(slot)
        ap.release_slot(slot)

    assert len(set(picks)) == 8, f"Round robin nie rozlozyl rownomiernie: {picks}"
