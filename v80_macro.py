from io import StringIO
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
            if date_col not in d.columns:
                date_col=d.columns[0]
            if value_col not in d.columns:
                value_col=d.columns[1]
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


def _bls_series(series_id, name):
    rows=[]
    for start,end in [(2016,2020),(2021,2026)]:
        try:
            r=requests.post('https://api.bls.gov/publicAPI/v2/timeseries/data/',json={'seriesid':[series_id],'startyear':str(start),'endyear':str(end)},timeout=45,headers={'User-Agent':'Mozilla/5.0'})
            r.raise_for_status(); j=r.json()
            ser=j.get('Results',{}).get('series',[])
            if not ser: continue
            for z in ser[0].get('data',[]):
                p=z.get('period','')
                if not p.startswith('M') or p=='M13': continue
                y=int(z['year']); m=int(p[1:])
                rows.append((pd.Timestamp(y,m,1),float(z['value'])))
        except Exception as e:
            print('WARN BLS',series_id,start,end,e)
    if not rows: return pd.Series(dtype=float,name=name)
    d=pd.DataFrame(rows,columns=['date','value']).drop_duplicates('date').sort_values('date')
    s=pd.Series(d.value.values,index=d.date,name=name)
    return s


def _yahoo_close(ticker,name,scale=1.0):
    try:
        d=yf.Ticker(ticker).history(start=START,end=END,auto_adjust=False,actions=False,repair=False,timeout=60)
        if len(d)==0: return pd.Series(dtype=float,name=name)
        d.index=pd.to_datetime(d.index).tz_localize(None)
        s=pd.to_numeric(d['Close'],errors='coerce')*scale; s.name=name
        return s.dropna()
    except Exception as e:
        print('WARN yahoo',ticker,e)
        return pd.Series(dtype=float,name=name)


def build_macro_v80():
    base='https://raw.githubusercontent.com/TGRADEA/gradea-fred-archive/main/'
    hy=_read_csv_url(base+'BAMLH0A0HYM2.csv',name='BAMLH0A0HYM2')
    d2=_read_csv_url(base+'DGS2.csv',name='DGS2')
    d10=_read_csv_url(base+'DGS10.csv',name='DGS10')
    # Yahoo ^TYX is the CBOE 30-year Treasury yield index quoted as yield x10.
    d30=_yahoo_close('^TYX','DGS30')
    if len(d30) and d30.median()>20: d30=d30/10.0
    cpi=_bls_series('CUUR0000SA0','CPI_LEVEL')
    core=_bls_series('CUUR0000SA0L1E','CORE_CPI_LEVEL')
    cpi_yoy=cpi.pct_change(12)*100 if len(cpi) else pd.Series(dtype=float)
    core_yoy=core.pct_change(12)*100 if len(core) else pd.Series(dtype=float)
    # Point-in-time: monthly CPI for month t becomes available around the middle of t+1.
    if len(cpi_yoy): cpi_yoy.index=cpi_yoy.index+pd.DateOffset(months=1,days=14)
    if len(core_yoy): core_yoy.index=core_yoy.index+pd.DateOffset(months=1,days=14)
    cpi_yoy.name='CPI_YOY'; core_yoy.name='CORE_CPI_YOY'
    vix=_yahoo_close('^VIX','VIX'); move=_yahoo_close('^MOVE','MOVE')
    dxy=_yahoo_close('DX-Y.NYB','DXY'); wti=_yahoo_close('CL=F','WTI')
    # DFF is not required for the hard veto; leave as NaN if official FRED is unavailable.
    idx=pd.date_range(START,END,freq='D')
    m=pd.DataFrame(index=idx)
    for s in [hy,d2,d10,d30,cpi_yoy,core_yoy,vix,move,dxy,wti]:
        if len(s): m=m.join(s,how='outer')
    m=m.sort_index().ffill()
    if 'DFF' not in m: m['DFF']=np.nan
    hy=m.get('BAMLH0A0HYM2',pd.Series(index=m.index,dtype=float))
    vix=m.get('VIX',pd.Series(index=m.index,dtype=float)); move=m.get('MOVE',pd.Series(index=m.index,dtype=float))
    m['HY_5D']=hy-hy.shift(5); m['HY_20D']=hy-hy.shift(20)
    m['VIX_5D']=vix-vix.shift(5); m['MOVE_5D']=move-move.shift(5)
    m['DGS2_60D']=m['DGS2']-m['DGS2'].shift(60)
    m['DFF_60D']=m['DFF']-m['DFF'].shift(60)
    hy_stress=(hy>4.5)|(m['HY_20D']>1.0)|(m['HY_5D']>0.5)
    vol_stress=(vix>30)|((vix>25)&(m['VIX_5D']>7))
    move_stress=(move>140)|((move>120)&(m['MOVE_5D']>20))
    m['MACRO_VETO']=(hy_stress|(vol_stress&move_stress)|((hy>3.5)&(vix>25))).fillna(False)
    m['MACRO_HEADWIND']=((m['CPI_YOY']>4.0)&((m['DGS2_60D']>0.75)|(m['DFF_60D']>0.50))).fillna(False)
    m['MACRO_STRESS_SCORE']=((hy.clip(2,8)-2)/6+(vix.clip(10,50)-10)/40+(move.clip(70,180)-70)/110)/3
    return m
