from __future__ import annotations

import json
import sys
from pathlib import Path

import v70_macro_only_source_qa as base
from v70_fed_board_h41_probe import fetch_h41_total_assets
from v70_nyfed_rrp_probe import fetch_rrp_operations
from v70_treasury_rates_probe import fetch_treasury_rate_components
from v70_sahm_official_probe import fetch_sahm_official

OUT = Path('v70_macro_source_qa_output')
REPORT = OUT / 'source_qa.json'
REQUIRED = {'5Y_BREAKEVEN', 'REAL_10Y', 'WALCL', 'RRP', 'TGA', 'SAHM_RULE'}
OK = {
    'RAW_SOURCE_OK',
    'RAW_SOURCE_OK_OFFICIAL_FALLBACK',
    'RAW_SOURCE_OK_OFFICIAL_FED_BOARD',
    'RAW_SOURCE_OK_OFFICIAL_NYFED',
    'RAW_SOURCE_OK_OFFICIAL_TREASURY',
    'RAW_SOURCE_OK_OFFICIAL_FRED_ALTERNATE',
    'RAW_SOURCE_OK_OFFICIAL_FRED_PINNED_SNAPSHOT',
}


def _replace(rows: list[dict], logical_input: str, replacement: dict) -> list[dict]:
    return [r for r in rows if r.get('logical_input') != logical_input] + [replacement]


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
            rows = _replace(rows, 'WALCL', replacement)
        except Exception as exc:
            if walcl_row is not None:
                walcl_row['fed_board_fallback_error'] = repr(exc)

    rrp_row = next((r for r in rows if r.get('logical_input') == 'RRP'), None)
    if rrp_row is None or rrp_row.get('status') not in OK:
        try:
            operations = fetch_rrp_operations()
            dates = [r.get('operationDate') for r in operations if r.get('operationDate')]
            replacement = {
                'logical_input': 'RRP',
                'series_id': 'NYFED_REVERSE_REPO_OPERATIONS',
                'source': 'Federal Reserve Bank of New York Markets Data API',
                'fallback_from': 'RRPONTSYD',
                'status': 'RAW_SOURCE_OK_OFFICIAL_NYFED',
                'first_observation': min(dates) if dates else None,
                'last_observation': max(dates) if dates else None,
                'n': int(len(operations)),
                'field_candidate': 'totalAmtAccepted',
                'formal_pit_ready': False,
                'pit_note': 'Official NY Fed operations source retrieved. Formal use still requires field-equivalence to the locked RRP input, operation/release timing, unit and PIT/T+1 QA.',
            }
            rows = _replace(rows, 'RRP', replacement)
        except Exception as exc:
            if rrp_row is not None:
                rrp_row['nyfed_fallback_error'] = repr(exc)

    breakeven_row = next((r for r in rows if r.get('logical_input') == '5Y_BREAKEVEN'), None)
    real10_row = next((r for r in rows if r.get('logical_input') == 'REAL_10Y'), None)
    need_treasury = (
        breakeven_row is None or breakeven_row.get('status') not in OK or
        real10_row is None or real10_row.get('status') not in OK
    )
    if need_treasury:
        try:
            rates = fetch_treasury_rate_components()
            if breakeven_row is None or breakeven_row.get('status') not in OK:
                x = rates[['date', 't5yie_candidate']].dropna()
                replacement = {
                    'logical_input': '5Y_BREAKEVEN',
                    'series_id': 'TREASURY_BC_5YEAR_MINUS_TC_5YEAR',
                    'source': 'U.S. Department of the Treasury Daily Interest Rate XML Feed',
                    'fallback_from': 'T5YIE',
                    'status': 'RAW_SOURCE_OK_OFFICIAL_TREASURY',
                    'first_observation': None if x.empty else str(x['date'].min().date()),
                    'last_observation': None if x.empty else str(x['date'].max().date()),
                    'n': int(len(x)),
                    'formula_candidate': 'BC_5YEAR - TC_5YEAR',
                    'formal_pit_ready': False,
                    'pit_note': 'Official Treasury components retrieved. Formal use still requires exact T5YIE equivalence, publication-availability, unit and PIT/T+1 QA.',
                }
                rows = _replace(rows, '5Y_BREAKEVEN', replacement)
            if real10_row is None or real10_row.get('status') not in OK:
                x = rates[['date', 'real_10y']].dropna()
                replacement = {
                    'logical_input': 'REAL_10Y',
                    'series_id': 'TREASURY_TC_10YEAR',
                    'source': 'U.S. Department of the Treasury Daily Real Yield Curve XML Feed',
                    'fallback_from': 'DFII10',
                    'status': 'RAW_SOURCE_OK_OFFICIAL_TREASURY',
                    'first_observation': None if x.empty else str(x['date'].min().date()),
                    'last_observation': None if x.empty else str(x['date'].max().date()),
                    'n': int(len(x)),
                    'field_candidate': 'TC_10YEAR',
                    'formal_pit_ready': False,
                    'pit_note': 'Official Treasury real 10Y retrieved. Formal use still requires exact DFII10 equivalence, publication-availability, unit and PIT/T+1 QA.',
                }
                rows = _replace(rows, 'REAL_10Y', replacement)
        except Exception as exc:
            if breakeven_row is not None:
                breakeven_row['treasury_fallback_error'] = repr(exc)
            if real10_row is not None:
                real10_row['treasury_fallback_error'] = repr(exc)

    sahm_row = next((r for r in rows if r.get('logical_input') == 'SAHM_RULE'), None)
    if sahm_row is None or sahm_row.get('status') not in OK:
        try:
            s, transport, provenance = fetch_sahm_official()
            status = (
                'RAW_SOURCE_OK_OFFICIAL_FRED_PINNED_SNAPSHOT'
                if transport == 'OFFICIAL_FRED_PINNED_SNAPSHOT'
                else 'RAW_SOURCE_OK_OFFICIAL_FRED_ALTERNATE'
            )
            replacement = {
                'logical_input': 'SAHM_RULE',
                'series_id': 'SAHMREALTIME',
                'source': 'Federal Reserve Bank of St. Louis FRED official series',
                'fallback_from': 'SAHMREALTIME direct FRED runner transport',
                'status': status,
                'transport': transport,
                'first_observation': str(s.index.min().date()),
                'last_observation': str(s.index.max().date()),
                'n': int(len(s)),
                'latest_value': float(s.iloc[-1]),
                'provenance': provenance,
                'formal_pit_ready': False,
                'pit_note': 'Official SAHMREALTIME raw series retrieved or hash-pinned from the same official FRED table. Formal use still requires release-availability/T+1 mapping and gap QA.',
            }
            rows = _replace(rows, 'SAHM_RULE', replacement)
        except Exception as exc:
            if sahm_row is not None:
                sahm_row['official_sahm_fallback_error'] = repr(exc)

    rows.sort(key=lambda r: r.get('logical_input', ''))
    report['source_rows'] = rows
    report['raw_source_ok_count'] = sum(r.get('status') in OK for r in rows)
    report['transport_fail_count'] = sum(r.get('status') in {
        'RUNNER_NETWORK_TIMEOUT', 'RUNNER_NETWORK_ERROR',
        'RUNNER_NETWORK_TIMEOUT_AND_OFFICIAL_FALLBACK_FAIL'
    } for r in rows)
    fallbacks = report.setdefault('official_fallbacks', {})
    fallbacks['WALCL'] = (
        'Federal Reserve Board H.4.1 RESPPMA_N.WW; requires equivalence and PIT QA before formal use'
    )
    fallbacks['RRP'] = (
        'Federal Reserve Bank of New York Markets Data API reverse-repo operations; '
        'requires field-equivalence, operation/release timing, unit and PIT/T+1 QA before formal use'
    )
    fallbacks['5Y_BREAKEVEN'] = (
        'U.S. Treasury BC_5YEAR minus TC_5YEAR; requires exact T5YIE equivalence and publication/PIT QA before formal use'
    )
    fallbacks['REAL_10Y'] = (
        'U.S. Treasury TC_10YEAR; requires exact DFII10 equivalence and publication/PIT QA before formal use'
    )
    fallbacks['SAHM_RULE'] = (
        'Federal Reserve Bank of St. Louis FRED SAHMREALTIME; if runner transport fails, use hash-pinned snapshot of the same official table; '
        'requires release-availability/T+1 and gap QA before formal use'
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
