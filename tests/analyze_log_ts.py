import re
import datetime
from pathlib import Path

p = Path("proxy_output.log")
if not p.exists():
    print("proxy_output.log does not exist")
    exit(0)

with open(p, "rb") as f:
    text = f.read().decode("utf-8", errors="replace")

ts_matches = re.findall(r'"(?:inserted_at|updated_at)":\s*([0-9]{10})', text)
if ts_matches:
    ts_ints = sorted(set(int(x) for x in ts_matches))
    print("Unique timestamps in proxy_output.log:", len(ts_ints))
    print("First timestamp:", datetime.datetime.fromtimestamp(ts_ints[0]))
    print("Last timestamp:", datetime.datetime.fromtimestamp(ts_ints[-1]))
    print("\nTimestamps after 21:00 yesterday:")
    for t in ts_ints:
        dt = datetime.datetime.fromtimestamp(t)
        if dt.day == 20 or (dt.day == 19 and dt.hour >= 21):
            print(f"  {dt} (ts={t})")
