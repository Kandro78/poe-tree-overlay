"""Run the overlay against tools/fake_game.py for a while and sample its CPU
and memory use (needs psutil).

    python tools/soak.py [minutes] [out.csv] [still]
"""
import csv
import os
import subprocess
import sys
import time
from pathlib import Path

import psutil

ROOT = Path(__file__).resolve().parent.parent
minutes = float(sys.argv[1]) if len(sys.argv) > 1 else 10
out = Path(sys.argv[2]) if len(sys.argv) > 2 else ROOT / "soak.csv"
py = sys.executable
game = subprocess.Popen([py, str(ROOT / "tools" / "fake_game.py"), str(minutes * 60 + 60)] + sys.argv[3:4], cwd=ROOT)
time.sleep(4)
env = dict(os.environ, TREEOVERLAY_FAKE_GAME="1", TREEOVERLAY_IGNORE_FOREGROUND="1", TREEOVERLAY_MINIMIZED="1")
app = subprocess.Popen([py, str(ROOT / "run.py")], cwd=ROOT, env=env)
# a venv's python.exe is a launcher that starts the real interpreter as a
# child: measure the whole process tree, rescanned at every sample
launcher = psutil.Process(app.pid)
known = {}
rows = []
end = time.time() + minutes * 60
try:
    while time.time() < end and app.poll() is None:
        time.sleep(5)
        procs = [launcher] + launcher.children(recursive=True)
        cpu = rss = threads = 0
        for found in procs:
            if found.pid not in known:
                known[found.pid] = found
                found.cpu_percent()       # first call only starts the measurement
                continue
            pr = known[found.pid]         # cpu_percent measures since the last call on the same object
            cpu += pr.cpu_percent()
            rss += pr.memory_info().rss
            threads += pr.num_threads()
        rows.append({"t": round(time.time() - (end - minutes * 60)), "cpu": cpu,
                     "rss_mb": round(rss / 2**20, 1), "threads": threads})
        print(rows[-1], flush=True)
finally:
    app.terminate()
    game.terminate()
with open(out, "w", newline="") as fh:
    w = csv.DictWriter(fh, fieldnames=["t", "cpu", "rss_mb", "threads"])
    w.writeheader()
    w.writerows(rows)
print("saved", out)
