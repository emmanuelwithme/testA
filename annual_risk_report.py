from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

import backtest_33_models as b

OUT = Path("backtest_33_output")


def flow_schedule(allowed_assets, mode, price_map):
    contribs = []
    years = range(pd.Timestamp(b.START).year, pd.Timestamp(b.END).year)
    for y in years:
        if mode.startswith("annual"):
            nominals = [pd.Timestamp(y, 1, 1)]
            amount = b.ANNUAL_CONTRIB_TWD
        else:
            nominals = [pd.Timestamp(y, m, 1) for m in range(1, 13)]
            amount = b.MONTHLY_CONTRIB_TWD
        for nominal in nominals:
            if nominal >= pd.Timestamp(b.END):
                continue
            if "single:" in mode:
                asset = mode.split("single:")[1]
                d = b.next_valid_date(price_map[asset], nominal)
                if d is None or d >= pd.Timestamp(b.END):
                    continue
                contribs.append((d, amount))
            else:
                investable, dates = [], {}
                for a in allowed_assets:
                    d = b.next_valid_date(price_map[a], nominal)
                    if d is not None and d <= nominal + pd.Timedelta(days=7) and d < pd.Timestamp(b.END):
                        investable.append(a); dates[a] = d
                if not investable:
                    continue
                d = max(dates.values())
                active = [a for a in investable if price_map[a].index.min() <= d and d in price_map[a].index]
                if active:
                    contribs.append((d, amount))
    return contribs


def unitize(nav, contribs):
    nav = nav.dropna()
    if nav.empty:
        return nav
    flows = {}
    for d, v in contribs:
        flows[d] = flows.get(d, 0.0) + float(v)
    u = []
    unit = 1.0
    prev = None
    for d, v in nav.items():
        f = flows.get(d, 0.0)
        if prev is not None and prev > 0:
            r = (float(v) - f) / prev - 1.0
            unit *= (1.0 + r)
        u.append(unit)
        prev = float(v)
    return pd.Series(u, index=nav.index, name=nav.name + "_unit")


def annual_rows(model, nav, unit, contribs):
    rows = []
    flows = pd.DataFrame(contribs, columns=["date", "amount"]) if contribs else pd.DataFrame(columns=["date", "amount"])
    for y in sorted(set(nav.index.year)):
        ny = nav[nav.index.year == y]
        uy = unit[unit.index.year == y]
        if ny.empty or uy.empty:
            continue
        prev_nav = nav[nav.index < ny.index[0]]
        begin = float(prev_nav.iloc[-1]) if len(prev_nav) else 0.0
        added = float(flows.loc[flows.date.dt.year == y, "amount"].sum()) if len(flows) else 0.0
        prev_u = unit[unit.index < uy.index[0]]
        base_u = float(prev_u.iloc[-1]) if len(prev_u) else float(uy.iloc[0])
        ann_ret = float(uy.iloc[-1] / base_u - 1.0) if base_u > 0 else np.nan
        runmax = uy.cummax()
        dd = uy / runmax - 1.0
        trough = dd.idxmin(); mdd = float(dd.loc[trough]); peak_val = float(runmax.loc[trough])
        peak = uy.loc[:trough][uy.loc[:trough] >= peak_val * (1 - 1e-12)].index[-1]
        post = unit[unit.index >= trough]
        rec = post[post >= peak_val]
        rec_date = rec.index[0] if len(rec) else None
        recovered_yend = bool(rec_date is not None and rec_date <= ny.index[-1])
        rec_days = int((rec_date - peak).days) if rec_date is not None else np.nan
        if not recovered_yend:
            risk = "高：年底未恢復前高"
        elif mdd <= -0.30:
            risk = "高：年內MDD≤-30%"
        elif mdd <= -0.20 or (np.isfinite(rec_days) and rec_days > 365):
            risk = "中高"
        elif mdd <= -0.10 or (np.isfinite(rec_days) and rec_days > 180):
            risk = "中"
        else:
            risk = "低"
        rows.append({
            "model": model,
            "year": y,
            "beginning_asset_twd": begin,
            "external_contribution_twd": added,
            "ending_asset_twd": float(ny.iloc[-1]),
            "annual_return": ann_ret,
            "annual_mdd": mdd,
            "mdd_peak_date": str(peak.date()),
            "mdd_trough_date": str(trough.date()),
            "peak_to_trough_days": int((trough - peak).days),
            "recovery_date": str(rec_date.date()) if rec_date is not None else None,
            "recovery_time_days": rec_days,
            "recovered_by_year_end": recovered_yend,
            "year_min_unit_nav": float(uy.min()),
            "withdrawal_risk": risk,
        })
    return rows


def cross_year(model, df):
    d = df.sort_values("year").copy()
    r = d.annual_return.astype(float)
    tri = (1 + r).rolling(3).apply(np.prod, raw=True) - 1
    out = {
        "model": model,
        "negative_years": int((r < 0).sum()),
        "effective_years": int(len(d)),
        "annual_mdd_le_20_count": int((d.annual_mdd <= -0.20).sum()),
        "annual_mdd_le_30_count": int((d.annual_mdd <= -0.30).sum()),
        "annual_mdd_le_40_count": int((d.annual_mdd <= -0.40).sum()),
        "worst_calendar_year": int(d.loc[r.idxmin(), "year"]),
        "worst_calendar_year_return": float(r.min()),
        "year_end_unrecovered_count": int((~d.recovered_by_year_end).sum()),
        "longest_recovery_days": float(d.recovery_time_days.dropna().max()) if d.recovery_time_days.notna().any() else np.nan,
    }
    if tri.notna().any():
        i = tri.idxmin(); y2 = int(d.loc[i, "year"])
        out.update({"worst_3y_start": y2 - 2, "worst_3y_end": y2, "worst_3y_total_return": float(tri.loc[i])})
    return out


def run_all():
    prices = b.fetch_prices(); fx = b.fetch_fx_usdtwd(); twd = b.to_twd_total_return(prices, fx)
    specs = []
    for a in b.RISK: specs.append((f"Case2_AnnualSingle_{a}", [a], f"annual_single:{a}"))
    specs.append(("Case3_AnnualEqual_All11", list(b.RISK), "annual_equal"))
    for a in b.RISK: specs.append((f"Case4_MonthlySingle_{a}", [a], f"monthly_single:{a}"))
    specs.append(("Case5_MonthlyEqual_All11", list(b.RISK), "monthly_equal"))
    specs.append(("Case6_AnnualEqual_Stocks6", list(b.STOCKS), "annual_equal"))
    for a in b.STOCKS: specs.append((f"Case7_MonthlySingleStock_{a}", [a], f"monthly_single:{a}"))
    specs.append(("Case8_MonthlyEqual_Stocks6", list(b.STOCKS), "monthly_equal"))

    annual = []
    for name, assets, mode in specs:
        _, nav = b.run_schedule_model(name, assets, mode, twd)
        if nav.empty: continue
        flows = flow_schedule(assets, mode, twd)
        unit = unitize(nav, flows)
        annual.extend(annual_rows(name, nav, unit, flows))

    adf = pd.DataFrame(annual)
    adf.to_csv(OUT / "annual_risk_by_model.csv", index=False)
    cross = [cross_year(m, g) for m, g in adf.groupby("model")]
    pd.DataFrame(cross).to_csv(OUT / "cross_year_risk_summary.csv", index=False)
    adf[adf.year.isin([2008, 2020, 2022])].to_csv(OUT / "stress_2008_2020_2022.csv", index=False)
    case8 = adf[adf.model == "Case8_MonthlyEqual_Stocks6"]
    if len(case8):
        print("CASE8 ANNUAL RISK")
        print(case8[["year","annual_return","annual_mdd","recovery_time_days","recovered_by_year_end","withdrawal_risk"]].to_string(index=False))
    print(json.dumps({"annual_rows": len(adf), "models_with_annual_output": int(adf.model.nunique())}, ensure_ascii=False))


if __name__ == "__main__":
    run_all()
