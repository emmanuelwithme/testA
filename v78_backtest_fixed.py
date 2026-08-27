from pathlib import Path
import numpy as np
import pandas as pd
from v78_backtest import (
    OUT as OLD_OUT, START_EVAL, END_EVAL, ASSETS, PARAM,
    build_macro, get_prices, make_base, v78_state, state_events, annual_metrics
)

OUT=Path('v78_results_fixed'); OUT.mkdir(exist_ok=True)


def portfolio_event_driven(asset,x,events,strategy,initial=100000.):
    p=PARAM[asset]
    cash=initial; units=0.0; nav=[]; trades=0; monthly_seen=None
    ev=events.copy()
    if len(ev):
        ev['execution_date']=pd.to_datetime(ev['execution_date'])
        ev_by_date={d:g for d,g in ev.groupby('execution_date')}
    else:
        ev_by_date={}

    first_eval=True
    for dt,r in x.iterrows():
        if dt<START_EVAL or dt>END_EVAL:
            continue
        open_px=float(r.Open); close_px=float(r.Close)

        # Buy-and-hold and monthly baseline execute at that day's open.
        if strategy=='BUY_HOLD' and first_eval:
            total=cash+units*open_px
            delta=total-units*open_px
            if abs(delta)>1:
                units+=delta/open_px; cash-=delta; trades+=1
        elif strategy=='MONTHLY':
            m=dt.to_period('M')
            if m!=monthly_seen:
                total=cash+units*open_px
                cur=(units*open_px)/total if total>0 else 0
                target=min(1.0,cur+1/90)
                delta=total*target-units*open_px
                if abs(delta)>1:
                    units+=delta/open_px; cash-=delta; trades+=1
                monthly_seen=m

        # All V78 state-based strategies execute ONLY on validated T+1 event dates.
        if strategy not in ['BUY_HOLD','MONTHLY'] and dt in ev_by_date:
            for _,e in ev_by_date[dt].iterrows():
                st=e.executed_state
                total=cash+units*open_px
                cur=(units*open_px)/total if total>0 else 0
                target=None
                buy_scale=float(e.buy_scale) if pd.notna(e.buy_scale) else 1.0
                structural=e.structural_risk
                risk_mode=e.risk_mode

                if strategy=='LEFT_ONLY' and st=='LEFT_BUY':
                    frac=p['left_frac']*(.5 if structural=='S2' else 1.0)*buy_scale
                    target=min(1.0,cur+frac)
                elif strategy=='RIGHT_ONLY' and st=='RIGHT_ADD':
                    target=min(1.0,cur+p['right_frac']*buy_scale)
                elif strategy in ['LEFT_RIGHT','V78','V78_MACRO']:
                    if st=='LEFT_BUY':
                        frac=p['left_frac']*(.5 if structural=='S2' else 1.0)*buy_scale
                        target=min(1.0,cur+frac)
                    elif st=='RIGHT_ADD':
                        target=min(1.0,cur+p['right_frac']*buy_scale)
                    elif strategy in ['V78','V78_MACRO'] and st=='TECH_TRIM':
                        target=max(0.0,cur-p['trim'])
                    elif strategy in ['V78','V78_MACRO'] and st=='RISK_DOWN':
                        cut=.15 if risk_mode=='STRUCTURAL_PARTIAL' else .25
                        target=max(0.0,cur-cut)

                if target is not None:
                    delta=total*target-units*open_px
                    if abs(delta)>1:
                        units+=delta/open_px; cash-=delta; trades+=1

        nav.append(cash+units*close_px)
        first_eval=False

    m=annual_metrics(nav)
    m.update(asset=asset,strategy=strategy,trade_count=trades)
    return m


def main():
    macro=build_macro(); macro.to_csv(OUT/'macro_daily.csv')
    all_events=[]; port=[]
    for asset,ticker in ASSETS.items():
        print('V78 FIXED RUN',asset)
        price=get_prices(ticker)
        base=make_base(price,macro)
        sig=v78_state(asset,base)
        sig.to_csv(OUT/f'{asset}_daily_signals.csv')
        ev=state_events(asset,sig)
        ev.to_csv(OUT/f'{asset}_events.csv',index=False)
        all_events.append(ev)
        for strat in ['BUY_HOLD','MONTHLY','LEFT_ONLY','RIGHT_ONLY','LEFT_RIGHT','V78','V78_MACRO']:
            port.append(portfolio_event_driven(asset,sig,ev,strat))

    events=pd.concat(all_events,ignore_index=True)
    events.to_csv(OUT/'ALL_events.csv',index=False)
    mature=events[events.ret_3m.notna()].copy()
    st=mature.groupby(['asset','executed_state']).agg(
        N=('cluster_id','size'),mean_ret_1m=('ret_1m','mean'),mean_ret_3m=('ret_3m','mean'),
        mean_ret_6m=('ret_6m','mean'),median_ret_3m=('ret_3m','median'),
        MAE_3m=('mae_3m','mean'),MFE_3m=('mfe_3m','mean'),reward_risk_3m=('reward_risk_3m','mean')
    ).reset_index()
    st.to_csv(OUT/'state_summary.csv',index=False)
    pd.DataFrame(port).to_csv(OUT/'portfolio_summary.csv',index=False)
    events['period']=np.where(pd.to_datetime(events.signal_date)<pd.Timestamp('2024-01-01'),'IS_2019_2023','OOS_2024_2026')
    split=events[events.ret_3m.notna()].groupby(['asset','period','executed_state']).agg(
        N=('cluster_id','size'),ret3=('ret_3m','mean'),mae3=('mae_3m','mean'),mfe3=('mfe_3m','mean'),rr3=('reward_risk_3m','mean')
    ).reset_index()
    split.to_csv(OUT/'is_oos_state_summary.csv',index=False)
    risk=events[events.executed_state.isin(['RUNAWAY_DOWN','RISK_DOWN'])].copy()
    risk.to_csv(OUT/'risk_events.csv',index=False)
    (OUT/'README.md').write_text(
        'V78 corrected phase-1 validation. Portfolio simulation is event-driven: state actions execute only on validated T+1 execution dates from state_events, including Gap Recheck/buy_scale, instead of repeating trades every day a state persists. 0050 history remains dynamic-map based; 96.6 is not backfilled.\n',
        encoding='utf-8')
    print(pd.DataFrame(port).to_string(index=False))

if __name__=='__main__':
    main()
