"""V80 formal runner with DFNS as a dedicated defense/geopolitical ETF class.

DFNS is NOT treated as a generic high-volatility thematic ETF. It uses the
same locked V80 state engine, with its own price/ATR/swing/indicator data and
a defense-sector cross-confirmation layer. No pre-inception history is filled.

This runner also applies the V80 yen carry-trade overlay to ALL equity assets.
The yen overlay is a macro/liquidity amplifier, not a standalone buy/sell signal.
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
_original_make_base = core.make_base
_original_state_events = core.state_events


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


def make_base_with_yen(df, macro):
    """Attach point-in-time yen carry fields to every V80 equity signal frame."""
    x = _original_make_base(df, macro)
    mac = macro.reindex(macro.index.union(x.index)).sort_index().ffill().reindex(x.index)
    yen_cols = [
        'USDJPY','USDJPY_1D_PCT','USDJPY_5D_PCT',
        'JPY_APPRECIATION_1D_PCT','JPY_APPRECIATION_5D_PCT',
        'YEN_CARRY_CONFIRM_COUNT','YEN_CARRY_RISK_LEVEL',
        'YEN_CARRY_HEADWIND','YEN_CARRY_VETO','YEN_CARRY_BUY_SCALE'
    ]
    for c in yen_cols:
        x['X_'+c] = mac[c] if c in mac else pd.NA
    return x


core.make_base = make_base_with_yen


def state_events_with_yen(asset, x):
    """Apply yen-risk sizing at T+1 execution without creating hindsight.

    Level 0: 1.00x new-buy size
    Level 1: 0.75x
    Level 2: 0.50x
    Level 3: 0.00x and MACRO_VETO already forces risk-off logic.

    Yen appreciation alone never creates a hard veto. Level 3 requires severe
    yen appreciation plus at least two cross-asset confirmations from VIX,
    MOVE and HY OAS, as defined in v80_macro.py.
    """
    ev = _original_state_events(asset, x)
    if ev is None or len(ev) == 0:
        return ev
    ev = ev.copy()
    ev['execution_date'] = pd.to_datetime(ev['execution_date'])
    scales=[]; levels=[]; confirms=[]; yen1=[]; yen5=[]
    for _, r in ev.iterrows():
        dt=r['execution_date']
        if dt in x.index:
            row=x.loc[dt]
            scale=float(row.get('X_YEN_CARRY_BUY_SCALE',1.0)) if pd.notna(row.get('X_YEN_CARRY_BUY_SCALE',1.0)) else 1.0
            level=int(row.get('X_YEN_CARRY_RISK_LEVEL',0)) if pd.notna(row.get('X_YEN_CARRY_RISK_LEVEL',0)) else 0
            confirm=int(row.get('X_YEN_CARRY_CONFIRM_COUNT',0)) if pd.notna(row.get('X_YEN_CARRY_CONFIRM_COUNT',0)) else 0
            a1=float(row.get('X_JPY_APPRECIATION_1D_PCT',0.0)) if pd.notna(row.get('X_JPY_APPRECIATION_1D_PCT',0.0)) else 0.0
            a5=float(row.get('X_JPY_APPRECIATION_5D_PCT',0.0)) if pd.notna(row.get('X_JPY_APPRECIATION_5D_PCT',0.0)) else 0.0
        else:
            scale,level,confirm,a1,a5=1.0,0,0,0.0,0.0
        scales.append(scale); levels.append(level); confirms.append(confirm); yen1.append(a1); yen5.append(a5)
    ev['yen_carry_buy_scale']=scales
    ev['yen_carry_risk_level']=levels
    ev['yen_carry_confirm_count']=confirms
    ev['jpy_appreciation_1d_pct']=yen1
    ev['jpy_appreciation_5d_pct']=yen5
    buy_mask=ev['executed_state'].isin(['LEFT_BUY','RIGHT_ADD'])
    ev.loc[buy_mask,'buy_scale']=ev.loc[buy_mask,'buy_scale'].astype(float)*ev.loc[buy_mask,'yen_carry_buy_scale'].astype(float)
    # Level 3 is already reflected in MACRO_VETO/HARD_VETO; this additional
    # assertion guarantees that no new purchase survives a severe carry unwind.
    severe=ev['yen_carry_risk_level'].ge(3)&buy_mask
    ev.loc[severe,'executed_state']='RISK_DOWN'
    ev.loc[severe,'buy_scale']=0.0
    return ev


core.state_events = state_events_with_yen


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
        'Cross-market confirmation uses ITA/XLI market data only; historical policy/news events are not hindsight-filled.\n'
        'All V80 equity assets also use the point-in-time yen carry overlay: rapid yen appreciation scales new buys to 0.75x/0.50x; severe yen appreciation plus >=2 VIX/MOVE/HY confirmations blocks new buys.\n',
        encoding='utf-8')


if __name__ == '__main__':
    main()
