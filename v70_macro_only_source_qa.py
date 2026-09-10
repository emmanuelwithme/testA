from __future__ import annotations

from io import StringIO
from pathlib import Path
import json
import sys
import time
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


def fred_csv(series_id: str, attempts: int = 4) -> pd.Series:
    url = f'https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}'
    last_exc = None
    headers = {'User-Agent': 'LivingWaterAI research backtest/1.0'}
    for attempt in range(1, attempts + 1):
        try:
            r = requests.get(url, timeout=(10, 60), headers=headers)
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
        except requests.exceptions.RequestException as exc:
            last_exc = exc
            if attempt < attempts:
                time.sleep(2 ** (attempt - 1))
                continue
            raise
    raise last_exc if last_exc else RuntimeError(f'{series_id}: unknown fetch failure')


def main() -> int:
    rows = []
    cached = {}

    # Fetch sequentially on purpose. Parallel FRED graph requests were causing all
    # six official series to time out together on the GitHub runner; that is a
    # transport artifact, not evidence that the series are unavailable.
    for logical, (sid, conversion) in FRED.items():
        try:
            s = fred_csv(sid)
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
                'note': 'Transport failure after retries is not evidence that the official series is unavailable.'
            })
        except requests.exceptions.RequestException as e:
            rows.append({
                'logical_input': logical, 'series_id': sid,
                'status': 'RUNNER_NETWORK_ERROR', 'error': repr(e),
                'source_unavailable': False, 'formal_pit_ready': False,
                'note': 'Transport failure after retries is not evidence that the official series is unavailable.'
            })
        except Exception as e:
            rows.append({
                'logical_input': logical, 'series_id': sid,
                'status': 'SOURCE_PARSE_OR_QA_FAIL', 'error': repr(e),
                'formal_pit_ready': False
            })
        time.sleep(1)

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

    raw_ok_count = sum(r.get('status') == 'RAW_SOURCE_OK' for r in rows)
    transport_fail_count = sum(r.get('status') in {'RUNNER_NETWORK_TIMEOUT', 'RUNNER_NETWORK_ERROR'} for r in rows)
    report = {
        'candidate': 'V70.2 Macro-only Weekly Candidate',
        'source_rows': rows,
        'raw_source_ok_count': raw_ok_count,
        'transport_fail_count': transport_fail_count,
        'net_liquidity_raw_feasibility': nl,
        'official_series_ids': ['T5YIE','DFII10','WALCL','RRPONTSYD','WTREGEN','SAHMREALTIME'],
        'still_requires_separate_licensed_or_archival_validation': ['PMI_MANUFACTURING','PMI_SERVICES','LEI_YOY'],
        'formal_backtest_ready': False,
        'qa_pass': raw_ok_count > 0,
        'qa_note': 'Workflow must not report success when every official-source fetch failed. Zero usable sources is a CI failure, even when the cause is transient transport failure.'
    }
    (OUT/'source_qa.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2))

    if raw_ok_count == 0:
        print('SOURCE_QA_FAIL: zero official sources were retrieved; inspect transport and retry/fallback endpoints.', file=sys.stderr)
        return 2
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
