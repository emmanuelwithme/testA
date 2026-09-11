from __future__ import annotations

import json
import time
import xml.etree.ElementTree as ET
from pathlib import Path

import pandas as pd
import requests

FORMAL_START = pd.Timestamp('2005-01-01')
FORMAL_END = pd.Timestamp('2026-08-31')
BASE = 'https://home.treasury.gov/resource-center/data-chart-center/interest-rates/pages/xml'
HEADERS = {
    'User-Agent': 'Mozilla/5.0 LivingWaterAI research backtest/1.0',
    'Accept': 'application/xml,text/xml,*/*',
    'Connection': 'close',
}
OUT = Path('v70_treasury_rates_probe_output')
OUT.mkdir(exist_ok=True)


def _local(tag: str) -> str:
    return tag.split('}', 1)[-1]


def _fetch_year(data_key: str, year: int, attempts: int = 3) -> list[dict[str, str]]:
    params = {'data': data_key, 'field_tdr_date_value': str(year)}
    last_exc = None
    for attempt in range(1, attempts + 1):
        try:
            r = requests.get(BASE, params=params, timeout=(10, 35), headers=HEADERS)
            r.raise_for_status()
            root = ET.fromstring(r.content)
            rows: list[dict[str, str]] = []
            for entry in root.iter():
                if _local(entry.tag).lower() != 'entry':
                    continue
                row: dict[str, str] = {}
                for node in entry.iter():
                    name = _local(node.tag)
                    if node.text and node.text.strip():
                        row[name] = node.text.strip()
                if row:
                    rows.append(row)
            if not rows:
                raise RuntimeError(f'{data_key} {year}: no XML entry rows')
            return rows
        except Exception as exc:
            last_exc = exc
            if attempt < attempts:
                time.sleep(attempt)
    raise RuntimeError(f'{data_key} {year}: fetch/parse failed: {last_exc!r}')


def _first_value(row: dict[str, str], candidates: list[str]) -> str | None:
    upper = {k.upper(): v for k, v in row.items()}
    for c in candidates:
        if c.upper() in upper:
            return upper[c.upper()]
    return None


def _to_frame(rows: list[dict[str, str]], kind: str) -> pd.DataFrame:
    out = []
    for row in rows:
        date_raw = _first_value(row, ['NEW_DATE', 'TDR_DATE', 'DATE'])
        if not date_raw:
            # Treasury entries often include a generic updated/published date plus NEW_DATE.
            # Never guess from unrelated XML timestamps.
            continue
        dt = pd.to_datetime(date_raw, errors='coerce')
        if pd.isna(dt):
            continue
        if kind == 'nominal':
            v5 = _first_value(row, ['BC_5YEAR'])
            if v5 is None:
                continue
            out.append({'date': dt, 'nominal_5y': pd.to_numeric(v5, errors='coerce')})
        elif kind == 'real':
            v5 = _first_value(row, ['TC_5YEAR'])
            v10 = _first_value(row, ['TC_10YEAR'])
            if v5 is None and v10 is None:
                continue
            out.append({
                'date': dt,
                'real_5y': pd.to_numeric(v5, errors='coerce'),
                'real_10y': pd.to_numeric(v10, errors='coerce'),
            })
        else:
            raise ValueError(kind)
    df = pd.DataFrame(out)
    if df.empty:
        raise RuntimeError(f'{kind}: parsed zero usable observations')
    return df.sort_values('date').drop_duplicates('date', keep='last')


def fetch_treasury_rate_components() -> pd.DataFrame:
    """Fetch official Treasury 5Y nominal, 5Y real and 10Y real observations.

    This helper provides raw official components only. It deliberately does not
    declare FRED-series equivalence or PIT/T+1 readiness; those remain separate QA gates.
    """
    nominal_rows: list[dict[str, str]] = []
    real_rows: list[dict[str, str]] = []

    for year in range(FORMAL_START.year, FORMAL_END.year + 1):
        nominal_rows.extend(_fetch_year('daily_treasury_yield_curve', year))
        real_rows.extend(_fetch_year('daily_treasury_real_yield_curve', year))

    nominal = _to_frame(nominal_rows, 'nominal')
    real = _to_frame(real_rows, 'real')
    merged = nominal.merge(real, on='date', how='outer').sort_values('date')
    merged = merged[(merged['date'] >= FORMAL_START) & (merged['date'] <= FORMAL_END)].copy()
    merged['t5yie_candidate'] = merged['nominal_5y'] - merged['real_5y']
    return merged


def main() -> int:
    discovered = {'nominal': set(), 'real': set()}
    # Discovery is kept separate from the reusable fetch helper so the probe artifact
    # retains explicit field evidence without changing formal source semantics.
    nrows = _fetch_year('daily_treasury_yield_curve', FORMAL_START.year)
    rrows = _fetch_year('daily_treasury_real_yield_curve', FORMAL_START.year)
    for r in nrows[:3]:
        discovered['nominal'].update(r.keys())
    for r in rrows[:3]:
        discovered['real'].update(r.keys())

    merged = fetch_treasury_rate_components()

    def summary(col: str) -> dict:
        x = merged[['date', col]].dropna()
        return {
            'n': int(len(x)),
            'first_observation': None if x.empty else str(x['date'].min().date()),
            'last_observation': None if x.empty else str(x['date'].max().date()),
            'last_value': None if x.empty else float(x.iloc[-1][col]),
        }

    report = {
        'source': 'U.S. Department of the Treasury Daily Interest Rate XML Feed',
        'formal_window': f'{FORMAL_START.date()}..{FORMAL_END.date()}',
        'transport_status': 'RAW_SOURCE_OK_OFFICIAL_TREASURY',
        'discovered_tags': {k: sorted(v) for k, v in discovered.items()},
        'DFII10_candidate': {
            **summary('real_10y'),
            'treasury_field': 'TC_10YEAR',
            'formal_pit_ready': False,
            'qa_note': 'Official Treasury real 10Y raw data retrieved. Must pass equivalence and publication-availability/T+1 QA against locked DFII10 semantics before formal use.',
        },
        'T5YIE_candidate': {
            **summary('t5yie_candidate'),
            'formula': 'BC_5YEAR - TC_5YEAR',
            'formal_pit_ready': False,
            'qa_note': 'FRED defines T5YIE from 5Y nominal and 5Y inflation-indexed constant maturity yields. Treasury official components retrieved; exact historical equivalence and publication-availability/T+1 QA remain mandatory before formal use.',
        },
        'formal_backtest_ready': False,
    }
    (OUT / 'treasury_rates_probe.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    merged.to_csv(OUT / 'treasury_rates_components.csv', index=False)
    print(json.dumps(report, ensure_ascii=False, indent=2))

    ok = report['DFII10_candidate']['n'] > 0 and report['T5YIE_candidate']['n'] > 0
    return 0 if ok else 2


if __name__ == '__main__':
    raise SystemExit(main())
