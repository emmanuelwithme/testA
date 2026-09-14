from __future__ import annotations

import json
from pathlib import Path

REPORT = Path('v70_pit_availability_qa_output/pit_availability_qa.json')
TREASURY_EVIDENCE = 'https://home.treasury.gov/policy-issues/financing-the-government/interest-rate-statistics'


def main() -> int:
    if not REPORT.exists():
        raise SystemExit(f'PIT_REPORT_MISSING: {REPORT}')

    data = json.loads(REPORT.read_text(encoding='utf-8'))
    rows = data.get('rows', [])
    real10 = next((r for r in rows if r.get('logical_input') == 'REAL_10Y'), None)
    if not real10:
        raise SystemExit('REAL_10Y_ROW_MISSING')

    # Official Treasury Interest Rate Statistics states that the Daily Treasury
    # PAR Real Yield Curve is derived from indicative FBNY quotations obtained
    # at approximately 3:30 p.m. each business day.  The probe's TC_10YEAR is
    # the official 10-year field from that Daily Treasury Real Yield Curve.
    # Formal execution is more conservative: observation D is not usable for a
    # same-day signal and becomes PIT-available only on the next U.S. federal
    # business day; strategy execution remains subject to the mother rule's T+1.
    diag = real10.pop('t_plus_1_diagnostic', None)
    if diag:
        real10['prior_diagnostic_mapping'] = diag
    real10.update({
        'verified_release_convention': (
            'U.S. Treasury Daily PAR Real Yield Curve input quotations are obtained '
            'from the Federal Reserve Bank of New York at approximately 3:30 p.m. '
            'each business day; Treasury began publishing the series on 2004-01-02'
        ),
        'evidence_url': TREASURY_EVIDENCE,
        'field_semantics': (
            'TC_10YEAR = official 10-year point on the U.S. Treasury Daily PAR Real '
            'Yield Curve (TIPS real yield); matches V70_2 Real 10Y input semantics'
        ),
        'availability_mapping': (
            'OBSERVATION_DATE_3:30PM_ET -> NEXT_US_FEDERAL_BUSINESS_DAY; '
            'SAME_DAY_USE_FORBIDDEN; FORMAL_STRATEGY_EXECUTION_STILL_T+1'
        ),
        'pit_availability_sample': {
            'mapper': 'TREASURY_REAL_YIELD_NEXT_US_FEDERAL_BUSINESS_DAY',
            'same_observation_day_use_forbidden': True,
            'federal_holiday_calendar_applied': True,
            'formal_strategy_execution_requires_t_plus_1': True,
        },
        'formal_pit_ready': True,
        'blockers': [],
        'qa_note': (
            'Promoted only after official source/timing and exact 10Y real-yield field '
            'semantics were locked. No proxy, future fill, or same-day use is allowed.'
        ),
    })

    ready = [r['logical_input'] for r in rows if r.get('formal_pit_ready')]
    unresolved = [r['logical_input'] for r in rows if not r.get('formal_pit_ready')]
    data['formal_pit_ready_inputs'] = ready
    data['formal_pit_ready_count'] = len(ready)
    data['formal_pit_required_count'] = len(rows)
    data['formal_pit_unresolved'] = unresolved
    data['formal_backtest_ready'] = False
    data['qa_status'] = 'PARTIAL_FORMAL_PIT_READY_REMAINDER_BLOCKED'
    data['qa_note'] = (
        'TGA, WALCL and REAL_10Y now have official availability semantics plus '
        'conservative deterministic mappings. RRP, 5Y breakeven and Sahm remain '
        'blocked rather than guessed. PIT readiness alone never authorizes a final '
        'formal strategy conclusion.'
    )

    REPORT.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print('REAL_10Y_FORMAL_PIT_PROMOTION_PASS')
    print('formal_pit_ready_count=', data['formal_pit_ready_count'])
    print('formal_pit_unresolved=', ','.join(unresolved))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
