from __future__ import annotations

import time
import requests
import pandas as pd

FORMAL_START = '2005-01-01'
FORMAL_END = '2026-08-31'
HEADERS = {
    'User-Agent': 'Mozilla/5.0 LivingWaterAI research backtest/1.0',
    'Accept': 'application/json,*/*',
    'Connection': 'close',
}


def _select_tga_rows(df: pd.DataFrame) -> pd.DataFrame:
    acct = df['account_type'].astype(str).str.strip().str.lower()
    mask = (
        acct.str.contains('treasury general account', na=False)
        | acct.str.fullmatch(r'federal reserve account', na=False)
    )
    return df.loc[mask].copy()


def _fetch_slice(url: str, start: str, end: str, attempts: int, page_size: int) -> list[dict]:
    """Fetch one bounded date slice from Treasury Fiscal Data, exhausting pages."""
    out: list[dict] = []
    page = 1
    while True:
        params = {
            'fields': 'record_date,account_type,close_today_bal',
            'filter': f'record_date:gte:{start},record_date:lte:{end}',
            'sort': 'record_date',
            'page[size]': str(page_size),
            'page[number]': str(page),
            'format': 'json',
        }
        payload = None
        last_exc = None
        for attempt in range(1, attempts + 1):
            try:
                r = requests.get(url, params=params, timeout=(8, 30), headers=HEADERS)
                r.raise_for_status()
                payload = r.json()
                break
            except requests.exceptions.RequestException as exc:
                last_exc = exc
                if attempt < attempts:
                    time.sleep(attempt)
        if payload is None:
            raise last_exc if last_exc else RuntimeError(f'Treasury DTS: unknown fetch failure {start}..{end}')

        rows = payload.get('data', [])
        if not rows:
            break
        out.extend(rows)

        meta = payload.get('meta', {}) or {}
        total_pages = meta.get('total-pages') or meta.get('total_pages')
        if total_pages is not None:
            if page >= int(total_pages):
                break
        elif len(rows) < page_size:
            break

        page += 1
        if page > 20:
            raise RuntimeError(f'Treasury DTS: pagination safety limit exceeded for {start}..{end}')
    return out


def fetch_tga_paged(attempts: int = 3, page_size: int = 10000) -> pd.Series:
    """Fetch full formal-window TGA from official Treasury Fiscal Data.

    Treasury's broad multi-year query can truncate despite pagination because the
    underlying DTS table is large and its schema evolved. To make coverage
    deterministic, request each calendar year separately, then combine and QA.
    """
    url = 'https://api.fiscaldata.treasury.gov/services/api/fiscal_service/v1/accounting/dts/operating_cash_balance'
    all_rows: list[dict] = []
    formal_start = pd.Timestamp(FORMAL_START)
    formal_end = pd.Timestamp(FORMAL_END)

    for year in range(formal_start.year, formal_end.year + 1):
        start = max(formal_start, pd.Timestamp(f'{year}-01-01'))
        end = min(formal_end, pd.Timestamp(f'{year}-12-31'))
        all_rows.extend(_fetch_slice(url, start.date().isoformat(), end.date().isoformat(), attempts, page_size))

    if not all_rows:
        raise RuntimeError('Treasury DTS: empty yearly-sliced data')

    df = pd.DataFrame(all_rows)
    required = {'record_date', 'account_type', 'close_today_bal'}
    if not required.issubset(df.columns):
        raise RuntimeError(f'Treasury DTS: missing fields {required - set(df.columns)}')

    x = _select_tga_rows(df)
    if x.empty:
        labels = sorted(df['account_type'].dropna().astype(str).unique().tolist())[:50]
        raise RuntimeError(f'Treasury DTS: TGA/Federal Reserve Account rows not found; observed account_type={labels}')

    dt = pd.to_datetime(x['record_date'], errors='coerce')
    val = pd.to_numeric(x['close_today_bal'], errors='coerce')
    s = pd.Series(val.values, index=dt, name='TGA_DTS').dropna()
    s = s[~s.index.isna()].sort_index()
    s = s[~s.index.duplicated(keep='last')]
    s = s[(s.index >= formal_start) & (s.index <= formal_end)]
    if s.empty:
        raise RuntimeError('Treasury DTS: no usable yearly-sliced TGA observations')
    return s
