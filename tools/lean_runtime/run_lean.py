"""Run the pinned open-source LEAN engine locally, in backtest mode only.

This wrapper does not use the QuantConnect CLI, a cloud account, or a broker.
Use the existing project interpreter; the engine embeds that interpreter's base
CPython DLL and activates its existing virtual environment through LEAN config.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from datetime import datetime, timezone


PINNED_LEAN_COMMIT = "8ee075a39918f2df6fe9e0a5944e366fb60d10dc"
DEFAULT_SOURCE = Path("M:/quantconnect-lean-runtime/Lean")


def sha256(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def run(config_path: Path, log_path: Path, source: Path = DEFAULT_SOURCE) -> dict:
    config_path = config_path.resolve()
    config = json.loads(config_path.read_text(encoding="utf-8-sig"))
    environment = config.get("environment", "backtesting")
    resolved = {**config, **config.get("environments", {}).get(environment, {})}
    if environment != "backtesting" or resolved.get("live-mode") is not False:
        raise ValueError("This migration runner only accepts explicit backtesting/live-mode=false")
    required = {
        "data-provider": "QuantConnect.Lean.Engine.DataFeeds.DefaultDataProvider",
        "setup-handler": "QuantConnect.Lean.Engine.Setup.BacktestingSetupHandler",
        "data-feed-handler": "QuantConnect.Lean.Engine.DataFeeds.FileSystemDataFeed",
        "transaction-handler": "QuantConnect.Lean.Engine.TransactionHandlers.BacktestingTransactionHandler",
    }
    for key, expected in required.items():
        if resolved.get(key) != expected:
            raise ValueError(f"Unexpected {key}: local backtesting handler required")
    commit = subprocess.check_output(
        ["git", "-C", str(source), "rev-parse", "HEAD"], text=True
    ).strip()
    if commit != PINNED_LEAN_COMMIT:
        raise ValueError(f"LEAN commit differs from pinned identity: {commit}")
    launcher = source / "Launcher/bin/Release/QuantConnect.Lean.Launcher.dll"
    if not launcher.is_file():
        raise FileNotFoundError(f"Build LEAN first; launcher not found: {launcher}")
    base_python = Path(sys.base_prefix)
    python_dll = base_python / f"python{sys.version_info.major}{sys.version_info.minor}.dll"
    if not python_dll.is_file():
        raise FileNotFoundError(python_dll)
    output = Path(resolved["results-destination-folder"]).resolve()
    if output.exists() and any(output.iterdir()):
        raise FileExistsError(f"Refusing to reuse nonempty engine output directory: {output}")
    output.mkdir(parents=True, exist_ok=True)
    original_config_sha = sha256(config_path)
    algorithm_identity = {}
    if resolved.get("algorithm-language") == "Python":
        algorithm = Path(resolved["algorithm-location"]).resolve()
        code_dir = output / "code"
        code_dir.mkdir()
        for original in sorted(algorithm.parent.glob("*.py")):
            copied = code_dir / original.name
            shutil.copy2(original, copied)
            algorithm_identity[str(original)] = {"snapshot": str(copied), "sha256": sha256(copied)}
        config["algorithm-location"] = str(code_dir / algorithm.name)
        if environment in config.get("environments", {}):
            config["environments"][environment].pop("algorithm-location", None)
    config_path = output / "executed_config.json"
    config_path.write_text(json.dumps(config, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    env = os.environ.copy()
    env["PYTHONNET_PYDLL"] = str(python_dll)
    env["PYTHONHOME"] = str(base_python)
    env["PYTHONIOENCODING"] = "utf-8"
    env["DOTNET_CLI_TELEMETRY_OPTOUT"] = "1"
    # Process-local only; do not change the user's shell/system environment.
    command = ["dotnet", str(launcher), "--config", str(config_path)]
    log_path.parent.mkdir(parents=True, exist_ok=True)
    if log_path.exists():
        raise FileExistsError(f"Refusing to overwrite an earlier engine log: {log_path}")
    started = datetime.now(timezone.utc).isoformat()
    with log_path.open("w", encoding="utf-8") as log:
        process = subprocess.run(
            command, cwd=launcher.parent, env=env,
            stdout=log, stderr=subprocess.STDOUT, check=False,
        )
    source_status = subprocess.check_output(
        ["git", "-C", str(source), "status", "--porcelain"], text=True
    ).strip()
    source_patch = subprocess.check_output(
        ["git", "-C", str(source), "diff", "--", "Common/Python/PythonInitializer.cs"]
    )
    if source_patch:
        (output / "lean_runtime.patch").write_bytes(source_patch)
    dll_names = ["QuantConnect.Lean.Launcher.dll", "QuantConnect.Lean.Engine.dll",
                 "QuantConnect.Algorithm.dll", "QuantConnect.Common.dll",
                 "QuantConnect.AlgorithmFactory.dll", "Python.Runtime.dll"]
    dll_identity = {name: sha256(launcher.parent / name) for name in dll_names if (launcher.parent / name).is_file()}
    completion_ok = None
    if resolved.get("algorithm-type-name") == "H60MigrationAlgorithm":
        completion_path = Path(resolved["parameters"]["h60-output-dir"]) / "completion.json"
        if completion_path.is_file():
            completion = json.loads(completion_path.read_text(encoding="utf-8"))
            completion_ok = (completion.get("engine") == "LEAN" and completion.get("status") == "completed"
                             and completion.get("live_mode") is False)
        else:
            completion_ok = False
    return {
        "started_at_utc": started,
        "completed_at_utc": datetime.now(timezone.utc).isoformat(),
        "command": command,
        "working_directory": str(launcher.parent),
        "source_commit": commit,
        "source_git_status": source_status,
        "source_patch_sha256": hashlib.sha256(source_patch).hexdigest() if source_patch else None,
        "python_initializer_sha256": sha256(source / "Common/Python/PythonInitializer.cs"),
        "launcher_sha256": sha256(launcher),
        "engine_dll_sha256": dll_identity,
        "algorithm_snapshots": algorithm_identity,
        "original_config_sha256": original_config_sha,
        "config_sha256": sha256(config_path),
        "python_executable": sys.executable,
        "python_dll": str(python_dll),
        "log_path": str(log_path.resolve()),
        "log_sha256": sha256(log_path),
        "process_exit_code": process.returncode,
        "algorithm_completion_check": completion_ok,
        "validated_exit_code": process.returncode if process.returncode else (1 if completion_ok is False else 0),
        "evidence_scope": "Actual local LEAN engine process; algorithm results require separate inspection",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--log", type=Path, required=True)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    args = parser.parse_args()
    result = run(args.config, args.log, args.source)
    identity_path = args.log.with_suffix(".run.json")
    identity_path.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2, ensure_ascii=False))
    raise SystemExit(result["validated_exit_code"])


if __name__ == "__main__":
    main()
