import time
import traceback
from pathlib import Path
from io import StringIO
import numpy as np
import pandas as pd
import requests
import yfinance as yf

import v82_backtest_extended as e

# Data-integrity wrapper for the 2005-2026 robustness replay.
# 1) Corporate actions: request Yahoo auto-adjusted + repair=True OHLC directly.
# 2) Total return: auto-adjusted Close already embeds distributions/splits, so
#    do not add Dividends a second time.
# 3) Stress windows: only mark a crisis window available when the instrument
#    actually covers the whole requested window.
# 4) 0050: Yahoo's long history contains a known discontinuity around
#    2014-01-02 in this workflow. Until an authoritative TWSE/Yuanta pre-2014
#    total-return source is integrated, pre-2014 0050 is treated as N/A rather
#    than silently ratio-adjusted or winsorized.
# 5) Extended USD/TWD conversion uses Federal Reserve H.10 / FRED DEXTAUS,
#    not Yahoo TWD=X, whose vendor history showed an impossible 2011 jump.
# 6) Any fatal exception is persisted to the artifact output directory.


def dl_long_adjusted(ticker, start='2004-01-01', end='2026-09-02'):
    last = None
    for i in range(5):
        try:
            d = yf.Ticker(ticker).history(
                start=start, end=end, auto_adjust=True,
                actions=True, repair=True, timeout=60
            )
            if d is None or len(d) < 20:
                raise RuntimeError(f'short history {len(d) if d is not None else 0}')
            d.index = pd.to_datetime(d.index).tz_localize(None)
            d = d[~d.index.duplicated(keep='last')].sort_index()
            for c in ['Open','High','Low','Close','Volume']:
                d[c] = pd.to_numeric(d[c], errors='coerce')
            if 'Dividends' not in d:
                d['Dividends'] = 0.0
            d = d.dropna(subset=['Open','High','Low','Close'])

            r = pd.to_numeric(d['Close'], errors='coerce').pct_change().dropna()
            if ticker == '0050.TW' and len(r):
                bad = r[(r < -0.60) | (r > 1.50)]
                if len(bad):
                    first_bad = pd.Timestamp(bad.index.min())
                    if first_bad <= pd.Timestamp('2014-01-03'):
                        print(
                            'WARN 0050 vendor history before 2014-01-02 excluded; '
                            'pre-2014 Extended Actual ETF = N/A pending authoritative '
                            'TWSE/Yuanta source. first_bad=', first_bad.date(),
                            'return=', float(bad.loc[first_bad])
                        )
                        d = d.loc[d.index >= pd.Timestamp('2014-01-02')].copy()
                        if len(d) < 20:
                            raise RuntimeError('0050 post-2014 verified segment too short')
                        r = pd.to_numeric(d['Close'], errors='coerce').pct_change().dropna()

            if len(r) and float(r.min()) < -0.60:
                dt = r.idxmin()
                raise RuntimeError(
                    f'{ticker} repaired adjusted Close still has implausible one-day '
                    f'return {float(r.min()):.2%} on {pd.Timestamp(dt).date()}'
                )
            if len(r) and float(r.max()) > 1.50:
                dt = r.idxmax()
                raise RuntimeError(
                    f'{ticker} repaired adjusted Close still has implausible one-day '
                    f'return {float(r.max()):.2%} on {pd.Timestamp(dt).date()}'
                )
            return d
        except Exception as exc:
            last = exc
            print(f'WARN dl_long_adjusted {ticker} attempt {i+1}: {exc}')
            time.sleep(3*(i+1))
    raise RuntimeError(f'{ticker} failed: {last}')


def fred_dextaus_long(index):
    """Point-in-Time USD/TWD spot series from Federal Reserve H.10 via FRED.

    DEXTAUS is Taiwan dollars per one U.S. dollar. Calendar/trading-day gaps are
    filled only forward from the latest already-published observation; no
    future observation is backfilled into earlier dates.
    """
    idx = pd.DatetimeIndex(index).sort_values()
    url = ('https://fred.stlouisfed.org/graph/fredgraph.csv?'
           'id=DEXTAUS&cosd=2004-01-01&coed=2026-08-31')
    last = None
    for i in range(5):
        try:
            rr = requests.get(url, timeout=120, headers={'User-Agent':'Mozilla/5.0'})
            rr.raise_for_status()
            z = pd.read_csv(StringIO(rr.text))
            z.columns = ['date','rate']
            z['date'] = pd.to_datetime(z['date'], errors='coerce')
            z['rate'] = pd.to_numeric(z['rate'], errors='coerce')
            s = z.dropna().set_index('date').rate.sort_index()
            if s.empty:
                raise RuntimeError('FRED DEXTAUS returned no valid observations')
            combined = s.reindex(s.index.union(idx)).sort_index().ffill().reindex(idx)
            if combined.isna().any():
                first_missing = combined[combined.isna()].index.min()
                raise RuntimeError(f'DEXTAUS cannot cover required date {first_missing}')
            if not np.isfinite(combined).all() or (combined <= 0).any():
                raise RuntimeError('DEXTAUS contains invalid/non-positive values')
            # Sanity only; do not alter data. A >20% daily FX move is treated as
            # source corruption and fails closed for investigation.
            fxret = combined.pct_change().dropna()
            bad = fxret[fxret.abs() > 0.20]
            if len(bad):
                dt = pd.Timestamp(bad.index[0])
                raise RuntimeError(
                    f'DEXTAUS sanity failure: {float(bad.iloc[0]):.2%} daily move on {dt.date()}'
                )
            return combined.astype(float)
        except Exception as exc:
            last = exc
            print(f'WARN fred_dextaus_long attempt {i+1}: {exc}')
            time.sleep(3*(i+1))
    raise RuntimeError(f'FRED DEXTAUS failed: {last}')


def adjusted_total_return_index(d):
    c = pd.to_numeric(d['Close'], errors='coerce').dropna().astype(float)
    if len(c) < 2:
        raise RuntimeError('adjusted total-return series too short')
    r = c / c.shift(1)
    r.iloc[0] = 1.0
    one_day = r.dropna() - 1.0
    if len(one_day) and float(one_day.min()) < -0.60:
        dt = one_day.idxmin()
        raise RuntimeError(
            f'corporate-action/data sanity failure: one-day adjusted total return '
            f'{float(one_day.min()):.2%} on {pd.Timestamp(dt).date()}'
        )
    if len(one_day) and float(one_day.max()) > 1.50:
        dt = one_day.idxmax()
        raise RuntimeError(
            f'corporate-action/data sanity failure: one-day adjusted total return '
            f'{float(one_day.max()):.2%} on {pd.Timestamp(dt).date()}'
        )
    return r.replace([np.inf,-np.inf], np.nan).fillna(1.0).cumprod()


def stress_rows_full_coverage(asset, strategy, unit):
    out = []
    umin = pd.Timestamp(unit.index.min())
    umax = pd.Timestamp(unit.index.max())
    tol = pd.Timedelta(days=7)
    for name, (s, z) in e.STRESS_WINDOWS.items():
        start = pd.Timestamp(s); end = pd.Timestamp(z)
        full = (umin <= start + tol) and (umax >= end - tol)
        q = unit.loc[(unit.index >= start) & (unit.index <= end)] if full else unit.iloc[0:0]
        if (not full) or len(q) < 2:
            out.append({
                'asset':asset,'strategy':strategy,'window':name,
                'start':s,'end':z,'available':False,
                'period_return':np.nan,'max_drawdown':np.nan
            })
            continue
        out.append({
            'asset':asset,'strategy':strategy,'window':name,
            'start':s,'end':z,'available':True,
            'period_return':float(q.iloc[-1]/q.iloc[0]-1),
            'max_drawdown':float((q/q.cummax()-1).min())
        })
    return out


# Monkey-patch the imported extended engine before main() executes.
e.dl_long = dl_long_adjusted
e.usd_twd_long = fred_dextaus_long
e.b.total_return_index = adjusted_total_return_index
e.stress_rows = stress_rows_full_coverage

if __name__ == '__main__':
    try:
        e.main()
    except Exception:
        tb = traceback.format_exc()
        print(tb)
        out = Path('v82_extended_results')
        out.mkdir(exist_ok=True)
        (out / 'extended_failure.txt').write_text(tb, encoding='utf-8')
        raise
