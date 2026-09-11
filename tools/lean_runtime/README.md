# Native LEAN runtime for the H60 migration check

This is an isolated **local historical backtest** runner. It invokes the Apache-2.0
LEAN source engine directly, not the paid QuantConnect CLI or any cloud service.
It does not connect to a broker. H60 migration is an engineering comparison of
frozen development inputs; it does not qualify the strategy for trading.

## Verified local installation

- Source: `M:\quantconnect-lean-runtime\Lean` (outside this project's Git tree).
- Official repository: <https://github.com/QuantConnect/Lean>.
- Pinned source commit: `8ee075a39918f2df6fe9e0a5944e366fb60d10dc`.
- Engine: .NET SDK 10.0.400, `Launcher\bin\Release\QuantConnect.Lean.Launcher.dll`.
- Python: existing project `.venv` using CPython 3.12.2, NumPy 2.5.3, pandas 3.0.5.
- Source build command, from the external source checkout:

```powershell
dotnet build Launcher/QuantConnect.Lean.Launcher.csproj -c Release --nologo -v minimal
```

The initial build succeeded with zero errors. The original upstream dependency
and analyzer warnings are preserved in `data/experiments/lean_migration_v10/runtime/native_build.log`.
No upstream package versions were changed to suppress them.

Docker is installed but its Desktop backend failed startup because its local
`dockerInference` socket could not be accessed. Native LEAN was built and run
successfully, so Docker is not required for this experiment. No factory reset,
OS feature change, or restart was performed.

The native H60 custom-data run initially stalled with the engine's 32-worker
default. An actual managed stack capture showed Python.NET first-use converter
initialization waiting in a lock/GIL cycle between data workers. Generated config
therefore sets the engine's existing `data-feed-workers-count` option to `1`.
This only serializes data-feed processing; it does not alter strategy parameters
or fill rules. The failed attempt and stack evidence remain in `runtime/`.

Python execution then exposed a separate shutdown crash: LEAN's outer `Py.GIL()`
guard was left finalizable while the pinned Python.NET shutdown performed garbage
collection. A narrow local patch suppresses finalization of **that shutdown
guard only**; `PythonEngine.Shutdown()` still runs, releases the GIL internally,
and process exit must succeed. It changes no strategy, cost, order or fill code.
See `patches/native_shutdown_gil.patch` and its adjacent JSON for the exact source
change and before/after SHA256. The source version is therefore the pinned
upstream commit **plus this recorded patch**, not an unmodified upstream engine.

From a clean external source checkout, apply before building:

```powershell
git apply --check 'M:\ml项目\tools\lean_runtime\patches\native_shutdown_gil.patch'
git apply 'M:\ml项目\tools\lean_runtime\patches\native_shutdown_gil.patch'
dotnet build Launcher/QuantConnect.Lean.Launcher.csproj -c Release --nologo -v minimal
```

The local `.nuspec` identifies `QuantConnect.pythonnet` 2.0.66 as commit
`56b3b6e72cf1f0c00bee0ebc77b8c3edcd2764f2`. Its
[runtime shutdown implementation](https://github.com/QuantConnect/pythonnet/blob/56b3b6e72cf1f0c00bee0ebc77b8c3edcd2764f2/src/runtime/Runtime.cs#L238)
and [GIL guard implementation](https://github.com/QuantConnect/pythonnet/blob/56b3b6e72cf1f0c00bee0ebc77b8c3edcd2764f2/src/runtime/Py.cs#L26)
explain this ownership boundary. Clean H60 process exit is verified in the
subsequent smoke attempt; earlier failed attempts remain available.

## Run a new H60 comparison

Run from `M:\ml项目`. Use a **new output directory and log name for each attempt**;
the runner deliberately refuses to overwrite earlier engine output.

```powershell
.\.venv\Scripts\python.exe tools/lean_runtime/make_config.py --output-dir data/experiments/lean_migration_v10/engine_runs/example_new_run --output-config data/experiments/lean_migration_v10/runtime/example_new_run_config.json --algorithm-path lean_migration/main.py --package data/experiments/lean_migration_v10/input
.\.venv\Scripts\python.exe tools/lean_runtime/run_lean.py --config data/experiments/lean_migration_v10/runtime/example_new_run_config.json --log data/experiments/lean_migration_v10/runtime/example_new_run.log
```

Use `smoke_input` instead of `input` for the frozen short window. These commands
only consume packages already prepared by the project exporter. They neither
train models nor acquire market data.

`make_config.py` defaults to the official C# `BasicTemplateDailyAlgorithm` if no
`--algorithm-path` is supplied. This built-in sample uses bundled 2013 SPY daily
data, not the project's H60 model. Its successful run and actual order events
are retained under `runtime/builtin_smoke_01/`. Missing optional hourly SPY and
interest-rate files are recorded by LEAN; no download was attempted.

## What the wrapper records

`run_lean.py` checks the pinned source commit and explicit local backtest handlers,
sets `PYTHONNET_PYDLL`/`PYTHONHOME` only for the child process, and uses LEAN's
`python-venv` option to activate the existing environment. Each run preserves:

- a copy of algorithm Python source under its `code/` directory;
- the exact `executed_config.json`, input config hash, engine DLL hashes and
  external source Git status;
- combined stdout/stderr log plus adjacent `.run.json` metadata;
- LEAN's own results and order-event files, and the adapter's reconciliation files.

For H60, success additionally requires the adapter's `completion.json` to say
`engine=LEAN`, `status=completed`, and `live_mode=false`. This is only completion
evidence: the project comparator must still check trades, positions, fees and
close equity against the original implementation. A passing sample or process
exit code alone is not migration acceptance or broker integration evidence.

## Rebuilding on another machine

The source and built binaries are intentionally not committed here. Obtain the
official source at the exact commit above, build it with .NET 10, and supply its
path with `--source` to both scripts. The sparse source checkout used here includes
all engine source, `Data/market-hours`, `Data/symbol-properties`, and the three
bundled SPY daily/map/factor files. Reusing our frozen input package requires no
new price history. Source, binaries, sample files and runtime identities are
listed in `runtime/RUNTIME_IDENTITY.json`.
