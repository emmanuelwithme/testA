from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from v70_treasury_tga_paged import fetch_tga_paged
from v70_fed_board_h41_probe import fetch_h41_total_assets
from v70_nyfed_rrp_probe import fetch_rrp_operations
from v70_treasury_rates_probe import fetch_treasury_rate_components
from v70_sahm_official_probe import fetch_sahm_official

OUT = Path('v70_pit_availability_qa_output')
OUT.mkdir(exist_ok=True)
REPORT = OUT / 'pit_availability_qa.json'
FORMAL_START = pd.Timestamp('2005-01-01')
FORMAL_END = pd.Timestamp('2026-08-31')


def _coverage(first, last, n):
    return {
        'first_observation': None if first is None else str(pd.Timestamp(first).date()),
        'last_observation': None if last is None else str(pd.Timestamp(last).date()),
        'n': int(n),
    }


def main() -> int:
    rows = []

    # Current formal architecture: Mentor v3.6 owns S0/B0; V70_2.html is the
    # executable tactical allocator and V70_16白皮書.md is its explanatory SOT.
    # Missing historical PIT values remain NA / Insufficient Data; never backfill.
    tga = fetch_tga_paged()
    rows.append({
        'logical_input': 'TGA',
        'source': 'U.S. Treasury Fiscal Data Daily Treasury Statement',
        **_coverage(tga.index.min(), tga.index.max(), len(tga)),
        'availability_mapping': 'UNRESOLVED_MACHINE_VERIFICATION',
        'coverage_before_first_observation': 'NA_ONLY_NO_BACKFILL',
        'formal_pit_ready': False,
        'blockers': [
            'official publication/availability timestamp mapping not yet machine-verified',
            'formal window 2005-01-01..2005-10-02 has no TGA observation in this official series and must remain NA',
        ],
    })

    walcl = fetch_h41_total_assets()
    rows.append({
        'logical_input': 'WALCL',
        'source': 'Federal Reserve Board H.4.1',
        **_coverage(walcl.index.min(), walcl.index.max(), len(walcl)),
        'verified_release_convention': 'Thursday generally 4:30 p.m. ET; holiday shifts possible',
        'evidence_url': 'https://www.federalreserve.gov/releases/h41/',
        'availability_mapping': 'HISTORICAL_HOLIDAY_CALENDAR_NOT_YET_MAPPED',
        'formal_pit_ready': False,
        'blockers': [
            'historical release-date calendar including holiday shifts not yet mapped',
            'exact equivalence QA to V70_2 WALCL semantics not yet completed',
        ],
    })

    operations = fetch_rrp_operations()
    dates = [r.get('operationDate') for r in operations if r.get('operationDate')]
    first_rrp = min(dates) if dates else None
    last_rrp = max(dates) if dates else None
    rows.append({
        'logical_input': 'RRP',
        'source': 'Federal Reserve Bank of New York Markets Data API',
        **_coverage(first_rrp, last_rrp, len(operations)),
        'verified_release_convention': 'summary results are published after completion of each reverse repo operation',
        'evidence_url': 'https://www.newyorkfed.org/markets/rrp_faq/rrp-faq-archive/rrp-faq-230726',
        'availability_mapping': 'OPERATION_DATE_RESULTS_KNOWN_AFTER_OPERATION; FORMAL EXECUTION MAPPER NOT_YET_LOCKED',
        'coverage_before_first_observation': 'NA_ONLY_NO_BACKFILL',
        'formal_pit_ready': False,
        'blockers': [
            'formal execution-time mapper not yet locked to operation result publication time',
            '2005-01-01..2007-04-25 has no observation in current official operation API and must remain NA unless archival official data is validated',
            'field/unit equivalence of totalAmtAccepted to V70_2 RRP definition still requires explicit QA',
        ],
    })

    rates = fetch_treasury_rate_components()
    be = rates[['date', 't5yie_candidate']].dropna()
    real10 = rates[['date', 'real_10y']].dropna()
    rows.append({
        'logical_input': '5Y_BREAKEVEN',
        'source': 'U.S. Treasury Daily Interest Rate XML',
        **_coverage(be['date'].min(), be['date'].max(), len(be)),
        'candidate_formula': 'BC_5YEAR - TC_5YEAR',
        'availability_mapping': 'CONSERVATIVE_T_PLUS_1_NOT_YET_FORMALLY_LOCKED',
        'formal_pit_ready': False,
        'blockers': [
            'exact equivalence QA to V70_2 5Y breakeven semantics is not complete',
            'official publication availability timing has not yet been machine-verified for full history',
        ],
    })
    rows.append({
        'logical_input': 'REAL_10Y',
        'source': 'U.S. Treasury Daily Real Yield Curve XML',
        **_coverage(real10['date'].min(), real10['date'].max(), len(real10)),
        'candidate_field': 'TC_10YEAR',
        'availability_mapping': 'CONSERVATIVE_T_PLUS_1_NOT_YET_FORMALLY_LOCKED',
        'formal_pit_ready': False,
        'blockers': [
            'exact equivalence QA to V70_2 real-10Y semantics is not complete',
            'official publication availability timing has not yet been machine-verified for full history',
        ],
    })

    sahm, transport, provenance = fetch_sahm_official(attempts=0)
    missing_values = provenance.get('snapshot_meta', {}).get('missing_values', [])
    rows.append({
        'logical_input': 'SAHM_RULE',
        'source': 'Federal Reserve Bank of St. Louis FRED SAHMREALTIME official pinned snapshot',
        **_coverage(sahm.index.min(), sahm.index.max(), len(sahm)),
        'transport': transport,
        'missing_values': missing_values,
        'availability_mapping': 'OBSERVATION_SERIES_ONLY; HISTORICAL_RELEASE_DATES_NOT_YET_MAPPED',
        'formal_pit_ready': False,
        'blockers': [
            'historical release availability dates must be mapped before weekly PIT use',
            '2025-10-01 official-series missing value must remain missing unless an official vintage/archive resolves it',
        ],
    })

    unresolved = [r['logical_input'] for r in rows if not r.get('formal_pit_ready')]
    report = {
        'architecture': 'Mentor v3.6 S0/B0 -> V70_2 tactical C/T total budgets -> V82/BondV75 security execution',
        'v70_executable_source': 'V70_2.html',
        'v70_explanatory_source': 'V70_16白皮書.md',
        'formal_window': '2005-01-01..2026-08-31',
        'policy': {
            'point_in_time_only': True,
            'no_future_fill': True,
            'no_neutral_imputation': True,
            'missing_before_first_valid_pit': 'NA / Insufficient Data',
            'same_day_close_signal_execution': 'T+1 required by user-explicit formal backtest contract; standalone 母規則回測.md currently unresolved in Drive root',
        },
        'rows': rows,
        'formal_pit_ready_count': sum(bool(r.get('formal_pit_ready')) for r in rows),
        'formal_pit_required_count': len(rows),
        'formal_pit_unresolved': unresolved,
        'formal_backtest_ready': False,
        'qa_status': 'DIAGNOSTIC_COMPLETE_FORMAL_PIT_BLOCKED',
        'qa_note': 'Hard-gate diagnostic only. It changes no strategy rule and invents no missing observations. Raw-source availability is necessary but not sufficient for formal PIT/T+1 readiness.',
    }
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
