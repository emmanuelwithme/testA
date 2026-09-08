from pathlib import Path
from io import StringIO
import time
import numpy as np
import pandas as pd
import requests
import yfinance as yf

import v82_backtest_phase1 as b
import v82_backtest_phase1_retry as r
import v80_macro as vm

# V82 extended-history robustness replay.
# IMPORTANT: deployment parameters are FROZEN from successful Run #8 and are
# NOT re-optimized on 2005-2026 data. This is a fixed-rule robustness test,
# not yet the final IS/OOS or Walk-Forward certification.
START = pd.Timestamp('2005-01-01')
END = pd.Timestamp('2026-08-31')
ANNUAL_CONTRIBUTION = 1_000_000.0
OUT = Path('v82_extended_results')
OUT.mkdir(exist_ok=True)

ASSETS = {
    'QQQ': ('QQQ', 'USD', 'B'),
    'VT': ('VT', 'USD', 'A'),
    '0050': ('0050.TW', 'TWD', 'B'),
    'VWRA': ('VWRA.L', 'USD', 'A'),
    'PPH': ('PPH', 'USD', 'C'),
    'SOXX': ('SOXX', 'USD', 'C'),
}
AUX = {'SOXX':'SOXX','NVDA':'NVDA','TSM':'TSM','2330':'2330.TW','XLV':'XLV'}

# Frozen best candidates from Run #8 (2019-2026 phase-1 calibration artifact).
# They are deliberately NOT re-fit on the extended history.
FROZEN = {
    'QQQ':  dict(base=.15,left=.40,deep=.65,extreme=1.00,right=1.00,trend=1.00),
    'VT':   dict(base=.20,left=.45,deep=.70,extreme=.85,right=1.00,trend=1.00),
    '0050': dict(base=.15,left=.50,deep=.85,extreme=1.00,right=1.00,trend=.85),
    'VWRA': dict(base=.20,left=.65,deep=.70,extreme=.85,right=.90,trend=.90),
    'PPH':  dict(base=.30,left=.50,deep=.80,extreme=.80,right=.60,trend=.60),
    'SOXX': dict(base=.10,left=.30,deep=.80,extreme=.80,right=.90,trend=.90),
}

STRESS_WINDOWS = {
    'GFC_2008': ('2007-10-01','2009-06-30'),
    'COVID_2020': ('2020-02-01','2020-06-30'),
    'RATE_BEAR_2022': ('2022-01-01','2022-12-31'),
}

# No fabricated pre-inception index histories. A proxy is admitted only after
# its exact original Total Return Index source is verified. These remain N/A
# until that source is formally added.
PROXY_STATUS = {
    'QQQ':  ('ACTUAL_COVERS_2005', '', False),
    '0050': ('ACTUAL_COVERS_2005', '', False),
    'SOXX': ('ACTUAL_COVERS_2005', '', False),
    'VT':   ('N/A_PENDING_VERIFIED_ORIGINAL_TOTAL_RETURN_INDEX', 'FTSE Global All Cap Index', None),
    'VWRA': ('N/A_PENDING_VERIFIED_ORIGINAL_TOTAL_RETURN_INDEX', 'FTSE All-World Index', None),
    'PPH':  ('N/A_PENDING_VERIFIED_ORIGINAL_TOTAL_RETURN_INDEX', 'formal benchmark source pending exact verification', None),
}


def dl_long(ticker, start='2004-01-01', end='2026-09-02'):
    last = None
    for i in range(5):
        try:
            d = yf.Ticker(ticker).history(start=start, end=end, auto_adjust=False,
                                          actions=True, repair=False, timeout=60)
            if d is None or len(d) < 20:
                raise RuntimeError(f'short history {len(d) if d is not None else 0}')
            d.index = pd.to_datetime(d.index).tz_localize(None)
            d = d[~d.index.duplicated(keep='last')].sort_index()
            for c in ['Open','High','Low','Close','Volume']:
                d[c] = pd.to_numeric(d[c], errors='coerce')
            if 'Dividends' not in d:
                d['Dividends'] = 0.0
            return d.dropna(subset=['Open','High','Low','Close'])
        except Exception as e:
            last = e
            time.sleep(3*(i+1))
    raise RuntimeError(f'{ticker} failed: {last}')


def usd_twd_long(index):
    fx = dl_long('TWD=X', '2004-01-01', '2026-09-02').Close.astype(float)
    idx = pd.DatetimeIndex(index).sort_values()
    fx = fx.reindex(fx.index.union(idx)).sort_index().ffill().bfill().reindex(idx)
    if fx.isna().any() or not np.isfinite(fx).all():
        raise RuntimeError('USD/TWD long history contains invalid values')
    return fx


def fred_dtb3_long():
    url = ('https://fred.stlouisfed.org/graph/fredgraph.csv?'
           'id=DTB3&cosd=2004-01-01&coed=2026-08-31')
    rr = requests.get(url, timeout=60, headers={'User-Agent':'Mozilla/5.0'})
    rr.raise_for_status()
    z = pd.read_csv(StringIO(rr.text))
    z.columns = ['date','rate']
    z['date'] = pd.to_datetime(z.date, errors='coerce')
    z['rate'] = pd.to_numeric(z.rate, errors='coerce')
    return z.dropna().set_index('date').rate.sort_index()


def parking_long(index):
    idx = pd.DatetimeIndex(index).sort_values()
    cal = pd.date_range(idx.min(), idx.max(), freq='D')
    rate = fred_dtb3_long().reindex(cal).ffill().bfill()
    if rate.isna().any():
        raise RuntimeError('DTB3 cannot cover extended parking period')
    daily = (1 + rate/100.0) ** (1/365.0)
    tb = daily.cumprod()
    tb = tb / float(tb.iloc[0])
    tb = tb.reindex(idx).ffill().bfill()

    fx = usd_twd_long(idx)
    pre = tb * fx / float(fx.iloc[0])
    out = pre.copy()

    sg = dl_long('SGOV', '2020-05-26', '2026-09-02')
    sgtr = b.total_return_index(sg).replace([np.inf,-np.inf], np.nan).dropna().sort_index()
    if not sgtr.empty:
        first_sg = pd.Timestamp(sgtr.index.min())
        eligible = idx[idx >= first_sg]
        if len(eligible):
            first_idx = pd.Timestamp(eligible[0])
            aligned = sgtr.reindex(sgtr.index.union(idx)).sort_index().ffill().reindex(idx)
            base = float(pre.loc[first_idx])
            sgrel = aligned / float(aligned.loc[first_idx])
            fxrel = fx / float(fx.loc[first_idx])
            out.loc[idx >= first_idx] = base * (sgrel * fxrel).loc[idx >= first_idx]
    out = out.ffill().bfill()
    if out.isna().any() or not np.isfinite(out).all():
        raise RuntimeError('extended parking series invalid')
    return out


def unitize(nav, flows):
    unit = 1.0
    prev = None
    vals = []
    flowmap = {pd.Timestamp(k): float(v) for k,v in flows.items()}
    for dt, asset in nav.items():
        if prev is None:
            prev = float(asset)
            vals.append(unit)
            continue
        fl = flowmap.get(pd.Timestamp(dt), 0.0)
        before = float(asset) - fl
        if prev > 0:
            unit *= before / prev
        prev = float(asset)
        vals.append(unit)
    return pd.Series(vals, index=nav.index, dtype=float)


def simulate_with_series(y, tr_twd, park_twd, params, strategy):
    dates = y.index[(y.index >= START) & (y.index <= END)]
    if len(dates) == 0:
        return None
    tr = tr_twd.reindex(dates).ffill().bfill()
    pk = park_twd.reindex(dates).ffill().bfill()
    sig = y.shift(1).reindex(dates)  # strict T+1

    stock_units = 0.0
    park_units = 0.0
    nav = []
    exp = []
    flows = {}
    cfs = []
    yr_done = set()
    dca_seen = set()

    for dt in dates:
        if dt.year not in yr_done:
            amt = ANNUAL_CONTRIBUTION
            park_units += amt / float(pk.loc[dt])
            flows[dt] = flows.get(dt, 0.0) + amt
            cfs.append((dt, -amt))
            yr_done.add(dt.year)

        total = stock_units * float(tr.loc[dt]) + park_units * float(pk.loc[dt])
        if total <= 0:
            continue
        cur = stock_units * float(tr.loc[dt]) / total
        target = cur

        if strategy == 'BUY_HOLD':
            target = 1.0
        elif strategy == 'DCA':
            key = (dt.year, dt.month)
            if key not in dca_seen:
                target = min(1.0, cur + (ANNUAL_CONTRIBUTION/12.0)/total)
                dca_seen.add(key)
        elif strategy == 'V82_FIXED_RUN8':
            row = sig.loc[dt]
            if pd.notna(row.get('V82_RISK', np.nan)):
                if bool(row.V82_RISK):
                    target = max(0.0, cur - .25)
                elif bool(row.V82_TRIM):
                    target = max(0.0, cur - .10)
                elif bool(row.V82_TREND):
                    target = max(cur, params['trend'])
                elif bool(row.V82_RIGHT):
                    target = max(cur, params['right'])
                elif bool(row.V82_BASE_OK):
                    target = max(cur, params['base'])
                    tier = str(row.V82_TIER)
                    if tier == 'LEFT':
                        target = max(target, params['left'])
                    elif tier == 'DEEP':
                        target = max(target, params['deep'])
                    elif tier == 'EXTREME':
                        target = max(target, params['extreme'])

        delta = total * target - stock_units * float(tr.loc[dt])
        if abs(delta) > 1.0:
            if delta > 0:
                buy = min(delta, park_units * float(pk.loc[dt]))
                stock_units += buy / float(tr.loc[dt])
                park_units -= buy / float(pk.loc[dt])
            else:
                sell = min(-delta, stock_units * float(tr.loc[dt]))
                stock_units -= sell / float(tr.loc[dt])
                park_units += sell / float(pk.loc[dt])

        total = stock_units * float(tr.loc[dt]) + park_units * float(pk.loc[dt])
        nav.append((dt, total))
        exp.append((dt, stock_units * float(tr.loc[dt]) / total if total else 0.0))

    nav = pd.Series(dict(nav)).sort_index()
    exposure = pd.Series(dict(exp)).sort_index()
    if nav.empty:
        return None

    cfs.append((nav.index[-1], float(nav.iloc[-1])))
    unit = unitize(nav, flows)
    perf = r.performance_metrics(unit)
    cost = len(yr_done) * ANNUAL_CONTRIBUTION
    final = float(nav.iloc[-1])
    summary = dict(
        total_cost=cost,
        final_asset=final,
        total_profit=final-cost,
        total_return=final/cost-1,
        xirr=b.xirr(cfs),
        max_drawdown=float((unit/unit.cummax()-1).min()),
        avg_stock_exposure=float(exposure.mean()),
        avg_parking_exposure=float(1-exposure.mean()),
        **perf,
    )
    return summary, nav, unit, exposure


def audit_state(asset, y):
    z = y.loc[(y.index >= START) & (y.index <= END)].copy()
    risk = z.V82_RISK.fillna(False).astype(bool)
    trim = z.V82_TRIM.fillna(False).astype(bool) & ~risk
    trend = z.V82_TREND.fillna(False).astype(bool) & ~risk & ~trim
    right = z.V82_RIGHT.fillna(False).astype(bool) & ~risk & ~trim & ~trend
    base_ok = z.V82_BASE_OK.fillna(False).astype(bool) & ~risk & ~trim & ~trend & ~right
    tier = z.V82_TIER.astype(str)
    return {
        'asset': asset,
        'rows': int(len(z)),
        'raw_runaway_up': int(z.RUNAWAY_UP.fillna(False).astype(bool).sum()),
        'raw_runaway_down': int(z.RUNAWAY_DOWN.fillna(False).astype(bool).sum()),
        'exec_risk': int(risk.sum()),
        'exec_trim': int(trim.sum()),
        'exec_trend': int(trend.sum()),
        'exec_right': int(right.sum()),
        'exec_base': int((base_ok & tier.eq('BASE')).sum()),
        'exec_left': int((base_ok & tier.eq('LEFT')).sum()),
        'exec_deep': int((base_ok & tier.eq('DEEP')).sum()),
        'exec_extreme': int((base_ok & tier.eq('EXTREME')).sum()),
    }


def stress_rows(asset, strategy, unit):
    out = []
    for name, (s, e) in STRESS_WINDOWS.items():
        q = unit.loc[(unit.index >= pd.Timestamp(s)) & (unit.index <= pd.Timestamp(e))]
        if len(q) < 2:
            out.append({'asset':asset,'strategy':strategy,'window':name,'start':s,'end':e,
                        'available':False,'period_return':np.nan,'max_drawdown':np.nan})
            continue
        out.append({'asset':asset,'strategy':strategy,'window':name,'start':s,'end':e,
                    'available':True,'period_return':float(q.iloc[-1]/q.iloc[0]-1),
                    'max_drawdown':float((q/q.cummax()-1).min())})
    return out


def main():
    # Extend macro/yahoo date range before building the historical macro frame.
    vm.START = '2004-01-01'
    vm.END = '2026-08-31'
    macro = vm.build_macro_v80()
    macro.to_csv(OUT/'extended_macro.csv')

    raw_aux = {}
    for k,t in AUX.items():
        try:
            raw_aux[k] = dl_long(t)
        except Exception as exc:
            print('WARN AUX', k, exc)

    summary_rows = []
    audit_rows = []
    boundary_rows = []
    stress = []

    # Ensure imported V82 simulator helpers see the extended boundaries.
    b.START = START
    b.END = END
    b.YEARS = list(range(START.year, END.year+1))
    b.ANNUAL_CONTRIBUTION = ANNUAL_CONTRIBUTION

    for asset, (ticker, ccy, cls) in ASSETS.items():
        print('\n=== EXTENDED ACTUAL ETF', asset, ticker, '===')
        d = dl_long(ticker)
        actual_first = pd.Timestamp(d.index.min())
        actual_last = pd.Timestamp(d.index.max())
        x = b.make_base(d, macro)
        aux = r.align_aux_native(raw_aux, x.index)
        y = r.v82_native_state(asset, x, aux)
        audit_rows.append(audit_state(asset, y))

        tr = b.total_return_index(d).reindex(x.index).ffill().bfill()
        if ccy == 'USD':
            fx = usd_twd_long(x.index)
            tr = tr * (fx / float(fx.iloc[0]))
        park = parking_long(x.index)

        eligible = y.index[(y.index >= START) & (y.index <= END)]
        if len(eligible) == 0:
            continue
        eff_start = pd.Timestamp(eligible.min())
        years = sorted(set(int(z) for z in eligible.year))
        proxy_status, proxy_name, backfilled = PROXY_STATUS[asset]
        boundary_rows.append({
            'asset':asset,'ticker':ticker,'currency':ccy,
            'requested_start':str(START.date()),'actual_first_date':str(actual_first.date()),
            'effective_test_start':str(eff_start.date()),'effective_test_end':str(pd.Timestamp(eligible.max()).date()),
            'effective_contribution_years':len(years),'expected_total_cost':len(years)*ANNUAL_CONTRIBUTION,
            'actual_etf_only':True,'extended_proxy_status':proxy_status,
            'proxy_name':proxy_name,'proxy_backfilled':backfilled,
        })

        for strategy in ['BUY_HOLD','DCA','V82_FIXED_RUN8']:
            params = FROZEN[asset] if strategy == 'V82_FIXED_RUN8' else dict(base=0,left=0,deep=0,extreme=0,right=0,trend=0)
            sim = simulate_with_series(y, tr, park, params, strategy)
            if sim is None:
                continue
            sm, nav, unit, exposure = sim
            sm.update(asset=asset, strategy=strategy, cls=cls,
                      effective_start=str(nav.index.min().date()), effective_end=str(nav.index.max().date()))
            if strategy == 'V82_FIXED_RUN8':
                sm.update(FROZEN[asset])
            summary_rows.append(sm)
            stress.extend(stress_rows(asset, strategy, unit))

    summary = pd.DataFrame(summary_rows)
    audit = pd.DataFrame(audit_rows)
    boundary = pd.DataFrame(boundary_rows)
    stress_df = pd.DataFrame(stress)
    proxy_df = pd.DataFrame([
        {'asset':a,'status':v[0],'original_index_name':v[1],'backfilled':v[2]}
        for a,v in PROXY_STATUS.items()
    ])

    summary.to_csv(OUT/'extended_actual_summary.csv', index=False)
    audit.to_csv(OUT/'extended_actual_state_audit.csv', index=False)
    boundary.to_csv(OUT/'extended_data_boundary.csv', index=False)
    stress_df.to_csv(OUT/'extended_stress_periods.csv', index=False)
    proxy_df.to_csv(OUT/'extended_proxy_status.csv', index=False)

    print('\nEXTENDED ACTUAL ETF SUMMARY')
    cols=['asset','strategy','total_cost','final_asset','xirr','max_drawdown','twr_cagr','sortino','calmar','recovery_days','avg_stock_exposure','avg_parking_exposure']
    print(summary[cols].to_string(index=False))
    print('\nDATA BOUNDARY')
    print(boundary.to_string(index=False))
    print('\nPROXY STATUS')
    print(proxy_df.to_string(index=False))


if __name__ == '__main__':
    main()
