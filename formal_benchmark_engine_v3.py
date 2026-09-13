from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

import backtest_33_models_v2 as base

# Mentor.md is the candidate-universe source of truth.
# V82.md / 債券V75.md remain the execution-rule sources; this file only builds
# the mechanical B&H/DCA benchmark layers while Case 1 remains blocked until
# the complete PIT/T+1 dynamic rule-engine pipeline is available.
STOCKS = {
    'VT': 'VT',
    'VOO': 'VOO',
    'QQQ': 'QQQ',
    '0050': '0050.TW',
    'SOXX': 'SOXX',
    'PPH': 'PPH',
    'NATO': 'NATO.L',
}
BONDS = {
    'SHY': 'SHY',
    'IEF': 'IEF',
    'SPIB': 'SPIB',
}
RISK = {**STOCKS, **BONDS}
PARKING_ASSET = 'SGOV'
OUT = Path('formal_benchmark_v3_output')
OUT.mkdir(exist_ok=True)

# Keep the imported mechanical benchmark helpers on the same formal universe.
base.STOCKS = STOCKS
base.BONDS = BONDS
base.RISK = RISK
base.OUT = OUT


def capital_conservation_check(model: str, res: dict | None) -> dict:
    """Verify daily NAV identity for mechanical benchmark portfolios.

    The benchmark simulator has no leverage or borrowing. Daily NAV must equal
    risk-asset market value plus the SGOV/formal-short-bond parking balance.
    """
    if not res:
        return {
            'model': model,
            'status': 'N/A',
            'max_abs_nav_identity_error_twd': np.nan,
            'capital_conservation_pass': False,
        }
    nav = res['nav']
    errors = []
    for i, (_, _, parking_weight, vals) in enumerate(res['exps']):
        n = float(nav.iloc[i])
        risk_value = float(sum(vals.values()))
        parking_value = float(parking_weight * n)
        errors.append(abs(n - risk_value - parking_value))
    max_error = float(max(errors)) if errors else 0.0
    tolerance = max(0.01, float(nav.max()) * 1e-10)
    return {
        'model': model,
        'status': 'OK',
        'max_abs_nav_identity_error_twd': max_error,
        'tolerance_twd': tolerance,
        'capital_conservation_pass': bool(max_error <= tolerance),
    }


def main():
    p, fx = base.prices_twd()
    park = base.parking_index(fx)
    rows = []
    results = {}

    # V70.2 owns the upper stock/bond/parking bucket caps. V82 owns stock
    # execution and Bond V75 owns bond execution. The two risk buckets cannot
    # borrow each other's unused allowance; unused capital remains parked.
    # Latest V82 now directly owns a fixed cumulative deployment ladder
    # (10/20/30/45/60/75/85/95/100% of project target position), so missing
    # deployment calibration is no longer a blocker. Case 1 remains blocked
    # only until the full dynamic engines and complete PIT/T+1 inputs exist.
    rows.append({
        'model': 'Case1_V82_plus_BondV75_dynamic_common_pool',
        'status': 'BLOCKED_MISSING_COMPLETE_PIT_T1_DYNAMIC_EXECUTION_PIPELINE',
        'reason': 'V70.2 bucket governance and the formal V82 deployment ladder are resolved. The remaining blocker is implementation of the complete V82/BondV75 dynamic execution pipeline with complete PIT/T+1 inputs. No artificial rule or proxy is inserted.',
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
        rows.append(row)
        results[name] = res

    # 7 equity + 3 US risk-bond candidates => 10 risk assets.
    # Dynamic Case 1 + benchmark cases = 32 model rows.
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
        pd.DataFrame([base.cross_year(m, g) for m, g in adf.groupby('model')]).to_csv(
            OUT / 'cross_year_risk_summary.csv', index=False
        )
        adf[adf.year.isin([2008, 2020, 2022])].to_csv(
            OUT / 'stress_2008_2020_2022.csv', index=False
        )

    audit = [
        {
            'asset': a,
            'first_valid': str(s.index.min().date()) if len(s) else None,
            'last_valid': str(s.index.max().date()) if len(s) else None,
            'n_obs': len(s),
        }
        for a, s in p.items()
    ]
    pd.DataFrame(audit).to_csv(OUT / 'data_audit.csv', index=False)

    if not adf.empty:
        annual_contribution_qa = (
            adf.groupby(['model', 'year']).external_contribution_twd.sum().reset_index()
        )
        bad_contrib = annual_contribution_qa[
            annual_contribution_qa.external_contribution_twd > base.ANNUAL + 0.01
        ]
    else:
        annual_contribution_qa = pd.DataFrame()
        bad_contrib = pd.DataFrame()
    annual_contribution_qa.to_csv(OUT / 'annual_contribution_qa.csv', index=False)

    capital_rows = [capital_conservation_check(name, res) for name, res in results.items()]
    capital_df = pd.DataFrame(capital_rows)
    capital_df.to_csv(OUT / 'capital_conservation_qa.csv', index=False)
    bad_capital = capital_df[
        (capital_df.status == 'OK') & (~capital_df.capital_conservation_pass)
    ]

    status = {
        'engine': 'formal_benchmark_engine_v3',
        'formal_window': '2005-01-01..2026-08-31',
        'mentor_equity_candidates': list(STOCKS),
        'mentor_us_risk_bond_candidates': list(BONDS),
        'parking_asset': PARKING_ASSET,
        'v82_formal_deployment_ladder_pct': [10, 20, 30, 45, 60, 75, 85, 95, 100],
        'expected_models': expected_models,
        'actual_models': len(df),
        'ok_models': int((df.status == 'OK').sum()),
        'blocked_models': int(df.status.astype(str).str.startswith('BLOCKED').sum()),
        'qa_contribution_over_1m_rows': len(bad_contrib),
        'capital_conservation_failures': len(bad_capital),
        'case1_blocker': rows[0],
    }
    (OUT / 'run_status.json').write_text(
        json.dumps(status, ensure_ascii=False, indent=2), encoding='utf-8'
    )

    if len(bad_contrib):
        raise RuntimeError('Contribution QA failed: > NT$1m in an effective year')
    if len(bad_capital):
        raise RuntimeError('Capital conservation QA failed')

    preferred_cols = ['model', 'status', 'ending_asset_twd', 'xirr_mwr', 'twr_cagr', 'unitized_mdd']
    printable_cols = [c for c in preferred_cols if c in df.columns]
    print(df[printable_cols].to_string(index=False))
    print(json.dumps(status, ensure_ascii=False))


if __name__ == '__main__':
    main()
