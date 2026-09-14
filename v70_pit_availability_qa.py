from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
from pandas.tseries.holiday import USFederalHolidayCalendar
from pandas.tseries.offsets import CustomBusinessDay

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
US_FEDERAL_BDAY = CustomBusinessDay(calendar=USFederalHolidayCalendar())


def _coverage(first, last, n):
    return {
        'first_observation': None if first is None else str(pd.Timestamp(first).date()),
        'last_observation': None if last is None else str(pd.Timestamp(last).date()),
        'n': int(n),
    }


def _next_federal_business_day(value):
    if value is None or pd.isna(value):
        return None
    return str((pd.Timestamp(value).normalize() + US_FEDERAL_BDAY).date())


def _federal_tplus1_sample(first, last, mapper='US_FEDERAL_NEXT_BUSINESS_DAY'):
    return {
        'first_observation_available_date': _next_federal_business_day(first),
        'last_observation_available_date': _next_federal_business_day(last),
        'mapper': mapper,
        'same_observation_day_use_forbidden': True,
        'federal_holiday_calendar_applied': True,
    }


def _weekday_t_plus_1(value):
    """Diagnostic-only next-weekday mapper for sources not yet formally timed."""
    if value is None or pd.isna(value):
        return None
    return str((pd.Timestamp(value).normalize() + pd.offsets.BDay(1)).date())


def _diagnostic_tplus1_sample(first, last):
    return {
        'first_observation_diagnostic_available_date': _weekday_t_plus_1(first),
        'last_observation_diagnostic_available_date': _weekday_t_plus_1(last),
        'mapper': 'WEEKDAY_BDAY_PLUS_1_DIAGNOSTIC_ONLY',
        'same_day_use_forbidden': True,
        'formal_holiday_calendar_locked': False,
    }


def main() -> int:
    rows = []

    # Current formal architecture: Mentor v3.6 owns S0/B0; V70_2.html is the
    # executable tactical allocator and V70_16白皮書.md is its explanatory SOT.
    # 母規則回測.md (Library, 2026-09-10 00:56) owns the formal experiment/PIT/T+1 contract.
    # Missing historical PIT values remain NA / Insufficient Data; never backfill.
    tga = fetch_tga_paged()
    tga_first, tga_last = tga.index.min(), tga.index.max()
    rows.append({
        'logical_input': 'TGA',
        'source': 'U.S. Treasury Fiscal Data Daily Treasury Statement / Operating Cash Balance',
        **_coverage(tga_first, tga_last, len(tga)),
        'verified_release_convention': 'Daily Treasury Statement is available by 4:00 p.m. the following business day',
        'evidence_url': 'https://home.treasury.gov/policy-issues/financial-markets-financial-institutions-and-fiscal-service/cash-and-debt-forecasting',
        'availability_mapping': 'OBSERVATION_DATE -> NEXT_US_FEDERAL_BUSINESS_DAY_BY_16:00_ET',
        'pit_availability_sample': _federal_tplus1_sample(tga_first, tga_last, 'DTS_NEXT_US_FEDERAL_BUSINESS_DAY'),
        'field_semantics': 'Treasury General Account / operating cash closing balance normalized from official DTS legacy+modern schemas',
        'coverage_before_first_observation': 'NA_ONLY_NO_BACKFILL',
        'formal_pit_ready': True,
        'blockers': [],
        'coverage_note': 'formal window 2005-01-01..2005-10-02 has no observation in this official series and remains NA; readiness starts with first official observation',
    })

    walcl = fetch_h41_total_assets()
    walcl_first, walcl_last = walcl.index.min(), walcl.index.max()
    rows.append({
        'logical_input': 'WALCL',
        'source': 'Federal Reserve Board H.4.1 Data Download Program',
        **_coverage(walcl_first, walcl_last, len(walcl)),
        'official_series_mnemonic': 'RESPPMA_N.WW',
        'field_semantics': 'Total assets (less eliminations from consolidation), Wednesday level; Board-source line underlying WALCL semantics',
        'verified_release_convention': 'H.4.1 is released each Thursday, generally at 4:30 p.m.; federal-holiday release shifts are handled conservatively by next federal business day',
        'evidence_url': 'https://www.federalreserve.gov/releases/h41/',
        'availability_mapping': 'WEDNESDAY_OBSERVATION -> NEXT_US_FEDERAL_BUSINESS_DAY_BY_16:30_ET',
        'pit_availability_sample': _federal_tplus1_sample(walcl_first, walcl_last, 'H41_NEXT_US_FEDERAL_BUSINESS_DAY'),
        'formal_pit_ready': True,
        'blockers': [],
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
        'availability_mapping': 'OPERATION_DATE_RESULTS_KNOWN_AFTER_OPERATION; CONSERVATIVE T+1 DIAGNOSTIC MAPPER IMPLEMENTED',
        't_plus_1_diagnostic': _diagnostic_tplus1_sample(first_rrp, last_rrp),
        'coverage_before_first_observation': 'NA_ONLY_NO_BACKFILL',
        'formal_pit_ready': False,
        'blockers': [
            'exact historical operation-result publication timestamp and applicable operation/trading holiday calendar still need formal lock',
            '2005-01-01..2007-04-25 has no observation in current official operation API and must remain NA unless archival official data is validated',
            'field/unit equivalence of totalAmtAccepted to V70_2 RRP definition still requires explicit QA',
        ],
    })

    rates = fetch_treasury_rate_components()
    be = rates[['date', 't5yie_candidate']].dropna()
    real10 = rates[['date', 'real_10y']].dropna()
    be_first, be_last = be['date'].min(), be['date'].max()
    real_first, real_last = real10['date'].min(), real10['date'].max()
    rows.append({
        'logical_input': '5Y_BREAKEVEN',
        'source': 'U.S. Treasury Daily Interest Rate XML',
        **_coverage(be_first, be_last, len(be)),
        'candidate_formula': 'BC_5YEAR - TC_5YEAR',
        'availability_mapping': 'CONSERVATIVE T+1 DIAGNOSTIC MAPPER IMPLEMENTED; FORMAL PUBLICATION LOCK PENDING',
        't_plus_1_diagnostic': _diagnostic_tplus1_sample(be_first, be_last),
        'formal_pit_ready': False,
        'blockers': [
            'exact equivalence QA to V70_2 5Y breakeven semantics is not complete',
            'official publication availability timing has not yet been machine-verified for full history',
        ],
    })
    rows.append({
        'logical_input': 'REAL_10Y',
        'source': 'U.S. Treasury Daily Real Yield Curve XML',
        **_coverage(real_first, real_last, len(real10)),
        'candidate_field': 'TC_10YEAR',
        'availability_mapping': 'CONSERVATIVE T+1 DIAGNOSTIC MAPPER IMPLEMENTED; FORMAL PUBLICATION LOCK PENDING',
        't_plus_1_diagnostic': _diagnostic_tplus1_sample(real_first, real_last),
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
    ready = [r['logical_input'] for r in rows if r.get('formal_pit_ready')]
    tplus1_diag = [r['logical_input'] for r in rows if r.get('t_plus_1_diagnostic')]
    report = {
        'architecture': 'Mentor v3.6 S0/B0 -> V70_2 tactical C/T total budgets -> V82/BondV75 security execution',
        'v70_executable_source': 'V70_2.html Output Contract v1.1.1',
        'v70_explanatory_source': 'V70_16白皮書.md v3.4.1',
        'mother_backtest_source': '母規則回測.md Library snapshot 2026-09-10 00:56',
        'formal_window': '2005-01-01..2026-08-31',
        'policy': {
            'point_in_time_only': True,
            'no_future_fill': True,
            'no_neutral_imputation': True,
            'missing_before_first_valid_pit': 'NA / Insufficient Data',
            'same_day_close_signal_execution': 'T+1 required by formal 母規則回測.md; signals formed from same-day close data may execute no earlier than the next permitted trading session',
            'availability_vs_execution': 'formal_pit_ready means historical availability is mapped; strategy execution must still occur no earlier than the next permitted T+1 execution session',
            'diagnostic_tplus1_mapper': 'weekday next-business-day mapper for unresolved sources is engineering proof only and never overrides missing publication evidence',
        },
        'rows': rows,
        'formal_pit_ready_inputs': ready,
        't_plus_1_diagnostic_mapper_implemented_for': tplus1_diag,
        'formal_pit_ready_count': len(ready),
        'formal_pit_required_count': len(rows),
        'formal_pit_unresolved': unresolved,
        'formal_backtest_ready': False,
        'qa_status': 'PARTIAL_FORMAL_PIT_READY_REMAINDER_BLOCKED',
        'qa_note': 'TGA and WALCL have official availability conventions plus deterministic federal-business-day mappings. Remaining inputs stay blocked rather than guessed. PIT input readiness alone does not authorize final formal backtest conclusions.',
    }
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
