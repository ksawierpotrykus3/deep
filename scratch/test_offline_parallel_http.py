"""Deterministyczny test: czy endpoint /v1/chat/completions obsluguje rownolegle zle zadania.

Fix: endpoint jest teraz zwyklym `def`, wiec FastAPI odpala go w puli watkow.
Ten test podmienia globalny obiekt `ds.stream_completion` na generator, ktory spi 1s,
i sprawdza, czy 4 rownolegle zadania schodza w ~1s (rownolegle) zamiast ~4s (serializacja).
Nie uzywa zadnych zywych kont ani sieci.
"""
import time
import threading
import concurrent.futures

# Importujemy server jako modul, zeby nie startowal uvicorn (start jest w __main__).
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

spec = importlib.util.spec_from_file_location("server_mod", ROOT / "server.py")
server = importlib.util.module_from_spec(spec)
spec.loader.exec_module(server)

# 1) Podmieniamy ds.stream_completion na generator spiacy 1s i zwracajacy 1 porcje SSE.
def fake_stream_completion(account_idx, chat_session_id, prompt, parent_message_id=None,
                           max_tokens=8192, temperature=1.0, top_p=1.0,
                           model_type=None, ref_file_ids=None,
                           thinking_enabled=False, search_enabled=False, _retry=0):
    time.sleep(1.0)
    # Zwracamy generator jednego chunku SSE w formacie, jakiego oczekuje _stream()
    def gen():
        import json
        payload = {
            "type": "text",
            "content": "hello",
            "model": model_type or "deepseek-v4-pro",
        }
        yield ("data: " + json.dumps(payload)).encode("utf-8")
    return gen()

server.ds.stream_completion = fake_stream_completion

# 2) Upewnij sie, ze zadna inna ciezka logika nie ruszy sieci w te proby.
#    Sprawiamy, ze wybor konta i inne kontrole sa szybkie i bez sieci.
class FakeDS:
    def is_valid(self, slot):
        return True
    def create_session(self, slot):
        return "fake_session_id"
    def upload_file(self, *a, **k):
        return "fake_file_id"
    def ingest_chunk_fast(self, *a, **k):
        return "fake_pid"
    def stream_completion(self, *a, **k):
        return fake_stream_completion(*a, **k)

# Podmieniamy obiekt ds na w pelni bezpieczny fake
server.ds = FakeDS()

# 3) TestClient: odpala aplikacje w jej natywnym trybie (bez zewnetrznego serwera).
from fastapi.testclient import TestClient

client = TestClient(server.app, raise_server_exceptions=False)

def make_request(i):
    t0 = time.perf_counter()
    r = client.post(
        "/v1/chat/completions",
        json={
            "model": "deepseek-v4-pro",
            "messages": [
                {"role": "user", "content": f"hello {i}"}
            ],
            "stream": True,
        },
        headers={"acl-token": ""},
    )
    dt = time.perf_counter() - t0
    err = r.text if r.status_code != 200 else ""
    return i, dt, r.status_code, err

# 4) Odpalamy 4 zadania rownolegle.
N = 4
t_start = time.perf_counter()
with concurrent.futures.ThreadPoolExecutor(max_workers=N) as ex:
    results = list(ex.map(make_request, range(N)))
t_total = time.perf_counter() - t_start

times = [dt for _, dt, _, _ in results]
statuses = [s for _, _, s, _ in results]

print("=" * 60)
print("OFLLINE ROWNOLEGLOSC — HTTP /v1/chat/completions")
print("=" * 60)
for i, dt, s, err in results:
    print(f"  request {i}: {dt:.3f}s  status={s}")
    if err:
        print(f"    BŁĄD WALIDACJI: {err[:500]}")
print(f"  total wall clock: {t_total:.3f}s")
print(f"  suma indywidualnych czasow: {sum(times):.3f}s")
print("-" * 60)
if t_total < 2.0:
    print("WYNIK: ROWNOLEGLE (czas calkowity ~1s, a nie ~4s)")
else:
    print("WYNIK: SERIALIZACJA (czas calkowity ~4s — endpoint wciaz blokuje)")
print("=" * 60)