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


def fetch_tga_paged(attempts: int = 3, page_size: int = 10000) -> pd.Series:
    """Fetch the full formal-window TGA series from U.S. Treasury Fiscal Data.

    The earlier implementation requested page[size]=10000 but did not paginate,
    which truncated the selected TGA history around 2019. This helper exhausts
    all official API pages before selecting the Treasury/Federal Reserve account.
    """
    url = 'https://api.fiscaldata.treasury.gov/services/api/fiscal_service/v1/accounting/dts/operating_cash_balance'
    all_rows: list[dict] = []
    page = 1

    while True:
        params = {
            'fields': 'record_date,account_type,close_today_bal',
            'filter': f'record_date:gte:{FORMAL_START},record_date:lte:{FORMAL_END}',
            'sort': 'record_date',
            'page[size]': str(page_size),
            'page[number]': str(page),
            'format': 'json',
        }
        last_exc = None
        payload = None
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
            raise last_exc if last_exc else RuntimeError('Treasury DTS: unknown paged fetch failure')

        rows = payload.get('data', [])
        if not rows:
            break
        all_rows.extend(rows)

        meta = payload.get('meta', {}) or {}
        total_pages = meta.get('total-pages') or meta.get('total_pages')
        if total_pages is not None:
            if page >= int(total_pages):
                break
        elif len(rows) < page_size:
            break

        page += 1
        if page > 100:
            raise RuntimeError('Treasury DTS: pagination safety limit exceeded')

    if not all_rows:
        raise RuntimeError('Treasury DTS: empty paged data')

    df = pd.DataFrame(all_rows)
    required = {'record_date', 'account_type', 'close_today_bal'}
    if not required.issubset(df.columns):
        raise RuntimeError(f'Treasury DTS: missing fields {required - set(df.columns)}')

    x = _select_tga_rows(df)
    if x.empty:
        labels = sorted(df['account_type'].dropna().astype(str).unique().tolist())[:30]
        raise RuntimeError(f'Treasury DTS: TGA/Federal Reserve Account rows not found; observed account_type={labels}')

    dt = pd.to_datetime(x['record_date'], errors='coerce')
    val = pd.to_numeric(x['close_today_bal'], errors='coerce')
    s = pd.Series(val.values, index=dt, name='TGA_DTS').dropna()
    s = s[~s.index.isna()].sort_index()
    s = s[~s.index.duplicated(keep='last')]
    s = s[(s.index >= pd.Timestamp(FORMAL_START)) & (s.index <= pd.Timestamp(FORMAL_END))]
    if s.empty:
        raise RuntimeError('Treasury DTS: no usable paged TGA observations')
    return s
