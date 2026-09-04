from pathlib import Path
import math, time
import numpy as np
import pandas as pd
import yfinance as yf
import requests

from investment_backtest import add_indicators, period_bars, asof_cols
from v80_macro import build_macro_v80
from v80_backtest import v80_state, align_aux, PARAM as V80_PARAM

OUT = Path('v82_results'); OUT.mkdir(exist_ok=True)
START = pd.Timestamp('2019-01-01')
END = pd.Timestamp('2026-08-31')
ANNUAL_CONTRIBUTION = 1_000_000.0
YEARS = list(range(2019, 2027))

ASSETS = {
    'QQQ': ('QQQ','USD','B'),
    'VT': ('VT','USD','A'),
    '0050': ('0050.TW','TWD','B'),
    'VWRA': ('VWRA.L','USD','A'),
    'PPH': ('PPH','USD','C'),
    'SOXX': ('SOXX','USD','C'),
}
AUX = {'SOXX':'SOXX','NVDA':'NVDA','TSM':'TSM','2330':'2330.TW','XLV':'XLV'}

# Phase-1 coarse grid. These are candidates, NOT validated V82 defaults.
GRID = {
    'A': dict(base=[.20,.30,.40], left=[.45,.55,.65], deep=[.70,.80,.90], extreme=[.85,.95,1.0], right=[.75,.90,1.0], trend=[.75,.90,1.0]),
    'B': dict(base=[.15,.25,.35], left=[.40,.50,.60], deep=[.65,.75,.85], extreme=[.80,.90,1.0], right=[.70,.85,1.0], trend=[.70,.85,1.0]),
    'C': dict(base=[.10,.20,.30], left=[.30,.40,.50], deep=[.50,.65,.80], extreme=[.65,.80,.95], right=[.60,.75,.90], trend=[.60,.75,.90]),
}


def dl(ticker, start='2016-01-01', end='2026-09-02'):
    last=None
    for i in range(5):
        try:
            d=yf.Ticker(ticker).history(start=start,end=end,auto_adjust=False,actions=True,repair=False,timeout=60)
            if d is None or len(d)<100: raise RuntimeError(f'short history {len(d) if d is not None else 0}')
            d.index=pd.to_datetime(d.index).tz_localize(None)
            d=d[~d.index.duplicated(keep='last')].sort_index()
            for c in ['Open','High','Low','Close','Volume']:
                d[c]=pd.to_numeric(d[c],errors='coerce')
            if 'Dividends' not in d: d['Dividends']=0.0
            return d.dropna(subset=['Open','High','Low','Close'])
        except Exception as e:
            last=e; time.sleep(3*(i+1))
    raise RuntimeError(f'{ticker} failed: {last}')


def total_return_index(d):
    c=d.Close.astype(float); div=pd.to_numeric(d.get('Dividends',0),errors='coerce').fillna(0.0)
    r=(c+div)/c.shift(1)
    r.iloc[0]=1.0
    return r.fillna(1.0).cumprod()


def usd_twd(index):
    fx=dl('TWD=X','2016-01-01','2026-09-02').Close.astype(float)
    fx=fx.reindex(fx.index.union(index)).sort_index().ffill().reindex(index)
    return fx


def fred_dtb3():
    u='https://fred.stlouisfed.org/graph/fredgraph.csv?id=DTB3&cosd=2018-01-01&coed=2026-08-31'
    r=requests.get(u,timeout=60,headers={'User-Agent':'Mozilla/5.0'}); r.raise_for_status()
    from io import StringIO
    z=pd.read_csv(StringIO(r.text)); z.columns=['date','rate']; z['date']=pd.to_datetime(z.date); z['rate']=pd.to_numeric(z.rate,errors='coerce')
    return z.set_index('date').rate


def parking_tr_twd(index):
    # Before SGOV inception: point-in-time 3M T-bill rate accrual proxy.
    # From SGOV inception onward: SGOV price+distribution total-return path.
    idx=pd.DatetimeIndex(index).sort_values()
    rate=fred_dtb3().reindex(pd.date_range(idx.min(),idx.max(),freq='D')).ffill()
    daily=(1+rate/100.0)**(1/365.0)
    tb=daily.cumprod(); tb=tb/tb.iloc[0]
    tb=tb.reindex(idx).ffill()
    sg=dl('SGOV','2020-05-26','2026-09-02')
    sgtr=total_return_index(sg)
    fx=usd_twd(idx)
    pre=(tb * fx / fx.iloc[0]).copy()
    out=pre.copy()
    cut=pd.Timestamp('2020-05-26')
    if (idx>=cut).any():
        sgtr=sgtr.reindex(sgtr.index.union(idx)).sort_index().ffill().reindex(idx)
        first_idx=idx[idx>=cut][0]
        base=float(pre.loc[first_idx])
        sgrel=sgtr/float(sgtr.loc[first_idx])
        fxrel=fx/float(fx.loc[first_idx])
        out.loc[idx>=first_idx]=base*(sgrel*fxrel).loc[idx>=first_idx]
    return out.ffill().bfill()


def make_base(d, macro):
    x=add_indicators(d)
    for n in [5,10,60]: x[f'MA{n}']=x.Close.rolling(n).mean()
    wb=add_indicators(period_bars(d,'W-FRI'),52); mb=add_indicators(period_bars(d,'M'),36)
    for z in [wb,mb]:
        for n in [5,10,60]: z[f'MA{n}']=z.Close.rolling(n).mean()
    x=asof_cols(x,wb,'W_',['Close','MA20','MA50','MA200','TD_HIGH','TD_LOW','K','D','MACD_HIST','RSI','EMV','Volume'])
    x=asof_cols(x,mb,'M_',['Close','MA20','MA50','MA200','TD_HIGH','TD_LOW','K','D','MACD_HIST','RSI','EMV','Volume'])
    mac=macro.reindex(macro.index.union(x.index)).sort_index().ffill().reindex(x.index)
    for c in ['BAMLH0A0HYM2','VIX','MOVE','DGS2','DGS10','DGS30','DFF','CPI_YOY','CORE_CPI_YOY','MACRO_VETO','MACRO_HEADWIND','MACRO_STRESS_SCORE']:
        x['X_'+c]=mac[c] if c in mac else np.nan
    lo=x.Low; hi=x.High
    sl=(lo.shift(2)<lo.shift(4))&(lo.shift(2)<lo.shift(3))&(lo.shift(2)<lo.shift(1))&(lo.shift(2)<lo)
    sh=(hi.shift(2)>hi.shift(4))&(hi.shift(2)>hi.shift(3))&(hi.shift(2)>hi.shift(1))&(hi.shift(2)>hi)
    x['CONF_SWING_LOW']=lo.shift(2).where(sl).ffill(); x['CONF_SWING_HIGH']=hi.shift(2).where(sh).ffill()
    return x


def price_tier(x):
    dd=x.DD252
    tier=pd.Series('BASE',index=x.index,dtype='object')
    tier[dd<=-.05]='LEFT'; tier[dd<=-.10]='DEEP'; tier[dd<=-.15]='EXTREME'
    return tier


def add_v82_phase1_state(asset,x,aux):
    # Use the existing validated V80 macro/runaway machinery only as the safety/structure scaffold.
    # V82 deployment semantics are applied below; this file is explicitly Phase-1, not final rule parity.
    if asset not in V80_PARAM:
        # SOXX uses QQQ-like thresholds only for the temporary phase-1 safety scaffold.
        V80_PARAM[asset]=dict(dd=-.10,left_frac=.175,right_frac=.50,trend_frac=.325,left_decel=3,right_count=4,trim=.15)
    y=v80_state(asset,x,aux)
    y['V82_TIER']=price_tier(y)
    hard=y.HARD_VETO.fillna(False).astype(bool)
    rd=y.RUNAWAY_DOWN.fillna(False).astype(bool) | y.RISK_MODE.ne('NONE')
    overheat=(y.DD252>-.03)&((y.K>85)|(y.RSI>75))&(~y.RUNAWAY_UP.fillna(False))
    y['V82_SAFE']=(~hard)&(~rd)
    y['V82_BASE_OK']=y.V82_SAFE&(~overheat)
    y['V82_RIGHT']=y.STATE.eq('RIGHT_ADD')&y.V82_SAFE
    y['V82_TREND']=y.RUNAWAY_UP.fillna(False).astype(bool)&y.V82_SAFE
    y['V82_TRIM']=y.STATE.eq('TECH_TRIM')
    y['V82_RISK']=rd|hard
    return y


def xirr(cfs):
    dates=[pd.Timestamp(d) for d,_ in cfs]; vals=np.array([v for _,v in cfs],float); d0=dates[0]
    yrs=np.array([(d-d0).days/365.25 for d in dates])
    def f(r): return np.sum(vals/((1+r)**yrs))
    lo,hi=-.9999,10.0; flo,fhi=f(lo),f(hi)
    if np.sign(flo)==np.sign(fhi): return np.nan
    for _ in range(200):
        mid=(lo+hi)/2; fm=f(mid)
        if abs(fm)<1e-7: return mid
        if np.sign(fm)==np.sign(flo): lo=mid; flo=fm
        else: hi=mid
    return (lo+hi)/2


def mdd_unitized(nav, flows):
    # Unitize NAV so annual contributions do not mechanically hide drawdowns.
    units=1.0; unit=1.0; prev_asset=None; out=[]
    flowmap={pd.Timestamp(k):v for k,v in flows.items()}
    for dt,asset in nav.items():
        if prev_asset is None:
            units=asset; unit=1.0; prev_asset=asset; out.append(unit); continue
        fl=flowmap.get(pd.Timestamp(dt),0.0)
        before=asset-fl
        if prev_asset>0: unit*=before/prev_asset
        if fl!=0: units += fl/unit
        prev_asset=asset
        out.append(unit)
    s=pd.Series(out,index=nav.index)
    return float((s/s.cummax()-1).min()), s


def simulate(asset,y,tr_twd,park_twd,params,strategy):
    dates=y.index[(y.index>=START)&(y.index<=END)]
    if len(dates)==0: return None
    tr=tr_twd.reindex(dates).ffill().bfill(); pk=park_twd.reindex(dates).ffill().bfill()
    stock_units=0.0; park_units=0.0; nav=[]; exp=[]; flows={}; cfs=[]; yr_done=set(); dca_seen=set()
    for i,dt in enumerate(dates):
        # annual external contribution on first observed trading date of each year
        if dt.year in YEARS and dt.year not in yr_done:
            amt=ANNUAL_CONTRIBUTION; park_units += amt/float(pk.loc[dt]); flows[dt]=flows.get(dt,0)+amt; cfs.append((dt,-amt)); yr_done.add(dt.year)
        total=stock_units*float(tr.loc[dt])+park_units*float(pk.loc[dt])
        if total<=0: continue
        cur=(stock_units*float(tr.loc[dt]))/total
        target=cur
        row=y.loc[dt]
        if strategy=='BUY_HOLD': target=1.0
        elif strategy=='DCA':
            key=(dt.year,dt.month)
            if key not in dca_seen:
                # Approx. 12 equal monthly tranches per annual contribution, but never force selling prior stock.
                target=min(1.0,cur+(ANNUAL_CONTRIBUTION/12.0)/total); dca_seen.add(key)
        elif strategy.startswith('V82'):
            if bool(row.V82_RISK): target=max(0.0,cur-.25)
            elif bool(row.V82_TRIM): target=max(0.0,cur-.10)
            elif bool(row.V82_TREND): target=max(cur,params['trend'])
            elif bool(row.V82_RIGHT): target=max(cur,params['right'])
            elif bool(row.V82_BASE_OK):
                tier=row.V82_TIER
                target=max(cur,params['base'])
                if tier=='LEFT': target=max(target,params['left'])
                elif tier=='DEEP': target=max(target,params['deep'])
                elif tier=='EXTREME': target=max(target,params['extreme'])
        delta=total*target-stock_units*float(tr.loc[dt])
        if abs(delta)>1:
            if delta>0:
                buy=min(delta,park_units*float(pk.loc[dt])); stock_units+=buy/float(tr.loc[dt]); park_units-=buy/float(pk.loc[dt])
            else:
                sell=min(-delta,stock_units*float(tr.loc[dt])); stock_units-=sell/float(tr.loc[dt]); park_units+=sell/float(pk.loc[dt])
        total=stock_units*float(tr.loc[dt])+park_units*float(pk.loc[dt]); nav.append((dt,total)); exp.append((dt,(stock_units*float(tr.loc[dt]))/total if total else 0))
    nav=pd.Series(dict(nav)).sort_index(); exposure=pd.Series(dict(exp)).sort_index()
    if len(nav)==0:return None
    cfs.append((nav.index[-1],float(nav.iloc[-1])))
    mdd,unit=mdd_unitized(nav,flows)
    cost=len(yr_done)*ANNUAL_CONTRIBUTION; final=float(nav.iloc[-1]); total_return=final/cost-1
    return dict(final_asset=final,total_cost=cost,total_profit=final-cost,total_return=total_return,xirr=xirr(cfs),max_drawdown=mdd,avg_stock_exposure=float(exposure.mean()),avg_parking_exposure=float(1-exposure.mean()))


def grid_iter(cls):
    g=GRID[cls]
    for b in g['base']:
      for l in g['left']:
       for d in g['deep']:
        for e in g['extreme']:
         for r in g['right']:
          for t in g['trend']:
           if b<=l<=d<=e and b<=r and b<=t:
            yield dict(base=b,left=l,deep=d,extreme=e,right=r,trend=t)


def main():
    macro=build_macro_v80(); macro.to_csv(OUT/'macro.csv')
    raw={k:dl(t) for k,t in AUX.items()}; results=[]; grid_rows=[]
    for asset,(ticker,ccy,cls) in ASSETS.items():
        d=dl(ticker)
        x=make_base(d,macro); aux=align_aux(raw,x.index); y=add_v82_phase1_state(asset,x,aux)
        tr=total_return_index(d).reindex(x.index).ffill()
        if ccy=='USD': tr=tr*(usd_twd(x.index)/usd_twd(x.index).iloc[0])
        park=parking_tr_twd(x.index)
        # Fixed baselines
        dummy=dict(base=0,left=0,deep=0,extreme=0,right=0,trend=0)
        for strat in ['BUY_HOLD','DCA']:
            m=simulate(asset,y,tr,park,dummy,strat); m.update(asset=asset,strategy=strat,cls=cls); results.append(m)
        # V82 + SGOV/T-bill proxy grid
        best=None
        for p in grid_iter(cls):
            m=simulate(asset,y,tr,park,p,'V82_SGOV');
            score=(m['xirr'] if np.isfinite(m['xirr']) else -9) + 0.35*m['max_drawdown']
            row={**m,**p,'asset':asset,'strategy':'V82_SGOV','cls':cls,'score':score}; grid_rows.append(row)
            if best is None or score>best['score']: best=row
        results.append(best)
        print(asset,'best',best)
    pd.DataFrame(results).to_csv(OUT/'phase1_summary.csv',index=False)
    pd.DataFrame(grid_rows).to_csv(OUT/'phase1_grid.csv',index=False)
    print('\nPHASE1 SUMMARY')
    print(pd.DataFrame(results)[['asset','strategy','total_cost','final_asset','total_return','xirr','max_drawdown','avg_stock_exposure','avg_parking_exposure']].to_string(index=False))

if __name__=='__main__': main()
