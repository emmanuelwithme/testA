"""V80 formal runner with DFNS as a dedicated defense/geopolitical ETF class.

DFNS is NOT treated as a generic high-volatility thematic ETF. It uses the
same locked V80 state engine, with its own price/ATR/swing/indicator data and
a defense-sector cross-confirmation layer. No pre-inception history is filled.
"""
import pandas as pd
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


def dfns_cross_factors(asset, x, aux):
    if asset != 'DFNS':
        return _original_cross(asset, x, aux)
    ita = aux['ITA']
    xli = aux['XLI']
    # Left-side veto only when BOTH defense and industrial market proxies are
    # simultaneously below MA20 with negative 20-day trend.
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
