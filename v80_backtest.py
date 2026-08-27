from pathlib import Path
import numpy as np
import pandas as pd
from investment_backtest import get_prices, build_macro, add_indicators, period_bars, asof_cols
from v78_phase2 import cross_factors, yearly_walk_forward
from v78_backtest import state_events, annual_metrics

OUT=Path('v80_results'); OUT.mkdir(exist_ok=True)
START_EVAL=pd.Timestamp('2019-01-01'); END_EVAL=pd.Timestamp('2026-08-26')
ASSETS={'QQQ':'QQQ','VT':'VT','0050':'0050.TW','VWRA':'VWRA.L','PPH':'PPH'}
PARAM={
 'QQQ':dict(dd=-.10,left_frac=.175,right_frac=.50,trend_frac=.325,left_decel=3,right_count=4,trim=.15),
 'VT':dict(dd=-.07,left_frac=.275,right_frac=.40,trend_frac=.325,left_decel=2,right_count=3,trim=.075),
 '0050':dict(dd=-.08,left_frac=.225,right_frac=.45,trend_frac=.325,left_decel=2,right_count=3,trim=.075),
 'VWRA':dict(dd=-.07,left_frac=.275,right_frac=.40,trend_frac=.325,left_decel=2,right_count=3,trim=.075),
 'PPH':dict(dd=-.09,left_frac=.225,right_frac=.375,trend_frac=.40,left_decel=2,right_count=3,trim=.10),
}
AUX={'SOXX':'SOXX','NVDA':'NVDA','TSM':'TSM','2330':'2330.TW','XLV':'XLV'}


def make_base(df,macro):
    x=add_indicators(df)
    # V80 locks MA5/10/20/50/60/200; shared engine already provides 20/50/200.
    for n in [5,10,60]: x[f'MA{n}']=x.Close.rolling(n).mean()
    wb=add_indicators(period_bars(df,'W-FRI'),52); mb=add_indicators(period_bars(df,'M'),36)
    for z in [wb,mb]:
        for n in [5,10,60]: z[f'MA{n}']=z.Close.rolling(n).mean()
    x=asof_cols(x,wb,'W_',['Close','MA20','MA50','MA200','TD_HIGH','TD_LOW','K','D','MACD_HIST','RSI','EMV','Volume'])
    x=asof_cols(x,mb,'M_',['Close','MA20','MA50','MA200','TD_HIGH','TD_LOW','K','D','MACD_HIST','RSI','EMV','Volume'])
    mac=macro.reindex(macro.index.union(x.index)).sort_index().ffill().reindex(x.index)
    for c in ['BAMLH0A0HYM2','VIX','MOVE','DGS2','DGS10','DGS30','DFF','CPI_YOY','CORE_CPI_YOY','MACRO_VETO','MACRO_HEADWIND','MACRO_STRESS_SCORE']:
        x['X_'+c]=mac[c] if c in mac else np.nan
    # V80 confirmed swing low/high: candidate t-2 becomes known only on day t.
    lo=x.Low; hi=x.High
    swing_low=(lo.shift(2)<lo.shift(4))&(lo.shift(2)<lo.shift(3))&(lo.shift(2)<lo.shift(1))&(lo.shift(2)<lo)
    swing_high=(hi.shift(2)>hi.shift(4))&(hi.shift(2)>hi.shift(3))&(hi.shift(2)>hi.shift(1))&(hi.shift(2)>hi)
    x['CONF_SWING_LOW']=lo.shift(2).where(swing_low).ffill()
    x['CONF_SWING_HIGH']=hi.shift(2).where(swing_high).ffill()
    return x


def align_aux(raw,index):
    out={}
    for k,d in raw.items():
        z=pd.DataFrame(index=d.index)
        z['C']=d.Close; z['M20']=d.Close.rolling(20).mean(); z['M50']=d.Close.rolling(50).mean()
        z['R5']=d.Close.pct_change(5); z['R20']=d.Close.pct_change(20)
        out[k]=z.reindex(z.index.union(index)).sort_index().ffill().reindex(index)
    return out


def v80_state(asset,x,aux):
    p=PARAM[asset]; c=x.Close
    weekly_bear=(x.W_Close<x.W_MA20)&(x.W_MACD_HIST<0)&(x.W_MACD_HIST.diff()<0)
    monthly_broken=(x.M_Close<x.M_MA20)&(x.M_MACD_HIST<0)
    ma200_down=x.MA200.diff(20)<0
    hard_veto=x.X_MACRO_VETO.fillna(False).astype(bool)
    head=x.X_MACRO_HEADWIND.fillna(False).astype(bool)
    extreme_struct=((monthly_broken&weekly_bear&ma200_down&(x.DD252<=-.25))|(weekly_bear&ma200_down&(x.DD252<=-.30)))
    structural=np.select([extreme_struct,monthly_broken|((c<x.MA200)&weekly_bear),weekly_bear|((c<x.MA200)&(~ma200_down))],['S3','S2','S2'],default='S1')
    s2=pd.Series(structural,index=x.index).eq('S2'); s3=pd.Series(structural,index=x.index).eq('S3')

    oversold=(x.K<20)|(x.RSI<30)|(x.TD_LOW>=5)
    overbought=(x.K>80)|(x.RSI>70)|(x.TD_HIGH>=8)
    support=(abs(c-x.CONF_SWING_LOW)<=1.25*x.ATR)
    attractive=(x.DD252<=p['dd'])|(c<=x.MA50-1.25*x.ATR)|(c<=x.MA200+0.5*x.ATR)|support

    hist_shrink=(x.MACD_HIST>x.MACD_HIST.shift(1))&(x.MACD_HIST<0)
    dif_not_accel=x.DIF.diff()>=x.DIF.diff().shift(1)
    kd_stabilize=(x.K>x.K.shift(1))|(x.K.diff().abs()<2)
    rsi_improve=x.RSI>x.RSI.shift(3)
    emv_improve=x.EMV>x.EMV.shift(3)
    atr_cool=x.ATR_PCT<=x.ATR_PCT.shift(3)
    low_stop=x.Low.rolling(3).min()>=x.Low.shift(3).rolling(3).min()
    downvol_cool=x.VOL_R20<=x.VOL_R20.shift(2)
    decel=pd.concat([hist_shrink,dif_not_accel,kd_stabilize,rsi_improve,emv_improve,atr_cool,low_stop,downvol_cool],axis=1).sum(axis=1)

    kd_up=(x.K>x.D)&(x.K.shift(1)<=x.D.shift(1))&(x.K.shift(1)<40)
    dif_up=x.DIF>x.DIF.shift(1)
    ma20_regain=(c>x.MA20)&(c.shift(1)<=x.MA20.shift(1))
    low_higher=x.Low.rolling(3).min()>x.Low.shift(3).rolling(3).min()
    upvol=(c>c.shift(1))&(x.VOL_R20>1.05)
    right_count=pd.concat([kd_up,hist_shrink,dif_up,rsi_improve,emv_improve,ma20_regain,low_higher,upvol],axis=1).sum(axis=1)
    cross_ok,right_bonus=cross_factors(asset,x,aux)
    right_count=right_count+right_bonus
    recent_os=oversold.rolling(20,min_periods=1).max().astype(bool)

    # V80 Runaway Up = structure necessary condition + >=3 strength confirmations.
    prior_swing_high=x.CONF_SWING_HIGH.shift(1)
    structure_up=(c>=c.rolling(20).max())|(c>prior_swing_high)
    kd_hot=(x.K>80)&(x.D>70)&(x.K>=x.K.shift(1)-3)
    macd_expand=(x.MACD_HIST>0)&(x.MACD_HIST>x.MACD_HIST.shift(1))
    ma_stack=(x.MA5>x.MA10)&(x.MA10>x.MA20)
    emv_pos=(x.EMV>0)|(x.EMV>x.EMV.shift(3))
    vol_ok=(x.VOL_R20>=.8)&(x.VOL_R20<=2.5)
    td9_continue=(x.TD_HIGH>=8)&(c>=c.shift(1))
    rsi_hot_no_fail=(x.RSI>=60)&(x.RSI>=x.RSI.shift(3)-5)
    strength_count=pd.concat([kd_hot,macd_expand,ma_stack,emv_pos,vol_ok,td9_continue,rsi_hot_no_fail],axis=1).sum(axis=1)
    runaway_up=structure_up&(strength_count>=3)&(~hard_veto)&(~s3)

    # V80 Runaway Down = support break/new low + >=2 acceleration confirmations.
    break_support=(c<x.CONF_SWING_LOW)|(c<=c.rolling(20).min())
    macd_dn=(x.MACD_HIST<0)&(x.MACD_HIST<x.MACD_HIST.shift(1))
    kd_dn=(x.K<20)&(x.K<x.D)&(x.K<=x.K.shift(1))
    emv_dn=(x.EMV<x.EMV.shift(3))
    rsi_dn=(x.RSI<x.RSI.shift(3))
    price_vol_dn=(c<c.shift(1))&(x.VOL_R20>1.2)
    atr_expand=x.ATR_PCT>x.ATR_PCT.rolling(60,min_periods=20).median()*1.25
    down_count=pd.concat([macd_dn,kd_dn,emv_dn,rsi_dn,price_vol_dn,atr_expand],axis=1).sum(axis=1)
    runaway_down=break_support&(down_count>=2)&((c<x.MA20)|(weekly_bear))

    # V80 trim: high TD/KD alone never enough; exclude Runaway Up first.
    kd_cross_dn=(x.K<x.D)&(x.K.shift(1)>=x.D.shift(1))&(x.K.shift(1)>65)
    hist_fall=(x.MACD_HIST<x.MACD_HIST.shift(1))&(x.MACD_HIST.shift(1)<x.MACD_HIST.shift(2))
    dif_dn=x.DIF<x.DIF.shift(1)
    ma20_break=(c<x.MA20)&(c.shift(1)>=x.MA20.shift(1))
    emv_weak=(x.EMV<0)&(x.EMV<x.EMV.shift(2))
    stall=(c<=c.shift(1))&(x.VOL_R20>1.2)
    weak_count=pd.concat([kd_cross_dn,hist_fall,dif_dn,ma20_break,emv_weak,stall],axis=1).sum(axis=1)
    trim=overbought&(weak_count>=3 if asset in ['VT','VWRA','0050'] else weak_count>=2)&(~runaway_up)

    systemic=weekly_bear&(monthly_broken|(c<x.MA200))&hard_veto
    structural_partial=extreme_struct&(~hard_veto)
    left=attractive&oversold&(decel>=p['left_decel'])&(~s3)&(~hard_veto)&(~runaway_down)&cross_ok
    right=recent_os&(right_count>=p['right_count'])&(~weekly_bear)&(~hard_veto)&(~runaway_down)&((~head)|(c>x.MA50))
    strong=runaway_up|((c>x.MA20)&(x.MA20>x.MA50)&(x.W_Close>x.W_MA20)&overbought&(~hard_veto)&(~structural_partial))

    state=pd.Series('WAIT',index=x.index,dtype='object')
    state[left]='LEFT_BUY'; state[right]='RIGHT_ADD'; state[strong]='STRONG_HOLD'
    state[trim&(~strong)]='TECH_TRIM'; state[runaway_down]='RUNAWAY_DOWN'; state[structural_partial|systemic]='RISK_DOWN'
    risk_mode=pd.Series('NONE',index=x.index,dtype='object'); risk_mode[structural_partial]='STRUCTURAL_PARTIAL'; risk_mode[systemic]='SYSTEMIC'
    y=x.copy(); y['STATE']=state; y['DECEL_COUNT']=decel; y['RIGHT_COUNT']=right_count; y['HARD_VETO']=hard_veto; y['STRUCTURAL_RISK']=structural; y['RISK_MODE']=risk_mode; y['MACRO_VETO_BOOL']=hard_veto; y['RUNAWAY_UP']=runaway_up; y['RUNAWAY_DOWN']=runaway_down; y['STRENGTH_COUNT']=strength_count; y['DOWN_COUNT']=down_count
    return y


def portfolio_event_driven(asset,x,events,strategy,initial=100000.,start=None,end=None):
    p=PARAM[asset]; start=START_EVAL if start is None else pd.Timestamp(start); end=END_EVAL if end is None else pd.Timestamp(end)
    cash=initial; units=0.; nav=[]; nav_dates=[]; trades=0; monthly_seen=None
    ev=events.copy()
    if len(ev):
        ev['execution_date']=pd.to_datetime(ev.execution_date); ev=ev[(ev.execution_date>=start)&(ev.execution_date<=end)]
        ev_by_date={d:g for d,g in ev.groupby('execution_date')}
    else: ev_by_date={}
    first=True
    for dt,r in x.iterrows():
        if dt<start or dt>end or pd.isna(r.Close): continue
        op=float(r.Open); cl=float(r.Close)
        if strategy=='BUY_HOLD' and first:
            units=cash/op; cash=0.; trades+=1
        elif strategy=='MONTHLY':
            m=dt.to_period('M')
            if m!=monthly_seen:
                total=cash+units*op; cur=(units*op)/total if total else 0; target=min(1.,cur+1/6 if (end-start).days<370 else cur+1/90)
                delta=total*target-units*op; units+=delta/op; cash-=delta; trades+=1; monthly_seen=m
        elif dt in ev_by_date:
            for _,e in ev_by_date[dt].iterrows():
                st=e.executed_state; total=cash+units*op; cur=(units*op)/total if total else 0; target=None
                buy_scale=float(e.buy_scale) if 'buy_scale' in e and pd.notna(e.buy_scale) else 1.
                structural=e.structural_risk if 'structural_risk' in e else 'S1'; risk_mode=e.risk_mode if 'risk_mode' in e else 'NONE'
                if strategy=='LEFT_ONLY' and st=='LEFT_BUY': target=min(1.,cur+p['left_frac']*(.5 if structural=='S2' else 1.)*buy_scale)
                elif strategy=='RIGHT_ONLY' and st=='RIGHT_ADD': target=min(1.,cur+p['right_frac']*buy_scale)
                elif strategy in ['LEFT_RIGHT','V80','V80_MACRO']:
                    if st=='LEFT_BUY': target=min(1.,cur+p['left_frac']*(.5 if structural=='S2' else 1.)*buy_scale)
                    elif st=='RIGHT_ADD': target=min(1.,cur+p['right_frac']*buy_scale)
                    elif strategy in ['V80','V80_MACRO'] and st=='TECH_TRIM': target=max(0.,cur-p['trim'])
                    elif strategy in ['V80','V80_MACRO'] and st=='RISK_DOWN': target=max(0.,cur-(.15 if risk_mode=='STRUCTURAL_PARTIAL' else .25))
                if target is not None:
                    delta=total*target-units*op
                    if abs(delta)>1: units+=delta/op; cash-=delta; trades+=1
        nav.append(cash+units*cl); nav_dates.append(dt); first=False
    if not nav: return dict(asset=asset,strategy=strategy,final_value=np.nan,CAGR=np.nan,TWR=np.nan,max_drawdown=np.nan,annual_vol=np.nan,Sharpe=np.nan,Sortino=np.nan,Calmar=np.nan,CVaR_5=np.nan,trade_count=trades)
    m=annual_metrics(nav); m.update(asset=asset,strategy=strategy,trade_count=trades)
    return m


def halfyear_rows(asset,x,events,macro):
    rows=[]
    for year in range(2019,2027):
        for half,(m1,m2) in [('H1',(1,6)),('H2',(7,12))]:
            start=pd.Timestamp(year,m1,1); end=min(pd.Timestamp(year,m2,1)+pd.offsets.MonthEnd(0),END_EVAL)
            if start>END_EVAL: continue
            z=x[(x.index>=start)&(x.index<=end)].dropna(subset=['Open','Close'])
            if len(z)<20: continue
            first=z.index[0]; last=z.index[-1]; entry=float(z.Open.iloc[0]); finish=float(z.Close.iloc[-1]); bh_ret=finish/entry-1
            bh_curve=z.Close/entry; bh_mdd=float((bh_curve/bh_curve.cummax()-1).min()); low_date=z.Low.idxmin(); low_from_entry=float(z.Low.min()/entry-1)
            v80=portfolio_event_driven(asset,x,events,'V80',100000.,first,last)
            monthly=portfolio_event_driven(asset,x,events,'MONTHLY',100000.,first,last)
            mac=macro[(macro.index>=first)&(macro.index<=last)]
            rows.append(dict(asset=asset,period=f'{year}_{half}',start_date=first,end_date=last,start_price=entry,end_price=finish,buy_hold_return=bh_ret,buy_hold_max_drawdown=bh_mdd,lowest_date=low_date,lowest_from_entry=low_from_entry,v80_return=(v80['final_value']/100000-1) if pd.notna(v80['final_value']) else np.nan,v80_max_drawdown=v80['max_drawdown'],v80_sortino=v80['Sortino'],v80_calmar=v80['Calmar'],monthly_return=(monthly['final_value']/100000-1) if pd.notna(monthly['final_value']) else np.nan,hy_oas_mean=mac.BAMLH0A0HYM2.mean() if 'BAMLH0A0HYM2' in mac else np.nan,vix_max=mac.VIX.max() if 'VIX' in mac else np.nan,move_max=mac.MOVE.max() if 'MOVE' in mac else np.nan,dgs10_start=mac.DGS10.dropna().iloc[0] if 'DGS10' in mac and mac.DGS10.notna().any() else np.nan,dgs10_end=mac.DGS10.dropna().iloc[-1] if 'DGS10' in mac and mac.DGS10.notna().any() else np.nan,cpi_yoy_mean=mac.CPI_YOY.mean() if 'CPI_YOY' in mac else np.nan))
    return rows


def main():
    macro=build_macro(); macro.to_csv(OUT/'macro_daily.csv')
    aux_raw={k:get_prices(t) for k,t in AUX.items()}
    all_events=[]; ports=[]; halves=[]
    for asset,ticker in ASSETS.items():
        print('V80 RUN',asset)
        price=get_prices(ticker); base=make_base(price,macro); aux=align_aux(aux_raw,base.index); sig=v80_state(asset,base,aux); sig.to_csv(OUT/f'{asset}_daily_signals.csv')
        ev=state_events(asset,sig); ev.to_csv(OUT/f'{asset}_events.csv',index=False); all_events.append(ev)
        for strat in ['BUY_HOLD','MONTHLY','LEFT_ONLY','RIGHT_ONLY','LEFT_RIGHT','V80','V80_MACRO']:
            ports.append(portfolio_event_driven(asset,sig,ev,strat))
        halves.extend(halfyear_rows(asset,sig,ev,macro))
    events=pd.concat(all_events,ignore_index=True); events.to_csv(OUT/'ALL_events.csv',index=False)
    pd.DataFrame(ports).to_csv(OUT/'portfolio_summary.csv',index=False)
    pd.DataFrame(halves).to_csv(OUT/'halfyear_summary.csv',index=False)
    mature=events[events.ret_3m.notna()]
    mature.groupby(['asset','executed_state']).agg(N=('cluster_id','size'),ret1=('ret_1m','mean'),ret3=('ret_3m','mean'),ret6=('ret_6m','mean'),mae3=('mae_3m','mean'),mfe3=('mfe_3m','mean'),rr3=('reward_risk_3m','mean')).reset_index().to_csv(OUT/'state_summary.csv',index=False)
    events['period']=np.where(pd.to_datetime(events.signal_date)<pd.Timestamp('2024-01-01'),'IS_2019_2023','OOS_2024_2026')
    events[events.ret_3m.notna()].groupby(['asset','period','executed_state']).agg(N=('cluster_id','size'),ret3=('ret_3m','mean'),mae3=('mae_3m','mean'),mfe3=('mfe_3m','mean'),rr3=('reward_risk_3m','mean')).reset_index().to_csv(OUT/'is_oos_state_summary.csv',index=False)
    yearly_walk_forward(events).to_csv(OUT/'walk_forward_expanding_yearly.csv',index=False)
    events[events.executed_state.isin(['RUNAWAY_DOWN','RISK_DOWN'])].to_csv(OUT/'risk_events.csv',index=False)
    (OUT/'README.md').write_text('V80 formal validation. Uses V80 locked logic: ATR14; KD/MACD/RSI from shared engine; confirmed swing lows/highs known only after two right-side bars; Runaway Up requires breakout/new 20d close high or confirmed swing high plus >=3 strength confirmations; Runaway Down requires support/new-low break plus >=2 bearish acceleration confirmations; high TD9 is never an automatic sell; low TD5-6 may start only with stop-falling confluence; event-driven T+1 + Gap Recheck; QQQ/0050 cross factors; VWRA/PPH included; half-year cohorts compare new-money Buy & Hold versus V80 and monthly deployment. Historical 0050 does not backfill the current 96.6 tactical trigger.\n',encoding='utf-8')

if __name__=='__main__': main()
