from __future__ import annotations
import json, math
from pathlib import Path
from typing import Dict, List, Tuple
import numpy as np
import pandas as pd
import requests
import yfinance as yf

START='2005-01-01'; END='2026-09-01'; FORMAL_END=pd.Timestamp('2026-08-31')
ANNUAL=1_000_000.0; MONTHLY=ANNUAL/12.0
STOCKS={'0050':'0050.TW','VWRA':'VWRA.L','QQQ':'QQQ','SOXX':'SOXX','PPH':'PPH','NATO':'NATO.L'}
BONDS={'TLT':'TLT','IEF':'IEF','SPLB':'SPLB','SPIB':'SPIB','SPSB':'SPSB'}
RISK={**STOCKS,**BONDS}; OUT=Path('backtest_33_output'); OUT.mkdir(exist_ok=True)

def get_yf(ticker):
    d=yf.download(ticker,start=START,end=END,auto_adjust=True,repair=True,progress=False,actions=False,threads=False)
    if d.empty:return pd.Series(dtype=float)
    c=d['Close']; c=c.iloc[:,0] if isinstance(c,pd.DataFrame) else c
    c=pd.to_numeric(c,errors='coerce').dropna().astype(float); c.index=pd.to_datetime(c.index).tz_localize(None)
    return c.sort_index()

def fx_usdtwd():
    r=requests.get('https://fred.stlouisfed.org/graph/fredgraph.csv?id=DEXTAUS',timeout=45); r.raise_for_status()
    d=pd.read_csv(pd.io.common.StringIO(r.text)); d.columns=['date','fx']; d.date=pd.to_datetime(d.date); d.fx=pd.to_numeric(d.fx,errors='coerce')
    return d.dropna().set_index('date').fx.sort_index().loc[START:FORMAL_END]

def dtb3():
    r=requests.get('https://fred.stlouisfed.org/graph/fredgraph.csv?id=DTB3',timeout=45); r.raise_for_status()
    d=pd.read_csv(pd.io.common.StringIO(r.text)); d.columns=['date','rate']; d.date=pd.to_datetime(d.date); d.rate=pd.to_numeric(d.rate,errors='coerce')
    return d.dropna().set_index('date').rate.sort_index().loc[START:FORMAL_END]

def prices_twd():
    fx=fx_usdtwd(); out={}
    for name,t in RISK.items():
        s=get_yf(t)
        if s.empty: out[name]=s; continue
        twd=s if name=='0050' else (s*fx.reindex(s.index,method='ffill')).dropna()
        bad=twd.pct_change().abs()>0.55
        if bad.any(): twd=twd.loc[bad[bad].index[0]:]
        twd.name=name; out[name]=twd
    return out,fx

def parking_index(fx):
    # Formal parking proxy: DTB3 before SGOV history; actual SGOV adjusted total-return price after inception.
    rate=dtb3(); days=pd.date_range(START,FORMAL_END,freq='D')
    rr=rate.reindex(days,method='ffill').fillna(0)/100.0
    base=pd.Series(index=days,dtype=float); base.iloc[0]=1.0
    for i in range(1,len(days)):
        base.iloc[i]=base.iloc[i-1]*(1+rr.iloc[i-1])**(1/365.2425)
    sgov=get_yf('SGOV')
    if len(sgov):
        sgov_twd=(sgov*fx.reindex(sgov.index,method='ffill')).dropna()
        first=sgov_twd.index.min(); anchor=float(base.loc[first])
        actual=anchor*(sgov_twd/float(sgov_twd.loc[first]))
        base.loc[actual.index]=actual.values
        base=base.sort_index().ffill()
    return base

def first_valid(s,nominal):
    x=s.index[s.index>=nominal]; return x[0] if len(x) else None

def eligible(s,nominal):
    if s.empty:return False
    first=s.index.min()
    if first<=nominal:return True
    # Allow only an early-month first observation (holiday/data-boundary), never a mid-month listing/backfill.
    return first.year==nominal.year and first.month==nominal.month and first.day<=7

def unitize(nav,flows):
    f={}
    for d,v in flows:f[d]=f.get(d,0.0)+v
    u=[]; unit=1.0; prev=None
    for d,v in nav.items():
        flow=f.get(d,0.0)
        if prev is not None and prev>0:
            unit*=max((float(v)-flow)/prev,0.0)
        u.append(unit); prev=float(v)
    return pd.Series(u,index=nav.index,name='unit')

def xirr(cfs):
    if not cfs or not any(v<0 for _,v in cfs) or not any(v>0 for _,v in cfs):return np.nan
    t0=cfs[0][0]
    def f(r):return sum(v/((1+r)**((d-t0).days/365.2425)) for d,v in cfs)
    lo,hi=-.999,10.; flo,fhi=f(lo),f(hi)
    for _ in range(20):
        if flo*fhi<=0:break
        hi*=2; fhi=f(hi)
    if flo*fhi>0:return np.nan
    for _ in range(160):
        mid=(lo+hi)/2; fm=f(mid)
        if flo*fm<=0:hi=mid; fhi=fm
        else:lo=mid; flo=fm
    return (lo+hi)/2

def twr_metrics(nav,unit,flows):
    total=sum(v for _,v in flows); end=float(nav.iloc[-1]); r=unit.pct_change().dropna(); dd=unit/unit.cummax()-1
    yrs=(unit.index[-1]-unit.index[0]).days/365.2425
    cagr=(unit.iloc[-1]/unit.iloc[0])**(1/yrs)-1 if yrs>0 else np.nan
    sh=r.mean()/r.std()*math.sqrt(365.2425) if len(r)>2 and r.std()>0 else np.nan
    dn=r[r<0]; so=r.mean()/dn.std()*math.sqrt(365.2425) if len(dn)>2 and dn.std()>0 else np.nan
    mdd=float(dd.min()); cal=cagr/abs(mdd) if mdd<0 else np.nan
    cf=[(d,-v) for d,v in flows]+[(nav.index[-1],end)]
    return dict(total_cost_twd=total,ending_asset_twd=end,total_profit_twd=end-total,total_return=end/total-1 if total else np.nan,
                xirr_mwr=xirr(cf),twr_cagr=cagr,unitized_mdd=mdd,sharpe=sh,sortino=so,calmar=cal)

def build_schedule(assets,mode,p):
    # events: (date, asset, amount). flows: external annual 1m dates.
    events=[]; flows=[]; years=range(2005,2027)
    single=mode.split(':')[1] if 'single:' in mode else None
    monthly=mode.startswith('monthly')
    for y in years:
        if pd.Timestamp(y,1,1)>=pd.Timestamp(END):continue
        if not monthly:
            nominal=pd.Timestamp(y,1,1)
            if single:
                s=p[single]
                if not eligible(s,nominal):continue
                d=first_valid(s,nominal)
                if d is None or d.year!=y or d>FORMAL_END:continue
                flows.append((d,ANNUAL)); events.append((d,single,ANNUAL))
            else:
                active=[a for a in assets if eligible(p[a],nominal)]
                if not active:continue
                dates={a:first_valid(p[a],nominal) for a in active}
                active=[a for a in active if dates[a] is not None and dates[a].year==y and dates[a]<=FORMAL_END]
                if not active:continue
                d=min(dates[a] for a in active); flows.append((d,ANNUAL)); each=ANNUAL/len(active)
                for a in active:events.append((dates[a],a,each))
        else:
            month_specs=[]
            for m in range(1,13):
                nominal=pd.Timestamp(y,m,1)
                if nominal>=pd.Timestamp(END):continue
                if single:
                    s=p[single]
                    if not eligible(s,nominal):continue
                    d=first_valid(s,nominal)
                    if d is None or d.month!=m or d.year!=y or d>FORMAL_END:continue
                    month_specs.append((d,[single]))
                else:
                    active=[a for a in assets if eligible(p[a],nominal)]
                    dates={a:first_valid(p[a],nominal) for a in active}
                    active=[a for a in active if dates[a] is not None and dates[a].month==m and dates[a].year==y and dates[a]<=FORMAL_END]
                    if active:month_specs.append((min(dates[a] for a in active),[(a,dates[a]) for a in active]))
            if not month_specs:continue
            flow_date=month_specs[0][0]; flows.append((flow_date,ANNUAL))
            for d,spec in month_specs:
                if single:events.append((d,single,MONTHLY))
                else:
                    each=MONTHLY/len(spec)
                    for a,da in spec:events.append((da,a,each))
    return sorted(events),sorted(flows)

def simulate(name,assets,mode,p,park):
    events,flows=build_schedule(assets,mode,p)
    if not flows:return {'model':name,'status':'N/A_NO_EFFECTIVE_CONTRIBUTION'},None
    first=min(d for d,_ in flows); last=FORMAL_END
    idx=pd.date_range(first,last,freq='D')
    flowmap={}; evmap={}
    for d,v in flows:flowmap[d]=flowmap.get(d,0)+v
    for d,a,v in events:evmap.setdefault(d,[]).append((a,v))
    h={}; pcash=0.0; prev=None; nav=[]; exps=[]
    for d in idx:
        if prev is not None and pcash>0:
            pi0=float(park.asof(prev)); pi1=float(park.asof(d));
            if pi0>0:pcash*=pi1/pi0
        pcash+=flowmap.get(d,0.0)
        for a,amt in evmap.get(d,[]):
            spend=min(amt,pcash); px=float(p[a].asof(d))
            if spend>0 and np.isfinite(px) and px>0:
                h[a]=h.get(a,0)+spend/px; pcash-=spend
        vals={a:sh*float(p[a].asof(d)) for a,sh in h.items() if np.isfinite(float(p[a].asof(d)))}
        n=pcash+sum(vals.values()); nav.append(n)
        sv=sum(v for a,v in vals.items() if a in STOCKS); bv=sum(v for a,v in vals.items() if a in BONDS)
        exps.append((sv/n if n else 0,bv/n if n else 0,pcash/n if n else 0,vals))
        prev=d
    nav=pd.Series(nav,index=idx,name=name); u=unitize(nav,flows); met=twr_metrics(nav,u,flows)
    row={'model':name,'status':'OK',**met,'avg_stock_exposure':float(np.mean([x[0] for x in exps])),'avg_bond_exposure':float(np.mean([x[1] for x in exps])),'avg_parking_exposure':float(np.mean([x[2] for x in exps]))}
    return row,{'nav':nav,'unit':u,'flows':flows,'exps':exps}

def annual_rows(model,res):
    nav,u,flows=res['nav'],res['unit'],res['flows']; fdf=pd.DataFrame(flows,columns=['date','amount'])
    rows=[]
    for y in sorted(set(nav.index.year)):
        ny=nav[nav.index.year==y]; uy=u[u.index.year==y]
        if ny.empty:continue
        prevu=u[u.index<uy.index[0]]; base=float(prevu.iloc[-1]) if len(prevu) else float(uy.iloc[0])
        ar=float(uy.iloc[-1]/base-1) if base else np.nan; dd=uy/uy.cummax()-1; trough=dd.idxmin(); mdd=float(dd.min()); peakval=float(uy.loc[:trough].max()); peak=uy.loc[:trough][uy.loc[:trough]>=peakval*(1-1e-12)].index[-1]
        rec=u[u.index>=trough]; rec=rec[rec>=peakval]; rd=rec.index[0] if len(rec) else None; rend=bool(rd is not None and rd<=ny.index[-1]); rdays=(rd-peak).days if rd is not None else np.nan
        risk='高：年底未恢復前高' if not rend else ('高：年內MDD≤-30%' if mdd<=-.30 else ('中高' if mdd<=-.20 or (np.isfinite(rdays) and rdays>365) else ('中' if mdd<=-.10 or (np.isfinite(rdays) and rdays>180) else '低')))
        begin=float(nav[nav.index<ny.index[0]].iloc[-1]) if len(nav[nav.index<ny.index[0]]) else 0.0; added=float(fdf[fdf.date.dt.year==y].amount.sum()) if len(fdf) else 0.0
        rows.append(dict(model=model,year=y,beginning_asset_twd=begin,external_contribution_twd=added,ending_asset_twd=float(ny.iloc[-1]),annual_return=ar,annual_mdd=mdd,mdd_peak_date=str(peak.date()),mdd_trough_date=str(trough.date()),peak_to_trough_days=(trough-peak).days,recovery_date=str(rd.date()) if rd is not None else None,recovery_time_days=rdays,recovered_by_year_end=rend,year_min_unit_nav=float(uy.min()),withdrawal_risk=risk))
    return rows

def cross_year(model,d):
    d=d.sort_values('year').copy(); r=d.annual_return.astype(float); tri=(1+r).rolling(3).apply(np.prod,raw=True)-1
    five=(1+r).rolling(5).apply(np.prod,raw=True)-1
    out=dict(model=model,negative_years=int((r<0).sum()),effective_years=len(d),annual_mdd_le_20_count=int((d.annual_mdd<=-.20).sum()),annual_mdd_le_30_count=int((d.annual_mdd<=-.30).sum()),annual_mdd_le_40_count=int((d.annual_mdd<=-.40).sum()),worst_calendar_year=int(d.loc[r.idxmin(),'year']),worst_calendar_year_return=float(r.min()),year_end_unrecovered_count=int((~d.recovered_by_year_end).sum()),longest_recovery_days=float(d.recovery_time_days.dropna().max()) if d.recovery_time_days.notna().any() else np.nan)
    if tri.notna().any():i=tri.idxmin(); y=int(d.loc[i,'year']); out.update(worst_3y_start=y-2,worst_3y_end=y,worst_3y_total_return=float(tri.loc[i]))
    if five.notna().any():i=five.idxmin(); y=int(d.loc[i,'year']); total=float(five.loc[i]); out.update(worst_5y_start=y-4,worst_5y_end=y,worst_5y_total_return=total,worst_5y_annualized=(1+total)**(1/5)-1)
    return out

def main():
    p,fx=prices_twd(); park=parking_index(fx); rows=[]; results={}
    rows.append({'model':'Case1_V82_plus_BondV75_dynamic_common_pool','status':'BLOCKED_UNPROGRAMMABLE_CROSS_ASSET_ALLOCATOR','reason':'V82/V75缺少共同資金不足時跨股票/債券的正式仲裁規則；依母規則不可人工補值。'})
    specs=[]
    for a in RISK:specs.append((f'Case2_AnnualSingle_{a}',[a],f'annual_single:{a}'))
    specs.append(('Case3_AnnualEqual_All11',list(RISK),'annual_equal'))
    for a in RISK:specs.append((f'Case4_MonthlySingle_{a}',[a],f'monthly_single:{a}'))
    specs += [('Case5_MonthlyEqual_All11',list(RISK),'monthly_equal'),('Case6_AnnualEqual_Stocks6',list(STOCKS),'annual_equal')]
    for a in STOCKS:specs.append((f'Case7_MonthlySingleStock_{a}',[a],f'monthly_single:{a}'))
    specs.append(('Case8_MonthlyEqual_Stocks6',list(STOCKS),'monthly_equal'))
    for n,a,m in specs:
        row,res=simulate(n,a,m,p,park); rows.append(row); results[n]=res
    df=pd.DataFrame(rows); assert len(df)==33; df.to_csv(OUT/'model_summary.csv',index=False)
    annual=[]
    for n,res in results.items():
        if res:annual.extend(annual_rows(n,res))
    adf=pd.DataFrame(annual); adf.to_csv(OUT/'annual_risk_by_model.csv',index=False)
    pd.DataFrame([cross_year(m,g) for m,g in adf.groupby('model')]).to_csv(OUT/'cross_year_risk_summary.csv',index=False)
    adf[adf.year.isin([2008,2020,2022])].to_csv(OUT/'stress_2008_2020_2022.csv',index=False)
    audit=[{'asset':a,'first_valid':str(s.index.min().date()) if len(s) else None,'last_valid':str(s.index.max().date()) if len(s) else None,'n_obs':len(s)} for a,s in p.items()]
    pd.DataFrame(audit).to_csv(OUT/'data_audit.csv',index=False)
    qa=adf.groupby(['model','year']).external_contribution_twd.sum().reset_index(); bad=qa[qa.external_contribution_twd>ANNUAL+0.01]
    status={'engine':'v2','formal_window':'2005-01-01..2026-08-31','expected_models':33,'actual_models':len(df),'ok_models':int((df.status=='OK').sum()),'blocked_models':int(df.status.astype(str).str.startswith('BLOCKED').sum()),'parking':'DTB3 official 3m Treasury proxy before SGOV history; actual adjusted SGOV total return after inception; TWD converted with Fed H.10 DEXTAUS','qa_contribution_over_1m_rows':len(bad),'case1_blocker':rows[0]}
    (OUT/'run_status.json').write_text(json.dumps(status,ensure_ascii=False,indent=2),encoding='utf-8')
    qa.to_csv(OUT/'annual_contribution_qa.csv',index=False)
    if len(bad):raise RuntimeError('Contribution QA failed: > NT$1m in an effective year')
    print(df[['model','status','ending_asset_twd','xirr_mwr','twr_cagr','unitized_mdd']].to_string(index=False)); print(json.dumps(status,ensure_ascii=False))
if __name__=='__main__':main()
