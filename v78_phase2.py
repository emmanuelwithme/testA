from pathlib import Path
import numpy as np
import pandas as pd
from investment_backtest import get_prices, build_macro, add_indicators, period_bars, asof_cols
from v78_backtest_fixed import portfolio_event_driven
from v78_backtest import state_events, annual_metrics

OUT=Path('v78_phase2_results'); OUT.mkdir(exist_ok=True)
START_EVAL=pd.Timestamp('2019-01-01'); END_EVAL=pd.Timestamp('2026-08-26')
ASSETS={'QQQ':'QQQ','VT':'VT','0050':'0050.TW','VWRA':'VWRA.L','PPH':'PPH'}
PARAM={
 'QQQ':dict(dd=-.10,left_frac=.175,right_frac=.50,left_decel=3,right_count=4,trim=.15),
 'VT':dict(dd=-.07,left_frac=.275,right_frac=.40,left_decel=2,right_count=3,trim=.075),
 '0050':dict(dd=-.08,left_frac=.225,right_frac=.45,left_decel=2,right_count=3,trim=.075),
 'VWRA':dict(dd=-.07,left_frac=.275,right_frac=.40,left_decel=2,right_count=3,trim=.075),
 'PPH':dict(dd=-.09,left_frac=.225,right_frac=.375,left_decel=2,right_count=3,trim=.10),
}

AUX={'SOXX':'SOXX','NVDA':'NVDA','TSM':'TSM','2330':'2330.TW','XLV':'XLV'}

def make_base(df,macro):
    x=add_indicators(df)
    wb=add_indicators(period_bars(df,'W-FRI'),52); mb=add_indicators(period_bars(df,'M'),36)
    x=asof_cols(x,wb,'W_',['Close','MA20','TD_HIGH','TD_LOW','K','D','MACD_HIST','RSI','EMV','Volume'])
    x=asof_cols(x,mb,'M_',['Close','MA20','TD_HIGH','TD_LOW','K','D','MACD_HIST','RSI','EMV','Volume'])
    mac=macro.reindex(macro.index.union(x.index)).sort_index().ffill().reindex(x.index)
    for c in ['BAMLH0A0HYM2','VIX','MOVE','DGS10','DGS30','CPI_YOY','CORE_CPI_YOY','MACRO_VETO','MACRO_HEADWIND','MACRO_STRESS_SCORE']:
        x['X_'+c]=mac[c] if c in mac else np.nan
    return x

def aux_series(ticker,index):
    d=get_prices(ticker)
    z=pd.DataFrame(index=d.index)
    z['C']=d.Close
    z['M20']=d.Close.rolling(20).mean(); z['M50']=d.Close.rolling(50).mean()
    z['R5']=d.Close.pct_change(5); z['R20']=d.Close.pct_change(20)
    return z.reindex(z.index.union(index)).sort_index().ffill().reindex(index)

def cross_factors(asset,x,aux):
    n=len(x); ok_left=pd.Series(True,index=x.index); right_bonus=pd.Series(0,index=x.index,dtype=float)
    if asset=='QQQ':
        so=aux['SOXX']; nv=aux['NVDA']; ts=aux['TSM']
        breaks=pd.concat([(so.C<so.M20)&(so.R20<0),(nv.C<nv.M20)&(nv.R20<0),(ts.C<ts.M20)&(ts.R20<0)],axis=1).sum(axis=1)
        improves=pd.concat([(so.R5>0)&(so.C>so.M20),(nv.R5>0)&(nv.C>nv.M20),(ts.R5>0)&(ts.C>ts.M20)],axis=1).sum(axis=1)
        ok_left=breaks<3
        right_bonus=(improves>=2).astype(int)
    elif asset=='0050':
        tw=aux['2330']; ts=aux['TSM']; so=aux['SOXX']
        breaks=pd.concat([(tw.C<tw.M20)&(tw.R20<0),(ts.C<ts.M20)&(ts.R20<0),(so.C<so.M20)&(so.R20<0)],axis=1).sum(axis=1)
        improves=pd.concat([(tw.R5>0)&(tw.C>tw.M20),(ts.R5>0)&(ts.C>ts.M20),(so.R5>0)&(so.C>so.M20)],axis=1).sum(axis=1)
        ok_left=breaks<3
        right_bonus=(improves>=2).astype(int)
    elif asset=='PPH':
        xl=aux['XLV']
        # Historical policy/FDA event data are not backfilled. XLV relative trend is used only as a market-based sector confirmation proxy.
        rel=(x.Close/xl.C).replace([np.inf,-np.inf],np.nan)
        rel20=rel/rel.rolling(20).mean()-1
        ok_left=(rel20>-0.06).fillna(True)
        right_bonus=((rel20>0)&(xl.R5>0)).astype(int)
    return ok_left.fillna(True),right_bonus.fillna(0)

def v78_state(asset,x,aux):
    p=PARAM[asset]; c=x.Close
    weekly_bear=(x.W_Close<x.W_MA20)&(x.W_MACD_HIST<0)&(x.W_MACD_HIST.diff()<0)
    monthly_broken=(x.M_Close<x.M_MA20)&(x.M_MACD_HIST<0)
    ma200_down=x.MA200.diff(20)<0
    hard_veto=x.X_MACRO_VETO.fillna(False).astype(bool)
    head=x.X_MACRO_HEADWIND.fillna(False).astype(bool)
    extreme_struct=((monthly_broken&weekly_bear&ma200_down&(x.DD252<=-.25))|(weekly_bear&ma200_down&(x.DD252<=-.30)))
    structural=np.select([extreme_struct,monthly_broken|((c<x.MA200)&weekly_bear),weekly_bear|((c<x.MA200)&(~ma200_down))],['S3','S2','S2'],default='S1')
    oversold=(x.K<20)|(x.RSI<30)|(x.TD_LOW>=5); overbought=(x.K>80)|(x.RSI>70)|(x.TD_HIGH>=8)
    attractive=(x.DD252<=p['dd'])|(c<=x.MA50-1.25*x.ATR)|(c<=x.MA200+0.5*x.ATR)
    hist_shrink=(x.MACD_HIST>x.MACD_HIST.shift(1))&(x.MACD_HIST<0)
    dif_not_accel=x.DIF.diff()>=x.DIF.diff().shift(1); kd_stabilize=(x.K>x.K.shift(1))|(x.K.diff().abs()<2)
    rsi_improve=x.RSI>x.RSI.shift(3); emv_improve=x.EMV>x.EMV.shift(3); atr_cool=x.ATR_PCT<=x.ATR_PCT.shift(3)
    low_stop=x.Low.rolling(3).min()>=x.Low.shift(3).rolling(3).min(); downvol_cool=x.VOL_R20<=x.VOL_R20.shift(2)
    decel=pd.concat([hist_shrink,dif_not_accel,kd_stabilize,rsi_improve,emv_improve,atr_cool,low_stop,downvol_cool],axis=1).sum(axis=1)
    kd_up=(x.K>x.D)&(x.K.shift(1)<=x.D.shift(1))&(x.K.shift(1)<40); dif_up=x.DIF>x.DIF.shift(1)
    ma20_regain=(c>x.MA20)&(c.shift(1)<=x.MA20.shift(1)); low_higher=x.Low.rolling(3).min()>x.Low.shift(3).rolling(3).min(); upvol=(c>c.shift(1))&(x.VOL_R20>1.05)
    right_count=pd.concat([kd_up,hist_shrink,dif_up,rsi_improve,emv_improve,ma20_regain,low_higher,upvol],axis=1).sum(axis=1)
    recent_os=oversold.rolling(20,min_periods=1).max().astype(bool)
    kd_dn=(x.K<x.D)&(x.K.shift(1)>=x.D.shift(1))&(x.K.shift(1)>65); hist_fall=(x.MACD_HIST<x.MACD_HIST.shift(1))&(x.MACD_HIST.shift(1)<x.MACD_HIST.shift(2))
    dif_dn=x.DIF<x.DIF.shift(1); ma20_break=(c<x.MA20)&(c.shift(1)>=x.MA20.shift(1)); emv_weak=(x.EMV<0)&(x.EMV<x.EMV.shift(2)); stall=(c<=c.shift(1))&(x.VOL_R20>1.2)
    weak_count=pd.concat([kd_dn,hist_fall,dif_dn,ma20_break,emv_weak,stall],axis=1).sum(axis=1)
    runaway=((x.TD_LOW>=8)|((x.K<15)&(x.RSI<30)))&(c<x.MA20)&(c<x.MA50)&weekly_bear&((x.VOL_R20>1.3)|(x.ATR_PCT>x.ATR_PCT.rolling(60,min_periods=20).median()*1.3))
    systemic=weekly_bear&(monthly_broken|(c<x.MA200))&hard_veto; partial=extreme_struct&(~hard_veto)
    s2=pd.Series(structural,index=x.index).eq('S2'); s3=pd.Series(structural,index=x.index).eq('S3')
    cross_ok,right_bonus=cross_factors(asset,x,aux)
    adj_right=right_count+right_bonus
    left=attractive&oversold&(decel>=p['left_decel'])&(~s3)&(~hard_veto)&cross_ok
    right=recent_os&(adj_right>=p['right_count'])&(~weekly_bear)&(~hard_veto)&((~head)|(c>x.MA50))
    strong=(c>x.MA20)&(x.MA20>x.MA50)&(x.W_Close>x.W_MA20)&overbought&(~hard_veto)&(~systemic)&(~partial)
    trim=overbought&(weak_count>=3 if asset in ['VT','VWRA','0050'] else weak_count>=2)&(~systemic)&(~partial)
    state=pd.Series('WAIT',index=x.index,dtype='object'); state[left]='LEFT_BUY'; state[right]='RIGHT_ADD'; state[strong]='STRONG_HOLD'; state[trim]='TECH_TRIM'; state[runaway]='RUNAWAY_DOWN'; state[partial|systemic]='RISK_DOWN'
    risk_mode=pd.Series('NONE',index=x.index,dtype='object'); risk_mode[partial]='STRUCTURAL_PARTIAL'; risk_mode[systemic]='SYSTEMIC'
    y=x.copy(); y['STATE']=state; y['DECEL_COUNT']=decel; y['RIGHT_COUNT']=adj_right; y['HARD_VETO']=hard_veto; y['STRUCTURAL_RISK']=structural; y['RISK_MODE']=risk_mode; y['MACRO_VETO_BOOL']=hard_veto; y['CROSS_OK']=cross_ok; y['CROSS_RIGHT_BONUS']=right_bonus
    return y

def yearly_walk_forward(events):
    e=events.copy(); e['signal_date']=pd.to_datetime(e.signal_date); rows=[]
    for asset,g in e.groupby('asset'):
        for year in range(2020,2027):
            train=g[g.signal_date<pd.Timestamp(f'{year}-01-01')]
            test=g[(g.signal_date>=pd.Timestamp(f'{year}-01-01'))&(g.signal_date<pd.Timestamp(f'{year+1}-01-01'))]
            # No parameter retuning: this is a strict expanding-window stability check, not an optimization exercise.
            mature=test[test.ret_3m.notna()]
            rows.append(dict(asset=asset,test_year=year,train_events=len(train),test_events=len(test),mature_3m=len(mature),mean_ret3=float(mature.ret_3m.mean()) if len(mature) else np.nan,mean_mae3=float(mature.mae_3m.mean()) if len(mature) else np.nan,mean_mfe3=float(mature.mfe_3m.mean()) if len(mature) else np.nan))
    return pd.DataFrame(rows)

def main():
    macro=build_macro(); macro.to_csv(OUT/'macro_daily.csv')
    aux={k:None for k in AUX}; all_events=[]; ports=[]
    # Build an index union lazily per asset; auxiliary data are fetched once then aligned per asset.
    aux_raw={k:get_prices(t) for k,t in AUX.items()}
    for asset,ticker in ASSETS.items():
        print('V78 PHASE2',asset)
        price=get_prices(ticker); base=make_base(price,macro)
        aligned={}
        for k,d in aux_raw.items():
            z=pd.DataFrame(index=d.index); z['C']=d.Close; z['M20']=d.Close.rolling(20).mean(); z['M50']=d.Close.rolling(50).mean(); z['R5']=d.Close.pct_change(5); z['R20']=d.Close.pct_change(20)
            aligned[k]=z.reindex(z.index.union(base.index)).sort_index().ffill().reindex(base.index)
        sig=v78_state(asset,base,aligned); sig.to_csv(OUT/f'{asset}_daily_signals.csv')
        ev=state_events(asset,sig); ev.to_csv(OUT/f'{asset}_events.csv',index=False); all_events.append(ev)
        # VWRA has no artificial pre-inception backfill; portfolio begins only when its own data/indicators exist.
        for strat in ['BUY_HOLD','MONTHLY','LEFT_ONLY','RIGHT_ONLY','LEFT_RIGHT','V78','V78_MACRO']:
            ports.append(portfolio_event_driven(asset,sig,ev,strat))
    events=pd.concat(all_events,ignore_index=True); events.to_csv(OUT/'ALL_events.csv',index=False)
    pd.DataFrame(ports).to_csv(OUT/'portfolio_summary.csv',index=False)
    mature=events[events.ret_3m.notna()]
    mature.groupby(['asset','executed_state']).agg(N=('cluster_id','size'),ret1=('ret_1m','mean'),ret3=('ret_3m','mean'),ret6=('ret_6m','mean'),mae3=('mae_3m','mean'),mfe3=('mfe_3m','mean'),rr3=('reward_risk_3m','mean')).reset_index().to_csv(OUT/'state_summary.csv',index=False)
    events['period']=np.where(pd.to_datetime(events.signal_date)<pd.Timestamp('2024-01-01'),'IS_2019_2023','OOS_2024_2026')
    events[events.ret_3m.notna()].groupby(['asset','period','executed_state']).agg(N=('cluster_id','size'),ret3=('ret_3m','mean'),mae3=('mae_3m','mean'),mfe3=('mfe_3m','mean'),rr3=('reward_risk_3m','mean')).reset_index().to_csv(OUT/'is_oos_state_summary.csv',index=False)
    yearly_walk_forward(events).to_csv(OUT/'walk_forward_expanding_yearly.csv',index=False)
    events[events.executed_state.isin(['RUNAWAY_DOWN','RISK_DOWN'])].to_csv(OUT/'risk_events.csv',index=False)
    (OUT/'README.md').write_text('V78 phase-2: QQQ/VT/0050 plus VWRA/PPH; event-driven T+1 execution; dynamic 0050 history (no 96.6 backfill); QQQ cross-confirmation uses SOXX/NVDA/TSM; 0050 uses 2330/TSM/SOXX; PPH uses XLV relative trend as a market proxy only. Historical FDA/policy events are NOT artificially backfilled. Includes expanding-window yearly stability output without parameter retuning.\n',encoding='utf-8')

if __name__=='__main__': main()
