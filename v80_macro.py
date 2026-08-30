from io import StringIO
from pathlib import Path
import time
import numpy as np
import pandas as pd
import requests
import yfinance as yf

START='2016-01-01'
END='2026-08-26'


def _read_csv_url(url, date_col='observation_date', value_col='value', name=None):
    last=None
    for i in range(4):
        try:
            r=requests.get(url,timeout=45,headers={'User-Agent':'Mozilla/5.0'}); r.raise_for_status()
            d=pd.read_csv(StringIO(r.text))
            if date_col not in d.columns: date_col=d.columns[0]
            if value_col not in d.columns: value_col=d.columns[1]
            d[date_col]=pd.to_datetime(d[date_col],errors='coerce')
            s=pd.to_numeric(d[value_col],errors='coerce')
            out=pd.Series(s.values,index=d[date_col],name=name or value_col).dropna()
            out=out[~out.index.isna()].sort_index()
            if len(out)<100: raise RuntimeError(f'short series {len(out)}')
            return out
        except Exception as e:
            last=e; time.sleep(2*(i+1))
    print('WARN mirror',name,last)
    return pd.Series(dtype=float,name=name)


def _licensed_hy_override(path='data/licensed/hyoas_bamlh0a0hym2.csv'):
    p=Path(path)
    if not p.exists(): return pd.Series(dtype=float,name='BAMLH0A0HYM2')
    try:
        d=pd.read_csv(p)
        dc='trade_date' if 'trade_date' in d.columns else ('date' if 'date' in d.columns else None)
        vc='value' if 'value' in d.columns else ('BAMLH0A0HYM2' if 'BAMLH0A0HYM2' in d.columns else None)
        if dc is None or vc is None: raise ValueError('licensed HYOAS CSV requires trade_date/date and value/BAMLH0A0HYM2')
        dt=pd.to_datetime(d[dc],errors='coerce'); val=pd.to_numeric(d[vc],errors='coerce')
        z=pd.DataFrame({'date':dt,'value':val}).dropna().sort_values('date')
        if z.date.duplicated().any() or len(z)<525: raise ValueError('licensed HYOAS CSV duplicate dates or insufficient history')
        if not np.isfinite(z.value).all() or (z.value<0).any() or (z.value>30).any(): raise ValueError('licensed HYOAS values invalid')
        s=pd.Series(z.value.values,index=z.date,name='BAMLH0A0HYM2')
        print('HY OAS source=licensed_csv_override',s.index.min(),s.index.max(),len(s))
        return s
    except Exception as e:
        print('WARN licensed HYOAS override rejected',e)
        return pd.Series(dtype=float,name='BAMLH0A0HYM2')


def _validated_public_hy_history():
    historical=_read_csv_url(
        'https://raw.githubusercontent.com/maaurocp/Trading_Protocol/2b4beabfa89088dce2a877c272dd2dc6038f029d/data/raw/fred_BAMLH0A0HYM2.csv',
        date_col='date',value_col='BAMLH0A0HYM2',name='BAMLH0A0HYM2')
    recent=_read_csv_url(
        'https://raw.githubusercontent.com/TGRADEA/gradea-fred-archive/main/BAMLH0A0HYM2.csv',
        name='BAMLH0A0HYM2')
    if len(historical)==0: return pd.Series(dtype=float,name='BAMLH0A0HYM2')
    if historical.index.min()>pd.Timestamp('2016-01-15') or historical.index.max()<pd.Timestamp('2025-12-01'):
        print('WARN historical HY snapshot rejected: insufficient span',historical.index.min(),historical.index.max())
        return pd.Series(dtype=float,name='BAMLH0A0HYM2')
    if len(recent):
        ov=pd.concat([historical.rename('historical'),recent.rename('recent')],axis=1,join='inner').dropna()
        if len(ov)<250:
            print('WARN HY snapshot rejected: insufficient overlap',len(ov))
            return pd.Series(dtype=float,name='BAMLH0A0HYM2')
        diff=(ov['historical']-ov['recent']).abs()
        print('HY OAS overlap validation n=',len(ov),'max_abs_diff=',float(diff.max()),'mean_abs_diff=',float(diff.mean()))
        if float(diff.max())>0.03 or float(diff.mean())>0.005:
            print('WARN HY snapshot rejected: overlap mismatch')
            return pd.Series(dtype=float,name='BAMLH0A0HYM2')
        combined=recent.combine_first(historical).sort_index()
    else:
        combined=historical.sort_index()
    combined.name='BAMLH0A0HYM2'
    print('HY OAS source=validated_pre_restriction_snapshot_plus_recent',combined.index.min(),combined.index.max(),len(combined))
    return combined


def _bls_series(series_id, name):
    rows=[]
    for start,end in [(2016,2018),(2019,2021),(2022,2024),(2025,2026)]:
        try:
            r=requests.post('https://api.bls.gov/publicAPI/v2/timeseries/data/',json={'seriesid':[series_id],'startyear':str(start),'endyear':str(end)},timeout=45,headers={'User-Agent':'Mozilla/5.0'})
            r.raise_for_status(); j=r.json()
            if j.get('status')!='REQUEST_SUCCEEDED': raise RuntimeError(f"BLS status={j.get('status')} message={j.get('message')}")
            ser=j.get('Results',{}).get('series',[])
            if not ser: raise RuntimeError('BLS empty series')
            got=0
            for z in ser[0].get('data',[]):
                p=z.get('period','')
                if not p.startswith('M') or p=='M13': continue
                y=int(z['year']); m=int(p[1:]); v=pd.to_numeric(z.get('value'),errors='coerce')
                if pd.notna(v): rows.append((pd.Timestamp(y,m,1),float(v))); got+=1
            print('BLS',series_id,start,end,'rows=',got)
        except Exception as e: print('WARN BLS',series_id,start,end,e)
    if not rows: return pd.Series(dtype=float,name=name)
    d=pd.DataFrame(rows,columns=['date','value']).drop_duplicates('date').sort_values('date')
    mi=pd.date_range(d.date.min(),d.date.max(),freq='MS')
    return pd.Series(d.value.values,index=d.date,name=name).reindex(mi)


def _yahoo_close(ticker,name,scale=1.0):
    try:
        d=yf.Ticker(ticker).history(start=START,end=END,auto_adjust=False,actions=False,repair=False,timeout=60)
        if len(d)==0: return pd.Series(dtype=float,name=name)
        d.index=pd.to_datetime(d.index).tz_localize(None)
        s=pd.to_numeric(d['Close'],errors='coerce')*scale; s.name=name
        return s.dropna()
    except Exception as e:
        print('WARN yahoo',ticker,e); return pd.Series(dtype=float,name=name)


def build_macro_v80():
    base='https://raw.githubusercontent.com/TGRADEA/gradea-fred-archive/main/'
    hy=_licensed_hy_override()
    if len(hy)==0: hy=_validated_public_hy_history()
    d2=_read_csv_url(base+'DGS2.csv',name='DGS2'); d10=_read_csv_url(base+'DGS10.csv',name='DGS10')
    d30=_yahoo_close('^TYX','DGS30')
    if len(d30) and d30.median()>20: d30=d30/10.0
    cpi=_bls_series('CUUR0000SA0','CPI_LEVEL'); core=_bls_series('CUUR0000SA0L1E','CORE_CPI_LEVEL')
    cpi_yoy=cpi.pct_change(12,fill_method=None)*100 if len(cpi) else pd.Series(dtype=float)
    core_yoy=core.pct_change(12,fill_method=None)*100 if len(core) else pd.Series(dtype=float)
    if len(cpi_yoy): cpi_yoy.index=cpi_yoy.index+pd.DateOffset(months=1,days=14)
    if len(core_yoy): core_yoy.index=core_yoy.index+pd.DateOffset(months=1,days=14)
    cpi_yoy.name='CPI_YOY'; core_yoy.name='CORE_CPI_YOY'

    vix=_yahoo_close('^VIX','VIX')
    move=_yahoo_close('^MOVE','MOVE')
    dxy=_yahoo_close('DX-Y.NYB','DXY')
    wti=_yahoo_close('CL=F','WTI')
    # Yahoo JPY=X is USD/JPY (yen per U.S. dollar). Falling USDJPY means yen appreciation.
    usdjpy=_yahoo_close('JPY=X','USDJPY')

    idx=pd.date_range(START,END,freq='D'); m=pd.DataFrame(index=idx)
    for s in [hy,d2,d10,d30,cpi_yoy,core_yoy,vix,move,dxy,wti,usdjpy]:
        if len(s): m=m.join(s,how='outer')
    m=m.sort_index().ffill()
    if 'DFF' not in m: m['DFF']=np.nan
    for c in ['BAMLH0A0HYM2','DGS2','DGS10','DGS30','CPI_YOY','CORE_CPI_YOY','VIX','MOVE','DXY','USDJPY']:
        if c not in m: m[c]=np.nan

    hy=m['BAMLH0A0HYM2']; vix=m['VIX']; move=m['MOVE']
    m['HY_5D']=hy-hy.shift(5); m['HY_20D']=hy-hy.shift(20)
    m['VIX_5D']=vix-vix.shift(5); m['MOVE_5D']=move-move.shift(5)
    m['DGS2_60D']=m['DGS2']-m['DGS2'].shift(60); m['DFF_60D']=m['DFF']-m['DFF'].shift(60)

    # Yen carry-trade radar. These are market-observed point-in-time inputs only.
    # Positive JPY_APPRECIATION means the yen strengthened against the dollar.
    m['USDJPY_1D_PCT']=m['USDJPY'].pct_change(1)*100
    m['USDJPY_5D_PCT']=m['USDJPY'].pct_change(5)*100
    m['JPY_APPRECIATION_1D_PCT']=-m['USDJPY_1D_PCT']
    m['JPY_APPRECIATION_5D_PCT']=-m['USDJPY_5D_PCT']
    m['DXY_5D_PCT']=m['DXY'].pct_change(5)*100

    yen_fast=(m['JPY_APPRECIATION_1D_PCT']>=1.5)|(m['JPY_APPRECIATION_5D_PCT']>=3.0)
    yen_severe=(m['JPY_APPRECIATION_1D_PCT']>=2.5)|(m['JPY_APPRECIATION_5D_PCT']>=5.0)
    yen_confirm_count=pd.concat([
        (m['VIX_5D']>5.0),
        (m['MOVE_5D']>10.0),
        (m['HY_5D']>0.25),
    ],axis=1).fillna(False).sum(axis=1)
    m['YEN_CARRY_CONFIRM_COUNT']=yen_confirm_count.astype(int)
    m['YEN_CARRY_RISK_LEVEL']=np.select(
        [yen_severe&(yen_confirm_count>=2), yen_fast&(yen_confirm_count>=1), yen_fast],
        [3,2,1], default=0).astype(int)
    m['YEN_CARRY_HEADWIND']=(m['YEN_CARRY_RISK_LEVEL']>=1)
    # Yen alone never gets a hard veto. Level 3 requires severe yen appreciation PLUS
    # at least two cross-asset stress confirmations (VIX/MOVE/HY OAS).
    m['YEN_CARRY_VETO']=(m['YEN_CARRY_RISK_LEVEL']>=3)
    m['YEN_CARRY_BUY_SCALE']=m['YEN_CARRY_RISK_LEVEL'].map({0:1.0,1:0.75,2:0.50,3:0.0}).astype(float)

    hy_stress=(hy>4.5)|(m['HY_20D']>1.0)|(m['HY_5D']>0.5)
    vol_stress=(vix>30)|((vix>25)&(m['VIX_5D']>7))
    move_stress=(move>140)|((move>120)&(m['MOVE_5D']>20))
    base_veto=(hy_stress|(vol_stress&move_stress)|((hy>3.5)&(vix>25)))
    m['MACRO_VETO']=(base_veto|m['YEN_CARRY_VETO']).fillna(False)
    inflation_headwind=((m['CPI_YOY']>4.0)&(m['DGS2_60D']>0.75))
    m['MACRO_HEADWIND']=(inflation_headwind|m['YEN_CARRY_HEADWIND']).fillna(False)

    base_stress=((hy.clip(2,8)-2)/6+(vix.clip(10,50)-10)/40+(move.clip(70,180)-70)/110)/3
    yen_stress=m['YEN_CARRY_RISK_LEVEL']/3.0
    # Keep legacy macro stress comparable while allowing the yen radar to raise stress modestly.
    m['MACRO_STRESS_SCORE']=(0.85*base_stress+0.15*yen_stress).clip(0,1.5)
    return m
