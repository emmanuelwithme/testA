from __future__ import annotations

import json
import time
from pathlib import Path

import pandas as pd
import requests

FORMAL_START = pd.Timestamp('2005-01-01')
TWSE_API_START = pd.Timestamp('2010-01-04')
END = pd.Timestamp('2026-08-31')
OUT = Path('twse_0050_official_history_probe_output')
OUT.mkdir(exist_ok=True)
URL = 'https://www.twse.com.tw/exchangeReport/STOCK_DAY'


def roc_to_date(s: str) -> pd.Timestamp:
    y, m, d = [int(x) for x in s.split('/')]
    return pd.Timestamp(y + 1911, m, d)


def num(s):
    if s is None:
        return None
    x = str(s).replace(',', '').strip()
    if x in {'', '--', '---', 'X0.00'}:
        return None
    try:
        return float(x)
    except Exception:
        return None


def fetch_month(session: requests.Session, first_day: pd.Timestamp):
    params = {'response': 'json', 'date': first_day.strftime('%Y%m01'), 'stockNo': '0050'}
    last_err = None
    for attempt in range(5):
        try:
            r = session.get(URL, params=params, timeout=30, headers={'User-Agent': 'Mozilla/5.0 LivingWaterAI formal backtest QA'})
            r.raise_for_status()
            j = r.json()
            stat = str(j.get('stat', ''))
            if stat == 'OK':
                return j
            if '查詢日期小於99年1月4日' in stat:
                return {'stat': stat, 'data': [], 'fields': [], 'pre2010_archive_limit': True}
            if '很抱歉' in stat or '查無資料' in stat:
                return j
            last_err = RuntimeError(f'TWSE stat={stat}')
        except Exception as e:
            last_err = e
        time.sleep(0.8 * (attempt + 1))
    raise RuntimeError(f'Failed TWSE month {first_day:%Y-%m}: {last_err}')


def main() -> int:
    session = requests.Session()
    # Formal window starts in 2005, but the current official STOCK_DAY API itself
    # hard-rejects dates before ROC 99/01/04 (2010-01-04). We record that as NA,
    # never substitute NAV/index/proxy data, and fetch the official API from 2010 onward.
    months = pd.date_range(TWSE_API_START.replace(day=1), END.replace(day=1), freq='MS')
    rows = []
    month_status = []
    for i, m in enumerate(months):
        j = fetch_month(session, m)
        data = j.get('data') or []
        fields = j.get('fields') or []
        month_status.append({'month': str(m.date()), 'stat': j.get('stat'), 'rows': len(data), 'fields': fields})
        for rec in data:
            if len(rec) < 7:
                continue
            dt = roc_to_date(rec[0])
            if dt < TWSE_API_START or dt > END:
                continue
            rows.append({
                'date': dt,
                'volume_shares': num(rec[1]),
                'turnover_twd': num(rec[2]),
                'open': num(rec[3]),
                'high': num(rec[4]),
                'low': num(rec[5]),
                'close': num(rec[6]),
                'change': rec[7] if len(rec) > 7 else None,
                'transactions': num(rec[8]) if len(rec) > 8 else None,
                'source_month': str(m.date()),
            })
        if i < len(months) - 1:
            time.sleep(0.12)

    df = pd.DataFrame(rows)
    if df.empty:
        raise RuntimeError('TWSE returned no 0050 official daily history for its supported 2010+ window')
    df = df.drop_duplicates('date').sort_values('date')
    df.to_csv(OUT / '0050_twse_daily_close.csv', index=False)
    pd.DataFrame(month_status).to_json(OUT / 'month_status.json', orient='records', force_ascii=False, indent=2)

    pct = df.set_index('date')['close'].pct_change()
    jumps = pct[pct.abs() > 0.55]
    jump_df = pd.DataFrame({'date': jumps.index, 'daily_return': jumps.values})
    jump_df.to_csv(OUT / '0050_twse_gt55pct_jumps.csv', index=False)

    event = df[(df.date >= '2013-12-20') & (df.date <= '2014-01-10')]
    event.to_csv(OUT / '0050_twse_event_window_2013-12-20_2014-01-10.csv', index=False)

    status = {
        'source': 'TWSE official STOCK_DAY monthly endpoint',
        'ticker': '0050',
        'formal_requested_window': '2005-01-01..2026-08-31',
        'official_api_supported_start': '2010-01-04',
        'pre2010_policy': 'NA_ONLY_DO_NOT_PROXY; current STOCK_DAY API returns 查詢日期小於99年1月4日',
        'first_official_observation': str(df.date.min().date()),
        'last_official_observation': str(df.date.max().date()),
        'n_observations': int(len(df)),
        'gt55pct_jump_count': int(len(jumps)),
        '2014_01_02_present': bool((df.date == pd.Timestamp('2014-01-02')).any()),
        '2014_event_rows': int(len(event)),
        'price_history_2010plus_ready_for_total_return_construction': True,
        'price_history_2005_2009_ready': False,
        'total_return_ready': False,
        'remaining_requirement': 'Locate lawful actual-ETF 2005-2009 trading history if available; merge official cash distributions; validate 2025 1-for-4 split handling. No NAV/index proxy allowed.'
    }
    (OUT / 'status.json').write_text(json.dumps(status, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(status, ensure_ascii=False, indent=2))
    print(event.to_string(index=False))
    if len(jumps):
        print(jump_df.to_string(index=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
