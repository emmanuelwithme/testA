import json
from pathlib import Path

OUT = Path('v70_weekly_preflight_output')
OUT.mkdir(exist_ok=True)

# Exact source-defined inputs that require historical Point-in-Time reconstruction
# before the V70.2 weekly top-level allocator can produce a FORMAL backtest.
requirements = [
    ('VIX', 'market_daily', True, 'V70.2 panic/volatility'),
    ('MOVE', 'market_daily', True, 'V70.2 panic/volatility'),
    ('HY_OAS', 'fred_daily', True, 'V70.2 credit'),
    ('CORE_CPI_YOY', 'macro_release_pit', True, 'V70.2 inflation'),
    ('5Y_BREAKEVEN', 'fred_daily', True, 'V70.2 inflation/crisis'),
    ('5Y_BREAKEVEN_DELTA_1M', 'derived_from_pit', True, 'V70.2 inflation/crisis'),
    ('REAL_10Y', 'fred_daily', True, 'V70.2 rates/crisis'),
    ('10Y_MINUS_2Y', 'fred_daily', True, 'V70.2 rates'),
    ('NET_LIQUIDITY_DELTA_13W', 'derived_fed_rrp_tga_pit', True, 'V70.2 liquidity/crisis'),
    ('DXY', 'market_daily', True, 'V70.2 liquidity/accelerator'),
    ('WTI', 'market_daily', True, 'V70.2 liquidity/accelerator'),
    ('PMI_MANUFACTURING', 'macro_release_pit', True, 'V70.2 growth'),
    ('PMI_SERVICES', 'macro_release_pit', True, 'V70.2 growth'),
    ('LEI_YOY', 'macro_release_pit', True, 'V70.2 growth/recession'),
    ('SAHM_RULE', 'fred_monthly_pit', True, 'V70.2 recession'),
    ('U3_UNEMPLOYMENT', 'macro_release_pit', True, 'V70.2 recession'),
    ('NFP_3M_AVG', 'macro_release_pit', True, 'V70.2 recession'),
    ('FED_CUT_EXPECTATION', 'historical_futures_expectation_pit', True, 'visible V70.2 input'),
    ('QQQ_TTM_PE', 'historical_valuation_pit', True, 'V70.2 valuation'),
    ('SPY_TTM_PE', 'historical_valuation_pit', True, 'V70.2 valuation'),
    ('VT_TTM_PE', 'historical_valuation_pit', True, 'V70.2 valuation'),
]

# Repository plumbing confirmed by code search before this file was committed.
# "available" here means there is already reusable historical plumbing in the repo,
# NOT that formal PIT parity is automatically proven.
repo_plumbing = {
    'VIX': True,
    'HY_OAS': True,
    'CORE_CPI_YOY': True,
    '10Y_MINUS_2Y': True,
    'U3_UNEMPLOYMENT': True,
    'NFP_3M_AVG': True,
    'REAL_10Y': False,
    'MOVE': True,
    '5Y_BREAKEVEN': False,
    '5Y_BREAKEVEN_DELTA_1M': False,
    'NET_LIQUIDITY_DELTA_13W': False,
    'DXY': False,
    'WTI': False,
    'PMI_MANUFACTURING': False,
    'PMI_SERVICES': False,
    'LEI_YOY': False,
    'SAHM_RULE': False,
    'FED_CUT_EXPECTATION': False,
    'QQQ_TTM_PE': False,
    'SPY_TTM_PE': False,
    'VT_TTM_PE': False,
}

rows=[]
for name,kind,required,role in requirements:
    rows.append({
        'input': name,
        'source_class': kind,
        'required_for_exact_v70_2': required,
        'repo_plumbing_found': bool(repo_plumbing.get(name, False)),
        'formal_pit_parity': 'UNVERIFIED',
        'role': role,
    })

missing=[r['input'] for r in rows if not r['repo_plumbing_found']]
status={
    'candidate': 'V82 + BondV75 + V70.2 Weekly Macro Allocator',
    'formal_window': '2005-01-01..2026-08-31',
    'modern_subsample': '2019-01-01..2026-08-31',
    'stress_periods': [2008,2020,2022],
    'state': 'BLOCKED_PRECHECK' if missing else 'READY_FOR_PIT_VALIDATION',
    'reason': 'Exact V70.2 historical PIT inputs must be sourced/validated before formal performance output. No substitution or manual backfill is allowed.',
    'missing_repo_plumbing': missing,
    'required_input_count': len(rows),
    'existing_plumbing_count': sum(r['repo_plumbing_found'] for r in rows),
    'weekly_anchor': 'SENSITIVITY_REQUIRED_NOT_SILENTLY_FIXED',
    'v82_changed': False,
    'bond_v75_changed': False,
}

(OUT/'preflight_status.json').write_text(json.dumps(status,ensure_ascii=False,indent=2),encoding='utf-8')
(OUT/'required_inputs.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(status,ensure_ascii=False,indent=2))
