from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np
import pandas as pd
import requests
import yfinance as yf

START = "2005-01-01"
END = "2026-09-01"  # yfinance end is exclusive; formal end 2026-08-31
ANNUAL_CONTRIB_TWD = 1_000_000.0
MONTHLY_CONTRIB_TWD = ANNUAL_CONTRIB_TWD / 12.0

STOCKS = {
    "0050": "0050.TW",
    "VWRA": "VWRA.L",
    "QQQ": "QQQ",
    "SOXX": "SOXX",
    "PPH": "PPH",
    "NATO": "NATO.L",
}
BONDS = {
    "TLT": "TLT",
    "IEF": "IEF",
    "SPLB": "SPLB",
    "SPIB": "SPIB",
    "SPSB": "SPSB",
}
RISK = {**STOCKS, **BONDS}

OUT = Path("backtest_33_output")
OUT.mkdir(exist_ok=True)


def fetch_fx_usdtwd() -> pd.Series:
    """Official Fed H.10 DEXTAUS: TWD per USD. Strictly historical observations only."""
    url = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=DEXTAUS"
    r = requests.get(url, timeout=45)
    r.raise_for_status()
    df = pd.read_csv(pd.io.common.StringIO(r.text))
    df.columns = ["date", "fx"]
    df["date"] = pd.to_datetime(df["date"])
    df["fx"] = pd.to_numeric(df["fx"], errors="coerce")
    s = df.dropna().set_index("date")["fx"].sort_index()
    return s.loc[(s.index >= pd.Timestamp(START)) & (s.index < pd.Timestamp(END))]


def fetch_prices() -> Dict[str, pd.Series]:
    out = {}
    for name, ticker in RISK.items():
        d = yf.download(ticker, start=START, end=END, auto_adjust=True, repair=True,
                        progress=False, actions=False, threads=False)
        if d.empty:
            out[name] = pd.Series(dtype=float, name=name)
            continue
        c = d["Close"]
        if isinstance(c, pd.DataFrame):
            c = c.iloc[:, 0]
        c = pd.to_numeric(c, errors="coerce").dropna().astype(float)
        c.index = pd.to_datetime(c.index).tz_localize(None)
        c.name = name
        out[name] = c.sort_index()
    return out


def to_twd_total_return(prices: Dict[str, pd.Series], fx: pd.Series) -> Dict[str, pd.Series]:
    out = {}
    for name, s in prices.items():
        if s.empty:
            out[name] = s
            continue
        if name == "0050":
            twd = s.copy()
        else:
            f = fx.reindex(s.index, method="ffill")
            twd = (s * f).dropna()
        # hard integrity screen: one-day adjusted-price jump > 55% is treated as data break.
        ret = twd.pct_change()
        bad = ret.abs() > 0.55
        if bad.any():
            first_bad = bad[bad].index[0]
            # Keep only the later continuous segment; never manufacture a split repair.
            twd = twd.loc[first_bad:]
        out[name] = twd
    return out


def next_valid_date(series: pd.Series, nominal: pd.Timestamp) -> pd.Timestamp | None:
    idx = series.index[series.index >= nominal]
    return idx[0] if len(idx) else None


def invest_amount(state, asset, amount_twd, price):
    if amount_twd <= 0 or not np.isfinite(price) or price <= 0:
        return
    shares = amount_twd / price
    state[asset] = state.get(asset, 0.0) + shares


def nav_on(date, holdings, cash, price_map):
    nav = cash
    for a, sh in holdings.items():
        s = price_map[a]
        hist = s.loc[s.index <= date]
        if len(hist):
            nav += sh * float(hist.iloc[-1])
    return nav


def xirr(cashflows: List[Tuple[pd.Timestamp, float]]) -> float:
    if not cashflows or not any(x < 0 for _, x in cashflows) or not any(x > 0 for _, x in cashflows):
        return float("nan")
    t0 = cashflows[0][0]
    def f(r):
        if r <= -0.999999:
            return 1e99
        return sum(v / ((1 + r) ** (((d - t0).days) / 365.2425)) for d, v in cashflows)
    lo, hi = -0.999, 10.0
    flo, fhi = f(lo), f(hi)
    for _ in range(20):
        if flo * fhi <= 0:
            break
        hi *= 2
        fhi = f(hi)
    if flo * fhi > 0:
        return float("nan")
    for _ in range(200):
        mid = (lo + hi) / 2
        fm = f(mid)
        if abs(fm) < 1e-7:
            return mid
        if flo * fm <= 0:
            hi = mid
            fhi = fm
        else:
            lo = mid
            flo = fm
    return (lo + hi) / 2


def metrics(nav: pd.Series, contribs: List[Tuple[pd.Timestamp, float]], ending: float) -> dict:
    nav = nav.dropna()
    total_cost = sum(v for _, v in contribs)
    total_profit = ending - total_cost
    total_return = ending / total_cost - 1 if total_cost else float("nan")
    dd = nav / nav.cummax() - 1 if len(nav) else pd.Series(dtype=float)
    mdd = float(dd.min()) if len(dd) else float("nan")
    rets = nav.pct_change().dropna()
    ann = 252
    sharpe = float(rets.mean() / rets.std() * math.sqrt(ann)) if len(rets) > 2 and rets.std() > 0 else float("nan")
    downside = rets[rets < 0]
    sortino = float(rets.mean() / downside.std() * math.sqrt(ann)) if len(downside) > 2 and downside.std() > 0 else float("nan")
    yrs = (nav.index[-1] - nav.index[0]).days / 365.2425 if len(nav) > 1 else float("nan")
    cagr = float((nav.iloc[-1] / nav.iloc[0]) ** (1 / yrs) - 1) if len(nav) > 1 and yrs > 0 and nav.iloc[0] > 0 else float("nan")
    calmar = cagr / abs(mdd) if np.isfinite(cagr) and np.isfinite(mdd) and mdd < 0 else float("nan")
    cf = [(d, -v) for d, v in contribs] + [(nav.index[-1], ending)] if len(nav) else []
    return {
        "total_cost_twd": total_cost,
        "ending_asset_twd": ending,
        "total_profit_twd": total_profit,
        "total_return": total_return,
        "xirr_mwr": xirr(cf),
        "nav_cagr": cagr,
        "mdd": mdd,
        "sharpe": sharpe,
        "sortino": sortino,
        "calmar": calmar,
    }


def run_schedule_model(model_name: str, allowed_assets: List[str], mode: str, price_map: Dict[str, pd.Series]):
    # mode: annual_single:<asset>, annual_equal, monthly_single:<asset>, monthly_equal
    holdings = {}
    cash = 0.0
    contribs = []
    events = []

    union_idx = pd.DatetimeIndex(sorted(set().union(*[set(price_map[a].index) for a in allowed_assets if len(price_map[a])])))
    if len(union_idx) == 0:
        return {"model": model_name, "status": "N/A_NO_DATA"}, pd.Series(dtype=float)

    years = range(pd.Timestamp(START).year, pd.Timestamp(END).year)
    for y in years:
        if mode.startswith("annual"):
            nominals = [pd.Timestamp(y, 1, 1)]
            amount = ANNUAL_CONTRIB_TWD
        else:
            nominals = [pd.Timestamp(y, m, 1) for m in range(1, 13)]
            amount = MONTHLY_CONTRIB_TWD

        for nominal in nominals:
            if nominal >= pd.Timestamp(END):
                continue
            if "single:" in mode:
                asset = mode.split("single:")[1]
                d = next_valid_date(price_map[asset], nominal)
                if d is None or d >= pd.Timestamp(END):
                    continue
                # effective contribution begins only when this asset is investable.
                contribs.append((d, amount))
                invest_amount(holdings, asset, amount, float(price_map[asset].loc[d]))
                events.append((d, amount, asset))
            else:
                # Equal-weight new money among ETFs actually listed/investable on this scheduled date.
                investable = []
                dates = {}
                for a in allowed_assets:
                    d = next_valid_date(price_map[a], nominal)
                    # avoid admitting an ETF that only lists far after the schedule date.
                    if d is not None and d <= nominal + pd.Timedelta(days=7) and d < pd.Timestamp(END):
                        investable.append(a)
                        dates[a] = d
                if not investable:
                    continue
                # A shared contribution date is the latest first-valid date among investable assets for that schedule.
                d = max(dates.values())
                active = [a for a in investable if price_map[a].index.min() <= d and d in price_map[a].index]
                if not active:
                    continue
                contribs.append((d, amount))
                each = amount / len(active)
                for a in active:
                    invest_amount(holdings, a, each, float(price_map[a].loc[d]))
                    events.append((d, each, a))

    if not contribs:
        return {"model": model_name, "status": "N/A_NO_EFFECTIVE_CONTRIBUTION"}, pd.Series(dtype=float)

    first = min(d for d, _ in contribs)
    last = min(pd.Timestamp("2026-08-31"), max(union_idx))
    daily_idx = union_idx[(union_idx >= first) & (union_idx <= last)]
    nav_vals = []
    contrib_by_date = {}
    for d, v in contribs:
        contrib_by_date[d] = contrib_by_date.get(d, 0.0) + v

    # Reconstruct NAV as external capital + asset gains; all scheduled capital is fully deployed.
    # Holdings are built cumulatively, so rebuild day by day from events to avoid future holdings leakage.
    h = {}
    event_map = {}
    for d, amt, a in events:
        event_map.setdefault(d, []).append((amt, a))
    for d in daily_idx:
        for amt, a in event_map.get(d, []):
            invest_amount(h, a, amt, float(price_map[a].loc[d]))
        nav_vals.append(nav_on(d, h, 0.0, price_map))
    nav = pd.Series(nav_vals, index=daily_idx, name=model_name)
    ending = float(nav.iloc[-1])
    row = {"model": model_name, "status": "OK", **metrics(nav, contribs, ending)}
    return row, nav


def main():
    prices = fetch_prices()
    fx = fetch_fx_usdtwd()
    twd = to_twd_total_return(prices, fx)

    rows = []
    navs = {}

    # Case 1: formal audit. Mother rule forbids inventing a cross-asset allocator.
    # V82 explicitly does not bind a portfolio capital pool; 債券V75 likewise does not define
    # arbitration between simultaneous stock/bond demands. Until a programmable allocator is
    # specified in a formal rule file, this model must remain blocked rather than fabricated.
    rows.append({
        "model": "Case1_V82_plus_BondV75_dynamic_common_pool",
        "status": "BLOCKED_UNPROGRAMMABLE_CROSS_ASSET_ALLOCATOR",
        "reason": "V82/V75 define asset-level decisions but no formal common-pool arbitration rule for simultaneous stock/bond deployment; mother rule forbids manual invention."
    })

    # Case 2: 11 annual-start single-ETF benchmarks.
    for a in RISK:
        row, nav = run_schedule_model(f"Case2_AnnualSingle_{a}", [a], f"annual_single:{a}", twd)
        rows.append(row); navs[row["model"]] = nav

    # Case 3: annual-start equal-weight all 11 currently investable ETFs.
    row, nav = run_schedule_model("Case3_AnnualEqual_All11", list(RISK), "annual_equal", twd)
    rows.append(row); navs[row["model"]] = nav

    # Case 4: 11 monthly single-ETF DCA benchmarks.
    case4_rows = {}
    for a in RISK:
        row, nav = run_schedule_model(f"Case4_MonthlySingle_{a}", [a], f"monthly_single:{a}", twd)
        rows.append(row); navs[row["model"]] = nav; case4_rows[a] = row

    # Case 5: monthly equal-weight all 11.
    row, nav = run_schedule_model("Case5_MonthlyEqual_All11", list(RISK), "monthly_equal", twd)
    rows.append(row); navs[row["model"]] = nav

    # Case 6: annual equal-weight stock ETFs only.
    row, nav = run_schedule_model("Case6_AnnualEqual_Stocks6", list(STOCKS), "annual_equal", twd)
    rows.append(row); navs[row["model"]] = nav

    # Case 7: six separately reported monthly single-stock-ETF benchmarks.
    # Mathematically identical to Case 4 stock subset; reuse metrics to avoid duplicate computation.
    for a in STOCKS:
        base = case4_rows[a].copy()
        base["model"] = f"Case7_MonthlySingleStock_{a}"
        base["reused_from"] = f"Case4_MonthlySingle_{a}"
        rows.append(base)
        navs[base["model"]] = navs.get(f"Case4_MonthlySingle_{a}", pd.Series(dtype=float))

    # Case 8: monthly equal-weight stocks only.
    row, nav = run_schedule_model("Case8_MonthlyEqual_Stocks6", list(STOCKS), "monthly_equal", twd)
    rows.append(row); navs[row["model"]] = nav

    df = pd.DataFrame(rows)
    assert len(df) == 33, f"Expected 33 models, got {len(df)}"
    df.to_csv(OUT / "model_summary.csv", index=False)

    data_audit = []
    for a, s in twd.items():
        data_audit.append({
            "asset": a,
            "first_valid": str(s.index.min().date()) if len(s) else None,
            "last_valid": str(s.index.max().date()) if len(s) else None,
            "n_obs": int(len(s)),
        })
    pd.DataFrame(data_audit).to_csv(OUT / "data_audit.csv", index=False)

    status = {
        "formal_window": "2005-01-01..2026-08-31",
        "stock_pool": list(STOCKS),
        "bond_pool": list(BONDS),
        "sgov_role": "cash parking only; excluded from equal-weight denominator",
        "expected_models": 33,
        "actual_models": int(len(df)),
        "ok_models": int((df.status == "OK").sum()),
        "blocked_models": int(df.status.astype(str).str.startswith("BLOCKED").sum()),
        "case1_blocker": rows[0],
    }
    (OUT / "run_status.json").write_text(json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8")

    print(df[[c for c in ["model", "status", "ending_asset_twd", "xirr_mwr", "mdd", "sortino", "calmar"] if c in df.columns]].to_string(index=False))
    print(json.dumps(status, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
