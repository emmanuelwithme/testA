import numpy as np
import pandas as pd
import v82_backtest_phase1 as b
import v82_backtest_phase1_retry as r

# Formal main-run wrapper.
# Keeps the V82-native T+1 state/deployment engine from v82_backtest_phase1_retry,
# but replaces the DCA control with the user's formal calendar rule:
# - external contribution: NT$1,000,000 at the first valid trading day of each year;
# - DCA transfer: NT$1,000,000 / 12 each month;
# - nominal date: calendar day 1;
# - if day 1 is not a trading day, execute on the first trading day AFTER day 1;
# - never move the trade backward;
# - if an instrument's reliable history begins materially mid-month, do not
#   fabricate a day-1 trade for that partial first month; start DCA next month;
# - untransferred capital remains in the same SGOV/short-bond parking pool.


def formal_dca_dates(dates):
    dates = pd.DatetimeIndex(dates).sort_values()
    if len(dates) == 0:
        return set()
    first = pd.Timestamp(dates[0])
    out = set()
    months = pd.period_range(first.to_period('M'), dates[-1].to_period('M'), freq='M')
    for m in months:
        month_start = pd.Timestamp(m.start_time).normalize()
        q = dates[(dates >= month_start) & (dates.to_period('M') == m)]
        if len(q) == 0:
            continue
        trade_day = pd.Timestamp(q[0])
        # A start on day 2-7 is normally just weekend/holiday/test-boundary handling.
        # A later start is treated as a partial inception/data month and skipped.
        if m == first.to_period('M') and first.day > 7:
            continue
        out.add(trade_day)
    return out


def simulate_formal(asset, y, tr_twd, park_twd, params, strategy):
    dates = y.index[(y.index >= b.START) & (y.index <= b.END)]
    if len(dates) == 0:
        return None
    tr = tr_twd.reindex(dates).ffill().bfill()
    pk = park_twd.reindex(dates).ffill().bfill()
    sig = y.shift(1).reindex(dates)
    dca_dates = formal_dca_dates(dates) if strategy == 'DCA' else set()

    stock_units = 0.0
    park_units = 0.0
    nav = []
    exp = []
    flows = {}
    cfs = []
    yr_done = set()

    for dt in dates:
        dt = pd.Timestamp(dt)
        if dt.year in b.YEARS and dt.year not in yr_done:
            amt = b.ANNUAL_CONTRIBUTION
            park_units += amt / float(pk.loc[dt])
            flows[dt] = flows.get(dt, 0.0) + amt
            cfs.append((dt, -amt))
            yr_done.add(dt.year)

        total = stock_units * float(tr.loc[dt]) + park_units * float(pk.loc[dt])
        if total <= 0:
            continue
        stock_value = stock_units * float(tr.loc[dt])
        cur = stock_value / total
        target = cur

        if strategy == 'BUY_HOLD':
            target = 1.0
        elif strategy == 'DCA':
            if dt in dca_dates:
                # Fixed nominal NT$ amount, independent of price or V82 state.
                desired_buy = b.ANNUAL_CONTRIBUTION / 12.0
                available = park_units * float(pk.loc[dt])
                buy = min(desired_buy, available)
                if buy > 1.0:
                    stock_units += buy / float(tr.loc[dt])
                    park_units -= buy / float(pk.loc[dt])
                total = stock_units * float(tr.loc[dt]) + park_units * float(pk.loc[dt])
                nav.append((dt, total))
                exp.append((dt, (stock_units * float(tr.loc[dt])) / total if total else 0.0))
                continue
        elif strategy.startswith('V82'):
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
                    tier = row.V82_TIER
                    target = max(cur, params['base'])
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
        exp.append((dt, (stock_units * float(tr.loc[dt])) / total if total else 0.0))

    nav = pd.Series(dict(nav)).sort_index()
    exposure = pd.Series(dict(exp)).sort_index()
    if len(nav) == 0:
        return None
    cfs.append((nav.index[-1], float(nav.iloc[-1])))
    mdd, unit = b.mdd_unitized(nav, flows)
    perf = r.performance_metrics(unit)
    cost = len(yr_done) * b.ANNUAL_CONTRIBUTION
    final = float(nav.iloc[-1])
    return dict(
        final_asset=final,
        total_cost=cost,
        total_profit=final-cost,
        total_return=final/cost-1,
        xirr=b.xirr(cfs),
        max_drawdown=mdd,
        avg_stock_exposure=float(exposure.mean()),
        avg_parking_exposure=float(1-exposure.mean()),
        **perf,
    )


# retry import already installs V82-native state logic, robust parking, and audit.
# Override only the execution simulator to enforce the formal DCA calendar.
b.simulate = simulate_formal

if __name__ == '__main__':
    b.main()
    audit = pd.DataFrame(r._state_audit)
    audit.to_csv(b.OUT/'state_audit.csv', index=False)
    print('\nV82 NATIVE STATE AUDIT')
    print(audit.to_string(index=False))
