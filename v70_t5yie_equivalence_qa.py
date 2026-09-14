from __future__ import annotations

import io
import json
import time
from pathlib import Path

import pandas as pd
import requests

from v70_treasury_rates_probe import fetch_treasury_rate_components

OUT = Path('v70_t5yie_equivalence_qa_output')
OUT.mkdir(exist_ok=True)
REPORT = OUT / 't5yie_equivalence_qa.json'
FRED_URL = 'https://fred.stlouisfed.org/graph/fredgraph.csv?id=T5YIE&cosd=2005-01-01&coed=2026-08-31'


def fetch_fred_t5yie(attempts: int = 3) -> pd.DataFrame:
    last = None
    for i in range(attempts):
        try:
            r = requests.get(FRED_URL, timeout=(10, 45), headers={'User-Agent': 'LivingWaterAI formal backtest QA/1.0'})
            r.raise_for_status()
            df = pd.read_csv(io.StringIO(r.text))
            date_col = 'DATE' if 'DATE' in df.columns else 'observation_date'
            if date_col not in df.columns or 'T5YIE' not in df.columns:
                raise RuntimeError(f'unexpected FRED columns: {list(df.columns)}')
            df['date'] = pd.to_datetime(df[date_col], errors='coerce')
            df['fred_t5yie'] = pd.to_numeric(df['T5YIE'], errors='coerce')
            df = df[['date', 'fred_t5yie']].dropna().sort_values('date').drop_duplicates('date')
            if df.empty:
                raise RuntimeError('FRED T5YIE returned zero usable observations')
            return df
        except Exception as exc:
            last = exc
            if i + 1 < attempts:
                time.sleep(i + 1)
    raise RuntimeError(f'FRED_T5YIE_FETCH_FAILED: {last!r}')


def main() -> int:
    treasury = fetch_treasury_rate_components()[['date', 'nominal_5y', 'real_5y', 't5yie_candidate']].dropna()
    fred = fetch_fred_t5yie()
    merged = treasury.merge(fred, on='date', how='inner')
    if merged.empty:
        raise SystemExit('T5YIE_EQUIVALENCE_NO_OVERLAP')

    merged['diff'] = merged['t5yie_candidate'] - merged['fred_t5yie']
    merged['abs_diff'] = merged['diff'].abs()
    rounded_candidate = merged['t5yie_candidate'].round(2)
    exact_2dp = (rounded_candidate - merged['fred_t5yie']).abs() <= 1e-12
    within_1bp = merged['abs_diff'] <= 0.01 + 1e-12
    within_2bp = merged['abs_diff'] <= 0.02 + 1e-12

    report = {
        'candidate': 'Treasury BC_5YEAR - TC_5YEAR',
        'reference': 'FRED T5YIE official series',
        'reference_url': 'https://fred.stlouisfed.org/series/T5YIE',
        'fred_definition': '5Y Treasury Constant Maturity minus 5Y inflation-indexed Treasury Constant Maturity',
        'treasury_source': 'U.S. Treasury Daily PAR Yield Curve and Daily PAR Real Yield Curve XML feeds',
        'overlap_n': int(len(merged)),
        'first_overlap': str(merged['date'].min().date()),
        'last_overlap': str(merged['date'].max().date()),
        'max_abs_diff_pct_points': float(merged['abs_diff'].max()),
        'mean_abs_diff_pct_points': float(merged['abs_diff'].mean()),
        'p99_abs_diff_pct_points': float(merged['abs_diff'].quantile(0.99)),
        'exact_after_candidate_round_2dp_ratio': float(exact_2dp.mean()),
        'within_1bp_ratio': float(within_1bp.mean()),
        'within_2bp_ratio': float(within_2bp.mean()),
        'formal_equivalence_ready': bool(exact_2dp.mean() >= 0.999 and within_1bp.mean() >= 0.999),
        'policy': 'Diagnostic equivalence only. This script does not itself promote PIT readiness; publication availability and T+1 remain separate gates.',
    }
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    merged.to_csv(OUT / 't5yie_equivalence_rows.csv', index=False)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
