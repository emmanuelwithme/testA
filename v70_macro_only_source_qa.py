from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from io import StringIO
from pathlib import Path
import json
import requests
import pandas as pd

OUT = Path('v70_macro_source_qa_output')
OUT.mkdir(exist_ok=True)

FRED = {
    '5Y_BREAKEVEN': ('T5YIE', 'percent_to_ratio'),
    'REAL_10Y': ('DFII10', 'percent_to_ratio'),
    'WALCL': ('WALCL', 'million_usd_to_bn'),
    'RRP': ('RRPONTSYD', 'already_usd_bn'),
    'TGA': ('WTREGEN', 'million_usd_to_bn'),
    'SAHM_RULE': ('SAHMREALTIME', 'percentage_points_keep_numeric'),
}


def fred_csv(series_id: str) -> pd.Series:
    url = f'https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}'
    r = requests.get(url, timeout=20, headers={'User-Agent': 'LivingWaterAI research backtest'})
    r.raise_for_status()
    df = pd.read_csv(StringIO(r.text))
    if len(df.columns) < 2:
        raise RuntimeError(f'{series_id}: malformed FRED CSV')
    dc, vc = df.columns[:2]
    dt = pd.to_datetime(df[dc], errors='coerce')
    val = pd.to_numeric(df[vc], errors='coerce')
    s = pd.Series(val.values, index=dt, name=series_id).dropna()
    s = s[~s.index.isna()].sort_index()
    if s.index.duplicated().any():
        raise RuntimeError(f'{series_id}: duplicate dates')
    if len(s) == 0:
        raise RuntimeError(f'{series_id}: empty series')
    return s


def main():
    rows = []
    cached = {}
    with ThreadPoolExecutor(max_workers=len(FRED)) as ex:
        futs = {ex.submit(fred_csv, sid):(logical,sid,conversion) for logical,(sid,conversion) in FRED.items()}
        for fut in as_completed(futs):
            logical,sid,conversion = futs[fut]
            try:
                s = fut.result()
                cached[logical] = s
                rows.append({
                    'logical_input': logical,
                    'series_id': sid,
                    'status': 'RAW_SOURCE_OK',
                    'first_observation': str(s.index.min().date()),
                    'last_observation': str(s.index.max().date()),
                    'n': int(len(s)),
                    'conversion': conversion,
                    'formal_pit_ready': False,
                    'pit_note': 'Raw historical source exists; formal use still requires availability-date/release-lag mapping or vintage validation where applicable.',
                })
            except requests.exceptions.ReadTimeout as e:
                rows.append({
                    'logical_input': logical, 'series_id': sid,
                    'status': 'RUNNER_NETWORK_TIMEOUT', 'error': repr(e),
                    'source_unavailable': False, 'formal_pit_ready': False,
                    'note': 'Transport failure is not evidence that the official series is unavailable.'
                })
            except requests.exceptions.RequestException as e:
                rows.append({
                    'logical_input': logical, 'series_id': sid,
                    'status': 'RUNNER_NETWORK_ERROR', 'error': repr(e),
                    'source_unavailable': False, 'formal_pit_ready': False,
                    'note': 'Transport failure is not evidence that the official series is unavailable.'
                })
            except Exception as e:
                rows.append({
                    'logical_input': logical, 'series_id': sid,
                    'status': 'SOURCE_PARSE_OR_QA_FAIL', 'error': repr(e),
                    'formal_pit_ready': False
                })
    rows.sort(key=lambda z: z['logical_input'])

    nl = {'status': 'NOT_EVALUATED'}
    if all(k in cached for k in ('WALCL','RRP','TGA')):
        starts = {k: str(cached[k].index.min().date()) for k in ('WALCL','RRP','TGA')}
        ends = {k: str(cached[k].index.max().date()) for k in ('WALCL','RRP','TGA')}
        overlap_start = max(cached[k].index.min() for k in ('WALCL','RRP','TGA'))
        overlap_end = min(cached[k].index.max() for k in ('WALCL','RRP','TGA'))
        nl = {
            'status': 'RAW_COMPONENTS_OK',
            'component_starts': starts,
            'component_ends': ends,
            'overlap_start': str(overlap_start.date()),
            'overlap_end': str(overlap_end.date()),
            'covers_formal_start_2005': bool(overlap_start <= pd.Timestamp('2005-01-10')),
            'warning': 'No zero-imputation for unavailable RRP/TGA. Formal weekly series requires as-of release mapping before computing NetLiquidity and delta13W.',
        }

    report = {
        'candidate': 'V70.2 Macro-only Weekly Candidate',
        'source_rows': rows,
        'net_liquidity_raw_feasibility': nl,
        'official_series_ids': ['T5YIE','DFII10','WALCL','RRPONTSYD','WTREGEN','SAHMREALTIME'],
        'still_requires_separate_licensed_or_archival_validation': ['PMI_MANUFACTURING','PMI_SERVICES','LEI_YOY'],
        'formal_backtest_ready': False,
    }
    (OUT/'source_qa.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2))

if __name__ == '__main__':
    main()
