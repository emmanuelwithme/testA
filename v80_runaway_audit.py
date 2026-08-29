from pathlib import Path
import pandas as pd

OUT = Path('v80_results')
ASSETS = ['QQQ', 'VT', '0050', 'VWRA', 'PPH', 'DFNS']


def _to_bool(s):
    if s.dtype == bool:
        return s.fillna(False)
    return s.astype(str).str.strip().str.lower().isin(['true', '1', 'yes'])


def _cluster_events(df, mask, label, window=5):
    idx = df.index[mask].tolist()
    if not idx:
        return []
    clusters = []
    current = [idx[0]]
    for i in idx[1:]:
        if i - current[-1] <= window:
            current.append(i)
        else:
            clusters.append(current); current = [i]
    clusters.append(current)
    out = []
    for n, g in enumerate(clusters, 1):
        sub = df.loc[g]
        out.append({'asset': sub['asset'].iloc[0], 'runaway_type': label,
                    'cluster_no': n, 'start_date': sub['date'].iloc[0],
                    'end_date': sub['date'].iloc[-1], 'true_days': len(sub),
                    'first_state': sub['STATE'].iloc[0], 'last_state': sub['STATE'].iloc[-1]})
    return out


summary_rows=[]; event_rows=[]
for asset in ASSETS:
    p=OUT/f'{asset}_daily_signals.csv'
    if not p.exists(): raise SystemExit(f'MISSING runaway audit input: {p}')
    d=pd.read_csv(p)
    if 'date' not in d.columns: d=d.rename(columns={d.columns[0]:'date'})
    required={'date','STATE','RUNAWAY_UP','RUNAWAY_DOWN'}; miss=sorted(required-set(d.columns))
    if miss: raise SystemExit(f'{asset}: missing runaway audit columns {miss}')
    d['date']=pd.to_datetime(d['date'],errors='coerce'); d=d.dropna(subset=['date']).sort_values('date').reset_index(drop=True); d['asset']=asset
    ru=_to_bool(d.RUNAWAY_UP); rd=_to_bool(d.RUNAWAY_DOWN); strong=d.STATE.eq('STRONG_HOLD'); down_state=d.STATE.eq('RUNAWAY_DOWN')
    ru_events=_cluster_events(d,ru,'RUNAWAY_UP',5); rd_events=_cluster_events(d,rd,'RUNAWAY_DOWN',5)
    event_rows.extend(ru_events); event_rows.extend(rd_events)
    summary_rows.append({'asset':asset,'runaway_up_true_days':int(ru.sum()),'runaway_up_cluster_events_5d':len(ru_events),
        'runaway_up_first_date':d.loc[ru,'date'].min() if ru.any() else pd.NaT,'runaway_up_last_date':d.loc[ru,'date'].max() if ru.any() else pd.NaT,
        'strong_hold_days':int(strong.sum()),'strong_hold_non_runaway_up_days':int((strong&~ru).sum()),'runaway_up_not_strong_hold_days':int((ru&~strong).sum()),
        'runaway_down_true_days':int(rd.sum()),'runaway_down_cluster_events_5d':len(rd_events),'runaway_down_first_date':d.loc[rd,'date'].min() if rd.any() else pd.NaT,
        'runaway_down_last_date':d.loc[rd,'date'].max() if rd.any() else pd.NaT,'runaway_down_state_days':int(down_state.sum()),
        'runaway_down_flag_not_state_days':int((rd&~down_state).sum()),'runaway_up_down_overlap_days':int((ru&rd).sum())})

summary=pd.DataFrame(summary_rows); events=pd.DataFrame(event_rows)
summary.to_csv(OUT/'runaway_audit_summary.csv',index=False); events.to_csv(OUT/'runaway_audit_events.csv',index=False)
bad=[]
for _,r in summary.iterrows():
    # DFNS has a much shorter history (inception 2023-03-31), but it still must
    # produce both directions if the locked V80 conditions occurred. Zero is
    # never silently accepted: it is an audit failure requiring inspection.
    if r.runaway_up_true_days<=0 or r.runaway_up_cluster_events_5d<=0: bad.append((r.asset,'RUNAWAY_UP missing'))
    if r.runaway_down_true_days<=0 or r.runaway_down_cluster_events_5d<=0: bad.append((r.asset,'RUNAWAY_DOWN missing'))
    if r.strong_hold_days<=0: bad.append((r.asset,'STRONG_HOLD missing'))
    if r.runaway_up_down_overlap_days>0: bad.append((r.asset,f'RUNAWAY_UP/DOWN overlap={r.runaway_up_down_overlap_days}'))
print(summary.to_string(index=False))
if bad: raise SystemExit(f'INVALID V80 runaway audit: {bad}')
print('Runaway Up/Down audit passed for all V80 assets including DFNS.')
