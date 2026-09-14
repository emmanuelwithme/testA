from __future__ import annotations

import calendar
import html
import json
import re
from pathlib import Path

import pandas as pd
import requests

OUT = Path('v70_sahm_release_map_qa_output')
OUT.mkdir(exist_ok=True)
REPORT = OUT / 'sahm_release_map_qa.json'
CSV = OUT / 'sahm_release_map.csv'
ARCHIVE_URL = 'https://www.bls.gov/bls/news-release/empsit.htm'
FORMAL_START = pd.Timestamp('2005-01-01')
FORMAL_END = pd.Timestamp('2026-08-01')
KNOWN_OFFICIAL_SAHM_MISSING = {pd.Timestamp('2025-10-01')}
HEADERS = {
    'User-Agent': 'Mozilla/5.0 LivingWaterAI formal backtest QA/1.0',
    'Accept': 'text/html,*/*',
    'Connection': 'close',
}
MONTHS = {name.lower(): i for i, name in enumerate(calendar.month_name) if name}


def _clean_anchor_text(raw: str) -> str:
    raw = re.sub(r'<[^>]+>', ' ', raw)
    raw = html.unescape(raw)
    return re.sub(r'\s+', ' ', raw).strip()


def fetch_release_map() -> pd.DataFrame:
    r = requests.get(ARCHIVE_URL, timeout=(10, 45), headers=HEADERS)
    r.raise_for_status()
    text = r.text

    rows = []
    # BLS archive filenames encode the actual release date: empsit_MMDDYYYY.*
    # Anchor labels encode the reference month: "December 2019 Employment Situation".
    pattern = re.compile(
        r'<a\b[^>]*href=["\']([^"\']*empsit_([0-9]{8})[^"\']*)["\'][^>]*>(.*?)</a>',
        re.IGNORECASE | re.DOTALL,
    )
    for href, mmddyyyy, anchor_raw in pattern.findall(text):
        label = _clean_anchor_text(anchor_raw)
        m = re.search(r'([A-Za-z]+)\s+(20\d{2})\s+Employment\s+Situation', label, re.IGNORECASE)
        if not m:
            continue
        month_num = MONTHS.get(m.group(1).lower())
        if not month_num:
            continue
        year = int(m.group(2))
        reference_month = pd.Timestamp(year=year, month=month_num, day=1)
        release_date = pd.to_datetime(mmddyyyy, format='%m%d%Y', errors='coerce')
        if pd.isna(release_date):
            continue
        rows.append({
            'reference_month': reference_month,
            'release_date': release_date.normalize(),
            'archive_href': href,
            'anchor_label': label,
        })

    if not rows:
        raise RuntimeError('BLS_ARCHIVE_PARSED_ZERO_EMPLOYMENT_SITUATION_LINKS')

    df = pd.DataFrame(rows).sort_values(['reference_month', 'release_date'])
    # HTML/TXT/PDF duplicates for the same reference month are expected. They must
    # agree on release date. Multiple distinct release dates would be ambiguous.
    conflicts = (
        df.groupby('reference_month')['release_date']
        .nunique()
        .loc[lambda s: s > 1]
    )
    if not conflicts.empty:
        details = {
            str(k.date()): sorted(str(x.date()) for x in df.loc[df.reference_month == k, 'release_date'].unique())
            for k in conflicts.index
        }
        raise RuntimeError(f'BLS_RELEASE_DATE_CONFLICTS: {details}')

    out = df.drop_duplicates('reference_month', keep='first').copy()
    out = out[(out.reference_month >= FORMAL_START) & (out.reference_month <= FORMAL_END)]
    return out.sort_values('reference_month').reset_index(drop=True)


def main() -> int:
    report = {
        'logical_input': 'SAHM_RULE',
        'release_source': 'U.S. Bureau of Labor Statistics Employment Situation archived news releases',
        'archive_url': ARCHIVE_URL,
        'formal_reference_months': '2005-01..2026-08',
        'formal_release_map_ready': False,
    }
    try:
        df = fetch_release_map()
        expected = pd.date_range(FORMAL_START, FORMAL_END, freq='MS')
        got = set(df.reference_month)
        missing = [d for d in expected if d not in got]
        unexpected_missing = [d for d in missing if d not in KNOWN_OFFICIAL_SAHM_MISSING]

        # FRED SAHMREALTIME has an official missing observation for 2025-10. The
        # release map is allowed to be absent there, but nowhere else in the formal window.
        report.update({
            'status': 'QA_COMPLETE',
            'parsed_reference_months': int(len(df)),
            'first_reference_month': None if df.empty else str(df.reference_month.min().date()),
            'last_reference_month': None if df.empty else str(df.reference_month.max().date()),
            'missing_reference_months': [str(d.date()) for d in missing],
            'unexpected_missing_reference_months': [str(d.date()) for d in unexpected_missing],
            'known_official_sahm_missing_months': [str(d.date()) for d in sorted(KNOWN_OFFICIAL_SAHM_MISSING)],
            'release_date_encoding_rule': 'BLS archive empsit_MMDDYYYY filename encodes actual publication date; anchor label supplies reference month',
            'release_time_rule': 'Employment Situation releases are published at 08:30 ET; conservative formal strategy use will be no earlier than the next permitted business/trading day',
            'formal_release_map_ready': len(unexpected_missing) == 0,
        })
        export = df.copy()
        export['reference_month'] = export.reference_month.dt.strftime('%Y-%m-%d')
        export['release_date'] = export.release_date.dt.strftime('%Y-%m-%d')
        export.to_csv(CSV, index=False)
        REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if report['formal_release_map_ready'] else 2
    except Exception as exc:
        report.update({'status': 'QA_FAILURE', 'error': repr(exc), 'formal_release_map_ready': False})
        REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
