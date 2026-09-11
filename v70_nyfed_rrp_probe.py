from __future__ import annotations

import json
from pathlib import Path

import requests

URL = "https://markets.newyorkfed.org/api/rp/reverserepo/propositions/search.json"
PARAMS = {"startDate": "2005-01-01", "endDate": "2026-08-31"}
OUT = Path("v70_nyfed_rrp_probe_output.json")


def fetch_rrp_operations() -> list[dict]:
    r = requests.get(URL, params=PARAMS, timeout=45)
    r.raise_for_status()
    payload = r.json()
    repo = payload.get("repo", {}) if isinstance(payload, dict) else {}
    operations = repo.get("operations", []) if isinstance(repo, dict) else []
    if not operations:
        raise RuntimeError("NYFED_RRP_PROBE_EMPTY: official endpoint returned no operations")
    return operations


def main() -> int:
    r = requests.get(URL, params=PARAMS, timeout=45)
    r.raise_for_status()
    payload = r.json()

    repo = payload.get("repo", {}) if isinstance(payload, dict) else {}
    operations = repo.get("operations", []) if isinstance(repo, dict) else []
    sample = operations[0] if operations else None

    result = {
        "source": "Federal Reserve Bank of New York Markets Data API",
        "endpoint": r.url,
        "http_status": r.status_code,
        "top_level_keys": sorted(payload.keys()) if isinstance(payload, dict) else [],
        "repo_keys": sorted(repo.keys()) if isinstance(repo, dict) else [],
        "operation_count": len(operations),
        "sample_operation": sample,
        "formal_pit_ready": False,
        "note": "Transport/shape probe only. Formal use requires field-equivalence, operation-timing, release-availability, unit and PIT QA.",
    }
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))

    if not operations:
        raise SystemExit("NYFED_RRP_PROBE_EMPTY: official endpoint returned no operations")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
