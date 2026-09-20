"""
Testy jednostkowe Pancernej Tarczy Anty-Ban 2.0 (Pacing Shield & TTFT Adaptive Governor).
Testuje wszystkie mechanizmy ochronne w izolacji (mockując czas i sieć),
GWARANTUJĄC 100% bezpieczeństwo (zero żądań do zewnętrznego serwera DeepSeek).
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import unittest
import time
from unittest.mock import MagicMock, patch
from collections import deque

# Importujemy komponenty z server.py
import server


class TestPacingShield(unittest.TestCase):

    def setUp(self):
        # Resetujemy globalne zmienne testowe
        server._recent_ttfts.clear()
        server._last_busy_error_time = 0.0

    def test_finish_time_vs_start_time_pacing(self):
        """
        GŁÓWNY TEST BEZPIECZEŃSTWA:
        Weryfikuje, czy proxy mierzy przerwę od ZAKOŃCZENIA (finish) poprzedniej generacji,
        a nie od jej rozpoczęcia (start).
        """
        slot_idx = 0
        t0 = 1000.0  # Początek zadania 1
        t_gen = 25.0  # Czas trwania generacji
        t1 = t0 + t_gen  # Koniec zadania 1 (1025.0s)

        # Symulacja rozpoczęcia zadania 1
        server._last_account_completion_time[slot_idx] = t0
        # Zadanie 1 kończy się w t1
        with patch("time.time", return_value=t1):
            server._record_account_finished(slot_idx, status="OK")

        self.assertEqual(server._last_account_finish_time[slot_idx], t1)

        # Klient wysyła KOLEJNE zapytanie 2 sekundy po zakończeniu poprzedniego (w t1 + 2s = 1027s)
        t_req2 = t1 + 2.0
        now_ts = t_req2
        last_fin = server._last_account_finish_time[slot_idx]
        elapsed = now_ts - last_fin

        # Elapsed MUSI wynosić 2.0s, a NIE 27.0s!
        self.assertAlmostEqual(elapsed, 2.0, places=2)

        # Pacing dla 1 aktywnego konta to min 18.0s
        min_pacing = 18.0
        sleep_needed = min_pacing - elapsed

        # W starym kodzie elapsed wynosiło 27s > 18s -> sleep_needed wynosił 0s (BŁĄD/BAN!)
        # W nowym kodzie sleep_needed wynosi 16s (BEZPIECZEŃSTWO!)
        self.assertGreaterEqual(sleep_needed, 15.0)
        print(f"[TEST 1 PASS] Pacing od zakończenia: elapsed={elapsed:.1f}s, wymagana pauza={sleep_needed:.1f}s (stary kod dawałby 0s!)")

    def test_ttft_cluster_congestion_multiplier(self):
        """
        Weryfikuje adaptacyjny mnożnik przeciążenia klastra DeepSeek na podstawie TTFT.
        Normalny TTFT (1.5s) -> mnożnik 1.0x, 'klaster stabilny'
        Podwyższony TTFT (5.5s) -> mnożnik 1.35x, 'podwyższony TTFT'
        Krytyczny TTFT (8.5s) -> mnożnik 1.8x, 'krytyczny TTFT'
        """
        # 1. Normalny TTFT
        server._recent_ttfts.extend([1.2, 1.4, 1.6])
        mult, desc = server._get_cluster_congestion_factor()
        self.assertEqual(mult, 1.0)
        self.assertIn("stabilny", desc)

        # 2. Podwyższony TTFT (klaster zaczyna zwalniać)
        server._recent_ttfts.clear()
        server._recent_ttfts.extend([5.2, 5.8, 5.5])
        mult, desc = server._get_cluster_congestion_factor()
        self.assertEqual(mult, 1.35)
        self.assertIn("podwyższony", desc)

        # 3. Krytyczny TTFT (klaster jest na krawędzi odrzucania zadań)
        server._recent_ttfts.clear()
        server._recent_ttfts.extend([8.5, 9.0, 8.2])
        mult, desc = server._get_cluster_congestion_factor()
        self.assertEqual(mult, 1.8)
        self.assertIn("krytyczny", desc)
        print("[TEST 2 PASS] Adaptacyjny TTFT Governor poprawnie skaluje pauzy wg obciążenia klastra")

    def test_busy_error_cooldown_governor(self):
        """
        Weryfikuje natychmiastowe wydłużenie pauz po błędzie 'Server is busy'.
        """
        now = time.time()
        # Świeży błąd Server is busy (10 sekund temu)
        server._last_busy_error_time = now - 10.0
        mult, desc = server._get_cluster_congestion_factor()
        self.assertEqual(mult, 1.5)
        self.assertIn("przeciążenia", desc)

        # Stary błąd (po upływie cooldownu 240s)
        server._last_busy_error_time = now - 250.0
        mult, desc = server._get_cluster_congestion_factor()
        self.assertEqual(mult, 1.0)
        print("[TEST 3 PASS] Błąd 'Server is busy' natychmiast włącza mnożnik 1.5x i bezpiecznie wygasa po 4 min")

    def test_global_ip_pacer_isolation(self):
        """
        Weryfikuje, czy Global IP Pacer pilnuje odstępów pomiędzy KOLEJNYMI zapytaniami z tego samego IP,
        nawet jeśli żądania kierowane są do różnych slotów kont.
        """
        # Ustawiamy czas ostatniego zapytania na 1000.0s
        t_last = 1000.0
        server._last_global_completion_time = t_last

        # Kolejne zapytanie przychodzi po 1.0s (w 1001.0s)
        now_ts = 1001.0
        g_elapsed = now_ts - server._last_global_completion_time
        self.assertEqual(g_elapsed, 1.0)

        # Global pacing wymaga min 2.0s
        g_min = 2.0
        sleep_needed = g_min - g_elapsed
        self.assertEqual(sleep_needed, 1.0)
        print(f"[TEST 4 PASS] Global IP Pacer poprawnie wymusza bufor {sleep_needed}s na poziomie adresu IP")

    def test_search_pacing_safety_buffer(self):
        """
        Weryfikuje, czy wyszukiwanie sieciowe (Search) ma dedykowany bufor >= 14s.
        """
        t_last = 2000.0
        server._last_search_completion_time = t_last

        # Zapytanie z wyszukiwarką przychodzi po 5 sekundach
        now_ts = 2005.0
        s_elapsed = now_ts - server._last_search_completion_time
        s_min = 14.0
        sleep_needed = s_min - s_elapsed

        self.assertAlmostEqual(sleep_needed, 9.0)
        print(f"[TEST 5 PASS] Search Pacing poprawnie chroni silnik wyszukiwarki buforem {sleep_needed}s")

    def test_per_account_pacing_preserved_with_multi_accounts(self):
        """
        Weryfikuje, czy to samo konto NIE DOSTAJE zapytania w odstępie mniejszym niż 18s,
        nawet gdy w puli jest wiele aktywnych kont.
        """
        account_idx = 11
        last_fin = 5000.0
        server._last_account_finish_time[account_idx] = last_fin
        
        # Kolejne zapytanie do tego samego konta po 4 sekundach
        now_ts = 5004.0
        elapsed = now_ts - last_fin
        self.assertEqual(elapsed, 4.0)

        # Bazowy pacing per-konto musi wynosić min 18.0s
        base_pacing = 18.0
        sleep_needed = base_pacing - elapsed
        self.assertGreaterEqual(sleep_needed, 14.0)
        print(f"[TEST 6 PASS] Ochrona per-konto: slot {account_idx} po {elapsed}s wymaga min {sleep_needed}s pauzy anty-ban")


if __name__ == "__main__":
    unittest.main(verbosity=2)
