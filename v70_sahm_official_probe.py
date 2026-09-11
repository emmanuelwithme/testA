from __future__ import annotations

from io import StringIO
from pathlib import Path
import hashlib
import json
import re
import time
import requests
import pandas as pd

OUT = Path('v70_sahm_official_probe_output')
OUT.mkdir(exist_ok=True)
REPORT = OUT / 'sahm_probe.json'
FORMAL_START = pd.Timestamp('2005-01-01')
FORMAL_END = pd.Timestamp('2026-08-31')
SERIES_ID = 'SAHMREALTIME'
SNAPSHOT = Path('data/official_snapshots/SAHMREALTIME_2005_2026-08.csv')
SNAPSHOT_META = Path('data/official_snapshots/SAHMREALTIME_2005_2026-08.meta.json')
SNAPSHOT_SHA256 = '51c1ee746c15578b98ebda8f5f63bf9f293694b17b2655b2c77e3d0a6fe346ba'
HEADERS = {
    'User-Agent': 'Mozilla/5.0 LivingWaterAI research backtest/1.0',
    'Accept': 'text/csv,text/plain,text/html,*/*',
    'Connection': 'close',
}


def _clip(df: pd.DataFrame, dc: str, vc: str) -> pd.Series:
    dt = pd.to_datetime(df[dc], errors='coerce')
    val = pd.to_numeric(df[vc], errors='coerce')
    s = pd.Series(val.values, index=dt, name=SERIES_ID).dropna()
    s = s[~s.index.isna()].sort_index()
    s = s[(s.index >= FORMAL_START) & (s.index <= FORMAL_END)]
    s = s[~s.index.duplicated(keep='last')]
    if s.empty:
        raise RuntimeError('SAHMREALTIME: no usable observations in formal window')
    return s


def _parse_csv(text: str) -> pd.Series:
    df = pd.read_csv(StringIO(text))
    if len(df.columns) < 2:
        raise RuntimeError(f'malformed csv columns={list(df.columns)}')
    return _clip(df, df.columns[0], df.columns[1])


def _parse_table_text(text: str) -> pd.Series:
    pairs = []
    for line in text.splitlines():
        m = re.match(r'^\s*(\d{4}-\d{2}-\d{2})\s*[|,\t ]+\s*([+-]?(?:\d+(?:\.\d*)?|\.\d+))\s*$', line)
        if m:
            pairs.append((m.group(1), m.group(2)))
    if not pairs:
        raise RuntimeError('no DATE/VALUE pairs parsed')
    return _clip(pd.DataFrame(pairs, columns=['DATE', SERIES_ID]), 'DATE', SERIES_ID)


def _load_pinned_official_snapshot() -> tuple[pd.Series, dict]:
    if not SNAPSHOT.exists() or not SNAPSHOT_META.exists():
        raise RuntimeError('pinned official SAHM snapshot or metadata missing')

    raw = SNAPSHOT.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if digest != SNAPSHOT_SHA256:
        raise RuntimeError(f'pinned snapshot sha256 mismatch: {digest}')

    meta = json.loads(SNAPSHOT_META.read_text(encoding='utf-8'))
    if meta.get('series_id') != SERIES_ID:
        raise RuntimeError('pinned snapshot series_id mismatch')
    if meta.get('official_source') != 'Federal Reserve Bank of St. Louis FRED':
        raise RuntimeError('pinned snapshot official-source provenance mismatch')
    if meta.get('sha256') != digest:
        raise RuntimeError('pinned snapshot metadata sha256 mismatch')
    if meta.get('formal_pit_ready') is not False:
        raise RuntimeError('pinned snapshot must remain formal_pit_ready=false at raw-source stage')

    df = pd.read_csv(SNAPSHOT)
    if list(df.columns) != ['DATE', SERIES_ID]:
        raise RuntimeError(f'pinned snapshot columns mismatch: {list(df.columns)}')
    if len(df) != 260:
        raise RuntimeError(f'pinned snapshot row count mismatch: {len(df)}')

    dates = pd.to_datetime(df['DATE'], errors='raise')
    expected = pd.date_range('2005-01-01', '2026-08-01', freq='MS')
    if not dates.equals(pd.Series(expected)):
        raise RuntimeError('pinned snapshot month coverage mismatch')

    missing = dates[pd.to_numeric(df[SERIES_ID], errors='coerce').isna()].dt.strftime('%Y-%m-%d').tolist()
    if missing != ['2025-10-01']:
        raise RuntimeError(f'unexpected pinned snapshot missing values: {missing}')

    return _clip(df, 'DATE', SERIES_ID), meta


def fetch_sahm_official(attempts: int = 2) -> tuple[pd.Series, str, dict]:
    # All network candidates are official Federal Reserve Bank of St. Louis/FRED paths.
    # If GitHub runner transport to FRED times out, use a hash-pinned snapshot copied
    # from the same official FRED SAHMREALTIME table. This is not a third-party proxy.
    candidates = [
        ('FRED_SERIES_DOWNLOAD_CSV', f'https://fred.stlouisfed.org/series/{SERIES_ID}/downloaddata/{SERIES_ID}.csv', 'csv'),
        ('FRED_DATA_TABLE', f'https://fred.stlouisfed.org/data/{SERIES_ID}', 'text'),
        ('FRED_STATIC_TXT', f'https://fred.stlouisfed.org/data/{SERIES_ID}.txt', 'text'),
        ('FRED_GRAPH_CSV', f'https://fred.stlouisfed.org/graph/fredgraph.csv?id={SERIES_ID}', 'csv'),
    ]
    errors = []
    for label, url, kind in candidates:
        for attempt in range(1, attempts + 1):
            try:
                r = requests.get(url, timeout=(8, 25), headers=HEADERS, allow_redirects=True)
                r.raise_for_status()
                s = _parse_csv(r.text) if kind == 'csv' else _parse_table_text(r.text)
                return s, label, {'network_errors_before_success': errors}
            except Exception as exc:
                errors.append({'label': label, 'attempt': attempt, 'error': repr(exc)})
                if attempt < attempts:
                    time.sleep(attempt)

    s, meta = _load_pinned_official_snapshot()
    return s, 'OFFICIAL_FRED_PINNED_SNAPSHOT', {
        'network_errors_before_success': errors,
        'snapshot_meta': meta,
    }


def main() -> int:
    report = {
        'logical_input': 'SAHM_RULE',
        'series_id': SERIES_ID,
        'source': 'Federal Reserve Bank of St. Louis FRED official series only',
        'formal_window': '2005-01-01..2026-08-31',
        'formal_pit_ready': False,
        'status': 'NOT_RUN',
    }
    try:
        s, transport, provenance = fetch_sahm_official()
        status = (
            'RAW_SOURCE_OK_OFFICIAL_FRED_PINNED_SNAPSHOT'
            if transport == 'OFFICIAL_FRED_PINNED_SNAPSHOT'
            else 'RAW_SOURCE_OK_OFFICIAL_FRED_ALTERNATE'
        )
        report.update({
            'status': status,
            'transport': transport,
            'first_observation': str(s.index.min().date()),
            'last_observation': str(s.index.max().date()),
            'n': int(len(s)),
            'latest_value': float(s.iloc[-1]),
            'provenance': provenance,
            'pit_note': 'SAHMREALTIME is explicitly a real-time indicator series. Formal weekly use still requires release-availability/T+1 mapping and gap QA before backtest integration.',
        })
        REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0
    except Exception as exc:
        report.update({
            'status': 'OFFICIAL_FRED_SOURCE_FAIL',
            'error': repr(exc),
            'pit_note': 'Failure is not evidence that SAHMREALTIME is unavailable. No third-party proxy substituted.',
        })
        REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
