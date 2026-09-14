from __future__ import annotations

import io
import json
import re
import time
from pathlib import Path

import pandas as pd
import requests

from v70_treasury_rates_probe import fetch_treasury_rate_components

OUT = Path('v70_t5yie_equivalence_qa_output')
OUT.mkdir(exist_ok=True)
REPORT = OUT / 't5yie_equivalence_qa.json'
HEADERS = {
    'User-Agent': 'Mozilla/5.0 LivingWaterAI formal backtest QA/1.0',
    'Accept': 'text/csv,text/plain,text/html,*/*',
    'Connection': 'close',
}
FRED_CANDIDATES = [
    ('FRED_SERIES_DOWNLOAD_CSV', 'https://fred.stlouisfed.org/series/T5YIE/downloaddata/T5YIE.csv', 'csv'),
    ('FRED_STATIC_TXT', 'https://fred.stlouisfed.org/data/T5YIE.txt', 'text'),
    ('FRED_DATA_TABLE', 'https://fred.stlouisfed.org/data/T5YIE', 'text'),
    ('FRED_GRAPH_CSV', 'https://fred.stlouisfed.org/graph/fredgraph.csv?id=T5YIE&cosd=2005-01-01&coed=2026-08-31', 'csv'),
]


def _clip(df: pd.DataFrame, date_col: str, value_col: str) -> pd.DataFrame:
    out = pd.DataFrame({
        'date': pd.to_datetime(df[date_col], errors='coerce'),
        'fred_t5yie': pd.to_numeric(df[value_col], errors='coerce'),
    }).dropna()
    out = out[(out['date'] >= pd.Timestamp('2005-01-01')) & (out['date'] <= pd.Timestamp('2026-08-31'))]
    out = out.sort_values('date').drop_duplicates('date', keep='last')
    if out.empty:
        raise RuntimeError('FRED T5YIE returned zero usable observations')
    return out


def _parse_csv(text: str) -> pd.DataFrame:
    df = pd.read_csv(io.StringIO(text))
    date_col = 'DATE' if 'DATE' in df.columns else ('observation_date' if 'observation_date' in df.columns else df.columns[0])
    value_col = 'T5YIE' if 'T5YIE' in df.columns else (df.columns[1] if len(df.columns) > 1 else None)
    if value_col is None:
        raise RuntimeError(f'unexpected FRED CSV columns: {list(df.columns)}')
    return _clip(df, date_col, value_col)


def _parse_text(text: str) -> pd.DataFrame:
    pairs = []
    for line in text.splitlines():
        m = re.match(r'^\s*(\d{4}-\d{2}-\d{2})\s*[|,\t ]+\s*([+-]?(?:\d+(?:\.\d*)?|\.\d+))\s*$', line)
        if m:
            pairs.append((m.group(1), m.group(2)))
    if not pairs:
        raise RuntimeError('no DATE/VALUE pairs parsed from FRED text endpoint')
    return _clip(pd.DataFrame(pairs, columns=['DATE', 'T5YIE']), 'DATE', 'T5YIE')


def fetch_fred_t5yie(attempts: int = 2) -> tuple[pd.DataFrame, str, list[dict]]:
    errors: list[dict] = []
    for label, url, kind in FRED_CANDIDATES:
        for attempt in range(1, attempts + 1):
            try:
                r = requests.get(url, timeout=(8, 30), headers=HEADERS, allow_redirects=True)
                r.raise_for_status()
                df = _parse_csv(r.text) if kind == 'csv' else _parse_text(r.text)
                return df, label, errors
            except Exception as exc:
                errors.append({'transport': label, 'attempt': attempt, 'error': repr(exc)})
                if attempt < attempts:
                    time.sleep(attempt)
    raise RuntimeError(f'FRED_T5YIE_ALL_OFFICIAL_TRANSPORTS_FAILED: {errors!r}')


def main() -> int:
    report: dict = {
        'candidate': 'Treasury BC_5YEAR - TC_5YEAR',
        'reference': 'FRED T5YIE official series',
        'reference_url': 'https://fred.stlouisfed.org/series/T5YIE',
        'formal_equivalence_ready': False,
    }
    try:
        treasury = fetch_treasury_rate_components()[['date', 'nominal_5y', 'real_5y', 't5yie_candidate']].dropna()
        fred, transport, prior_errors = fetch_fred_t5yie()
        merged = treasury.merge(fred, on='date', how='inner')
        if merged.empty:
            raise RuntimeError('T5YIE_EQUIVALENCE_NO_OVERLAP')

        merged['diff'] = merged['t5yie_candidate'] - merged['fred_t5yie']
        merged['abs_diff'] = merged['diff'].abs()
        rounded_candidate = merged['t5yie_candidate'].round(2)
        exact_2dp = (rounded_candidate - merged['fred_t5yie']).abs() <= 1e-12
        within_1bp = merged['abs_diff'] <= 0.01 + 1e-12
        within_2bp = merged['abs_diff'] <= 0.02 + 1e-12

        report.update({
            'status': 'QA_COMPLETE',
            'fred_transport': transport,
            'fred_transport_errors_before_success': prior_errors,
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
            'policy': 'Diagnostic equivalence only. Publication availability and T+1 remain separate gates.',
        })
        merged.to_csv(OUT / 't5yie_equivalence_rows.csv', index=False)
        REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0
    except Exception as exc:
        report.update({
            'status': 'QA_TRANSPORT_OR_PROCESS_FAILURE',
            'error': repr(exc),
            'formal_equivalence_ready': False,
            'policy': 'Failure does not imply semantic non-equivalence. No third-party proxy is substituted.',
        })
        REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
