import os, math, json, time, warnings
from pathlib import Path
import numpy as np
import pandas as pd
import yfinance as yf
import requests
warnings.filterwarnings('ignore')

START='2017-01-01'
END='2026-08-26'
OUT=Path('backtest_results'); OUT.mkdir(exist_ok=True)
ASSETS={'QQQ':'QQQ','VT':'VT','0050':'0050.TW'}
PARAMS={'QQQ': {'dd_threshold':-0.10},'VT': {'dd_threshold':-0.08},'0050': {'dd_threshold':-0.08}}

def get_prices(ticker):
    last=None
    for i in range(4):
        try:
            df=yf.Ticker(ticker).history(start=START,end=END,auto_adjust=False,actions=True,repair=True,timeout=30)
            if df is None or len(df)<1000: raise RuntimeError(f'short history {0 if df is None else len(df)}')
            df.index=pd.to_datetime(df.index).tz_localize(None)
            cols=['Open','High','Low','Close','Volume']
            df=df[cols].copy().apply(pd.to_numeric,errors='coerce').dropna(subset=['Open','High','Low','Close'])
            return df[~df.index.duplicated(keep='last')].sort_index()
        except Exception as e:
            last=e; time.sleep(3*(i+1))
    raise RuntimeError(f'price download failed {ticker}: {last}')

def fred(series):
    url=f'https://fred.stlouisfed.org/graph/fredgraph.csv?id={series}&cosd=2016-01-01&coed=2026-08-26'
    last=None
    for i in range(4):
        try:
            r=requests.get(url,timeout=40,headers={'User-Agent':'Mozilla/5.0'}); r.raise_for_status()
            from io import StringIO
            d=pd.read_csv(StringIO(r.text)); d.columns=['date',series]
            d['date']=pd.to_datetime(d['date']); d[series]=pd.to_numeric(d[series],errors='coerce')
            return d.set_index('date')[series]
        except Exception as e:
            last=e; time.sleep(2*(i+1))
    print('WARN FRED',series,last); return pd.Series(dtype=float,name=series)

def yahoo_close(ticker,name):
    try:
        d=yf.Ticker(ticker).history(start='2016-01-01',end=END,auto_adjust=False,actions=False,repair=True,timeout=30)
        if len(d)==0:return pd.Series(dtype=float,name=name)
        d.index=pd.to_datetime(d.index).tz_localize(None); s=pd.to_numeric(d['Close'],errors='coerce'); s.name=name; return s
    except Exception as e:
        print('WARN yahoo macro',ticker,e); return pd.Series(dtype=float,name=name)

def build_macro():
    series=['BAMLH0A0HYM2','DGS2','DGS10','DGS30','DFF','CPIAUCNS','CPILFENS']
    m=pd.concat([fred(s) for s in series],axis=1).sort_index()
    m['VIX']=yahoo_close('^VIX','VIX'); m['MOVE']=yahoo_close('^MOVE','MOVE'); m['DXY']=yahoo_close('DX-Y.NYB','DXY'); m['WTI']=yahoo_close('CL=F','WTI')
    for s,out in [('CPIAUCNS','CPI_YOY'),('CPILFENS','CORE_CPI_YOY')]:
        x=m[s].dropna(); yoy=x.pct_change(12)*100
        avail=pd.Series(yoy.values,index=(yoy.index+pd.DateOffset(months=1,days=14)),name=out); m=m.join(avail,how='outer')
    m=m.sort_index().ffill(); hy=m['BAMLH0A0HYM2']; vix=m['VIX']; move=m['MOVE']
    m['HY_5D']=hy-hy.shift(5); m['HY_20D']=hy-hy.shift(20); m['VIX_5D']=vix-vix.shift(5); m['MOVE_5D']=move-move.shift(5)
    m['DGS2_60D']=m['DGS2']-m['DGS2'].shift(60); m['DFF_60D']=m['DFF']-m['DFF'].shift(60)
    hy_stress=(hy>4.5)|(m['HY_20D']>1.0)|(m['HY_5D']>0.5); vol_stress=((vix>30)|((vix>25)&(m['VIX_5D']>7))); move_stress=((move>140)|((move>120)&(m['MOVE_5D']>20)))
    m['MACRO_VETO']=(hy_stress | (vol_stress & move_stress) | ((hy>3.5)&(vix>25))).fillna(False)
    m['MACRO_HEADWIND']=((m['CPI_YOY']>4.0)&((m['DGS2_60D']>0.75)|(m['DFF_60D']>0.50))).fillna(False)
    m['MACRO_STRESS_SCORE']=((hy.clip(2,8)-2)/6+(vix.clip(10,50)-10)/40+(move.clip(70,180)-70)/110)/3
    return m

def ema(s,span): return s.ewm(span=span,adjust=False,min_periods=span).mean()
def wilder(s,n): return s.ewm(alpha=1/n,adjust=False,min_periods=n).mean()
def rolling_pct(s,w,minp=None):
    if minp is None:minp=max(20,w//4)
    def f(a):
        if np.isnan(a[-1]):return np.nan
        b=a[np.isfinite(a)]; return np.mean(b<=a[-1]) if len(b)>=5 else np.nan
    return s.rolling(w,min_periods=minp).apply(f,raw=True)
def td_counts(close):
    hi=[];lo=[];hc=lc=0;vals=close.values
    for i,x in enumerate(vals):
        if i<4 or not np.isfinite(x) or not np.isfinite(vals[i-4]):hc=lc=0
        elif x>vals[i-4]:hc=min(hc+1,9);lc=0
        elif x<vals[i-4]:lc=min(lc+1,9);hc=0
        else:hc=lc=0
        hi.append(hc);lo.append(lc)
    return pd.Series(hi,index=close.index),pd.Series(lo,index=close.index)
def add_indicators(df,pct_window=252):
    x=df.copy();c=x.Close;h=x.High;l=x.Low;v=x.Volume.replace(0,np.nan)
    x['MA20']=c.rolling(20).mean();x['MA50']=c.rolling(50).mean();x['MA200']=c.rolling(200).mean(); x['TD_HIGH'],x['TD_LOW']=td_counts(c)
    ll=l.rolling(9).min();hh=h.rolling(9).max();rsv=(c-ll)/(hh-ll).replace(0,np.nan)*100;K=[];D=[];kp=dp=50.0
    for rv in rsv:
        if np.isfinite(rv):kp=(2*kp+rv)/3;dp=(2*dp+kp)/3
        K.append(kp);D.append(dp)
    x['K']=K;x['D']=D;dif=ema(c,12)-ema(c,26);dea=ema(dif,9);x['DIF']=dif;x['DEA']=dea;x['MACD_HIST']=dif-dea
    delta=c.diff();rs=wilder(delta.clip(lower=0),14)/wilder(-delta.clip(upper=0),14);x['RSI']=100-100/(1+rs)
    prev=c.shift(1);tr=pd.concat([(h-l),(h-prev).abs(),(l-prev).abs()],axis=1).max(axis=1);x['ATR']=wilder(tr,14);x['ATR_PCT']=x.ATR/c
    mid=(h+l)/2;box=(h-l).replace(0,np.nan);x['EMV']=(mid.diff()*box/(v/1e8)).rolling(14).mean();x['MACD_PCT']=rolling_pct(x.MACD_HIST,pct_window);x['EMV_PCT']=rolling_pct(x.EMV,pct_window);x['ATR_PCT_RANK']=rolling_pct(x.ATR_PCT,pct_window)
    for n in [5,20,50]:x[f'VOL_MA{n}']=x.Volume.rolling(n).mean();x[f'VOL_R{n}']=x.Volume/x[f'VOL_MA{n}']
    x['DD252']=c/c.rolling(252,min_periods=60).max()-1;pivot=(l==l.rolling(11,center=True,min_periods=11).min());x['PIVOT_CONFIRMED']=l.where(pivot).shift(5);x['LAST_PIVOT']=x.PIVOT_CONFIRMED.ffill();x['PIVOT_ATR_DIST']=(c-x.LAST_PIVOT)/x.ATR
    return x
def period_bars(df,freq):
    p=df.index.to_period(freq);g=df.groupby(p);z=pd.DataFrame({'Open':g.Open.first(),'High':g.High.max(),'Low':g.Low.min(),'Close':g.Close.last(),'Volume':g.Volume.sum()});z.index=pd.DatetimeIndex([df.index[p==k].max() for k in z.index]);return z.sort_index()
def asof_cols(base,other,prefix,cols):
    tmp=other[cols].copy();tmp.columns=[prefix+c for c in cols];return pd.merge_asof(base.sort_index().reset_index().rename(columns={'index':'date'}),tmp.sort_index().reset_index().rename(columns={'index':'date'}),on='date',direction='backward').set_index('date')
def make_signals(asset,df,macro):
    x=add_indicators(df);wb=add_indicators(period_bars(df,'W-FRI'),52);mb=add_indicators(period_bars(df,'M'),36)
    x=asof_cols(x,wb,'W_',['Close','MA20','TD_HIGH','TD_LOW','K','D','MACD_HIST','RSI','EMV','Volume']);x=asof_cols(x,mb,'M_',['Close','MA20','TD_HIGH','TD_LOW','K','D','MACD_HIST','RSI','EMV','Volume'])
    mac=macro.reindex(macro.index.union(x.index)).sort_index().ffill().reindex(x.index)
    for col in ['BAMLH0A0HYM2','VIX','MOVE','DGS2','DGS10','DGS30','DFF','CPI_YOY','CORE_CPI_YOY','MACRO_VETO','MACRO_HEADWIND','MACRO_STRESS_SCORE']:x['X_'+col]=mac[col] if col in mac else np.nan
    c=x.Close;x['W_HIST_D']=x.W_MACD_HIST.diff();weekly_bear=(x.W_Close<x.W_MA20)&(x.W_MACD_HIST<0)&(x.W_HIST_D<0);weekly_strong=(x.W_Close>x.W_MA20)&(x.W_MACD_HIST>0);monthly_broken=(x.M_Close<x.M_MA20)&(x.M_MACD_HIST<0);monthly_strong=(x.M_Close>x.M_MA20)&(x.M_MACD_HIST>0)
    oversold=(x.K<20)|(x.RSI<30);overbought=(x.K>80)|(x.RSI>70);deep=(x.MACD_PCT<=.10)|(x.EMV_PCT<=.10);dd_thr=PARAMS[asset]['dd_threshold'];support=(x.PIVOT_ATR_DIST.abs()<=1)&(x.DD252<=-.05);price_attractive=(x.DD252<=dd_thr)|(c<=x.MA50-1.5*x.ATR)|support;very_cheap=x.DD252<=min(-.15,dd_thr-.05)
    kd_up=(x.K>x.D)&(x.K.shift(1)<=x.D.shift(1))&(x.K.shift(1)<35);kd_dn=(x.K<x.D)&(x.K.shift(1)>=x.D.shift(1))&(x.K.shift(1)>65);hist_rising=(x.MACD_HIST>x.MACD_HIST.shift(1))&(x.MACD_HIST.shift(1)>x.MACD_HIST.shift(2));dif_up=x.DIF>x.DIF.shift(1);rsi_recover=((x.RSI>30)&(x.RSI.shift(1)<=30))|(x.RSI>x.RSI.shift(3)+3);ma20_regain=(c>x.MA20)&(c.shift(1)<=x.MA20.shift(1));emv_recover=(x.EMV>x.EMV.shift(1))&(x.EMV>x.EMV.shift(3));upvol=(c>c.shift(1))&(x.VOL_R20>1.1);rcount=pd.concat([kd_up,hist_rising,dif_up,rsi_recover,ma20_regain,emv_recover,upvol],axis=1).sum(axis=1);recent_over=oversold.rolling(20,min_periods=1).max().astype(bool)
    macro_veto=x.X_MACRO_VETO.fillna(False).astype(bool);head=x.X_MACRO_HEADWIND.fillna(False).astype(bool);runaway_up=((x.TD_HIGH>=8)|overbought)&(c>x.MA20)&(x.MA20>x.MA50)&weekly_strong&(~monthly_broken)&(~macro_veto);downvol=(c<c.shift(1))&(x.VOL_R20>1.3);runaway_dn=((x.TD_LOW>=8)|oversold)&(c<x.MA20)&(x.MA20<x.MA50)&weekly_bear&(macro_veto|downvol)
    hist_fall=(x.MACD_HIST<x.MACD_HIST.shift(1))&(x.MACD_HIST.shift(1)<x.MACD_HIST.shift(2));dif_dn=x.DIF<x.DIF.shift(1);ma20_break=(c<x.MA20)&(c.shift(1)>=x.MA20.shift(1));emv_weak=(x.EMV<0)&(x.EMV<x.EMV.shift(2));stall=(c<=c.shift(1))&(x.VOL_R20>1.2);weak_count=pd.concat([kd_dn,hist_fall,dif_dn,ma20_break,emv_weak,stall],axis=1).sum(axis=1);trim=((x.TD_HIGH>=8)|overbought)&(weak_count>=2)&(~runaway_up);risk=macro_veto&weekly_bear&((c<x.MA200)|monthly_broken);left=price_attractive&oversold&((x.TD_LOW>=4)|deep)&(~weekly_bear)&(~monthly_broken)&(~macro_veto)&((~head)|very_cheap);right=recent_over&(rcount>=3)&(~weekly_bear)&(~macro_veto)&((~head)|(c>x.MA50))
    state=pd.Series('WAIT',index=x.index,dtype='object');state[runaway_up]='STRONG_WAIT';state[left]='LEFT_BUY';state[right]='RIGHT_ADD';state[trim]='TECH_TRIM';state[runaway_dn]='RUNAWAY_DOWN';state[risk]='RISK_DOWN';x['STATE']=state;x['PRICE_ATTRACTIVE']=price_attractive;x['OVERSOLD']=oversold;x['OVERBOUGHT']=overbought;x['WEEKLY_BEAR_ACCEL']=weekly_bear;x['WEEKLY_STRONG']=weekly_strong;x['MONTHLY_BROKEN']=monthly_broken;x['MONTHLY_STRONG']=monthly_strong;x['RUNAWAY_UP']=runaway_up;x['RUNAWAY_DOWN']=runaway_dn;x['RIGHT_COUNT']=rcount
    rng=(x.High-x.Low).replace(0,np.nan);x['CAPITULATION']=(c<c.shift(1))&(x.VOL_R20>=1.8)&(x.RSI<35)&(rng>=1.5*x.ATR)&(((c-x.Low)/rng)>=.5);return x
def crosses(a,level,dir='down'):
    return ((a<=level)&(a.shift(1)>level)) if dir=='down' else ((a>=level)&(a.shift(1)<level))
def build_events(asset,x):
    trig={};trig['MONTH_START']=x.index.to_period('M')!=pd.Series(x.index.to_period('M'),index=x.index).shift(1).values;trig['TD_HIGH_MATURE']=x.TD_HIGH.isin([8,9])&(~x.TD_HIGH.shift(1).isin([8,9]));trig['TD_LOW_MID']=x.TD_LOW.isin([5,6])&(~x.TD_LOW.shift(1).isin([5,6]));trig['TD_LOW_DEEP']=x.TD_LOW.isin([8,9])&(~x.TD_LOW.shift(1).isin([8,9]));trig['KD_LOW_ENTER']=crosses(x.K,20,'down');trig['KD_HIGH_ENTER']=crosses(x.K,80,'up');trig['KD_CROSS']=((x.K>x.D)&(x.K.shift(1)<=x.D.shift(1)))|((x.K<x.D)&(x.K.shift(1)>=x.D.shift(1)));trig['RSI30']=crosses(x.RSI,30,'down')|crosses(x.RSI,30,'up');trig['RSI70']=crosses(x.RSI,70,'down')|crosses(x.RSI,70,'up');trig['MACD_EXTREME']=crosses(x.MACD_PCT,.10,'down')|crosses(x.MACD_PCT,.90,'up')|crosses(x.MACD_PCT,.05,'down')|crosses(x.MACD_PCT,.95,'up');trig['MACD_ZERO']=((x.MACD_HIST>=0)&(x.MACD_HIST.shift(1)<0))|((x.MACD_HIST<0)&(x.MACD_HIST.shift(1)>=0))
    for n in [20,50,200]:trig[f'MA{n}_CROSS']=((x.Close>=x[f'MA{n}'])&(x.Close.shift(1)<x[f'MA{n}'].shift(1)))|((x.Close<x[f'MA{n}'])&(x.Close.shift(1)>=x[f'MA{n}'].shift(1)))
    sup=x.LAST_PIVOT;trig['PIVOT_CROSS']=((x.Close>=sup)&(x.Close.shift(1)<sup.shift(1)))|((x.Close<sup)&(x.Close.shift(1)>=sup.shift(1)));regime=pd.cut(x.ATR_PCT_RANK,[-np.inf,.80,.95,np.inf],labels=['N','H','X']);trig['VOL_REGIME']=regime!=regime.shift(1);trig['CAPITULATION']=x.CAPITULATION;trig['MACRO_VETO']=x.X_MACRO_VETO.fillna(False).astype(bool)!=x.X_MACRO_VETO.fillna(False).astype(bool).shift(1).fillna(False);trig['RUNAWAY_UP']=x.RUNAWAY_UP!=x.RUNAWAY_UP.shift(1).fillna(False);trig['RUNAWAY_DOWN']=x.RUNAWAY_DOWN!=x.RUNAWAY_DOWN.shift(1).fillna(False);trig['STATE_CHANGE']=x.STATE!=x.STATE.shift(1)
    event_lists=[[] for _ in range(len(x))];last={}
    for name,s in trig.items():
        for i,b in enumerate(s.fillna(False).values):
            if not b:continue
            if name not in ['MONTH_START','STATE_CHANGE'] and i-last.get(name,-999)<=5:continue
            event_lists[i].append(name);last[name]=i
    rows=[]
    for i,(dt,r) in enumerate(x.iterrows()):
        if not event_lists[i] or i+1>=len(x):continue
        nxt=x.iloc[i+1];execdt=x.index[i+1];entry=float(nxt.Open);atr=float(r.ATR) if np.isfinite(r.ATR) else np.nan;gap_atr=(entry-float(r.Close))/atr if np.isfinite(atr) and atr>0 else np.nan;state=r.STATE;executed_state=state;execution='OBSERVE'
        if state in ['LEFT_BUY','RIGHT_ADD','STRONG_WAIT']:
            execution='EXECUTED';threshold=.75 if state=='STRONG_WAIT' else 1.0
            if np.isfinite(gap_atr) and gap_atr>threshold:execution='CANCEL_GAP_UP';executed_state='WAIT' if state!='STRONG_WAIT' else 'STRONG_WAIT'
            elif np.isfinite(gap_atr) and gap_atr<-1.0:execution='HALF_GAP_DOWN'
        elif state in ['TECH_TRIM','RUNAWAY_DOWN','RISK_DOWN']:execution='EXECUTED_REDUCE'
        def outcome(n):
            if i+1+n>len(x)-1:return (np.nan,)*5
            path=x.iloc[i+1:i+1+n];ret=float(path.Close.iloc[-1]/entry-1);hi_idx=path.High.idxmax();lo_idx=path.Low.idxmin();mfe=float(path.High.max()/entry-1);mae=float(path.Low.min()/entry-1);return ret,mae,mfe,int(x.index.get_loc(lo_idx)-(i+1)),int(x.index.get_loc(hi_idx)-(i+1))
        o21=outcome(21);o63=outcome(63);o126=outcome(126);row={'asset':asset,'signal_date':dt,'execution_date':execdt,'triggers':';'.join(event_lists[i]),'state':state,'executed_state':executed_state,'execution':execution,'signal_close':r.Close,'entry_open':entry,'gap_atr':gap_atr,'TD_HIGH':r.TD_HIGH,'TD_LOW':r.TD_LOW,'K':r.K,'D':r.D,'RSI':r.RSI,'MACD_HIST':r.MACD_HIST,'MACD_PCT':r.MACD_PCT,'EMV_PCT':r.EMV_PCT,'ATR_PCT':r.ATR_PCT,'ATR_RANK':r.ATR_PCT_RANK,'DD252':r.DD252,'VOL_R20':r.VOL_R20,'weekly_bear_accel':r.WEEKLY_BEAR_ACCEL,'monthly_broken':r.MONTHLY_BROKEN,'macro_veto':r.X_MACRO_VETO,'macro_headwind':r.X_MACRO_HEADWIND,'hy_oas':r.X_BAMLH0A0HYM2,'vix':r.X_VIX,'move':r.X_MOVE,'cpi_yoy':r.X_CPI_YOY}
        for nm,o in [('1m',o21),('3m',o63),('6m',o126)]:row[f'ret_{nm}'],row[f'mae_{nm}'],row[f'mfe_{nm}'],row[f't_mae_{nm}'],row[f't_mfe_{nm}']=o
        rows.append(row)
    e=pd.DataFrame(rows)
    if len(e):
        def score(r):
            if pd.isna(r.ret_3m):return np.nan
            st=r.executed_state
            if st in ['LEFT_BUY','RIGHT_ADD']:return bool(((r.ret_3m>=.03) or (r.mfe_3m>=.08)) and r.mae_3m>-.10)
            if st=='STRONG_WAIT':return bool(((r.ret_3m>=.02) or (r.mfe_3m>=.05)) and r.mae_3m>-.10)
            if st in ['WAIT','TECH_TRIM']:return bool((r.ret_3m<=.03) or (r.mae_3m<=-.05))
            if st in ['RUNAWAY_DOWN','RISK_DOWN']:return bool((r.ret_3m<=0) or (r.mae_3m<=-.08))
            return np.nan
        e['correct_3m']=e.apply(score,axis=1);e['month_start']=e.triggers.str.contains('MONTH_START')
    return e
def benchmark_monthly(asset,x):
    first=~x.index.to_period('M').duplicated();rows=[]
    for i in np.where(first)[0]:
        if i+1>=len(x) or i+1+63>len(x)-1:continue
        entry=float(x.iloc[i+1].Open);p=x.iloc[i+1:i+1+63];rows.append({'asset':asset,'signal_date':x.index[i],'entry':entry,'ret_3m':p.Close.iloc[-1]/entry-1,'mae_3m':p.Low.min()/entry-1,'mfe_3m':p.High.max()/entry-1})
    b=pd.DataFrame(rows)
    if len(b):b['buy_correct']=((b.ret_3m>=.03)|(b.mfe_3m>=.08))&(b.mae_3m>-.10)
    return b
def summarize(events,bench):
    mature=events[events.correct_3m.notna()].copy();rows=[]
    for asset,g in mature.groupby('asset'):
        bg=bench[bench.asset==asset];rows.append({'asset':asset,'events_mature':len(g),'accuracy_3m':g.correct_3m.mean(),'mean_ret_3m':g.ret_3m.mean(),'median_ret_3m':g.ret_3m.median(),'mean_mae_3m':g.mae_3m.mean(),'mean_mfe_3m':g.mfe_3m.mean(),'median_mae_3m':g.mae_3m.median(),'median_mfe_3m':g.mfe_3m.median(),'month_start_events':int(g.month_start.sum()),'month_start_accuracy':g.loc[g.month_start,'correct_3m'].mean(),'benchmark_monthly_buy_accuracy':bg.buy_correct.mean() if len(bg) else np.nan,'benchmark_monthly_mean_ret3m':bg.ret_3m.mean() if len(bg) else np.nan})
    s=pd.DataFrame(rows)
    if len(s):s.loc[len(s)]={'asset':'ALL_EQUAL_WEIGHT','events_mature':s.events_mature.sum(),'accuracy_3m':s.accuracy_3m.mean(),'mean_ret_3m':s.mean_ret_3m.mean(),'median_ret_3m':s.median_ret_3m.mean(),'mean_mae_3m':s.mean_mae_3m.mean(),'mean_mfe_3m':s.mean_mfe_3m.mean(),'median_mae_3m':s.median_mae_3m.mean(),'median_mfe_3m':s.median_mfe_3m.mean(),'month_start_events':s.month_start_events.sum(),'month_start_accuracy':s.month_start_accuracy.mean(),'benchmark_monthly_buy_accuracy':s.benchmark_monthly_buy_accuracy.mean(),'benchmark_monthly_mean_ret3m':s.benchmark_monthly_mean_ret3m.mean()}
    return s
def main():
    macro=build_macro();macro.to_csv(OUT/'macro_daily.csv');all_events=[];all_bench=[]
    for asset,ticker in ASSETS.items():
        print('RUN',asset,ticker);p=get_prices(ticker);p.to_csv(OUT/f'{asset}_ohlcv.csv');sig=make_signals(asset,p,macro);sig.to_csv(OUT/f'{asset}_daily_signals.csv');e=build_events(asset,sig);e.to_csv(OUT/f'{asset}_events.csv',index=False);all_events.append(e);b=benchmark_monthly(asset,sig);b.to_csv(OUT/f'{asset}_monthly_benchmark.csv',index=False);all_bench.append(b)
    events=pd.concat(all_events,ignore_index=True);bench=pd.concat(all_bench,ignore_index=True);events.to_csv(OUT/'ALL_events.csv',index=False);bench.to_csv(OUT/'ALL_monthly_benchmark.csv',index=False);summary=summarize(events,bench);summary.to_csv(OUT/'summary.csv',index=False);mature=events[events.correct_3m.notna()];state=mature.groupby(['asset','executed_state']).agg(n=('correct_3m','size'),accuracy=('correct_3m','mean'),ret3=('ret_3m','mean'),mae3=('mae_3m','mean'),mfe3=('mfe_3m','mean')).reset_index();state.to_csv(OUT/'state_summary.csv',index=False);yearly=mature.assign(year=pd.to_datetime(mature.signal_date).dt.year).groupby(['asset','year']).agg(n=('correct_3m','size'),accuracy=('correct_3m','mean'),mae3=('mae_3m','mean'),mfe3=('mfe_3m','mean'),ret3=('ret_3m','mean')).reset_index();yearly.to_csv(OUT/'yearly_summary.csv',index=False)
    def wilson(k,n,z=1.96):
        if n==0:return(np.nan,np.nan)
        p=k/n;den=1+z*z/n;ctr=(p+z*z/(2*n))/den;half=z*math.sqrt(p*(1-p)/n+z*z/(4*n*n))/den;return ctr-half,ctr+half
    cis=[]
    for a,g in mature.groupby('asset'):
        lo,hi=wilson(int(g.correct_3m.sum()),len(g));cis.append({'asset':a,'n':len(g),'correct':int(g.correct_3m.sum()),'accuracy':g.correct_3m.mean(),'ci95_low':lo,'ci95_high':hi})
    pd.DataFrame(cis).to_csv(OUT/'accuracy_ci.csv',index=False)
    (OUT/'README.md').write_text('# Formal Backtest V1\n\nDaily OHLCV + true daily/weekly/monthly technicals + T+1 + Gap Recheck + High/Low MAE/MFE. Point-in-time macro veto uses daily market series (HY OAS, VIX, MOVE, Treasury yields, effective fed funds). CPI uses non-seasonally-adjusted YoY delayed ~45 days. GDP/PAYEMS are intentionally excluded from scoring in V1 because exact ALFRED vintages are not fetched, preventing revision look-ahead bias. Historical unstructured news/institution forecasts are not machine-scored; this is the formal quantifiable core.\n',encoding='utf-8')
    print('SUMMARY\n'+summary.to_string(index=False));print('STATE\n'+state.to_string(index=False));print('CI\n'+pd.DataFrame(cis).to_string(index=False))
if __name__=='__main__':main()
