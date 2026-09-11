"""Create explicit local-data-only LEAN backtest configuration."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from run_lean import DEFAULT_SOURCE


def make_config(output: Path, source: Path = DEFAULT_SOURCE) -> dict:
    return {
        "environment": "backtesting",
        "live-mode": False,
        "algorithm-type-name": "BasicTemplateDailyAlgorithm",
        "algorithm-language": "CSharp",
        "algorithm-location": str(source / "Launcher/bin/Release/QuantConnect.Algorithm.CSharp.dll"),
        "data-folder": str(source / "Data"),
        "results-destination-folder": str(output.resolve()),
        "object-store-root": str(output.resolve() / "storage"),
        "close-automatically": True,
        "debugging": False,
        "log-handler": "QuantConnect.Logging.CompositeLogHandler",
        "messaging-handler": "QuantConnect.Messaging.Messaging",
        "job-queue-handler": "QuantConnect.Queues.JobQueue",
        "api-handler": "QuantConnect.Api.Api",
        "map-file-provider": "QuantConnect.Data.Auxiliary.LocalDiskMapFileProvider",
        "factor-file-provider": "QuantConnect.Data.Auxiliary.LocalDiskFactorFileProvider",
        "data-provider": "QuantConnect.Lean.Engine.DataFeeds.DefaultDataProvider",
        "data-channel-provider": "DataChannelProvider",
        "object-store": "QuantConnect.Lean.Engine.Storage.LocalObjectStore",
        "data-aggregator": "QuantConnect.Lean.Engine.DataFeeds.AggregationManager",
        "setup-handler": "QuantConnect.Lean.Engine.Setup.BacktestingSetupHandler",
        "result-handler": "QuantConnect.Lean.Engine.Results.BacktestingResultHandler",
        "data-feed-handler": "QuantConnect.Lean.Engine.DataFeeds.FileSystemDataFeed",
        # Serialize first-use PythonData conversion in the native Python.NET runtime.
        # The 32-worker default deadlocked on a converter Lazy lock versus the GIL.
        "data-feed-workers-count": 1,
        "real-time-handler": "QuantConnect.Lean.Engine.RealTime.BacktestingRealTimeHandler",
        "history-provider": ["QuantConnect.Lean.Engine.HistoricalData.SubscriptionDataReaderHistoryProvider"],
        "transaction-handler": "QuantConnect.Lean.Engine.TransactionHandlers.BacktestingTransactionHandler",
        "show-missing-data-logs": True,
        "job-user-id": "0",
        "api-access-token": "",
        "job-organization-id": "",
        "python-venv": str(Path(sys.prefix)),
        "python-additional-paths": [str(source / "Launcher/bin/Release")],
        "parameters": {},
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--output-config", required=True, type=Path)
    parser.add_argument("--source", default=DEFAULT_SOURCE, type=Path)
    parser.add_argument("--algorithm-path", type=Path)
    parser.add_argument("--algorithm-name", default="H60MigrationAlgorithm")
    parser.add_argument("--package", type=Path)
    args = parser.parse_args()
    config = make_config(args.output_dir, args.source)
    if args.algorithm_path:
        if args.package is None:
            parser.error("--package is required with --algorithm-path")
        package_path = args.package.resolve()
        if package_path.is_dir():
            package_path = package_path / "package.json"
        if not package_path.is_file():
            parser.error(f"Frozen package file does not exist: {package_path}")
        config.update({"algorithm-type-name": args.algorithm_name, "algorithm-language": "Python",
                       "algorithm-location": str(args.algorithm_path.resolve())})
        config["parameters"] = {"h60-package-path": str(package_path),
                                "h60-output-dir": str(args.output_dir.resolve())}
    args.output_config.parent.mkdir(parents=True, exist_ok=True)
    if args.output_config.exists():
        raise FileExistsError(args.output_config)
    args.output_config.write_text(json.dumps(config, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(args.output_config)


if __name__ == "__main__":
    main()
