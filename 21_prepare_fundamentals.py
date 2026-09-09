"""下载公开 SEC companyfacts，并按真实申报日期构造研究财务特征。

请求明确声明本地研究软件，不冒充浏览器或伪造身份/联系方式。
只使用公开 API；失败最多重试一次，保留原响应与元数据，不绕访问限制。
"""

import argparse
import hashlib
import json
import sys
import time
from datetime import datetime, timezone

import requests

from panel_config import ROOT, SYMBOLS

SEC_DIR = ROOT / "data" / "raw" / "sec_companyfacts_20260909"
USER_AGENT = "QuantMLResearch/0.1 (personal educational research project; automated public-data access)"
# 这些只是解析候选；每个条目必须由官方 submissions 的 CIK/tickers 现场验证。
CIK_CANDIDATES = {
    "AAPL": 320193, "MSFT": 789019, "NVDA": 1045810, "AMZN": 1018724,
    "GOOGL": 1652044, "META": 1326801, "JPM": 19617, "BAC": 70858,
    "GS": 886982, "V": 1403161, "JNJ": 200406, "PFE": 78003,
    "MRK": 310158, "UNH": 731766, "XOM": 34088, "CVX": 93410,
    "COP": 1163165, "CAT": 18230, "HON": 773840, "DE": 315189,
    "PG": 80424, "KO": 21344, "PEP": 77476, "WMT": 104169,
    "COST": 909832, "HD": 354950, "MCD": 63908, "NEE": 753308,
    "DUK": 1326160, "SO": 92122,
}
FILING_TICKER_EVIDENCE = {
    "XOM": {
        "cik": 34088, "name": "EXXON MOBIL CORP",
        "url": "https://www.sec.gov/Archives/edgar/data/34088/000003408825000042/xom-20250630.htm",
        "verified_on_utc_date": "2026-09-09",
        "evidence": "Official 2025 Form 10-Q cover identifies Exxon Mobil common stock ticker XOM. Current submissions tickers is empty, so a historical filing verifies this mapping.",
    },
}


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def save_json(path, value):
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False), encoding="utf-8")


def download_json(session, stem, url):
    path = SEC_DIR / f"{stem}.json"
    meta_path = SEC_DIR / f"{stem}.metadata.json"
    if meta_path.exists():
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        if meta["url"] != url:
            raise ValueError("已有缓存来源不同，不覆盖。")
        if meta["status"] == "ok":
            if hashlib.sha256(path.read_bytes()).hexdigest() != meta["sha256"]:
                raise ValueError(f"缓存哈希不一致: {path}")
            return json.loads(path.read_text(encoding="utf-8")), meta
        return None, meta
    attempts = []
    for attempt in range(2):
        item = {"attempt": attempt + 1, "requested_at_utc": utc_now()}
        response = None
        try:
            response = session.get(url, timeout=25)
            item.update(status_code=response.status_code, bytes=len(response.content),
                        content_type=response.headers.get("content-type"),
                        response_sha256=hashlib.sha256(response.content).hexdigest())
            if response.status_code == 200:
                value = response.json()
                path.write_bytes(response.content)
                attempts.append(item)
                meta = {"status": "ok", "url": url, "retrieved_at_utc": utc_now(),
                        "user_agent": USER_AGENT, "attempts": attempts,
                        "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
                save_json(meta_path, meta)
                time.sleep(0.55)
                return value, meta
        except Exception as exc:
            item["error"] = f"{type(exc).__name__}: {str(exc)[:300]}"
        if response is not None:
            failure_path = SEC_DIR / f"{stem}.attempt{attempt+1}.failure.txt"
            failure_path.write_bytes(response.content)
            item["failure_response_file"] = failure_path.name
        attempts.append(item)
        if attempt == 0:
            time.sleep(2)
    meta = {"status": "failed", "url": url, "retrieved_at_utc": utc_now(),
            "user_agent": USER_AGENT, "attempts": attempts,
            "policy": "At most two attempts, same declared user agent; no bypass or alternate identity."}
    save_json(meta_path, meta)
    return None, meta


def download_all():
    SEC_DIR.mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT, "Accept-Encoding": "gzip, deflate", "Accept": "application/json"})
    resolution = {}
    for symbol in SYMBOLS:
        cik = CIK_CANDIDATES[symbol]
        submitted, submission_meta = download_json(session, f"submissions_{symbol}", f"https://data.sec.gov/submissions/CIK{cik:010d}.json")
        current_verified = (submitted is not None and int(submitted.get("cik", -1)) == cik
                            and symbol in submitted.get("tickers", []))
        evidence = FILING_TICKER_EVIDENCE.get(symbol)
        historical_verified = (submitted is not None and evidence is not None
                               and int(submitted.get("cik", -1)) == evidence["cik"]
                               and submitted.get("name") == evidence["name"])
        verified = current_verified or historical_verified
        item = {"candidate_cik": cik, "official_submissions_verified": verified,
                "submissions_status": submission_meta["status"]}
        item["current_submissions_ticker_match"] = current_verified
        if historical_verified:
            item["historical_filing_identity_evidence"] = evidence
        if verified:
            item.update(official_name=submitted.get("name"), official_current_tickers=submitted.get("tickers"))
            facts, facts_meta = download_json(session, symbol, f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json")
            if facts is not None and int(facts.get("cik", -1)) != cik:
                raise ValueError(f"{symbol}: companyfacts CIK 不匹配。")
            item["companyfacts_status"] = facts_meta["status"]
            item["us_gaap_concepts"] = len(facts.get("facts", {}).get("us-gaap", {})) if facts else 0
        else:
            item["companyfacts_status"] = "not_requested_unverified_mapping"
        resolution[symbol] = item
        save_json(SEC_DIR / "resolution.json", {"updated_at_utc": utc_now(), "symbols": resolution,
                  "ticker_list_preflight": {"url": "https://www.sec.gov/files/company_tickers.json", "observed_http_statuses": [403,403],
                  "note": "Initial availability probe on 2026-09-09; response body was not retained. Stopped this endpoint after one retry. Company-specific public APIs are used for their documented purpose."}})
        print(f"{symbol}: submissions_verified={verified}; companyfacts={item['companyfacts_status']}; concepts={item.get('us_gaap_concepts',0)}", flush=True)
    return resolution


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    parser.add_argument("--download-only", action="store_true")
    parser.add_argument("--prepare-only", action="store_true")
    args = parser.parse_args()
    if not args.prepare_only:
        resolution = download_all()
        print(f"SEC 下载完成：{sum(v['companyfacts_status']=='ok' for v in resolution.values())}/{len(SYMBOLS)}。", flush=True)
    if not args.download_only:
        from fundamental_features import prepare_and_save
        prepare_and_save()


if __name__ == "__main__":
    main()
