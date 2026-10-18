"""Tiny job queue for the shared GPU: ≤ 3 concurrent Tastoria jobs under the shared-GPU rules.

Jobs come from a JSON file (re-read every poll, so jobs can be appended while the queue runs):
    [{"name": "abl_none_s0", "cmd": ["train", "--name", "abl_none_s0", ...], "gpu": true, "after": []}, ...]
``cmd`` is passed to ``python -m tastoria_ml.cv.<module>`` (default module ``train_detector``; set
``"module"`` to override). A GPU job is launched only when
  * fewer than MAX_JOBS Tastoria jobs run, nvidia-smi reports ≥ 10 GB free and disk ≥ 30 GB free,
  * a ``"ram": true`` job (RAM image cache, ~8 GB) also needs < MAX_RAM_JOBS such jobs running and
    MemAvailable ≥ 20 GB,
  * at least RAMP_S seconds passed since the last GPU launch (so the previous job's memory is visible),
  * every job in ``after`` finished with exit code 0.
The per-job GpuGuard enforces the memory fraction, the slot locks and the watchdog. A job killed by its
watchdog (SIGKILL, exit -9) is re-queued and resumes from ``last.pt``; other failures are retried once.

Run:  python -m tastoria_ml.cv.gpu_queue ml/runs/queue/jobs.json
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

from tastoria_ml.cv.classes import REPO
from tastoria_ml.cv.train_detector import (
    MAX_JOBS,
    MIN_DISK_GB,
    MIN_FREE_START_MB,
    disk_free_gb,
    gpu_free_mb,
    mem_available_gb,
)

MAX_RAM_JOBS = 2  # jobs with the ~8 GB RAM image cache ("ram": true)
MIN_RAM_START_GB = 20

RAMP_S = 180
POLL_S = 30
QDIR = REPO / "ml" / "runs" / "queue"


def log(msg: str) -> None:
    print(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {msg}", flush=True)


def main(jobs_file: str) -> None:
    QDIR.mkdir(parents=True, exist_ok=True)
    state_f = QDIR / "state.json"
    state: dict[str, dict] = json.loads(state_f.read_text()) if state_f.exists() else {}
    procs: dict[str, subprocess.Popen] = {}
    last_launch = 0.0
    py = sys.executable
    env = dict(os.environ, PYTHONPATH=str(REPO / "ml" / "src"), MLFLOW_DISABLE_AGENT_HINT="1")
    while True:
        jobs = json.loads(Path(jobs_file).read_text())
        for name, p in list(procs.items()):
            rc = p.poll()
            if rc is None:
                continue
            st = state[name]
            st["rc"], st["end"] = rc, time.time()
            if rc == 0:
                st["status"] = "done"
            elif rc == -9:
                st["status"], st["kills"] = "pending", st.get("kills", 0) + 1
            else:
                st["tries"] = st.get("tries", 0) + 1
                st["status"] = "pending" if st["tries"] < 2 else "failed"
            log(f"{name} exited rc={rc} -> {st['status']}")
            del procs[name]
        n_gpu = sum(1 for n in procs if state[n].get("gpu", True))
        n_ram = sum(1 for n in procs if state[n].get("ram", False))
        for j in jobs:
            st = state.setdefault(j["name"], {"status": "pending"})
            st["gpu"] = j.get("gpu", True)
            st["ram"] = j.get("ram", False)
            if st["status"] != "pending" or j["name"] in procs:
                continue
            if any(state.get(a, {}).get("status") == "failed" for a in j.get("after", [])):
                st["status"] = "failed"
                log(f"{j['name']}: a dependency failed")
                continue
            if any(state.get(a, {}).get("status") != "done" for a in j.get("after", [])):
                continue
            if st["gpu"]:
                if n_gpu >= MAX_JOBS or time.time() - last_launch < RAMP_S:
                    continue
                if st["ram"] and (n_ram >= MAX_RAM_JOBS or mem_available_gb() < MIN_RAM_START_GB):
                    continue
                free, _ = gpu_free_mb()
                if free < MIN_FREE_START_MB or disk_free_gb() < MIN_DISK_GB:
                    continue
            out = (QDIR / f"{j['name']}.log").open("a")
            mod = j.get("module", "train_detector")
            procs[j["name"]] = subprocess.Popen([py, "-u", "-m", f"tastoria_ml.cv.{mod}", *j["cmd"]], cwd=REPO,
                                                env=env, stdout=out, stderr=subprocess.STDOUT)
            st.update(status="running", start=time.time())
            log(f"launched {j['name']} (gpu={st['gpu']})")
            if st["gpu"]:
                n_gpu += 1
                n_ram += int(st["ram"])
                last_launch = time.time()
        state_f.write_text(json.dumps(state, indent=1))
        if not procs and all(state.get(j["name"], {}).get("status") in ("done", "failed") for j in jobs):
            log("queue empty")
            (QDIR / "queue.done").write_text(time.strftime("%Y-%m-%d %H:%M:%S"))
            return
        time.sleep(POLL_S)


if __name__ == "__main__":
    main(sys.argv[1])
