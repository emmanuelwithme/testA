from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

import backtest_33_models_v2 as base

# Current formal architecture (Mentor.md v3.6.0):
# Mentor owns long-run S0/B0, candidate universes and client constraints.
# V70_2.html receives S0/B0 and outputs only total tactical equity/bond/dry-powder budgets.
# V82 owns equity security-level execution; 債券V75 owns bond security-level execution.
# This file is the mechanical benchmark layer only and must not invent dynamic
# V70/V82/BondV75 rules while the complete PIT/T+1 execution pipeline is unfinished.
STOCKS = {
    'VT': 'VT', 'VOO': 'VOO', 'QQQ': 'QQQ', '0050': '0050.TW',
    'SOXX': 'SOXX', 'PPH': 'PPH', 'NATO': 'NATO.L',
}
# Primary US-listed bond candidate examples currently supported by this benchmark's
# price pipeline. SGOV_BOND_BUCKET is a logical accounting role using ticker SGOV.
# No current-run bond weights are hardcoded here: BondV75 owns selection/sizing.
BONDS = {
    'SGOV_BOND_BUCKET': 'SGOV',
    'SPSB': 'SPSB',
    'BNDW': 'BNDW',
}
MENTOR_BOND_PRIMARY_EXAMPLES = ['SGOV', 'SPSB', 'BNDW', '00859B', '00860B']
MENTOR_BOND_EXTENDED_EXAMPLES = ['SHY', 'IEF', 'SPIB', 'TLT', 'SPLB', '00719B']
TAIWAN_BOND_CANDIDATES_REQUIRING_SEPARATE_FORMAL_DATA_PIPELINE = ['00859B', '00860B']
RISK = {**STOCKS, **BONDS}
PARKING_ASSET = 'SGOV_DRY_POWDER_BUCKET'
PARKING_TICKER = 'SGOV'
OUT = Path('formal_benchmark_v3_output')
OUT.mkdir(exist_ok=True)

base.STOCKS = STOCKS
base.BONDS = BONDS
base.RISK = RISK
base.OUT = OUT


def capital_conservation_check(model: str, res: dict | None) -> dict:
    if not res:
        return {'model': model, 'status': 'N/A', 'max_abs_nav_identity_error_twd': np.nan, 'capital_conservation_pass': False}
    nav = res['nav']
    errors = []
    for i, (_, _, parking_weight, vals) in enumerate(res['exps']):
        n = float(nav.iloc[i])
        risk_value = float(sum(vals.values()))
        parking_value = float(parking_weight * n)
        errors.append(abs(n - risk_value - parking_value))
    max_error = float(max(errors)) if errors else 0.0
    tolerance = max(0.01, float(nav.max()) * 1e-10)
    return {'model': model, 'status': 'OK', 'max_abs_nav_identity_error_twd': max_error,
            'tolerance_twd': tolerance, 'capital_conservation_pass': bool(max_error <= tolerance)}


def main():
    p, fx = base.prices_twd()
    park = base.parking_index(fx)
    rows, results = [], {}

    rows.append({
        'model': 'Case1_MentorS0B0_V70Tactical_V82_plus_BondV75_dynamic_common_pool',
        'status': 'BLOCKED_MISSING_COMPLETE_PIT_T1_DYNAMIC_EXECUTION_PIPELINE',
        'reason': (
            'Latest Mentor v3.6 architecture is now locked: Mentor S0/B0 -> V70_2 total tactical '
            'equity/bond/V70_ORIGINAL_DRY_POWDER budgets -> V82 and BondV75 security-level execution. '
            'Formal Case 1 remains blocked until PIT/T+1 historical V70 inputs and complete dynamic '
            'V82/BondV75 execution exist. No old fixed bond weights or cross-bucket shortcut is inserted.'
        ),
    })

    specs = []
    for a in RISK:
        specs.append((f'Case2_AnnualSingle_{a}', [a], f'annual_single:{a}'))
    specs.append(('Case3_AnnualEqual_AllRisk', list(RISK), 'annual_equal'))
    for a in RISK:
        specs.append((f'Case4_MonthlySingle_{a}', [a], f'monthly_single:{a}'))
    specs.append(('Case5_MonthlyEqual_AllRisk', list(RISK), 'monthly_equal'))
    specs.append(('Case6_AnnualEqual_Equities7', list(STOCKS), 'annual_equal'))
    for a in STOCKS:
        specs.append((f'Case7_MonthlySingleStock_{a}', [a], f'monthly_single:{a}'))
    specs.append(('Case8_MonthlyEqual_Equities7', list(STOCKS), 'monthly_equal'))

    for name, assets, mode in specs:
        row, res = base.simulate(name, assets, mode, p, park)
        rows.append(row); results[name] = res

    expected_models = 1 + len(RISK) + 1 + len(RISK) + 1 + 1 + len(STOCKS) + 1
    df = pd.DataFrame(rows)
    if len(df) != expected_models:
        raise RuntimeError(f'Unexpected model count: {len(df)} != {expected_models}')
    df.to_csv(OUT / 'model_summary.csv', index=False)

    annual = []
    for name, res in results.items():
        if res:
            annual.extend(base.annual_rows(name, res))
    adf = pd.DataFrame(annual)
    adf.to_csv(OUT / 'annual_risk_by_model.csv', index=False)
    if not adf.empty:
        pd.DataFrame([base.cross_year(m, g) for m, g in adf.groupby('model')]).to_csv(OUT / 'cross_year_risk_summary.csv', index=False)
        adf[adf.year.isin([2008, 2020, 2022])].to_csv(OUT / 'stress_2008_2020_2022.csv', index=False)

    audit = [{'asset': a, 'ticker': RISK[a], 'first_valid': str(s.index.min().date()) if len(s) else None,
              'last_valid': str(s.index.max().date()) if len(s) else None, 'n_obs': len(s)} for a, s in p.items()]
    pd.DataFrame(audit).to_csv(OUT / 'data_audit.csv', index=False)

    if not adf.empty:
        annual_contribution_qa = adf.groupby(['model', 'year']).external_contribution_twd.sum().reset_index()
        bad_contrib = annual_contribution_qa[annual_contribution_qa.external_contribution_twd > base.ANNUAL + 0.01]
    else:
        annual_contribution_qa = pd.DataFrame(); bad_contrib = pd.DataFrame()
    annual_contribution_qa.to_csv(OUT / 'annual_contribution_qa.csv', index=False)

    capital_df = pd.DataFrame([capital_conservation_check(name, res) for name, res in results.items()])
    capital_df.to_csv(OUT / 'capital_conservation_qa.csv', index=False)
    bad_capital = capital_df[(capital_df.status == 'OK') & (~capital_df.capital_conservation_pass)]

    status = {
        'engine': 'formal_benchmark_engine_v3',
        'mentor_version': 'v3.6.0',
        'formal_architecture': 'Mentor S0/B0 -> V70_2 tactical total budgets -> V82/BondV75 security-level execution -> undeployed execution budgets to SGOV_DRY_POWDER_BUCKET',
        'formal_window': '2005-01-01..2026-08-31',
        'mentor_equity_candidate_examples': list(STOCKS),
        'mentor_bond_primary_examples': MENTOR_BOND_PRIMARY_EXAMPLES,
        'mentor_bond_extended_examples': MENTOR_BOND_EXTENDED_EXAMPLES,
        'benchmark_supported_us_bond_logical_assets': list(BONDS),
        'taiwan_bond_candidates_pending_formal_data_pipeline': TAIWAN_BOND_CANDIDATES_REQUIRING_SEPARATE_FORMAL_DATA_PIPELINE,
        'mentor_current_run_bond_weights_hardcoded': False,
        'parking_asset_logical_role': PARKING_ASSET,
        'parking_ticker': PARKING_TICKER,
        'sgov_dual_role_separated': True,
        'v82_formal_deployment_ladder_pct': [10, 20, 30, 45, 60, 75, 85, 95, 100],
        'expected_models': expected_models,
        'actual_models': len(df),
        'ok_models': int((df.status == 'OK').sum()),
        'blocked_models': int(df.status.astype(str).str.startswith('BLOCKED').sum()),
        'qa_contribution_over_1m_rows': len(bad_contrib),
        'capital_conservation_failures': len(bad_capital),
        'case1_blocker': rows[0],
        'note': (
            'Mechanical equal-weight comparators are benchmarks only. They are not Mentor or BondV75 target weights. '
            'Taiwan-listed bond candidates require their own formal total-return/PIT-safe data path before inclusion.'
        )
    }
    (OUT / 'run_status.json').write_text(json.dumps(status, ensure_ascii=False, indent=2), encoding='utf-8')

    if len(bad_contrib):
        raise RuntimeError('Contribution QA failed: > NT$1m in an effective year')
    if len(bad_capital):
        raise RuntimeError('Capital conservation QA failed')

    cols = [c for c in ['model','status','ending_asset_twd','xirr_mwr','twr_cagr','unitized_mdd'] if c in df.columns]
    print(df[cols].to_string(index=False))
    print(json.dumps(status, ensure_ascii=False))


if __name__ == '__main__':
    main()
