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
OUT.mkdir(exist_ok=True)
REPORT = OUT / 'source_qa.json'
REQUIRED = {'5Y_BREAKEVEN', 'REAL_10Y', 'WALCL', 'RRP', 'TGA', 'SAHM_RULE'}
OK = {
    'RAW_SOURCE_OK_OFFICIAL_FALLBACK',
    'RAW_SOURCE_OK_OFFICIAL_FED_BOARD',
    'RAW_SOURCE_OK_OFFICIAL_NYFED',
    'RAW_SOURCE_OK_OFFICIAL_TREASURY',
    'RAW_SOURCE_OK_OFFICIAL_FRED_ALTERNATE',
    'RAW_SOURCE_OK_OFFICIAL_FRED_PINNED_SNAPSHOT',
}


def _fail(logical_input: str, source: str, exc: Exception) -> dict:
    return {
        'logical_input': logical_input,
        'source': source,
        'status': 'OFFICIAL_SOURCE_FAIL',
        'error': repr(exc),
        'formal_pit_ready': False,
    }


def main() -> int:
    rows: list[dict] = []

    # TGA: use the already validated U.S. Treasury DTS transport directly.
    try:
        s = base.treasury_tga()
        rows.append({
            'logical_input': 'TGA',
            'series_id': 'DTS_OPERATING_CASH_BALANCE_TGA',
            'source': 'U.S. Treasury Fiscal Data Daily Treasury Statement Operating Cash Balance',
            'status': 'RAW_SOURCE_OK_OFFICIAL_FALLBACK',
            'first_observation': str(s.index.min().date()),
            'last_observation': str(s.index.max().date()),
            'n': int(len(s)),
            'conversion': 'million_usd_to_bn',
            'formal_pit_ready': False,
            'pit_note': 'Official Treasury raw source retrieved; formal use still requires publication/availability-date mapping, coverage and unit QA.',
        })
    except Exception as exc:
        rows.append(_fail('TGA', 'U.S. Treasury Fiscal Data', exc))

    # WALCL equivalent underlying Board H.4.1 line item.
    try:
        s = fetch_h41_total_assets()
        rows.append({
            'logical_input': 'WALCL',
            'series_id': 'RESPPMA_N.WW',
            'source': 'Federal Reserve Board H.4.1 Data Download Program',
            'status': 'RAW_SOURCE_OK_OFFICIAL_FED_BOARD',
            'first_observation': str(s.index.min().date()),
            'last_observation': str(s.index.max().date()),
            'n': int(len(s)),
            'conversion': 'million_usd_to_bn',
            'formal_pit_ready': False,
            'pit_note': 'Official Board raw source retrieved. Formal use still requires WALCL equivalence QA plus release-availability/PIT mapping.',
        })
    except Exception as exc:
        rows.append(_fail('WALCL', 'Federal Reserve Board H.4.1', exc))

    # NY Fed reverse repo operations.
    try:
        operations = fetch_rrp_operations()
        dates = [r.get('operationDate') for r in operations if r.get('operationDate')]
        rows.append({
            'logical_input': 'RRP',
            'series_id': 'NYFED_REVERSE_REPO_OPERATIONS',
            'source': 'Federal Reserve Bank of New York Markets Data API',
            'status': 'RAW_SOURCE_OK_OFFICIAL_NYFED',
            'first_observation': min(dates) if dates else None,
            'last_observation': max(dates) if dates else None,
            'n': int(len(operations)),
            'field_candidate': 'totalAmtAccepted',
            'formal_pit_ready': False,
            'pit_note': 'Official NY Fed source retrieved. Formal use still requires field-equivalence, release timing, unit and PIT/T+1 QA.',
        })
    except Exception as exc:
        rows.append(_fail('RRP', 'Federal Reserve Bank of New York Markets Data API', exc))

    # Treasury nominal/real curve components for 5Y breakeven candidate and real 10Y.
    try:
        rates = fetch_treasury_rate_components()
        x = rates[['date', 't5yie_candidate']].dropna()
        rows.append({
            'logical_input': '5Y_BREAKEVEN',
            'series_id': 'TREASURY_BC_5YEAR_MINUS_TC_5YEAR',
            'source': 'U.S. Department of the Treasury Daily Interest Rate XML Feed',
            'status': 'RAW_SOURCE_OK_OFFICIAL_TREASURY',
            'first_observation': None if x.empty else str(x['date'].min().date()),
            'last_observation': None if x.empty else str(x['date'].max().date()),
            'n': int(len(x)),
            'formula_candidate': 'BC_5YEAR - TC_5YEAR',
            'formal_pit_ready': False,
            'pit_note': 'Formal use still requires exact T5YIE equivalence, publication availability, unit and PIT/T+1 QA.',
        })
        x = rates[['date', 'real_10y']].dropna()
        rows.append({
            'logical_input': 'REAL_10Y',
            'series_id': 'TREASURY_TC_10YEAR',
            'source': 'U.S. Department of the Treasury Daily Real Yield Curve XML Feed',
            'status': 'RAW_SOURCE_OK_OFFICIAL_TREASURY',
            'first_observation': None if x.empty else str(x['date'].min().date()),
            'last_observation': None if x.empty else str(x['date'].max().date()),
            'n': int(len(x)),
            'field_candidate': 'TC_10YEAR',
            'formal_pit_ready': False,
            'pit_note': 'Formal use still requires exact DFII10 equivalence, publication availability, unit and PIT/T+1 QA.',
        })
    except Exception as exc:
        rows.append(_fail('5Y_BREAKEVEN', 'U.S. Treasury Daily Interest Rate XML Feed', exc))
        rows.append(_fail('REAL_10Y', 'U.S. Treasury Daily Real Yield Curve XML Feed', exc))

    # Deterministic same-series FRED snapshot. attempts=0 intentionally skips the
    # known runner transport timeouts; the snapshot is hash-pinned and provenance-checked.
    try:
        s, transport, provenance = fetch_sahm_official(attempts=0)
        status = (
            'RAW_SOURCE_OK_OFFICIAL_FRED_PINNED_SNAPSHOT'
            if transport == 'OFFICIAL_FRED_PINNED_SNAPSHOT'
            else 'RAW_SOURCE_OK_OFFICIAL_FRED_ALTERNATE'
        )
        rows.append({
            'logical_input': 'SAHM_RULE',
            'series_id': 'SAHMREALTIME',
            'source': 'Federal Reserve Bank of St. Louis FRED official series',
            'status': status,
            'transport': transport,
            'first_observation': str(s.index.min().date()),
            'last_observation': str(s.index.max().date()),
            'n': int(len(s)),
            'latest_value': float(s.iloc[-1]),
            'provenance': provenance,
            'formal_pit_ready': False,
            'pit_note': 'Formal use still requires release-availability/T+1 mapping and gap QA.',
        })
    except Exception as exc:
        rows.append(_fail('SAHM_RULE', 'Federal Reserve Bank of St. Louis FRED SAHMREALTIME pinned official snapshot', exc))

    rows.sort(key=lambda r: r.get('logical_input', ''))
    status_by_logical = {r.get('logical_input'): r.get('status') for r in rows}
    missing = sorted(k for k in REQUIRED if status_by_logical.get(k) not in OK)

    report = {
        'candidate': 'V70.2 Macro-only Weekly Candidate',
        'formal_window': '2005-01-01..2026-08-31',
        'source_rows': rows,
        'raw_source_ok_count': sum(r.get('status') in OK for r in rows),
        'required_raw_sources_complete': not missing,
        'required_raw_sources_missing': missing,
        'formal_backtest_ready': False,
        'qa_pass': not missing,
        'qa_note': (
            'Official raw-source completeness only. Direct FRED runner paths are bypassed after repeated transport timeouts; '
            'no third-party proxies are used. Formal use remains blocked until release-availability/PIT, vintage, unit, coverage and equivalence QA are complete.'
        ),
        'still_requires_separate_licensed_or_archival_validation': ['PMI_MANUFACTURING', 'PMI_SERVICES', 'LEI_YOY'],
    }
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2))

    if missing:
        print(f'SOURCE_QA_INCOMPLETE: missing required official raw sources: {missing}', file=sys.stderr)
        return 2
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
