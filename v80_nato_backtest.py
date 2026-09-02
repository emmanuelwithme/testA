"""V80 formal runner with NATO as the dedicated defence/cyber/geopolitical ETF class.

NATO is the HANetf Future of Defence UCITS ETF, LSE USD line (NATO.L).
It is NOT treated as a generic high-volatility thematic ETF. It uses the locked
V80 state engine with its own price/ATR/swing/indicator data and a dedicated
defence + cyber cross-confirmation layer. No pre-inception history is filled.

This runner also applies the V80 yen carry-trade overlay to ALL equity assets.
The yen overlay is a macro/liquidity amplifier, not a standalone buy/sell signal.
"""
import pandas as pd
import yfinance as yf
import time
import v80_backtest as core

# HANetf Future of Defence UCITS ETF. Official LSE USD RIC: NATO.L.
core.ASSETS['NATO'] = 'NATO.L'

# Dedicated defence/cyber/policy/geopolitical satellite parameters.
# These are V80 execution parameters, not the portfolio's 5% allocation weight.
# We reuse the locked defence-satellite sizing skeleton, but ALL results are
# recomputed from NATO's own history; no DFNS price/result is reused.
core.PARAM['NATO'] = dict(
    dd=-.12,
    left_frac=.15,
    right_frac=.35,
    trend_frac=.50,
    left_decel=3,
    right_count=4,
    trim=.125,
)

# Point-in-time market proxies only. ITA/XLI cover traditional defence/industry;
# CIBR adds cyber-security confirmation, matching NATO's modern-defence exposure.
core.AUX.update({'ITA':'ITA', 'XLI':'XLI', 'CIBR':'CIBR'})
_original_cross = core.cross_factors
_original_get_prices = core.get_prices
_original_make_base = core.make_base
_original_state_events = core.state_events


def get_prices_allow_post_inception(ticker):
    """Use shared strict history gate for old assets; allow genuine shorter NATO history only.

    Fund inception is 2023-07-03 and the LSE USD line listed 2023-07-04.
    Require genuine post-listing observations and never create/backfill dates
    before the instrument actually traded.
    """
    if ticker != 'NATO.L':
        return _original_get_prices(ticker)
    last = None
    for i in range(4):
        try:
            df = yf.Ticker(ticker).history(
                start='2023-07-04',
                end=core.END_EVAL + pd.Timedelta(days=1),
                auto_adjust=False,
                actions=True,
                repair=False,
                timeout=60,
            )
            if df is None or len(df) < 250:
                raise RuntimeError(f'NATO genuine post-listing history too short {0 if df is None else len(df)}')
            df.index = pd.to_datetime(df.index).tz_localize(None)
            cols = ['Open','High','Low','Close','Volume']
            df = df[cols].copy().apply(pd.to_numeric, errors='coerce').dropna(subset=['Open','High','Low','Close'])
            df = df[~df.index.duplicated(keep='last')].sort_index()
            if df.index.min() < pd.Timestamp('2023-07-04'):
                raise RuntimeError(f'NATO contains pre-listing data starting {df.index.min()}')
            return df
        except Exception as e:
            last = e
            time.sleep(3*(i+1))
    raise RuntimeError(f'price download failed {ticker}: {last}')


core.get_prices = get_prices_allow_post_inception


def nato_cross_factors(asset, x, aux):
    if asset != 'NATO':
        return _original_cross(asset, x, aux)
    ita = aux['ITA']
    xli = aux['XLI']
    cibr = aux['CIBR']
    breaks = pd.concat([
        (ita.C < ita.M20) & (ita.R20 < 0),
        (xli.C < xli.M20) & (xli.R20 < 0),
        (cibr.C < cibr.M20) & (cibr.R20 < 0),
    ], axis=1).sum(axis=1)
    improves = pd.concat([
        (ita.R5 > 0) & (ita.C > ita.M20),
        (xli.R5 > 0) & (xli.C > xli.M20),
        (cibr.R5 > 0) & (cibr.C > cibr.M20),
    ], axis=1).sum(axis=1)
    # A single weak proxy must not veto NATO. Broad deterioration across all
    # three proxies blocks left-side confirmation; two-of-three improvement
    # adds one right-side confirmation.
    ok_left = (breaks < 3).fillna(True)
    right_bonus = (improves >= 2).astype(int).fillna(0)
    return ok_left, right_bonus


core.cross_factors = nato_cross_factors


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
    """Apply yen-risk sizing at T+1 execution without hindsight."""
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
    severe=ev['yen_carry_risk_level'].ge(3)&buy_mask
    ev.loc[severe,'executed_state']='RISK_DOWN'
    ev.loc[severe,'buy_scale']=0.0
    return ev


core.state_events = state_events_with_yen


def _remove_partial_inception_half(path):
    """Do not pretend NATO existed for the entire 2023H2; LSE listing was 2023-07-04."""
    p = core.OUT / path
    if not p.exists():
        return
    d = pd.read_csv(p)
    if {'asset','period'}.issubset(d.columns):
        d = d[~((d.asset == 'NATO') & (d.period == '2023_H2'))].copy()
        d.to_csv(p, index=False)


def main():
    core.main()
    _remove_partial_inception_half('halfyear_summary.csv')
    readme = core.OUT / 'NATO_V80_NOTE.md'
    readme.write_text(
        'NATO is the dedicated V80 defence/aerospace/military + cyber/policy/geopolitical equity ETF class.\n'
        'Instrument: HANetf Future of Defence UCITS ETF; ticker used: NATO.L (LSE USD line).\n'
        'Fund inception: 2023-07-03; LSE listing: 2023-07-04; no synthetic pre-listing history.\n'
        '2023H2 is treated as an inception half; first complete half-year cohort is 2024H1.\n'
        'Primary risk-adjusted metrics: Sortino + Calmar; secondary: MDD + Recovery Time; Sharpe auxiliary.\n'
        'Cross-market confirmation uses ITA/XLI/CIBR point-in-time market data only; historical policy/news events are not hindsight-filled.\n'
        'All V80 equity assets also use the point-in-time yen carry overlay.\n',
        encoding='utf-8')


if __name__ == '__main__':
    main()
