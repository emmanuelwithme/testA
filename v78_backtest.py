import math
from pathlib import Path
import numpy as np
import pandas as pd
from investment_backtest import get_prices, build_macro, add_indicators, period_bars, asof_cols

OUT=Path('v78_results'); OUT.mkdir(exist_ok=True)
START_EVAL=pd.Timestamp('2019-01-01'); END_EVAL=pd.Timestamp('2026-08-26')
ASSETS={'QQQ':'QQQ','VT':'VT','0050':'0050.TW'}
PARAM={
 'QQQ':dict(dd=-.10,left_frac=.175,right_frac=.50,trend_frac=.325,left_decel=3,right_count=4,trim=.15),
 'VT':dict(dd=-.07,left_frac=.275,right_frac=.40,trend_frac=.325,left_decel=2,right_count=3,trim=.075),
 '0050':dict(dd=-.08,left_frac=.225,right_frac=.45,trend_frac=.325,left_decel=2,right_count=3,trim=.075),
}

def make_base(df,macro):
    x=add_indicators(df)
    wb=add_indicators(period_bars(df,'W-FRI'),52); mb=add_indicators(period_bars(df,'M'),36)
    x=asof_cols(x,wb,'W_',['Close','MA20','TD_HIGH','TD_LOW','K','D','MACD_HIST','RSI','EMV','Volume'])
    x=asof_cols(x,mb,'M_',['Close','MA20','TD_HIGH','TD_LOW','K','D','MACD_HIST','RSI','EMV','Volume'])
    mac=macro.reindex(macro.index.union(x.index)).sort_index().ffill().reindex(x.index)
    for c in ['BAMLH0A0HYM2','VIX','MOVE','DGS10','DGS30','CPI_YOY','CORE_CPI_YOY','MACRO_VETO','MACRO_HEADWIND','MACRO_STRESS_SCORE']:
        x['X_'+c]=mac[c] if c in mac else np.nan
    return x

def v78_state(asset,x):
    p=PARAM[asset]; c=x.Close
    weekly_bear=(x.W_Close<x.W_MA20)&(x.W_MACD_HIST<0)&(x.W_MACD_HIST.diff()<0)
    monthly_broken=(x.M_Close<x.M_MA20)&(x.M_MACD_HIST<0)
    ma200_down=x.MA200.diff(20)<0
    macro_veto=x.X_MACRO_VETO.fillna(False).astype(bool)
    head=x.X_MACRO_HEADWIND.fillna(False).astype(bool)
    # V78 Hard Veto / Structural Risk
    hard_veto=macro_veto
    extreme_struct=((monthly_broken&weekly_bear&ma200_down&(x.DD252<=-.25)) | (weekly_bear&ma200_down&(x.DD252<=-.30)))
    structural=np.select([
        extreme_struct,
        monthly_broken|((c<x.MA200)&weekly_bear),
        weekly_bear|((c<x.MA200)&(~ma200_down))
    ],['S3','S2','S2'],default='S1')
    oversold=(x.K<20)|(x.RSI<30)|(x.TD_LOW>=5)
    overbought=(x.K>80)|(x.RSI>70)|(x.TD_HIGH>=8)
    # Dynamic price map only. 96.6 is a current tactical trigger and is NOT back-filled through history.
    attractive=(x.DD252<=p['dd'])|(c<=x.MA50-1.25*x.ATR)|(c<=x.MA200+0.5*x.ATR)
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
    recent_os=oversold.rolling(20,min_periods=1).max().astype(bool)
    kd_dn=(x.K<x.D)&(x.K.shift(1)>=x.D.shift(1))&(x.K.shift(1)>65)
    hist_fall=(x.MACD_HIST<x.MACD_HIST.shift(1))&(x.MACD_HIST.shift(1)<x.MACD_HIST.shift(2))
    dif_dn=x.DIF<x.DIF.shift(1); ma20_break=(c<x.MA20)&(c.shift(1)>=x.MA20.shift(1))
    emv_weak=(x.EMV<0)&(x.EMV<x.EMV.shift(2)); stall=(c<=c.shift(1))&(x.VOL_R20>1.2)
    weak_count=pd.concat([kd_dn,hist_fall,dif_dn,ma20_break,emv_weak,stall],axis=1).sum(axis=1)
    runaway=((x.TD_LOW>=8)|((x.K<15)&(x.RSI<30)))&(c<x.MA20)&(c<x.MA50)&weekly_bear&((x.VOL_R20>1.3)|(x.ATR_PCT>x.ATR_PCT.rolling(60,min_periods=20).median()*1.3))
    systemic_risk=weekly_bear&(monthly_broken|(c<x.MA200))&hard_veto
    partial_risk=extreme_struct&(~hard_veto)
    # S2 permits smaller left buys; S3 blocks ordinary left buys.
    s2=pd.Series(structural,index=x.index).eq('S2'); s3=pd.Series(structural,index=x.index).eq('S3')
    left=attractive&oversold&(decel>=p['left_decel'])&(~s3)&(~hard_veto)
    right=recent_os&(right_count>=p['right_count'])&(~weekly_bear)&(~hard_veto)&((~head)|(c>x.MA50))
    strong=(c>x.MA20)&(x.MA20>x.MA50)&(x.W_Close>x.W_MA20)&overbought&(~hard_veto)&(~systemic_risk)&(~partial_risk)
    trim=overbought&(weak_count>=3 if asset in ['VT','0050'] else weak_count>=2)&(~systemic_risk)&(~partial_risk)
    state=pd.Series('WAIT',index=x.index,dtype='object')
    state[left]='LEFT_BUY'; state[right]='RIGHT_ADD'; state[strong]='STRONG_HOLD'; state[trim]='TECH_TRIM'; state[runaway]='RUNAWAY_DOWN'; state[partial_risk|systemic_risk]='RISK_DOWN'
    risk_mode=pd.Series('NONE',index=x.index,dtype='object'); risk_mode[partial_risk]='STRUCTURAL_PARTIAL'; risk_mode[systemic_risk]='SYSTEMIC'
    x=x.copy(); x['STATE']=state; x['DECEL_COUNT']=decel; x['RIGHT_COUNT']=right_count; x['HARD_VETO']=hard_veto; x['STRUCTURAL_RISK']=structural; x['RISK_MODE']=risk_mode; x['MACRO_VETO_BOOL']=macro_veto
    return x

def state_events(asset,x):
    change=x.STATE.ne(x.STATE.shift(1)); idx=np.where(change.values)[0]
    rows=[]; cluster=0; last_event_i=-99
    for i in idx:
        if i<1 or x.index[i]<START_EVAL or x.index[i]>END_EVAL: continue
        st=x.STATE.iloc[i]; prev=x.STATE.iloc[i-1]
        if i-last_event_i<=5 and rows and rows[-1]['signal_state']==st: continue
        cluster+=1; last_event_i=i; j=i+1
        if j>=len(x): continue
        planned=float(x.Close.iloc[i]); actual=float(x.Open.iloc[j]); atr=float(x.ATR.iloc[i]) if pd.notna(x.ATR.iloc[i]) else np.nan
        gap=actual/planned-1; gap_atr=(actual-planned)/atr if atr and np.isfinite(atr) else np.nan
        exec_state=st; buy_scale=1.0
        if st in ['LEFT_BUY','RIGHT_ADD']:
            # Gap up changes only the NEW purchase amount; existing holdings are untouched.
            if np.isfinite(gap_atr) and gap_atr>1.0: exec_state='WAIT'; buy_scale=0.0
            elif np.isfinite(gap_atr) and gap_atr>.5: buy_scale=.5
            if bool(x.HARD_VETO.iloc[j]): exec_state='RISK_DOWN'; buy_scale=0.0
            if x.STATE.iloc[j] in ['RUNAWAY_DOWN','RISK_DOWN']: exec_state=x.STATE.iloc[j]; buy_scale=0.0
        row=dict(asset=asset,cluster_id=f'{asset}-{cluster:04d}',signal_date=x.index[i],execution_date=x.index[j],previous_state=prev,signal_state=st,executed_state=exec_state,planned_entry=planned,actual_entry=actual,gap_pct=gap,gap_atr=gap_atr,buy_scale=buy_scale,decel_count=float(x.DECEL_COUNT.iloc[i]),right_count=float(x.RIGHT_COUNT.iloc[i]),hard_veto=bool(x.HARD_VETO.iloc[i]),structural_risk=x.STRUCTURAL_RISK.iloc[i],risk_mode=x.RISK_MODE.iloc[i])
        for m,n in [(1,21),(3,63),(6,126)]:
            if j+n-1<len(x):
                w=x.iloc[j:j+n]; row[f'ret_{m}m']=float(w.Close.iloc[-1]/actual-1); row[f'mae_{m}m']=float(w.Low.min()/actual-1); row[f'mfe_{m}m']=float(w.High.max()/actual-1); row[f'reward_risk_{m}m']=float(row[f'mfe_{m}m']/abs(row[f'mae_{m}m'])) if row[f'mae_{m}m']<0 else np.nan
            else:
                row[f'ret_{m}m']=row[f'mae_{m}m']=row[f'mfe_{m}m']=row[f'reward_risk_{m}m']=np.nan
        rows.append(row)
    return pd.DataFrame(rows)

def drawdown(v):
    s=pd.Series(v); return float((s/s.cummax()-1).min())

def annual_metrics(nav):
    nav=pd.Series(nav).dropna(); r=nav.pct_change().dropna(); years=max(len(nav)/252,1/252); cagr=(nav.iloc[-1]/nav.iloc[0])**(1/years)-1
    vol=r.std()*np.sqrt(252); sharpe=(r.mean()*252/vol) if vol>0 else np.nan
    dn=r[r<0].std()*np.sqrt(252); sortino=(r.mean()*252/dn) if dn>0 else np.nan
    mdd=drawdown(nav); calmar=cagr/abs(mdd) if mdd<0 else np.nan
    q=r.quantile(.05) if len(r) else np.nan
    return dict(final_value=nav.iloc[-1],CAGR=cagr,TWR=nav.iloc[-1]/nav.iloc[0]-1,max_drawdown=mdd,annual_vol=vol,Sharpe=sharpe,Sortino=sortino,Calmar=calmar,CVaR_5=r[r<=q].mean() if len(r) else np.nan)

def portfolio(asset,x,strategy,initial=100000.):
    p=PARAM[asset]; cash=initial; units=0.; nav=[]; trades=0; monthly_seen=None
    for dt,r in x.iterrows():
        if dt<START_EVAL or dt>END_EVAL: continue
        px=float(r.Close); st=r.STATE; total=cash+units*px; cur=(units*px)/total if total>0 else 0; target=None
        if strategy=='BUY_HOLD': target=1.0 if len(nav)==0 else None
        elif strategy=='MONTHLY':
            m=dt.to_period('M')
            if m!=monthly_seen: target=min(1.0,cur+1/90); monthly_seen=m
        elif strategy=='LEFT_ONLY' and st=='LEFT_BUY': target=min(1,cur+p['left_frac']*(.5 if r.STRUCTURAL_RISK=='S2' else 1))
        elif strategy=='RIGHT_ONLY' and st=='RIGHT_ADD': target=min(1,cur+p['right_frac'])
        elif strategy in ['LEFT_RIGHT','V78','V78_MACRO']:
            if st=='LEFT_BUY': target=min(1,cur+p['left_frac']*(.5 if r.STRUCTURAL_RISK=='S2' else 1))
            elif st=='RIGHT_ADD': target=min(1,cur+p['right_frac'])
            elif strategy in ['V78','V78_MACRO'] and st=='TECH_TRIM': target=max(0,cur-p['trim'])
            elif strategy in ['V78','V78_MACRO'] and st=='RISK_DOWN': target=max(0,cur-(.15 if r.RISK_MODE=='STRUCTURAL_PARTIAL' else .25))
            elif strategy=='V78_MACRO' and bool(r.HARD_VETO): target=min(cur,.50)
        if target is not None:
            desired=total*target; delta=desired-units*px
            if abs(delta)>1: units+=delta/px; cash-=delta; trades+=1
        nav.append(cash+units*px)
    m=annual_metrics(nav); m.update(asset=asset,strategy=strategy,trade_count=trades); return m

def main():
    macro=build_macro(); macro.to_csv(OUT/'macro_daily.csv'); all_events=[]; port=[]
    for asset,ticker in ASSETS.items():
        print('V78 RUN',asset)
        price=get_prices(ticker); base=make_base(price,macro); sig=v78_state(asset,base); sig.to_csv(OUT/f'{asset}_daily_signals.csv')
        ev=state_events(asset,sig); ev.to_csv(OUT/f'{asset}_events.csv',index=False); all_events.append(ev)
        for strat in ['BUY_HOLD','MONTHLY','LEFT_ONLY','RIGHT_ONLY','LEFT_RIGHT','V78','V78_MACRO']:
            port.append(portfolio(asset,sig,strat))
    events=pd.concat(all_events,ignore_index=True); events.to_csv(OUT/'ALL_events.csv',index=False)
    mature=events[events.ret_3m.notna()].copy()
    st=mature.groupby(['asset','executed_state']).agg(N=('cluster_id','size'),mean_ret_1m=('ret_1m','mean'),mean_ret_3m=('ret_3m','mean'),mean_ret_6m=('ret_6m','mean'),median_ret_3m=('ret_3m','median'),MAE_3m=('mae_3m','mean'),MFE_3m=('mfe_3m','mean'),reward_risk_3m=('reward_risk_3m','mean')).reset_index(); st.to_csv(OUT/'state_summary.csv',index=False)
    pd.DataFrame(port).to_csv(OUT/'portfolio_summary.csv',index=False)
    events['period']=np.where(pd.to_datetime(events.signal_date)<pd.Timestamp('2024-01-01'),'IS_2019_2023','OOS_2024_2026')
    split=events[events.ret_3m.notna()].groupby(['asset','period','executed_state']).agg(N=('cluster_id','size'),ret3=('ret_3m','mean'),mae3=('mae_3m','mean'),mfe3=('mfe_3m','mean'),rr3=('reward_risk_3m','mean')).reset_index(); split.to_csv(OUT/'is_oos_state_summary.csv',index=False)
    risk=events[events.executed_state.isin(['RUNAWAY_DOWN','RISK_DOWN'])].copy(); risk.to_csv(OUT/'risk_events.csv',index=False)
    (OUT/'README.md').write_text('V78 phase-1 formal backtest: QQQ/VT/0050. Implements Hard Veto, Structural Risk S1-S3, Extreme Structural Override, dynamic 0050 historical price map (96.6 remains current tactical trigger only), 5-day cluster dedupe, T+1, Gap Recheck, state KPI and portfolio strategies. ETF-specific external cross-asset factors and VWRA/PPH are phase-2.\n',encoding='utf-8')
    print(pd.DataFrame(port).to_string(index=False))

if __name__=='__main__': main()
