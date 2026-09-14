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


def fetch_unrepaired_actions(ticker: str) -> pd.DataFrame:
    d = yf.download(ticker, start=START, end=END, auto_adjust=False, repair=False,
                    progress=False, actions=True, threads=False)
    if d.empty:
        return d
    if isinstance(d.columns, pd.MultiIndex):
        # yfinance single-ticker downloads may still return a ticker level.
        try:
            d = d.xs(ticker, axis=1, level=-1)
        except Exception:
            d.columns = [c[0] if isinstance(c, tuple) else c for c in d.columns]
    d.index = pd.to_datetime(d.index).tz_localize(None)
    return d.sort_index()


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
            'first_repaired_adjusted': str(s.index.min().date()) if len(s) else None,
            'last_repaired_adjusted': str(s.index.max().date()) if len(s) else None,
            'n_repaired_adjusted': int(len(s)),
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
                'previous_close_adjusted_repaired': prev,
                'current_close_adjusted_repaired': curr,
                'daily_return': float(r),
            })

    raw0050 = fetch_unrepaired_actions('0050.TW')
    raw0050_summary = {
        'first_unrepaired_observation': str(raw0050.index.min().date()) if len(raw0050) else None,
        'last_unrepaired_observation': str(raw0050.index.max().date()) if len(raw0050) else None,
        'n_unrepaired': int(len(raw0050)),
        'columns': [str(c) for c in raw0050.columns],
    }
    event_window = raw0050.loc['2013-12-20':'2014-01-10'].copy() if len(raw0050) else pd.DataFrame()
    event_window.to_csv(OUT / '0050_unrepaired_event_window_2013-12-20_2014-01-10.csv')

    # Save all explicitly reported split/dividend action rows if the provider supplies them.
    action_cols = [c for c in raw0050.columns if str(c).lower() in {'dividends', 'stock splits', 'capital gains'}]
    if len(raw0050) and action_cols:
        action_mask = pd.Series(False, index=raw0050.index)
        for c in action_cols:
            action_mask |= pd.to_numeric(raw0050[c], errors='coerce').fillna(0).ne(0)
        raw0050.loc[action_mask, action_cols].to_csv(OUT / '0050_unrepaired_corporate_actions.csv')
    else:
        pd.DataFrame().to_csv(OUT / '0050_unrepaired_corporate_actions.csv')

    pd.DataFrame(rows).to_csv(OUT / 'history_summary.csv', index=False)
    pd.DataFrame(jumps).to_csv(OUT / 'flagged_jumps.csv', index=False)
    status = {
        'policy': 'Diagnostic only. A >55% adjusted-price jump must not automatically erase all prior valid ETF history without corporate-action/data QA.',
        'assets': rows,
        'empty_assets': empty_assets,
        'flagged_jump_rows': len(jumps),
        '0050_unrepaired_summary': raw0050_summary,
        '0050_event_window_rows': int(len(event_window)),
        'qa_transport_pass': not empty_assets and len(raw0050) > 0,
        'formal_backtest_ready': False,
        'note': 'This QA does not alter strategy rules or price histories. It compares repaired adjusted history with unrepaired price/action data before deciding whether any truncation is legitimate.'
    }
    (OUT / 'status.json').write_text(json.dumps(status, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(status, ensure_ascii=False, indent=2))
    if jumps:
        print(pd.DataFrame(jumps).to_string(index=False))
    if not event_window.empty:
        print(event_window.to_string())
    if empty_assets or raw0050.empty:
        raise RuntimeError(f'Market-data transport failed; empty adjusted={empty_assets}, raw0050_empty={raw0050.empty}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
