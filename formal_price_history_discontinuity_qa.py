from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import yfinance as yf

START = '2005-01-01'
END = '2026-09-01'
OUT = Path('formal_price_history_discontinuity_qa_output')
OUT.mkdir(exist_ok=True)

TICKERS = {
    '0050': '0050.TW',
    '00859B': '00859B.TWO',
    '00860B': '00860B.TWO',
}


def fetch(ticker: str) -> pd.Series:
    d = yf.download(ticker, start=START, end=END, auto_adjust=True, repair=True,
                    progress=False, actions=False, threads=False)
    if d.empty:
        return pd.Series(dtype=float)
    c = d['Close']
    if isinstance(c, pd.DataFrame):
        c = c.iloc[:, 0]
    c = pd.to_numeric(c, errors='coerce').dropna().astype(float)
    c.index = pd.to_datetime(c.index).tz_localize(None)
    return c.sort_index()


def main() -> int:
    rows = []
    jumps = []
    empty_assets = []
    for name, ticker in TICKERS.items():
        s = fetch(ticker)
        if s.empty:
            empty_assets.append(name)
        pct = s.pct_change()
        flagged = pct[pct.abs() > 0.55]
        rows.append({
            'asset': name,
            'ticker': ticker,
            'first_raw': str(s.index.min().date()) if len(s) else None,
            'last_raw': str(s.index.max().date()) if len(s) else None,
            'n_raw': int(len(s)),
            'gt55pct_jump_count': int(len(flagged)),
            'first_gt55pct_jump': str(flagged.index.min().date()) if len(flagged) else None,
        })
        for d, r in flagged.items():
            pos = s.index.get_loc(d)
            prev = float(s.iloc[pos - 1]) if pos > 0 else None
            curr = float(s.loc[d])
            jumps.append({
                'asset': name,
                'ticker': ticker,
                'date': str(d.date()),
                'previous_close_adjusted': prev,
                'current_close_adjusted': curr,
                'daily_return': float(r),
            })

    pd.DataFrame(rows).to_csv(OUT / 'history_summary.csv', index=False)
    pd.DataFrame(jumps).to_csv(OUT / 'flagged_jumps.csv', index=False)
    status = {
        'policy': 'Diagnostic only. A >55% adjusted-price jump must not automatically erase all prior valid ETF history without event/data QA.',
        'assets': rows,
        'empty_assets': empty_assets,
        'flagged_jump_rows': len(jumps),
        'qa_transport_pass': not empty_assets,
        'formal_backtest_ready': False,
        'note': 'This QA does not alter strategy rules or price histories. It identifies whether the legacy truncation heuristic is destroying valid pre-event history.'
    }
    (OUT / 'status.json').write_text(json.dumps(status, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(status, ensure_ascii=False, indent=2))
    if jumps:
        print(pd.DataFrame(jumps).to_string(index=False))
    if empty_assets:
        raise RuntimeError(f'Market-data transport failed for: {empty_assets}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
