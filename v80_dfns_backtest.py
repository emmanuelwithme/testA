"""V80 formal runner with DFNS as a dedicated defense/geopolitical ETF class.

DFNS is NOT treated as a generic high-volatility thematic ETF. It uses the
same locked V80 state engine, with its own price/ATR/swing/indicator data and
a defense-sector cross-confirmation layer. No pre-inception history is filled.
"""
import pandas as pd
import yfinance as yf
import time
import v80_backtest as core

# London Stock Exchange USD line. VanEck: exchange ticker DFNS, Reuters/Yahoo-style DFNS.L.
core.ASSETS['DFNS'] = 'DFNS.L'

# Dedicated defense/policy/geopolitical satellite parameters. Wider drawdown
# activation and smaller left/right sizing than broad core ETFs reflect its
# concentration/event risk. These are V80 execution parameters, not Joseph's
# portfolio allocation weight.
core.PARAM['DFNS'] = dict(
    dd=-.12,
    left_frac=.15,
    right_frac=.35,
    trend_frac=.50,
    left_decel=3,
    right_count=4,
    trim=.125,
)

# Market-based cross checks only. We do not reconstruct historical wars,
# procurement decisions, NATO budgets or policy headlines with hindsight.
core.AUX.update({'ITA':'ITA', 'XLI':'XLI'})
_original_cross = core.cross_factors
_original_get_prices = core.get_prices


def get_prices_allow_post_inception(ticker):
    """Use shared strict history gate for old assets; allow genuine shorter history for DFNS only.

    DFNS began in 2023, so the shared >=1000-row requirement is inappropriate.
    This function still requires >=250 genuine observations and never creates
    or backfills any date before the fund actually traded.
    """
    if ticker != 'DFNS.L':
        return _original_get_prices(ticker)
    last = None
    for i in range(4):
        try:
            df = yf.Ticker(ticker).history(start='2023-03-31', end=core.END_EVAL + pd.Timedelta(days=1), auto_adjust=False, actions=True, repair=False, timeout=60)
            if df is None or len(df) < 250:
                raise RuntimeError(f'DFNS genuine post-inception history too short {0 if df is None else len(df)}')
            df.index = pd.to_datetime(df.index).tz_localize(None)
            cols = ['Open','High','Low','Close','Volume']
            df = df[cols].copy().apply(pd.to_numeric, errors='coerce').dropna(subset=['Open','High','Low','Close'])
            df = df[~df.index.duplicated(keep='last')].sort_index()
            if df.index.min() < pd.Timestamp('2023-03-31'):
                raise RuntimeError(f'DFNS contains pre-inception data starting {df.index.min()}')
            return df
        except Exception as e:
            last = e
            time.sleep(3*(i+1))
    raise RuntimeError(f'price download failed {ticker}: {last}')


# Patch the reference used by core.main(); no other asset loses the >=1000-row gate.
core.get_prices = get_prices_allow_post_inception


def dfns_cross_factors(asset, x, aux):
    if asset != 'DFNS':
        return _original_cross(asset, x, aux)
    ita = aux['ITA']
    xli = aux['XLI']
    breaks = pd.concat([
        (ita.C < ita.M20) & (ita.R20 < 0),
        (xli.C < xli.M20) & (xli.R20 < 0),
    ], axis=1).sum(axis=1)
    improves = pd.concat([
        (ita.R5 > 0) & (ita.C > ita.M20),
        (xli.R5 > 0) & (xli.C > xli.M20),
    ], axis=1).sum(axis=1)
    ok_left = (breaks < 2).fillna(True)
    right_bonus = (improves >= 2).astype(int).fillna(0)
    return ok_left, right_bonus


core.cross_factors = dfns_cross_factors


def _remove_partial_inception_half(path):
    """Do not pretend DFNS existed for all 2023H1; inception was 2023-03-31."""
    p = core.OUT / path
    if not p.exists():
        return
    d = pd.read_csv(p)
    if {'asset','period'}.issubset(d.columns):
        d = d[~((d.asset == 'DFNS') & (d.period == '2023_H1'))].copy()
        d.to_csv(p, index=False)


def main():
    core.main()
    _remove_partial_inception_half('halfyear_summary.csv')
    readme = core.OUT / 'DFNS_V80_NOTE.md'
    readme.write_text(
        'DFNS is a dedicated V80 defense/aerospace/military + policy/geopolitical equity ETF class.\n'
        'Ticker used: DFNS.L (LSE USD line). Fund inception: 2023-03-31; no synthetic pre-inception history.\n'
        'Formal half-year cohort comparison starts at 2023H2.\n'
        'Primary risk-adjusted metrics: Sortino + Calmar; secondary: MDD + Recovery Time; Sharpe auxiliary.\n'
        'Cross-market confirmation uses ITA/XLI market data only; historical policy/news events are not hindsight-filled.\n',
        encoding='utf-8')


if __name__ == '__main__':
    main()
