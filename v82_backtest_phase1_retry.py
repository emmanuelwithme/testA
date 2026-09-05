import functools
import numpy as np
import pandas as pd
import v82_backtest_phase1 as b

@functools.lru_cache(maxsize=1)
def irx_proxy():
    # Pull enough history to cover the warm-up used by long-history assets.
    d=b.dl('^IRX','2015-01-01','2026-09-02')
    s=pd.to_numeric(d.Close,errors='coerce').dropna().sort_index()
    if s.empty:
        raise RuntimeError('IRX proxy has no valid observations')
    s.name='rate'
    return s


def parking_tr_twd_robust(index):
    # Pre-SGOV: point-in-time 13-week T-bill yield accrual proxy.
    # SGOV: switch only on/after the first ACTUAL valid SGOV observation.
    # Never fabricate SGOV history on its inception date if the market data source has no valid bar that day.
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
    tb=daily.cumprod()
    first_tb=tb.dropna().iloc[0]
    tb=tb/first_tb
    tb=tb.reindex(idx).ffill().bfill()

    sg=b.dl('SGOV','2020-05-26','2026-09-02')
    sgtr=b.total_return_index(sg).replace([np.inf,-np.inf],np.nan).dropna().sort_index()
    fx=b.usd_twd(idx)
    if fx.isna().any() or not np.isfinite(fx).all():
        raise RuntimeError(f'USD/TWD contains invalid values for requested period: {int(fx.isna().sum())} NaN')

    pre=(tb * fx / float(fx.iloc[0])).copy()
    out=pre.copy()
    cut=pd.Timestamp('2020-05-26')

    valid_sg=sgtr.loc[sgtr.index>=cut]
    if valid_sg.empty:
        raise RuntimeError('SGOV has no valid total-return observation after inception boundary')
    sg_first=pd.Timestamp(valid_sg.index[0])

    eligible=idx[idx>=sg_first]
    if len(eligible):
        first_idx=pd.Timestamp(eligible[0])
        # Align SGOV only backward from observations that actually exist; do not backfill before first SGOV bar.
        aligned=sgtr.reindex(sgtr.index.union(idx)).sort_index().ffill().reindex(idx)
        if pd.isna(aligned.loc[first_idx]):
            raise RuntimeError(f'SGOV total-return index still missing at first valid strategy transition {first_idx}; source first={sg_first}')
        base=float(pre.loc[first_idx])
        sgrel=aligned/float(aligned.loc[first_idx])
        fxrel=fx/float(fx.loc[first_idx])
        out.loc[idx>=first_idx]=base*(sgrel*fxrel).loc[idx>=first_idx]

    out=out.ffill().bfill()
    if out.isna().any() or not np.isfinite(out).all():
        raise RuntimeError('parking total-return series contains invalid values')
    return out

# Replace the fragile direct FRED call and parking normalization.
b.fred_dtb3=irx_proxy
b.parking_tr_twd=parking_tr_twd_robust

# Capture state counts without changing the underlying V82 Phase-1 strategy logic.
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
        'asset':asset,
        'start_date':str(z.index.min().date()) if len(z) else '',
        'end_date':str(z.index.max().date()) if len(z) else '',
        'rows':int(len(z)),
        'raw_runaway_up':int(z.RUNAWAY_UP.fillna(False).astype(bool).sum()),
        'raw_runaway_down':int(z.RUNAWAY_DOWN.fillna(False).astype(bool).sum()),
        'raw_v82_base_ok':int(z.V82_BASE_OK.fillna(False).astype(bool).sum()),
        'raw_v82_right':int(z.V82_RIGHT.fillna(False).astype(bool).sum()),
        'raw_v82_trend':int(z.V82_TREND.fillna(False).astype(bool).sum()),
        'raw_v82_trim':int(z.V82_TRIM.fillna(False).astype(bool).sum()),
        'raw_v82_risk':int(z.V82_RISK.fillna(False).astype(bool).sum()),
        'exec_risk':int(risk.sum()),
        'exec_trim':int(trim.sum()),
        'exec_trend':int(trend.sum()),
        'exec_right':int(right.sum()),
        'exec_base':int((base_ok & tier.eq('BASE')).sum()),
        'exec_left':int((base_ok & tier.eq('LEFT')).sum()),
        'exec_deep':int((base_ok & tier.eq('DEEP')).sum()),
        'exec_extreme':int((base_ok & tier.eq('EXTREME')).sum()),
    })
    return y

b.add_v82_phase1_state=add_v82_phase1_state_audited

if __name__=='__main__':
    b.main()
    audit=pd.DataFrame(_state_audit)
    audit.to_csv(b.OUT/'state_audit.csv',index=False)
    print('\nV82 STATE AUDIT')
    print(audit.to_string(index=False))
