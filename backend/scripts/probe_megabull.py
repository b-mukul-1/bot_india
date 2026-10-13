"""
MegaBull API Probe Script
Calls read-only endpoints on https://api.megabull.in and saves raw responses to docs/raw_probes/
Validates observed schemas against OpenAPI spec.
"""

import os
import sys
import json
import httpx
from datetime import datetime, timezone

BASE_URL = "https://api.megabull.in"
PROBES_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "docs", "raw_probes")

def main():
    api_key = os.environ.get("MEGABULL_API_KEY")
    if len(sys.argv) > 1 and sys.argv[1].startswith("--api-key="):
        api_key = sys.argv[1].split("=", 1)[1]
    elif len(sys.argv) > 1 and sys.argv[1] == "--api-key" and len(sys.argv) > 2:
        api_key = sys.argv[2]

    os.makedirs(PROBES_DIR, exist_ok=True)

    headers = {}
    if api_key:
        headers["api-key"] = api_key
        print(f"[PROBE] Using provided MEGABULL_API_KEY (length {len(api_key)})")
    else:
        print("[PROBE] No MEGABULL_API_KEY provided; probing endpoints to observe unauthenticated/error responses.")

    endpoints = [
        {"name": "user_my", "path": "/api/user/my", "method": "GET"},
        {"name": "marketwatch_my", "path": "/api/marketwatch/my", "method": "GET"},
        {"name": "instruments_json", "path": "/api/marketwatch/instruments", "method": "GET"},
        {"name": "instruments_redirect", "path": "/api/marketwatch/instruments?redirect=true", "method": "GET"},
        {"name": "ltp_nifty50", "path": "/api/marketwatch/ltp/256265", "method": "GET"},
        {"name": "ltp_sensex", "path": "/api/marketwatch/ltp/265", "method": "GET"},
        {"name": "positions_my", "path": "/api/position/my", "method": "GET"},
        {"name": "orders_my", "path": "/api/order/my", "method": "GET"},
        {"name": "holdings_my", "path": "/api/holding/my", "method": "GET"},
        {"name": "virtual_report", "path": "/api/report/virtual/2026-10-01/2026-10-13", "method": "GET"},
        {"name": "monthly_report", "path": "/api/report/monthly/10/2026", "method": "GET"},
        {"name": "day_report", "path": "/api/report/monthly/day/2026-10-13", "method": "GET"},
    ]

    summary = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "has_api_key": bool(api_key),
        "results": {}
    }

    with httpx.Client(base_url=BASE_URL, timeout=10.0, follow_redirects=False) as client:
        for ep in endpoints:
            name = ep["name"]
            path = ep["path"]
            print(f"[PROBE] Calling {ep['method']} {path} ...")
            try:
                res = client.request(ep["method"], path, headers=headers)
                status_code = res.status_code
                content_type = res.headers.get("content-type", "")
                
                # Try parsing JSON or saving text
                try:
                    data = res.json()
                except Exception:
                    data = {"raw_text": res.text[:1000]}

                result_entry = {
                    "status_code": status_code,
                    "content_type": content_type,
                    "headers": dict(res.headers),
                    "body": data
                }
                summary["results"][name] = {
                    "path": path,
                    "status_code": status_code,
                    "error": data.get("error") if isinstance(data, dict) else None,
                    "message": data.get("message") if isinstance(data, dict) else None,
                }

                out_file = os.path.join(PROBES_DIR, f"{name}.json")
                with open(out_file, "w") as f:
                    json.dump(result_entry, f, indent=2)
                print(f"  -> HTTP {status_code} saved to {out_file}")

            except Exception as e:
                print(f"  -> Error: {e}")
                summary["results"][name] = {"path": path, "exception": str(e)}

    # Also test instrument CSV download direct from S3 if known
    s3_csv_url = "https://megabull-open.s3.us-east-1.amazonaws.com/Instrument-dev.csv"
    print(f"[PROBE] Testing S3 direct CSV download from {s3_csv_url} ...")
    try:
        with httpx.Client(timeout=15.0) as s3_client:
            r = s3_client.get(s3_csv_url)
            summary["s3_csv"] = {
                "status_code": r.status_code,
                "content_length": len(r.content),
                "sample_lines": r.text.splitlines()[:5]
            }
            print(f"  -> HTTP {r.status_code}, {len(r.content)} bytes received")
    except Exception as e:
        summary["s3_csv"] = {"exception": str(e)}

    summary_file = os.path.join(PROBES_DIR, "probe_summary.json")
    with open(summary_file, "w") as f:
        json.dump(summary, f, indent=2)
    print(f"[PROBE] Complete. Summary written to {summary_file}")

if __name__ == "__main__":
    main()
