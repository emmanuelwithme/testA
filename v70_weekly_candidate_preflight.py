import json
from pathlib import Path

OUT = Path('v70_weekly_preflight_output')
OUT.mkdir(exist_ok=True)

# V70.2 Macro-only Weekly Candidate: valuation group is intentionally removed.
# Slow macro data use Last Known Valid PIT / as-of carry-forward; absence of a new
# release is not missing data. Unit QA is a hard gate in the execution engine.
requirements = [
    ('VIX', 'market_daily', True, 'panic/volatility'),
    ('MOVE', 'market_daily', True, 'panic/volatility'),
    ('HY_OAS', 'fred_or_validated_snapshot', True, 'credit'),
    ('CORE_CPI_YOY', 'macro_release_pit', True, 'inflation'),
    ('5Y_BREAKEVEN', 'fred_daily', True, 'inflation/crisis'),
    ('5Y_BREAKEVEN_DELTA_1M', 'derived_from_pit', True, 'crisis'),
    ('REAL_10Y', 'fred_daily', True, 'rates/crisis'),
    ('10Y_MINUS_2Y', 'derived_fred_daily', True, 'rates'),
    ('NET_LIQUIDITY_DELTA_13W', 'derived_fed_rrp_tga_pit', True, 'liquidity/crisis'),
    ('DXY', 'market_daily', True, 'liquidity/accelerator'),
    ('WTI', 'market_daily', True, 'liquidity/accelerator'),
    ('PMI_MANUFACTURING', 'macro_release_pit', True, 'growth'),
    ('PMI_SERVICES', 'macro_release_pit', True, 'growth'),
    ('LEI_YOY', 'macro_release_pit', True, 'growth/recession'),
    ('SAHM_RULE', 'fred_realtime_or_pit', True, 'recession'),
    ('U3_UNEMPLOYMENT', 'macro_release_pit', True, 'recession'),
    ('NFP_3M_AVG', 'macro_release_pit', True, 'recession'),
]

# Confirmed reusable repo plumbing as of 2026-09-10. This means code/data access
# exists somewhere in the repository, not that full 2005-2026 PIT parity is proven.
repo_plumbing = {
    'VIX': True,
    'MOVE': True,
    'HY_OAS': True,
    'CORE_CPI_YOY': True,
    '5Y_BREAKEVEN': False,
    '5Y_BREAKEVEN_DELTA_1M': False,
    'REAL_10Y': False,
    '10Y_MINUS_2Y': True,
    'NET_LIQUIDITY_DELTA_13W': False,
    'DXY': True,
    'WTI': True,
    'PMI_MANUFACTURING': False,
    'PMI_SERVICES': False,
    'LEI_YOY': False,
    'SAHM_RULE': False,
    'U3_UNEMPLOYMENT': True,
    'NFP_3M_AVG': True,
}

public_source_path = {
    '5Y_BREAKEVEN': 'PUBLIC_OFFICIAL_SOURCE_IDENTIFIED',
    '5Y_BREAKEVEN_DELTA_1M': 'DERIVABLE_AFTER_5Y_BE',
    'REAL_10Y': 'PUBLIC_OFFICIAL_SOURCE_IDENTIFIED',
    'NET_LIQUIDITY_DELTA_13W': 'PUBLIC_COMPONENTS_IDENTIFIED',
    'SAHM_RULE': 'PUBLIC_OFFICIAL_SOURCE_IDENTIFIED',
    'PMI_MANUFACTURING': 'LICENSE_OR_PIT_HISTORY_TO_VALIDATE',
    'PMI_SERVICES': 'LICENSE_OR_PIT_HISTORY_TO_VALIDATE',
    'LEI_YOY': 'LICENSE_OR_PIT_HISTORY_TO_VALIDATE',
}

rows=[]
for name,kind,required,role in requirements:
    rows.append({
        'input': name,
        'source_class': kind,
        'required_for_macro_only': required,
        'repo_plumbing_found': bool(repo_plumbing.get(name, False)),
        'source_path_status': public_source_path.get(name, 'EXISTING_REPO_PLUMBING_REQUIRES_PIT_QA'),
        'formal_pit_parity': 'UNVERIFIED',
        'unit_qa_hard_gate': True,
        'asof_carry_forward_for_slow_release': kind in {'macro_release_pit','fred_realtime_or_pit'},
        'role': role,
    })

missing=[r['input'] for r in rows if not r['repo_plumbing_found']]
license_risk=[r['input'] for r in rows if r['source_path_status']=='LICENSE_OR_PIT_HISTORY_TO_VALIDATE']
status={
    'candidate': 'V70.2 Macro-only Weekly + V82 + BondV75',
    'formal_window': '2005-01-01..2026-08-31',
    'modern_subsample': '2019-01-01..2026-08-31',
    'stress_periods': [2008,2020,2022],
    'state': 'BLOCKED_PRECHECK' if missing else 'READY_FOR_PIT_VALIDATION',
    'reason': 'Macro-only removes ETF valuation PIT blockers. Remaining missing plumbing must be sourced and PIT-validated; no future backfill or silent proxy substitution.',
    'valuation_group_removed': True,
    'removed_inputs': ['QQQ_TTM_PE','SPY_TTM_PE','VT_TTM_PE'],
    'required_input_count': len(rows),
    'existing_plumbing_count': sum(r['repo_plumbing_found'] for r in rows),
    'missing_repo_plumbing': missing,
    'license_or_pit_history_risk': license_risk,
    'slow_data_rule': 'LAST_KNOWN_VALID_PIT_ASOF_CARRY_FORWARD',
    'unit_qa': 'HARD_GATE',
    'exact_group_weights': ['18/90','16/90','14/90','12/90','16/90','14/90'],
    'v82_changed': False,
    'bond_v75_changed': False,
}

(OUT/'preflight_status.json').write_text(json.dumps(status,ensure_ascii=False,indent=2),encoding='utf-8')
(OUT/'required_inputs.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(status,ensure_ascii=False,indent=2))
