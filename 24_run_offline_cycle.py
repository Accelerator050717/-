"""一条命令重现固定历史快照上的研究与执行流程；不请求网络或券商。"""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "data/cycles/offline_v1"
STAGES = [
    ("financial_features_from_cache", "fundamental_features.py"),
    ("fixed_research_or_saved_result", "22_train_fundamental_comparison.py"),
    ("historical_execution_and_reconciliation", "23_replay_execution.py"),
    ("research_and_execution_report", "25_write_automation_report.py"),
]


def file_hash(path):
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=["historical_replay"], default="historical_replay")
    args = parser.parse_args()
    OUTPUT.mkdir(parents=True, exist_ok=True)
    lock = OUTPUT / "cycle.lock"
    fd = os.open(lock, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(str(os.getpid()))
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S") + "_" + uuid.uuid4().hex[:8]
    folder = OUTPUT / run_id
    folder.mkdir()
    state = ROOT / "data/replays/offline_v1/state.json"
    record = {"run_id": run_id, "mode": args.mode, "started_at_utc": datetime.now(timezone.utc).isoformat(),
              "network_requested": False, "broker_connected": False,
              "source": "Saved fixed historical snapshots only; no live update or scheduling.",
              "execution_state_before_sha256": file_hash(state), "stages": [], "status": "running"}
    exit_code = 0
    try:
        for number, (stage, filename) in enumerate(STAGES, 1):
            start = time.perf_counter()
            result = subprocess.run([sys.executable, str(ROOT / filename)], cwd=ROOT,
                                    env={**os.environ, "PYTHONIOENCODING": "utf-8"},
                                    capture_output=True, text=True, encoding="utf-8", timeout=600)
            (folder / f"{number}_{stage}.log").write_text(result.stdout + result.stderr, encoding="utf-8")
            record["stages"].append({"stage": stage, "script": filename, "returncode": result.returncode,
                                      "seconds": round(time.perf_counter()-start, 3)})
            print(f"{stage}: {'OK' if result.returncode == 0 else 'FAILED'}", flush=True)
            if result.returncode:
                raise RuntimeError(f"{stage}失败，后续步骤未运行；见{folder}。")
        replay = json.loads((ROOT / "data/replays/offline_v1/completion.json").read_text(encoding="utf-8"))
        research = json.loads((ROOT / "data/experiments/automation_research_v2/completion.json").read_text(encoding="utf-8"))
        record.update(status="completed", new_simulated_fills=replay["new_fills"],
                      total_simulated_fills=replay["total_fills"], historical_nav=replay["final_snapshot"]["nav"],
                      research_gate_passes=research["gate_passes"])
    except Exception as exc:
        record.update(status="failed", error=f"{type(exc).__name__}: {exc}")
        exit_code = 1
    finally:
        record.update(completed_at_utc=datetime.now(timezone.utc).isoformat(),
                      execution_state_after_sha256=file_hash(state))
        text = json.dumps(record, ensure_ascii=False, indent=2, allow_nan=False)
        (folder / "run.json").write_text(text, encoding="utf-8")
        (OUTPUT / "latest.json").write_text(text, encoding="utf-8")
        lock.unlink()
    print(json.dumps({key: record.get(key) for key in ("run_id", "status", "new_simulated_fills", "research_gate_passes", "error")}, ensure_ascii=False))
    raise SystemExit(exit_code)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
