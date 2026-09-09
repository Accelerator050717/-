"""检查现有本机 IBKR 会话，不登录、不启动程序、不修改 TWS、不下单。"""

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys

from ibkr_readonly import ReadonlyConfig, check_readiness


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, help="只检查指定本机端口；端口不证明账户类型。")
    parser.add_argument("--expected-environment", choices=("paper", "live"))
    args = parser.parse_args()
    config = ReadonlyConfig(
        ports=(args.port,) if args.port else (7497, 4002, 7496, 4001),
        expected_account=os.environ.get("QUANT_IBKR_EXPECTED_ACCOUNT") or None,
        expected_environment=args.expected_environment,
    )
    result = check_readiness(config)
    root = Path(__file__).resolve().parent / "data" / "broker_readiness"
    root.mkdir(parents=True, exist_ok=True)
    name = datetime.now(timezone.utc).strftime("ibkr_readonly_%Y%m%dT%H%M%S%fZ.json")
    text = json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False)
    (root / name).write_text(text, encoding="utf-8")
    (root / "latest.json").write_text(text, encoding="utf-8")
    # 终端只打印连接、库版本和计数；账户、持仓数量和资金永不打印。
    print(json.dumps(dict(status=result["status"], client=result["client"],
                          tcp_open_ports=[item["port"] for item in result["ports"] if item["tcp_open"]],
                          handshake_attempts=len(result["connection_attempts"]),
                          paper_account_confirmed=result["paper_account_confirmed"],
                          blocker=result.get("blocker"), orders_sent=0, output_path=str(root / name)),
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
