from pathlib import Path
import numpy as np
import pandas as pd
from v80_backtest import ASSETS, PARAM, START_EVAL, END_EVAL

OUT = Path('v80_results')
INITIAL = 100000.0


def _annual_metrics(nav):
    s = pd.Series(nav, dtype=float)
    if len(s) < 2 or not np.isfinite(s.iloc[0]) or s.iloc[0] <= 0:
        return dict(final_value=np.nan, total_return=np.nan, max_drawdown=np.nan,
                    trough_date=pd.NaT, recovery_date=pd.NaT, recovery_days=np.nan,
                    Sortino=np.nan, Calmar=np.nan)
    r = s.pct_change().dropna()
    total_return = s.iloc[-1] / s.iloc[0] - 1
    running_max = s.cummax()
    dd = s / running_max - 1
    trough_date = dd.idxmin()
    max_drawdown = float(dd.min())
    peak_before = running_max.loc[trough_date]
    post = s.loc[trough_date:]
    recovered = post[post >= peak_before]
    recovery_date = recovered.index[0] if len(recovered) else pd.NaT
    recovery_days = ((recovery_date - trough_date).days
                     if pd.notna(recovery_date) else np.nan)
    downside = r[r < 0]
    sortino = (r.mean() / downside.std(ddof=1) * np.sqrt(252)
               if len(downside) > 1 and downside.std(ddof=1) > 0 else np.nan)
    years = max((s.index[-1] - s.index[0]).days / 365.25, 1 / 365.25)
    cagr = (s.iloc[-1] / s.iloc[0]) ** (1 / years) - 1
    calmar = cagr / abs(max_drawdown) if max_drawdown < 0 else np.nan
    return dict(final_value=float(s.iloc[-1]), total_return=float(total_return),
                max_drawdown=max_drawdown, trough_date=trough_date,
                recovery_date=recovery_date, recovery_days=recovery_days,
                Sortino=float(sortino) if np.isfinite(sortino) else np.nan,
                Calmar=float(calmar) if np.isfinite(calmar) else np.nan)


def _xirr(cashflows):
    # cashflows: [(date, amount)], contributions negative, terminal value positive.
    if len(cashflows) < 2:
        return np.nan
    dates = [pd.Timestamp(d) for d, _ in cashflows]
    vals = np.array([float(v) for _, v in cashflows], dtype=float)
    if not ((vals < 0).any() and (vals > 0).any()):
        return np.nan
    t0 = dates[0]
    yrs = np.array([(d - t0).days / 365.25 for d in dates], dtype=float)
    def npv(rate):
        return float(np.sum(vals / np.power(1.0 + rate, yrs)))
    lo, hi = -0.9999, 10.0
    flo, fhi = npv(lo), npv(hi)
    for _ in range(20):
        if flo * fhi <= 0:
            break
        hi *= 2
        fhi = npv(hi)
    if flo * fhi > 0:
        return np.nan
    for _ in range(200):
        mid = (lo + hi) / 2
        fm = npv(mid)
        if abs(fm) < 1e-10:
            return mid
        if flo * fm <= 0:
            hi, fhi = mid, fm
        else:
            lo, flo = mid, fm
    return (lo + hi) / 2


def simulate(asset, x, events, strategy, start, end, initial=INITIAL):
    p = PARAM[asset]
    z = x[(x.index >= start) & (x.index <= end)].dropna(subset=['Open', 'Close']).copy()
    if len(z) == 0:
        return None
    start, end = z.index[0], z.index[-1]
    cash, units, trades = initial, 0.0, 0
    nav = []
    monthly_seen = None
    dca_flows = []
    installment = initial / 6.0

    ev = events.copy()
    if len(ev):
        ev['execution_date'] = pd.to_datetime(ev['execution_date'])
        ev = ev[(ev.execution_date >= start) & (ev.execution_date <= end)]
        ev_by_date = {d: g for d, g in ev.groupby('execution_date')}
    else:
        ev_by_date = {}

    first = True
    for dt, r in z.iterrows():
        op, cl = float(r.Open), float(r.Close)
        if strategy == 'BUY_HOLD' and first:
            units = cash / op
            cash = 0.0
            trades += 1
        elif strategy == 'DCA':
            month = dt.to_period('M')
            if month != monthly_seen and cash > 1e-9:
                amount = min(installment, cash)
                units += amount / op
                cash -= amount
                trades += 1
                dca_flows.append((dt, -amount))
                monthly_seen = month
        elif strategy == 'V80' and dt in ev_by_date:
            for _, e in ev_by_date[dt].iterrows():
                st = e.executed_state
                total = cash + units * op
                cur = (units * op) / total if total else 0.0
                target = None
                buy_scale = float(e.buy_scale) if 'buy_scale' in e and pd.notna(e.buy_scale) else 1.0
                structural = e.structural_risk if 'structural_risk' in e else 'S1'
                risk_mode = e.risk_mode if 'risk_mode' in e else 'NONE'
                if st == 'LEFT_BUY':
                    target = min(1.0, cur + p['left_frac'] * (0.5 if structural == 'S2' else 1.0) * buy_scale)
                elif st == 'RIGHT_ADD':
                    target = min(1.0, cur + p['right_frac'] * buy_scale)
                elif st == 'TECH_TRIM':
                    target = max(0.0, cur - p['trim'])
                elif st == 'RISK_DOWN':
                    target = max(0.0, cur - (0.15 if risk_mode == 'STRUCTURAL_PARTIAL' else 0.25))
                if target is not None:
                    delta = total * target - units * op
                    if abs(delta) > 1.0:
                        units += delta / op
                        cash -= delta
                        trades += 1
        nav.append((dt, cash + units * cl))
        first = False

    ns = pd.Series(dict(nav)).sort_index()
    m = _annual_metrics(ns)
    m['trade_count'] = trades
    m['ending_cash'] = float(cash)
    m['ending_units'] = float(units)
    m['invested_capital'] = float(initial - cash) if strategy == 'DCA' else float(initial)
    if strategy == 'DCA':
        stock_value = units * float(z.Close.iloc[-1])
        flows = list(dca_flows) + [(end, stock_value)]
        m['XIRR_invested_flows'] = _xirr(flows) if len(dca_flows) else np.nan
        m['invested_only_return'] = (stock_value / m['invested_capital'] - 1
                                     if m['invested_capital'] > 0 else np.nan)
        m['months_invested'] = len(dca_flows)
    else:
        m['XIRR_invested_flows'] = np.nan
        m['invested_only_return'] = np.nan
        m['months_invested'] = np.nan
    return m


def main():
    rows = []
    for asset in ASSETS:
        sig_path = OUT / f'{asset}_daily_signals.csv'
        ev_path = OUT / f'{asset}_events.csv'
        if not sig_path.exists() or not ev_path.exists():
            raise FileNotFoundError(f'missing V80 output for {asset}')
        x = pd.read_csv(sig_path, index_col=0, parse_dates=True)
        x.index = pd.to_datetime(x.index)
        events = pd.read_csv(ev_path)

        for year in range(2019, 2027):
            for half, (m1, m2) in [('H1', (1, 6)), ('H2', (7, 12))]:
                nominal_start = pd.Timestamp(year, m1, 1)
                nominal_end = min(pd.Timestamp(year, m2, 1) + pd.offsets.MonthEnd(0), END_EVAL)
                if nominal_start > END_EVAL:
                    continue
                z = x[(x.index >= nominal_start) & (x.index <= nominal_end)].dropna(subset=['Open', 'Close'])
                if len(z) < 20:
                    continue
                start, end = z.index[0], z.index[-1]
                entry = float(z.Open.iloc[0])
                finish = float(z.Close.iloc[-1])
                result = {s: simulate(asset, x, events, s, start, end) for s in ['BUY_HOLD', 'V80', 'DCA']}
                bh, v80, dca = result['BUY_HOLD'], result['V80'], result['DCA']
                rows.append({
                    'asset': asset, 'period': f'{year}_{half}', 'start_date': start, 'end_date': end,
                    'is_incomplete_period': bool(end < pd.Timestamp(year, m2, 1) + pd.offsets.MonthEnd(0)),
                    'start_price_open': entry, 'end_price_close': finish,
                    'return_basis': 'price_return; dividends_and_fees_consistently_excluded',
                    'buy_hold_return': bh['total_return'], 'buy_hold_max_drawdown': bh['max_drawdown'],
                    'buy_hold_trough_date': bh['trough_date'], 'buy_hold_recovery_date': bh['recovery_date'],
                    'buy_hold_recovery_days': bh['recovery_days'], 'buy_hold_sortino': bh['Sortino'], 'buy_hold_calmar': bh['Calmar'],
                    'v80_return': v80['total_return'], 'v80_max_drawdown': v80['max_drawdown'],
                    'v80_trough_date': v80['trough_date'], 'v80_recovery_date': v80['recovery_date'],
                    'v80_recovery_days': v80['recovery_days'], 'v80_sortino': v80['Sortino'], 'v80_calmar': v80['Calmar'],
                    'v80_trade_count': v80['trade_count'],
                    'dca_return_on_total_budget': dca['total_return'], 'dca_max_drawdown': dca['max_drawdown'],
                    'dca_trough_date': dca['trough_date'], 'dca_recovery_date': dca['recovery_date'],
                    'dca_recovery_days': dca['recovery_days'], 'dca_sortino': dca['Sortino'], 'dca_calmar': dca['Calmar'],
                    'dca_months_invested': dca['months_invested'], 'dca_invested_capital': dca['invested_capital'],
                    'dca_ending_cash': dca['ending_cash'], 'dca_invested_only_return': dca['invested_only_return'],
                    'dca_xirr_invested_flows': dca['XIRR_invested_flows'],
                    'v80_minus_bh_return_pp': (v80['total_return'] - bh['total_return']) * 100,
                    'v80_minus_bh_mdd_pp': (v80['max_drawdown'] - bh['max_drawdown']) * 100,
                    'v80_minus_dca_return_pp': (v80['total_return'] - dca['total_return']) * 100,
                    'v80_minus_dca_mdd_pp': (v80['max_drawdown'] - dca['max_drawdown']) * 100,
                })

    out = pd.DataFrame(rows)
    out.to_csv(OUT / 'halfyear_cohort_benchmark.csv', index=False)
    stress = out[out.period.isin(['2020_H1', '2022_H1', '2022_H2'])].copy()
    stress.to_csv(OUT / 'halfyear_stress_2020_2022.csv', index=False)
    print('Half-year cohort benchmark rows:', len(out))
    print('Stress-test rows:', len(stress))
    print('DCA definition: fixed initial_budget/6 on each month first actual trading day; unused budget remains cash.')
    print('Return basis: price return; dividends and fees consistently excluded across all three cohorts.')


if __name__ == '__main__':
    main()
