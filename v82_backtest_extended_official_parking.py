import time
import traceback
import xml.etree.ElementTree as ET
from io import StringIO
from pathlib import Path

import numpy as np
import pandas as pd
import requests

import v82_backtest_extended_adjusted as a

# a imports the extended engine and applies the corporate-action-safe price,
# official USD/TWD, total-return and stress-window patches. This wrapper only
# hardens the parking-rate source. It does not alter any V82 strategy rule.
e = a.e


def official_3m_parking_rate():
    """Official 3-month U.S. Treasury yield for the pre-SGOV parking proxy.

    Primary source: FRED DTB3.
    Fallback: U.S. Treasury daily 3-month constant-maturity yield XML.
    Yahoo ^IRX is deliberately excluded after an impossible vendor jump was
    observed on 2020-03-30.
    """
    url = (
        'https://fred.stlouisfed.org/graph/fredgraph.csv?'
        'id=DTB3&cosd=2004-01-01&coed=2026-08-31'
    )
    last = None
    for wait in (0, 2, 5):
        try:
            if wait:
                time.sleep(wait)
            rr = requests.get(url, timeout=45, headers={'User-Agent': 'Mozilla/5.0'})
            rr.raise_for_status()
            z = pd.read_csv(StringIO(rr.text))
            z.columns = ['date', 'rate']
            z['date'] = pd.to_datetime(z['date'], errors='coerce')
            z['rate'] = pd.to_numeric(z['rate'], errors='coerce')
            out = z.dropna().set_index('date').rate.sort_index().astype(float)
            if len(out) < 1000:
                raise RuntimeError(f'DTB3 short series {len(out)}')
            if not np.isfinite(out).all() or (out < -1).any() or (out > 30).any():
                raise RuntimeError('FRED DTB3 sanity failure')
            print(
                'PARKING RATE source=FRED_DTB3 rows=', len(out),
                'start=', out.index.min(), 'end=', out.index.max()
            )
            return out
        except Exception as exc:
            last = exc
            print('WARN FRED DTB3 retry:', exc)

    print(
        'WARN FRED DTB3 unavailable; using official U.S. Treasury 3M CMT fallback:',
        last,
    )
    rows = []
    ns = {
        'atom': 'http://www.w3.org/2005/Atom',
        'm': 'http://schemas.microsoft.com/ado/2007/08/dataservices/metadata',
        'd': 'http://schemas.microsoft.com/ado/2007/08/dataservices',
    }
    for year in range(2004, 2027):
        yurl = (
            'https://home.treasury.gov/resource-center/data-chart-center/'
            'interest-rates/pages/xml?data=daily_treasury_yield_curve&'
            f'field_tdr_date_value={year}'
        )
        ylast = None
        success = False
        for wait in (0, 2, 5):
            try:
                if wait:
                    time.sleep(wait)
                rr = requests.get(yurl, timeout=45, headers={'User-Agent': 'Mozilla/5.0'})
                rr.raise_for_status()
                root = ET.fromstring(rr.content)
                n_before = len(rows)
                for entry in root.findall('atom:entry', ns):
                    props = entry.find('atom:content/m:properties', ns)
                    if props is None:
                        continue
                    dnode = props.find('d:NEW_DATE', ns)
                    vnode = props.find('d:BC_3MONTH', ns)
                    if dnode is None or vnode is None or not dnode.text or not vnode.text:
                        continue
                    dt = pd.to_datetime(dnode.text, errors='coerce')
                    val = pd.to_numeric(vnode.text, errors='coerce')
                    if pd.notna(dt) and pd.notna(val):
                        rows.append((pd.Timestamp(dt), float(val)))
                if len(rows) == n_before:
                    raise RuntimeError(f'no 3M observations parsed for {year}')
                success = True
                break
            except Exception as exc:
                ylast = exc
                print(f'WARN Treasury 3M {year} retry:', exc)
        if not success:
            raise RuntimeError(f'Official Treasury 3M fallback failed for {year}: {ylast}')

    out = pd.Series({d: v for d, v in rows}, dtype=float).sort_index()
    out = out[
        (out.index >= pd.Timestamp('2004-01-01'))
        & (out.index <= pd.Timestamp('2026-08-31'))
    ]
    out = out[~out.index.duplicated(keep='last')]
    if len(out) < 1000 or not np.isfinite(out).all() or (out < -1).any() or (out > 30).any():
        raise RuntimeError(f'Official Treasury 3M fallback sanity failure rows={len(out)}')
    print(
        'PARKING RATE source=US_TREASURY_3M_CMT rows=', len(out),
        'start=', out.index.min(), 'end=', out.index.max()
    )
    return out


# parking_long() resolves fred_dtb3_long from the extended module globals at
# runtime, so replacing this module attribute hardens only the data source.
e.fred_dtb3_long = official_3m_parking_rate


if __name__ == '__main__':
    try:
        e.main()
    except Exception:
        tb = traceback.format_exc()
        print(tb)
        out = Path('v82_extended_results')
        out.mkdir(exist_ok=True)
        (out / 'extended_failure.txt').write_text(tb, encoding='utf-8')
        raise
