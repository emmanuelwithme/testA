import functools
import pandas as pd
import v82_backtest_phase1 as b

@functools.lru_cache(maxsize=1)
def irx_proxy():
    d=b.dl('^IRX','2018-01-01','2026-09-02')
    s=pd.to_numeric(d.Close,errors='coerce').dropna()
    s.name='rate'
    return s

# Replace the fragile direct FRED call with Yahoo's historical 13-week T-bill yield proxy.
# This keeps the pre-SGOV parking leg point-in-time and avoids fabricating SGOV before inception.
b.fred_dtb3=irx_proxy

if __name__=='__main__':
    b.main()
