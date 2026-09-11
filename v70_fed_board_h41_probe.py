from __future__ import annotations

from io import StringIO
import csv
import json
import re
import sys
import requests
import pandas as pd

FORMAL_START = '2005-01-01'
FORMAL_END = '2026-08-31'

# Official Federal Reserve Board Data Download Program package that contains
# H41/H41/RESPPMA_N.WW = Total assets (Less eliminations from consolidation),
# Wednesday level.  This is the Board-source line item underlying FRED WALCL.
H41_PACKAGE_ID = '65cb5d86fcaca4f4a8129301bd9502bd'
H41_SERIES_MNEMONIC = 'RESPPMA_N.WW'

HEADERS = {
    'User-Agent': 'Mozilla/5.0 LivingWaterAI research backtest/1.0',
    'Accept': 'text/csv,text/plain,*/*',
    'Connection': 'close',
}


def fetch_h41_total_assets() -> pd.Series:
    url = 'https://www.federalreserve.gov/datadownload/Output.aspx'
    params = {
        'rel': 'H41',
        'series': H41_PACKAGE_ID,
        'lastobs': '',
        'from': '01/01/2005',
        'to': '08/31/2026',
        'filetype': 'csv',
        'label': 'include',
        'layout': 'seriescolumn',
        'type': 'package',
    }
    r = requests.get(url, params=params, timeout=(10, 60), headers=HEADERS)
    r.raise_for_status()
    text = r.text
    if H41_SERIES_MNEMONIC not in text:
        raise RuntimeError('Fed H41 package returned but RESPPMA_N.WW was not found')

    rows = list(csv.reader(StringIO(text)))
    target_col = None
    for row in rows[:25]:
        for j, cell in enumerate(row):
            if H41_SERIES_MNEMONIC in str(cell):
                target_col = j
                break
        if target_col is not None:
            break
    if target_col is None:
        raise RuntimeError('Could not locate RESPPMA_N.WW column in Fed H41 CSV')

    pairs = []
    date_re = re.compile(r'^\d{4}-\d{2}-\d{2}$|^\d{1,2}/\d{1,2}/\d{4}$')
    for row in rows:
        if len(row) <= target_col or not row:
            continue
        date_cell = str(row[0]).strip()
        if not date_re.match(date_cell):
            continue
        dt = pd.to_datetime(date_cell, errors='coerce')
        val = pd.to_numeric(str(row[target_col]).strip(), errors='coerce')
        if pd.isna(dt) or pd.isna(val):
            continue
        pairs.append((dt, float(val)))

    if not pairs:
        raise RuntimeError('Fed H41 CSV parsed but produced no RESPPMA_N.WW observations')

    s = pd.Series([v for _, v in pairs], index=[d for d, _ in pairs], name='RESPPMA_N.WW').sort_index()
    s = s.loc[(s.index >= pd.Timestamp(FORMAL_START)) & (s.index <= pd.Timestamp(FORMAL_END))]
    s = s[~s.index.duplicated(keep='last')]
    if s.empty:
        raise RuntimeError('Fed H41 RESPPMA_N.WW has no observations in formal window')
    return s


def main() -> int:
    try:
        s = fetch_h41_total_assets()
        report = {
            'status': 'RAW_SOURCE_OK_OFFICIAL_FED_BOARD',
            'logical_input': 'WALCL',
            'official_release': 'Federal Reserve Board H.4.1',
            'official_mnemonic': H41_SERIES_MNEMONIC,
            'first_observation': str(s.index.min().date()),
            'last_observation': str(s.index.max().date()),
            'n': int(len(s)),
            'units': 'millions_usd',
            'formal_pit_ready': False,
            'pit_note': 'Transport/equivalence probe only. Formal use still requires release-availability mapping and cross-check against WALCL values before integration.',
        }
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0
    except Exception as exc:
        print(json.dumps({'status': 'PROBE_FAIL', 'error': repr(exc)}, ensure_ascii=False, indent=2))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
