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
FORMAL_START = '2005-01-01'
FORMAL_END = '2026-08-31'

FRED = {
    '5Y_BREAKEVEN': ('T5YIE', 'percent_to_ratio'),
    'REAL_10Y': ('DFII10', 'percent_to_ratio'),
    'WALCL': ('WALCL', 'million_usd_to_bn'),
    'RRP': ('RRPONTSYD', 'already_usd_bn'),
    'TGA': ('WTREGEN', 'million_usd_to_bn'),
    'SAHM_RULE': ('SAHMREALTIME', 'percentage_points_keep_numeric'),
}

HEADERS = {
    'User-Agent': 'Mozilla/5.0 LivingWaterAI research backtest/1.0',
    'Accept': 'application/json,text/csv,text/plain,*/*',
    'Connection': 'close',
}


def fred_csv(series_id: str, attempts: int = 3) -> pd.Series:
    # Bound the request to the formal backtest window. This avoids asking the
    # FRED graph endpoint to build unnecessary pre-2005 history on every CI run.
    urls = [
        f'https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}&cosd={FORMAL_START}&coed={FORMAL_END}',
        f'https://fred.stlouisfed.org/graph/fredgraph.csv?cosd={FORMAL_START}&coed={FORMAL_END}&id={series_id}',
    ]
    last_exc = None
    for url in urls:
        for attempt in range(1, attempts + 1):
            try:
                r = requests.get(url, timeout=(8, 20), headers=HEADERS)
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
                    time.sleep(attempt)
                    continue
                break
    raise last_exc if last_exc else RuntimeError(f'{series_id}: unknown fetch failure')


def treasury_tga(attempts: int = 3) -> pd.Series:
    """Official U.S. Treasury Fiscal Data fallback for TGA/operating cash.

    Uses Daily Treasury Statement Table I.  This is a raw-source availability
    check only; formal PIT use still requires the publication/availability-date
    mapping required by the mother backtest rules.
    """
    base = 'https://api.fiscaldata.treasury.gov/services/api/fiscal_service/v1/accounting/dts/dts_table_1'
    params = {
        'fields': 'record_date,account_type,close_today_bal',
        'filter': f'record_date:gte:{FORMAL_START},record_date:lte:{FORMAL_END}',
        'sort': 'record_date',
        'page[size]': '10000',
        'format': 'json',
    }
    last_exc = None
    for attempt in range(1, attempts + 1):
        try:
            r = requests.get(base, params=params, timeout=(8, 30), headers=HEADERS)
            r.raise_for_status()
            payload = r.json()
            rows = payload.get('data', [])
            if not rows:
                raise RuntimeError('Treasury DTS: empty data')
            df = pd.DataFrame(rows)
            required = {'record_date', 'account_type', 'close_today_bal'}
            if not required.issubset(df.columns):
                raise RuntimeError(f'Treasury DTS: missing fields {required - set(df.columns)}')
            acct = df['account_type'].astype(str).str.lower()
            # Treasury changed labels over time; prefer exact TGA rows, otherwise
            # accept the official operating-cash/TGA row containing Treasury General Account.
            mask = acct.str.contains('treasury general account', na=False)
            if not mask.any():
                raise RuntimeError('Treasury DTS: Treasury General Account rows not found')
            x = df.loc[mask].copy()
            dt = pd.to_datetime(x['record_date'], errors='coerce')
            val = pd.to_numeric(x['close_today_bal'], errors='coerce')
            s = pd.Series(val.values, index=dt, name='TGA_DTS').dropna()
            s = s[~s.index.isna()].sort_index()
            s = s[~s.index.duplicated(keep='last')]
            if len(s) == 0:
                raise RuntimeError('Treasury DTS: no usable TGA observations')
            return s
        except requests.exceptions.RequestException as exc:
            last_exc = exc
            if attempt < attempts:
                time.sleep(attempt)
                continue
            break
    raise last_exc if last_exc else RuntimeError('Treasury DTS: unknown fetch failure')


def main() -> int:
    rows = []
    cached = {}

    for logical, (sid, conversion) in FRED.items():
        try:
            s = fred_csv(sid)
            cached[logical] = s
            rows.append({
                'logical_input': logical,
                'series_id': sid,
                'source': 'FRED official series endpoint',
                'status': 'RAW_SOURCE_OK',
                'first_observation': str(s.index.min().date()),
                'last_observation': str(s.index.max().date()),
                'n': int(len(s)),
                'conversion': conversion,
                'formal_pit_ready': False,
                'pit_note': 'Raw historical source exists; formal use still requires availability-date/release-lag mapping or vintage validation where applicable.',
            })
        except requests.exceptions.ReadTimeout as e:
            # For TGA only, try the independent official U.S. Treasury Fiscal Data API.
            if logical == 'TGA':
                try:
                    s = treasury_tga()
                    cached[logical] = s
                    rows.append({
                        'logical_input': logical,
                        'series_id': 'DTS_TABLE_1_TGA',
                        'source': 'U.S. Treasury Fiscal Data Daily Treasury Statement Table I',
                        'fallback_from': sid,
                        'status': 'RAW_SOURCE_OK_OFFICIAL_FALLBACK',
                        'first_observation': str(s.index.min().date()),
                        'last_observation': str(s.index.max().date()),
                        'n': int(len(s)),
                        'conversion': 'million_usd_to_bn',
                        'formal_pit_ready': False,
                        'pit_note': 'Official Treasury raw source retrieved; formal use still requires publication/availability-date mapping and unit QA.',
                    })
                    continue
                except Exception as fb:
                    rows.append({
                        'logical_input': logical, 'series_id': sid,
                        'status': 'RUNNER_NETWORK_TIMEOUT_AND_OFFICIAL_FALLBACK_FAIL',
                        'error': repr(e), 'fallback_error': repr(fb),
                        'source_unavailable': False, 'formal_pit_ready': False,
                        'note': 'Both FRED transport and Treasury official fallback failed; this does not establish source unavailability.'
                    })
                    continue
            rows.append({
                'logical_input': logical, 'series_id': sid,
                'status': 'RUNNER_NETWORK_TIMEOUT', 'error': repr(e),
                'source_unavailable': False, 'formal_pit_ready': False,
                'note': 'Transport failure after bounded-window retries is not evidence that the official series is unavailable.'
            })
        except requests.exceptions.RequestException as e:
            rows.append({
                'logical_input': logical, 'series_id': sid,
                'status': 'RUNNER_NETWORK_ERROR', 'error': repr(e),
                'source_unavailable': False, 'formal_pit_ready': False,
                'note': 'Transport failure after bounded-window retries is not evidence that the official series is unavailable.'
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

    ok_statuses = {'RAW_SOURCE_OK', 'RAW_SOURCE_OK_OFFICIAL_FALLBACK'}
    raw_ok_count = sum(r.get('status') in ok_statuses for r in rows)
    transport_fail_count = sum(r.get('status') in {
        'RUNNER_NETWORK_TIMEOUT', 'RUNNER_NETWORK_ERROR',
        'RUNNER_NETWORK_TIMEOUT_AND_OFFICIAL_FALLBACK_FAIL'
    } for r in rows)
    report = {
        'candidate': 'V70.2 Macro-only Weekly Candidate',
        'formal_window': f'{FORMAL_START}..{FORMAL_END}',
        'source_rows': rows,
        'raw_source_ok_count': raw_ok_count,
        'transport_fail_count': transport_fail_count,
        'net_liquidity_raw_feasibility': nl,
        'official_series_ids': ['T5YIE','DFII10','WALCL','RRPONTSYD','WTREGEN','SAHMREALTIME'],
        'official_fallbacks': {'TGA': 'U.S. Treasury Fiscal Data DTS Table I'},
        'still_requires_separate_licensed_or_archival_validation': ['PMI_MANUFACTURING','PMI_SERVICES','LEI_YOY'],
        'formal_backtest_ready': False,
        'qa_pass': raw_ok_count > 0,
        'qa_note': 'Raw-source transport QA only. A green source QA is not formal PIT readiness; availability-date/release-lag and vintage rules remain mandatory.'
    }
    (OUT/'source_qa.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2))

    if raw_ok_count == 0:
        print('SOURCE_QA_FAIL: zero official sources were retrieved; inspect transport and retry/fallback endpoints.', file=sys.stderr)
        return 2
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
