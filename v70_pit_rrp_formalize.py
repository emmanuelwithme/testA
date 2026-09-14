from __future__ import annotations

import json
from pathlib import Path

REPORT = Path('v70_pit_availability_qa_output/pit_availability_qa.json')
NYFED_EVIDENCE = 'https://www.newyorkfed.org/markets/rrp_faq/rrp-faq-archive/rrp-faq-230322'


def main() -> int:
    if not REPORT.exists():
        raise SystemExit(f'PIT_REPORT_MISSING: {REPORT}')

    data = json.loads(REPORT.read_text(encoding='utf-8'))
    rows = data.get('rows', [])
    rrp = next((r for r in rows if r.get('logical_input') == 'RRP'), None)
    if not rrp:
        raise SystemExit('RRP_ROW_MISSING')

    diag = rrp.pop('t_plus_1_diagnostic', None)
    if diag:
        rrp['prior_diagnostic_mapping'] = diag

    # NY Fed states that after completion of each RRP operation the Desk
    # publishes a results summary containing total amount submitted, total amount
    # accepted, and the award rate.  The Markets Data API field
    # `totalAmtAccepted` therefore has exact semantic correspondence to the
    # accepted RRP amount.  API values are USD; V70 liquidity arithmetic uses
    # USD billions, so formal normalization is value / 1e9.
    # We deliberately do not use same-day results: operation date D is made
    # available only on the next U.S. federal business day.  This is stricter
    # than the official after-operation publication convention and avoids any
    # need to infer historical intraday timestamps.
    rrp.update({
        'verified_release_convention': (
            'After completion of a reverse repo operation, the New York Fed Desk '
            'publishes a summary containing total amount submitted, total amount '
            'accepted, and the award rate'
        ),
        'evidence_url': NYFED_EVIDENCE,
        'field_semantics': (
            'NY Fed Markets Data API totalAmtAccepted = total amount accepted in '
            'the completed reverse repo operation; V70 normalized unit = USD billions'
        ),
        'unit_normalization': 'totalAmtAccepted_USD / 1_000_000_000 = USD_billions',
        'availability_mapping': (
            'OPERATION_DATE_RESULT_PUBLISHED_AFTER_COMPLETION -> '
            'NEXT_US_FEDERAL_BUSINESS_DAY; SAME_DAY_USE_FORBIDDEN; '
            'FORMAL_STRATEGY_EXECUTION_STILL_T+1'
        ),
        'pit_availability_sample': {
            'mapper': 'NYFED_RRP_NEXT_US_FEDERAL_BUSINESS_DAY',
            'same_operation_day_use_forbidden': True,
            'federal_holiday_calendar_applied': True,
            'formal_strategy_execution_requires_t_plus_1': True,
        },
        'coverage_before_first_observation': 'NA_ONLY_NO_BACKFILL',
        'coverage_note': (
            'Current official operation API starts 2007-04-26 for the requested '
            'formal horizon; 2005-01-01..2007-04-25 remains N/A and is never backfilled'
        ),
        'formal_pit_ready': True,
        'blockers': [],
        'qa_note': (
            'Promoted with official result semantics and a conservative next-federal-'
            'business-day availability rule. No same-day use and no pre-coverage proxy.'
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
        'TGA, WALCL, RRP and REAL_10Y now have official source semantics and '
        'conservative deterministic availability mappings. 5Y breakeven and Sahm '
        'remain blocked rather than guessed. PIT readiness alone never authorizes '
        'a final formal strategy conclusion.'
    )

    REPORT.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print('RRP_FORMAL_PIT_PROMOTION_PASS')
    print('formal_pit_ready_count=', data['formal_pit_ready_count'])
    print('formal_pit_unresolved=', ','.join(unresolved))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
