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


def _fetch_slice(url: str, start: str, end: str, attempts: int, page_size: int) -> list[dict]:
    """Fetch one bounded date slice from Treasury Fiscal Data, exhausting pages."""
    out: list[dict] = []
    page = 1
    while True:
        params = {
            # Treasury DTS changed the presentation of Table I around 2022.
            # Keep both balance fields so old and modern schemas can be normalized.
            'fields': 'record_date,account_type,open_today_bal,close_today_bal',
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


def _normalize_tga(df: pd.DataFrame) -> pd.Series:
    """Normalize legacy and modern DTS Table I layouts to one TGA closing series.

    Legacy rows use account labels such as Treasury General Account / Federal
    Reserve Account and expose the day's closing balance in close_today_bal.

    In the modern DTS layout, Treasury publishes an explicit
    "Treasury General Account (TGA) Closing Balance" row.  On that row the
    reported closing balance is carried in open_today_bal while close_today_bal
    can be null.  Treating only close_today_bal as authoritative therefore
    creates a false data stop around the schema transition.
    """
    if 'account_type' not in df.columns:
        raise RuntimeError('Treasury DTS: missing account_type')

    acct_raw = df['account_type'].astype(str).str.strip()
    acct = acct_raw.str.lower()
    dt = pd.to_datetime(df['record_date'], errors='coerce')
    close_val = pd.to_numeric(df.get('close_today_bal'), errors='coerce')
    open_val = pd.to_numeric(df.get('open_today_bal'), errors='coerce')

    # Modern explicit closing-balance row: prefer its reported value.
    modern_mask = (
        acct.str.contains('treasury general account', na=False)
        & acct.str.contains('closing balance', na=False)
    )
    modern = pd.Series(open_val.where(modern_mask).values, index=dt, dtype='float64')
    # Defensive fallback if Treasury later places the same explicit row value
    # back into close_today_bal.
    modern = modern.combine_first(
        pd.Series(close_val.where(modern_mask).values, index=dt, dtype='float64')
    )
    modern = modern.dropna()

    # Legacy Table I rows.
    legacy_mask = (
        (
            acct.str.contains('treasury general account', na=False)
            | acct.str.fullmatch(r'federal reserve account', na=False)
        )
        & ~acct.str.contains('opening balance', na=False)
        & ~acct.str.contains('closing balance', na=False)
    )
    legacy = pd.Series(close_val.where(legacy_mask).values, index=dt, dtype='float64').dropna()

    # Modern explicit rows take precedence on transition/duplicate dates.
    s = pd.concat([legacy.rename('value'), modern.rename('value')]).sort_index()
    s = s[~s.index.isna()]
    s = s[~s.index.duplicated(keep='last')]
    s.name = 'TGA_DTS'
    return s


def fetch_tga_paged(attempts: int = 3, page_size: int = 10000) -> pd.Series:
    """Fetch full formal-window TGA from official Treasury Fiscal Data.

    Treasury's broad multi-year query can truncate despite pagination because the
    underlying DTS table is large and its schema evolved. To make coverage
    deterministic, request each calendar year separately, then normalize the
    legacy and post-2022 Table I schemas and QA the combined series.
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
    required = {'record_date', 'account_type'}
    if not required.issubset(df.columns):
        raise RuntimeError(f'Treasury DTS: missing fields {required - set(df.columns)}')
    if 'close_today_bal' not in df.columns and 'open_today_bal' not in df.columns:
        raise RuntimeError('Treasury DTS: neither close_today_bal nor open_today_bal is available')

    s = _normalize_tga(df)
    s = s[(s.index >= formal_start) & (s.index <= formal_end)]
    if s.empty:
        labels = sorted(df['account_type'].dropna().astype(str).unique().tolist())[:80]
        raise RuntimeError(f'Treasury DTS: no usable TGA observations; observed account_type={labels}')

    # Coverage hard checks: source QA may still mark formal PIT false, but a raw
    # source success may not silently end years before the requested formal end.
    if s.index.min() > pd.Timestamp('2005-10-31'):
        raise RuntimeError(f'Treasury DTS: early-history coverage unexpectedly starts {s.index.min().date()}')
    if s.index.max() < formal_end - pd.Timedelta(days=7):
        raise RuntimeError(f'Treasury DTS: recent coverage unexpectedly ends {s.index.max().date()}')

    return s
