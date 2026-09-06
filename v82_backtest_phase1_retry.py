import functools
import numpy as np
import pandas as pd
import v82_backtest_phase1 as b

# V82 formal retry runner.
# Reliable shared OHLCV/macro plumbing may be reused, but ALL stock/ETF state
# classification and deployment execution below are V82-native. No v80_state()
# or V80 deployment parameters are used in the executed path.

@functools.lru_cache(maxsize=1)
def irx_proxy():
    d=b.dl('^IRX','2015-01-01','2026-09-02')
    s=pd.to_numeric(d.Close,errors='coerce').dropna().sort_index()
    if s.empty:
        raise RuntimeError('IRX proxy has no valid observations')
    s.name='rate'
    return s


def align_aux_native(raw,index):
    out={}
    for k,d in raw.items():
        z=pd.DataFrame(index=d.index)
        z['C']=pd.to_numeric(d.Close,errors='coerce')
        z['M20']=z.C.rolling(20).mean(); z['M50']=z.C.rolling(50).mean()
        z['R5']=z.C.pct_change(5); z['R20']=z.C.pct_change(20)
        out[k]=z.reindex(z.index.union(index)).sort_index().ffill().reindex(index)
    return out


def parking_tr_twd_robust(index):
    # Pre-SGOV: point-in-time 13-week T-bill yield accrual proxy.
    # SGOV: switch only on/after the first ACTUAL valid SGOV observation.
    idx=pd.DatetimeIndex(index).sort_values()
    cal=pd.date_range(idx.min(),idx.max(),freq='D')
    rate=irx_proxy().reindex(cal).ffill()
    if rate.isna().any():
        first_valid=rate.first_valid_index()
        if first_valid is None:
            raise RuntimeError('IRX proxy cannot cover requested period')
        if rate.loc[first_valid:].isna().any():
            raise RuntimeError('IRX proxy contains internal gaps after forward fill')
        rate.loc[:first_valid]=rate.loc[first_valid]
    daily=(1+rate/100.0)**(1/365.0)
    tb=daily.cumprod(); tb=tb/tb.dropna().iloc[0]
    tb=tb.reindex(idx).ffill().bfill()

    sg=b.dl('SGOV','2020-05-26','2026-09-02')
    sgtr=b.total_return_index(sg).replace([np.inf,-np.inf],np.nan).dropna().sort_index()
    fx=b.usd_twd(idx)
    if fx.isna().any() or not np.isfinite(fx).all():
        raise RuntimeError(f'USD/TWD contains invalid values for requested period: {int(fx.isna().sum())} NaN')

    pre=(tb * fx / float(fx.iloc[0])).copy(); out=pre.copy()
    cut=pd.Timestamp('2020-05-26'); valid_sg=sgtr.loc[sgtr.index>=cut]
    if valid_sg.empty:
        raise RuntimeError('SGOV has no valid total-return observation after inception boundary')
    sg_first=pd.Timestamp(valid_sg.index[0]); eligible=idx[idx>=sg_first]
    if len(eligible):
        first_idx=pd.Timestamp(eligible[0])
        aligned=sgtr.reindex(sgtr.index.union(idx)).sort_index().ffill().reindex(idx)
        if pd.isna(aligned.loc[first_idx]):
            raise RuntimeError(f'SGOV total-return index missing at first valid transition {first_idx}; source first={sg_first}')
        base=float(pre.loc[first_idx]); sgrel=aligned/float(aligned.loc[first_idx]); fxrel=fx/float(fx.loc[first_idx])
        out.loc[idx>=first_idx]=base*(sgrel*fxrel).loc[idx>=first_idx]
    out=out.ffill().bfill()
    if out.isna().any() or not np.isfinite(out).all():
        raise RuntimeError('parking total-return series contains invalid values')
    return out


def v82_native_state(asset,x,aux):
    """Implement the V82 seven-class hard matrix directly from V82.md.

    Price tiers remain Phase-1 calibration candidates; they are NOT declared
    permanent V82 price-map thresholds. Fundamental/event point-in-time gates
    that cannot be reconstructed reliably are not fabricated.
    """
    y=x.copy(); c=y.Close
    y['V82_TIER']=b.price_tier(y)

    # Hard Gate data available in this historical engine: macro/credit/liquidity
    # veto plus severe weekly+monthly structural break. Missing historical
    # issuer fundamental/event gates are audited as a formal-parity limitation.
    macro_hard=y.X_MACRO_VETO.fillna(False).astype(bool)
    weekly_bear=(y.W_Close<y.W_MA20)&(y.W_MACD_HIST<0)
    monthly_bear=(y.M_Close<y.M_MA20)&(y.M_MACD_HIST<0)
    ma200_down=y.MA200.diff(20)<0
    structural_major=weekly_bear&monthly_bear&(c<y.MA200)&ma200_down
    hard=macro_hard|structural_major

    # Runaway Up: structure A >=1 plus strength B >=3, exactly following V82.
    prior_swing_high=y.CONF_SWING_HIGH.shift(1)
    new20=c>=c.rolling(20,min_periods=20).max()
    swing_break=c>prior_swing_high
    hhhl=(y.High.rolling(10).max()>y.High.shift(10).rolling(10).max()) & (y.Low.rolling(10).min()>y.Low.shift(10).rolling(10).min())
    structure_up=new20|swing_break|hhhl
    kd_hot=(y.K>70)&(y.D>65)&(y.K>=y.K.shift(1)-3)
    macd_expand=(y.MACD_HIST>0)&(y.MACD_HIST>y.MACD_HIST.shift(1))
    ma_stack=(y.MA5>y.MA10)&(y.MA10>y.MA20)
    emv_pos=(y.EMV>0)|(y.EMV>y.EMV.shift(3))
    vol_healthy=(y.VOL_R20>=0.8)&(y.VOL_R20<=2.5)&(c>=c.shift(1))
    td9_continue=(y.TD_HIGH>=8)&(c>=c.shift(1))
    rsi_no_fail=(y.RSI>=60)&(y.RSI>=y.RSI.shift(3)-5)
    strength_count=pd.concat([kd_hot,macd_expand,ma_stack,emv_pos,vol_healthy,td9_continue,rsi_no_fail],axis=1).sum(axis=1)
    runaway_up=structure_up&(strength_count>=3)&(~hard)

    # Runaway Down: price-structure break A >=1 plus bearish acceleration B >=2.
    prior_swing_low=y.CONF_SWING_LOW.shift(1)
    new20low=c<=c.rolling(20,min_periods=20).min()
    swing_low_break=c<prior_swing_low
    support_break=((c<y.MA50)&(c.shift(1)>=y.MA50.shift(1)))|((c<y.MA200)&(c.shift(1)>=y.MA200.shift(1)))
    structure_down=new20low|swing_low_break|support_break
    macd_dn=(y.MACD_HIST<0)&(y.MACD_HIST<y.MACD_HIST.shift(1))
    kd_dn=(y.K<30)&(y.K<y.D)&(y.K<=y.K.shift(1))
    emv_dn=y.EMV<y.EMV.shift(3)
    rsi_dn=y.RSI<y.RSI.shift(3)
    price_vol_dn=(c<c.shift(1))&(y.VOL_R20>1.2)
    atr_expand=y.ATR_PCT>y.ATR_PCT.rolling(60,min_periods=20).median()*1.25
    speed_dn=c.pct_change(5)<c.shift(5).pct_change(5)
    down_count=pd.concat([macd_dn,kd_dn,emv_dn,rsi_dn,price_vol_dn,atr_expand,speed_dn],axis=1).sum(axis=1)
    runaway_down=structure_down&(down_count>=2)

    # Right Confirmation: >=3 independent confirmations, safe, non-runaway-down.
    higher_low=y.Low.rolling(3).min()>y.Low.shift(3).rolling(3).min()
    kd_cross=(y.K>y.D)&(y.K.shift(1)<=y.D.shift(1))
    hist_improve=(y.MACD_HIST>y.MACD_HIST.shift(1))
    dif_up=y.DIF>y.DIF.shift(1)
    emv_up=(y.EMV>0)|(y.EMV>y.EMV.shift(3))
    rsi_up=(y.RSI>=50)|(y.RSI>y.RSI.shift(3))
    ma20_regain=(c>y.MA20)&(c.shift(1)<=y.MA20.shift(1))
    upvol=(c>c.shift(1))&(y.VOL_R20>1.05)
    pressure_break=c>c.shift(1).rolling(20,min_periods=20).max()
    right_count=pd.concat([higher_low,kd_cross,hist_improve,dif_up,emv_up,rsi_up,ma20_regain,upvol,pressure_break],axis=1).sum(axis=1)
    right=(right_count>=3)&(~hard)&(~runaway_down)&(~runaway_up)

    # Technical trim: >=3 weakening confirmations; never trim solely because TD/RSI is high.
    td_high=y.TD_HIGH>=8
    kd_cross_dn=(y.K<y.D)&(y.K.shift(1)>=y.D.shift(1))
    macd_fall=(y.MACD_HIST>0)&(y.MACD_HIST<y.MACD_HIST.shift(1))&(y.MACD_HIST.shift(1)<y.MACD_HIST.shift(2))
    emv_weak=y.EMV<y.EMV.shift(3)
    rsi_weak=(y.RSI>65)&(y.RSI<y.RSI.shift(3))
    stall=(c<=c.shift(1))&(y.VOL_R20>1.2)
    ma_break=((c<y.MA10)&(c.shift(1)>=y.MA10.shift(1)))|((c<y.MA20)&(c.shift(1)>=y.MA20.shift(1)))
    failed_high=(c<y.CONF_SWING_HIGH)&(y.High.shift(1)>=y.CONF_SWING_HIGH.shift(1))
    weak_count=pd.concat([td_high,kd_cross_dn,macd_fall,emv_weak,rsi_weak,stall,ma_break,failed_high],axis=1).sum(axis=1)
    trim=(weak_count>=3)&(~runaway_up)&(~hard)&(~runaway_down)

    # Base/Left: price attractiveness is deployment intensity; technical weakness
    # cannot veto the first long-term tranche unless Runaway Down/Hard Gate fires.
    overheat=(y.DD252>-.03)&((y.K>90)|(y.RSI>78))&(~runaway_up)
    safe=(~hard)&(~runaway_down)
    base_ok=safe&(~overheat)&(~runaway_up)&(~right)&(~trim)

    y['HARD_VETO']=hard
    y['RUNAWAY_UP']=runaway_up
    y['RUNAWAY_DOWN']=runaway_down
    y['STRENGTH_COUNT']=strength_count
    y['DOWN_COUNT']=down_count
    y['RIGHT_COUNT']=right_count
    y['WEAK_COUNT']=weak_count
    y['V82_SAFE']=safe
    y['V82_BASE_OK']=base_ok
    y['V82_RIGHT']=right
    y['V82_TREND']=runaway_up&safe
    y['V82_TRIM']=trim
    y['V82_RISK']=hard
    y['V82_ENGINE']='V82_NATIVE_HARD_MATRIX'
    return y


def performance_metrics(unit):
    u=unit.dropna()
    if len(u)<2:
        return dict(twr_cagr=np.nan,sortino=np.nan,calmar=np.nan,recovery_days=np.nan)
    r=u.pct_change().dropna(); years=max((u.index[-1]-u.index[0]).days/365.25,1/365.25)
    cagr=(float(u.iloc[-1]/u.iloc[0])**(1/years)-1) if u.iloc[0]>0 else np.nan
    neg=r[r<0]
    downside=float(neg.std(ddof=0)*np.sqrt(252)) if len(neg)>1 else np.nan
    sortino=float(r.mean()*252/downside) if downside and np.isfinite(downside) and downside>0 else np.nan
    dd=u/u.cummax()-1; mdd=float(dd.min())
    calmar=float(cagr/abs(mdd)) if mdd<0 else np.nan
    # Longest time from a prior peak until a new peak (calendar days).
    peak=u.iloc[0]; peak_date=u.index[0]; max_rec=0
    for dt,val in u.items():
        if val>=peak:
            max_rec=max(max_rec,(dt-peak_date).days); peak=val; peak_date=dt
    if u.iloc[-1]<peak:
        max_rec=max(max_rec,(u.index[-1]-peak_date).days)
    return dict(twr_cagr=cagr,sortino=sortino,calmar=calmar,recovery_days=float(max_rec))


def simulate_tplus1(asset,y,tr_twd,park_twd,params,strategy):
    """Continuous portfolio simulation with external annual flows and T+1 signal execution.

    Signal formed on close(t) is eligible only on the next observed trading day.
    This removes same-close look-ahead. Explicit open-gap recheck remains a
    separate formal-parity item because this phase uses close-based TR indices.
    """
    dates=y.index[(y.index>=b.START)&(y.index<=b.END)]
    if len(dates)==0: return None
    tr=tr_twd.reindex(dates).ffill().bfill(); pk=park_twd.reindex(dates).ffill().bfill()
    sig=y.shift(1).reindex(dates)  # strict T+1: never execute today's close signal today
    stock_units=0.0; park_units=0.0; nav=[]; exp=[]; flows={}; cfs=[]; yr_done=set(); dca_seen=set()
    for dt in dates:
        if dt.year in b.YEARS and dt.year not in yr_done:
            amt=b.ANNUAL_CONTRIBUTION; park_units += amt/float(pk.loc[dt]); flows[dt]=flows.get(dt,0)+amt; cfs.append((dt,-amt)); yr_done.add(dt.year)
        total=stock_units*float(tr.loc[dt])+park_units*float(pk.loc[dt])
        if total<=0: continue
        cur=(stock_units*float(tr.loc[dt]))/total; target=cur
        if strategy=='BUY_HOLD': target=1.0
        elif strategy=='DCA':
            key=(dt.year,dt.month)
            if key not in dca_seen:
                target=min(1.0,cur+(b.ANNUAL_CONTRIBUTION/12.0)/total); dca_seen.add(key)
        elif strategy.startswith('V82'):
            row=sig.loc[dt]
            if pd.notna(row.get('V82_RISK',np.nan)):
                if bool(row.V82_RISK): target=max(0.0,cur-.25)
                elif bool(row.V82_TRIM): target=max(0.0,cur-.10)
                elif bool(row.V82_TREND): target=max(cur,params['trend'])
                elif bool(row.V82_RIGHT): target=max(cur,params['right'])
                elif bool(row.V82_BASE_OK):
                    tier=row.V82_TIER; target=max(cur,params['base'])
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
    mdd,unit=b.mdd_unitized(nav,flows); perf=performance_metrics(unit)
    cost=len(yr_done)*b.ANNUAL_CONTRIBUTION; final=float(nav.iloc[-1])
    return dict(final_asset=final,total_cost=cost,total_profit=final-cost,total_return=final/cost-1,xirr=b.xirr(cfs),max_drawdown=mdd,avg_stock_exposure=float(exposure.mean()),avg_parking_exposure=float(1-exposure.mean()),**perf)

# Replace fragile data functions, old alignment helper, old state scaffold and same-day execution.
b.fred_dtb3=irx_proxy
b.parking_tr_twd=parking_tr_twd_robust
b.align_aux=align_aux_native
b.add_v82_phase1_state=v82_native_state
b.simulate=simulate_tplus1

# Capture state counts after the V82-native engine.
_state_audit=[]
_original_add_state=b.add_v82_phase1_state

def add_v82_phase1_state_audited(asset,x,aux):
    y=_original_add_state(asset,x,aux)
    z=y.loc[(y.index>=b.START)&(y.index<=b.END)].copy()
    risk=z.V82_RISK.fillna(False).astype(bool)
    trim=z.V82_TRIM.fillna(False).astype(bool) & ~risk
    trend=z.V82_TREND.fillna(False).astype(bool) & ~risk & ~trim
    right=z.V82_RIGHT.fillna(False).astype(bool) & ~risk & ~trim & ~trend
    base_ok=z.V82_BASE_OK.fillna(False).astype(bool) & ~risk & ~trim & ~trend & ~right
    tier=z.V82_TIER.astype(str)
    _state_audit.append({
        'asset':asset,'engine':'V82_NATIVE_HARD_MATRIX','execution':'T+1_CLOSE_PROXY',
        'start_date':str(z.index.min().date()) if len(z) else '',
        'end_date':str(z.index.max().date()) if len(z) else '','rows':int(len(z)),
        'raw_runaway_up':int(z.RUNAWAY_UP.fillna(False).astype(bool).sum()),
        'raw_runaway_down':int(z.RUNAWAY_DOWN.fillna(False).astype(bool).sum()),
        'raw_v82_base_ok':int(z.V82_BASE_OK.fillna(False).astype(bool).sum()),
        'raw_v82_right':int(z.V82_RIGHT.fillna(False).astype(bool).sum()),
        'raw_v82_trend':int(z.V82_TREND.fillna(False).astype(bool).sum()),
        'raw_v82_trim':int(z.V82_TRIM.fillna(False).astype(bool).sum()),
        'raw_v82_risk':int(z.V82_RISK.fillna(False).astype(bool).sum()),
        'exec_risk':int(risk.sum()),'exec_trim':int(trim.sum()),'exec_trend':int(trend.sum()),'exec_right':int(right.sum()),
        'exec_base':int((base_ok & tier.eq('BASE')).sum()),'exec_left':int((base_ok & tier.eq('LEFT')).sum()),
        'exec_deep':int((base_ok & tier.eq('DEEP')).sum()),'exec_extreme':int((base_ok & tier.eq('EXTREME')).sum()),
    })
    return y

b.add_v82_phase1_state=add_v82_phase1_state_audited

if __name__=='__main__':
    b.main()
    audit=pd.DataFrame(_state_audit)
    audit.to_csv(b.OUT/'state_audit.csv',index=False)
    print('\nV82 NATIVE STATE AUDIT')
    print(audit.to_string(index=False))
