from __future__ import annotations

import json
import sys
from pathlib import Path

import v70_macro_only_source_qa as base
from v70_fed_board_h41_probe import fetch_h41_total_assets

OUT = Path('v70_macro_source_qa_output')
REPORT = OUT / 'source_qa.json'
REQUIRED = {'5Y_BREAKEVEN', 'REAL_10Y', 'WALCL', 'RRP', 'TGA', 'SAHM_RULE'}
OK = {'RAW_SOURCE_OK', 'RAW_SOURCE_OK_OFFICIAL_FALLBACK', 'RAW_SOURCE_OK_OFFICIAL_FED_BOARD'}


def main() -> int:
    # Run the existing official-source QA unchanged first.
    base.main()
    report = json.loads(REPORT.read_text(encoding='utf-8'))
    rows = report.get('source_rows', [])

    walcl_row = next((r for r in rows if r.get('logical_input') == 'WALCL'), None)
    if walcl_row is None or walcl_row.get('status') not in OK:
        try:
            s = fetch_h41_total_assets()
            replacement = {
                'logical_input': 'WALCL',
                'series_id': 'RESPPMA_N.WW',
                'source': 'Federal Reserve Board H.4.1 Data Download Program',
                'fallback_from': 'WALCL',
                'status': 'RAW_SOURCE_OK_OFFICIAL_FED_BOARD',
                'first_observation': str(s.index.min().date()),
                'last_observation': str(s.index.max().date()),
                'n': int(len(s)),
                'conversion': 'million_usd_to_bn',
                'formal_pit_ready': False,
                'pit_note': 'Official Board raw source retrieved. Formal use still requires WALCL equivalence QA plus release-availability/PIT mapping before backtest integration.',
            }
            rows = [r for r in rows if r.get('logical_input') != 'WALCL'] + [replacement]
        except Exception as exc:
            if walcl_row is not None:
                walcl_row['fed_board_fallback_error'] = repr(exc)

    rows.sort(key=lambda r: r.get('logical_input', ''))
    report['source_rows'] = rows
    report['raw_source_ok_count'] = sum(r.get('status') in OK for r in rows)
    report['transport_fail_count'] = sum(r.get('status') in {
        'RUNNER_NETWORK_TIMEOUT', 'RUNNER_NETWORK_ERROR',
        'RUNNER_NETWORK_TIMEOUT_AND_OFFICIAL_FALLBACK_FAIL'
    } for r in rows)
    report.setdefault('official_fallbacks', {})['WALCL'] = (
        'Federal Reserve Board H.4.1 RESPPMA_N.WW; requires equivalence and PIT QA before formal use'
    )

    status_by_logical = {r.get('logical_input'): r.get('status') for r in rows}
    missing = sorted(k for k in REQUIRED if status_by_logical.get(k) not in OK)
    report['required_raw_sources_complete'] = not missing
    report['required_raw_sources_missing'] = missing
    report['formal_backtest_ready'] = False
    report['qa_pass'] = not missing
    report['qa_note'] = (
        'Official raw-source transport completeness only. Even when complete, formal use remains blocked until '
        'release-availability/PIT, vintage, unit, and equivalence QA are complete.'
    )

    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2))

    if missing:
        print(f'SOURCE_QA_INCOMPLETE: missing required official raw sources: {missing}', file=sys.stderr)
        return 2
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
