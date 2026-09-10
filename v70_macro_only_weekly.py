from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from math import isfinite
from typing import Dict, Iterable, Mapping, Optional, Tuple


class UnitQAError(ValueError):
    pass


class InsufficientDataError(ValueError):
    pass


@dataclass(frozen=True)
class IndicatorSpec:
    name: str
    t0: float
    t5: float
    t10: float
    gamma: float
    direction: str
    unit: str
    plausible_min: Optional[float] = None
    plausible_max: Optional[float] = None


# Exact computation weights. Display percentages are rounded separately.
GROUP_WEIGHTS = {
    "panic_vol": Fraction(18, 90),
    "credit": Fraction(16, 90),
    "inflation": Fraction(14, 90),
    "rates_curve": Fraction(12, 90),
    "liquidity_fc": Fraction(16, 90),
    "growth": Fraction(14, 90),
}

assert sum(GROUP_WEIGHTS.values(), Fraction(0, 1)) == Fraction(1, 1)


SPECS: Dict[str, IndicatorSpec] = {
    "VIX": IndicatorSpec("VIX", 14.0, 20.0, 35.0, 2.0, "higher_is_riskier", "index", 0, 150),
    "MOVE": IndicatorSpec("MOVE", 80.0, 110.0, 140.0, 1.8, "higher_is_riskier", "index", 0, 300),
    "HY_OAS": IndicatorSpec("HY_OAS", 300.0, 450.0, 600.0, 2.0, "higher_is_riskier", "bps", 0, 3000),
    "CORE_CPI_YOY": IndicatorSpec("CORE_CPI_YOY", 0.0200, 0.0300, 0.0400, 1.4, "higher_is_riskier", "ratio", -0.10, 0.30),
    "5Y_BREAKEVEN": IndicatorSpec("5Y_BREAKEVEN", 0.0200, 0.0250, 0.0300, 1.6, "higher_is_riskier", "ratio", -0.10, 0.20),
    "REAL_10Y": IndicatorSpec("REAL_10Y", 0.0100, 0.0180, 0.0250, 1.8, "higher_is_riskier", "ratio", -0.10, 0.20),
    "10Y_MINUS_2Y": IndicatorSpec("10Y_MINUS_2Y", 0.0050, 0.0020, -0.0050, 1.8, "lower_is_riskier", "ratio", -0.10, 0.10),
    "NET_LIQUIDITY_DELTA_13W": IndicatorSpec("NET_LIQUIDITY_DELTA_13W", 300.0, 0.0, -300.0, 2.0, "lower_is_riskier", "usd_bn", -5000, 5000),
    "DXY": IndicatorSpec("DXY", 98.0, 103.0, 108.0, 1.6, "higher_is_riskier", "index", 40, 200),
    "WTI": IndicatorSpec("WTI", 75.0, 90.0, 110.0, 1.3, "higher_is_riskier", "usd_per_bbl", -100, 300),
    "PMI_MANUFACTURING": IndicatorSpec("PMI_MANUFACTURING", 55.0, 50.0, 45.0, 1.4, "lower_is_riskier", "index", 0, 100),
    "PMI_SERVICES": IndicatorSpec("PMI_SERVICES", 55.0, 50.0, 45.0, 1.4, "lower_is_riskier", "index", 0, 100),
    "LEI_YOY": IndicatorSpec("LEI_YOY", 0.0200, 0.0, -0.0400, 1.6, "lower_is_riskier", "ratio", -0.50, 0.50),
}

GROUPS = {
    "panic_vol": ("VIX", "MOVE"),
    "credit": ("HY_OAS",),
    "inflation": ("CORE_CPI_YOY", "5Y_BREAKEVEN"),
    "rates_curve": ("REAL_10Y", "10Y_MINUS_2Y"),
    "liquidity_fc": ("NET_LIQUIDITY_DELTA_13W", "DXY", "WTI"),
    "growth": ("PMI_MANUFACTURING", "PMI_SERVICES", "LEI_YOY"),
}


def _validate_spec(spec: IndicatorSpec) -> None:
    if spec.direction == "higher_is_riskier":
        if not (spec.t0 < spec.t5 < spec.t10):
            raise UnitQAError(f"{spec.name}: invalid higher_is_riskier thresholds")
    elif spec.direction == "lower_is_riskier":
        if not (spec.t0 > spec.t5 > spec.t10):
            raise UnitQAError(f"{spec.name}: invalid lower_is_riskier thresholds")
    else:
        raise UnitQAError(f"{spec.name}: invalid risk direction {spec.direction}")
    if not (spec.gamma > 0):
        raise UnitQAError(f"{spec.name}: gamma must be positive")


def unit_qa(name: str, value: float) -> float:
    if name not in SPECS:
        raise UnitQAError(f"Unknown indicator: {name}")
    spec = SPECS[name]
    _validate_spec(spec)
    if value is None or not isfinite(float(value)):
        raise UnitQAError(f"{name}: non-finite value")
    v = float(value)
    if spec.plausible_min is not None and v < spec.plausible_min:
        raise UnitQAError(f"{name}: value {v} below plausible range for {spec.unit}")
    if spec.plausible_max is not None and v > spec.plausible_max:
        raise UnitQAError(f"{name}: value {v} above plausible range for {spec.unit}")
    return v


def linear_risk(name: str, value: float) -> float:
    v = unit_qa(name, value)
    s = SPECS[name]
    if s.direction == "higher_is_riskier":
        if v <= s.t0:
            return 0.0
        if v < s.t5:
            return 5.0 * (v - s.t0) / (s.t5 - s.t0)
        if v < s.t10:
            return 5.0 + 5.0 * (v - s.t5) / (s.t10 - s.t5)
        return 10.0
    if v >= s.t0:
        return 0.0
    if v > s.t5:
        return 5.0 * (s.t0 - v) / (s.t0 - s.t5)
    if v > s.t10:
        return 5.0 + 5.0 * (s.t5 - v) / (s.t5 - s.t10)
    return 10.0


def gamma_risk(name: str, value: float) -> float:
    r = linear_risk(name, value)
    g = SPECS[name].gamma
    return max(0.0, min(10.0, 10.0 * (r / 10.0) ** g))


def group_risks(values: Mapping[str, Optional[float]]) -> Tuple[Dict[str, float], Dict[str, dict]]:
    out: Dict[str, float] = {}
    qa: Dict[str, dict] = {}
    for group, members in GROUPS.items():
        valid = []
        missing = []
        for name in members:
            v = values.get(name)
            if v is None:
                missing.append(name)
                continue
            valid.append(gamma_risk(name, float(v)))
        if not valid:
            raise InsufficientDataError(f"{group}: no valid PIT indicators")
        out[group] = sum(valid) / len(valid)
        qa[group] = {
            "valid_count": len(valid),
            "missing_count": len(missing),
            "missing": missing,
        }
    return out, qa


def accelerator(values: Mapping[str, Optional[float]]) -> float:
    # These inputs are mandatory when their accelerator is evaluated in the baseline candidate.
    nl = values.get("NET_LIQUIDITY_DELTA_13W")
    dxy = values.get("DXY")
    wti = values.get("WTI")
    be = values.get("5Y_BREAKEVEN")
    if any(v is None for v in (nl, dxy, wti, be)):
        raise InsufficientDataError("accelerator input missing")
    nl = unit_qa("NET_LIQUIDITY_DELTA_13W", float(nl))
    dxy = unit_qa("DXY", float(dxy))
    wti = unit_qa("WTI", float(wti))
    be = unit_qa("5Y_BREAKEVEN", float(be))

    a_nl = 1.2 if nl <= -500 else (0.7 if nl <= -300 else 0.0)
    a_dxy = 0.8 if dxy >= 112 else (0.4 if dxy >= 108 else 0.0)
    a_wti = 1.0 if (wti >= 125 and be >= 0.0270) else (0.6 if (wti >= 110 and be >= 0.0260) else 0.0)
    return a_nl + a_dxy + a_wti


def cap_scores(values: Mapping[str, Optional[float]], recession: Mapping[str, Optional[float]]) -> Dict[str, float]:
    needed = ["VIX", "MOVE", "HY_OAS", "5Y_BREAKEVEN", "REAL_10Y", "NET_LIQUIDITY_DELTA_13W"]
    if any(values.get(k) is None for k in needed):
        raise InsufficientDataError("CAP market input missing")
    if values.get("5Y_BREAKEVEN_DELTA_1M") is None:
        raise InsufficientDataError("5Y breakeven 1M delta missing")
    for k in ("SAHM_RULE", "U3_UNEMPLOYMENT", "NFP_3M_AVG", "LEI_YOY"):
        if recession.get(k) is None:
            raise InsufficientDataError(f"recession CAP input missing: {k}")
    if recession.get("LEI_NEG_3M") is None:
        raise InsufficientDataError("recession CAP input missing: LEI_NEG_3M")

    vix = unit_qa("VIX", float(values["VIX"]))
    move = unit_qa("MOVE", float(values["MOVE"]))
    hy = unit_qa("HY_OAS", float(values["HY_OAS"]))
    be = unit_qa("5Y_BREAKEVEN", float(values["5Y_BREAKEVEN"]))
    real10 = unit_qa("REAL_10Y", float(values["REAL_10Y"]))
    nl = unit_qa("NET_LIQUIDITY_DELTA_13W", float(values["NET_LIQUIDITY_DELTA_13W"]))
    be_delta = float(values["5Y_BREAKEVEN_DELTA_1M"])
    if not isfinite(be_delta) or not (-0.20 <= be_delta <= 0.20):
        raise UnitQAError("5Y_BREAKEVEN_DELTA_1M: implausible ratio value")

    panic = 100.0
    if vix >= 35 or (vix >= 28 and move >= 140):
        panic = 60.0
    elif vix >= 28:
        panic = 70.0

    crisis_count = sum([
        hy >= 600,
        be >= 0.0260 and be_delta >= 0.0025,
        move >= 160,
        nl <= -500,
        real10 >= 0.0250,
    ])
    crisis = 45.0 if crisis_count >= 3 else (55.0 if crisis_count == 2 else 100.0)

    sahm = float(recession["SAHM_RULE"])
    u3 = float(recession["U3_UNEMPLOYMENT"])
    nfp = float(recession["NFP_3M_AVG"])
    lei = float(recession["LEI_YOY"])
    lei_neg_3m = bool(recession["LEI_NEG_3M"])
    # hard unit plausibility checks for recession-only inputs
    if not (0 <= sahm <= 5):
        raise UnitQAError("SAHM_RULE: implausible")
    if not (0 <= u3 <= 0.50):
        raise UnitQAError("U3_UNEMPLOYMENT: expected decimal ratio")
    if not (-5000 <= nfp <= 5000):
        raise UnitQAError("NFP_3M_AVG: expected thousands of persons")
    if not (-0.50 <= lei <= 0.50):
        raise UnitQAError("LEI_YOY: expected decimal ratio")

    rec55 = sahm >= 0.4 or (lei_neg_3m and (u3 >= 0.0450 or nfp <= 0))
    rec45 = sahm >= 0.5 or nfp <= 0 or (lei <= -0.0400 and u3 >= 0.0450)
    recession_cap = 45.0 if rec45 else (55.0 if rec55 else 100.0)

    return {"panic": panic, "crisis": crisis, "recession": recession_cap, "crisis_trigger_count": float(crisis_count)}


def macro_score(values: Mapping[str, Optional[float]], recession: Mapping[str, Optional[float]]) -> Dict[str, object]:
    gr, qa = group_risks(values)
    avg_base = sum(gr[g] * float(GROUP_WEIGHTS[g]) for g in GROUP_WEIGHTS)
    acc = accelerator(values)
    avg_adj = max(0.0, min(10.0, avg_base + acc))
    m_raw = (10.0 - avg_adj) * 10.0
    caps = cap_scores(values, recession)
    m_final = max(0.0, min(100.0, m_raw, caps["panic"], caps["crisis"], caps["recession"]))
    return {
        "group_risk": gr,
        "group_qa": qa,
        "avgRiskBase": avg_base,
        "accelerator": acc,
        "avgRiskAdj": avg_adj,
        "mSafe_raw": m_raw,
        "caps": caps,
        "mSafe_final": m_final,
        "zone": macro_zone(m_final),
        "bucket_caps": bucket_caps(m_final),
    }


def macro_zone(m_safe: float) -> str:
    if not (0 <= m_safe <= 100):
        raise ValueError("mSafe outside [0,100]")
    if m_safe >= 70:
        return "ATTACK"
    if m_safe >= 55:
        return "STEADY"
    if m_safe >= 40:
        return "DEFENSE"
    return "PARK"


def bucket_caps(m_safe: float) -> Dict[str, float]:
    z = macro_zone(m_safe)
    if z == "ATTACK":
        return {"equity_max": 0.70, "bond_max": 0.20, "cash_min": 0.10}
    if z == "STEADY":
        return {"equity_max": 0.60, "bond_max": 0.30, "cash_min": 0.10}
    if z == "DEFENSE":
        return {"equity_max": 0.40, "bond_max": 0.40, "cash_min": 0.20}
    return {"equity_max": 0.00, "bond_max": 0.20, "cash_min": 0.80}


def apply_lower_layer_demands(
    m_safe: float,
    v82_equity_demand: float,
    bond_v75_demand: float,
) -> Dict[str, float]:
    caps = bucket_caps(m_safe)
    for name, v in (("v82_equity_demand", v82_equity_demand), ("bond_v75_demand", bond_v75_demand)):
        if not isfinite(v) or v < 0 or v > 1:
            raise UnitQAError(f"{name}: expected NAV fraction in [0,1]")
    equity = min(v82_equity_demand, caps["equity_max"])
    bond_available = 1.0 - equity - caps["cash_min"]
    bond = min(bond_v75_demand, caps["bond_max"], max(0.0, bond_available))
    cash = 1.0 - equity - bond
    if equity > caps["equity_max"] + 1e-12:
        raise AssertionError("equity exceeded weekly cap")
    if bond > caps["bond_max"] + 1e-12:
        raise AssertionError("bond exceeded weekly cap")
    if cash + 1e-12 < caps["cash_min"]:
        raise AssertionError("cash below weekly floor")
    if abs(equity + bond + cash - 1.0) > 1e-12:
        raise AssertionError("capital conservation failed")
    return {"equity_actual": equity, "bond_actual": bond, "cash_actual": cash, **caps}


def apply_intrawweek_hard_gate(
    current: Mapping[str, float],
    equity_target_after_gate: Optional[float] = None,
    bond_target_after_gate: Optional[float] = None,
) -> Dict[str, float]:
    """Lower layers may reduce exposure intrawweek, but never raise above weekly caps."""
    emax = float(current["equity_max"])
    bmax = float(current["bond_max"])
    cmin = float(current["cash_min"])
    e0 = float(current["equity_actual"])
    b0 = float(current["bond_actual"])
    e1 = e0 if equity_target_after_gate is None else float(equity_target_after_gate)
    b1 = b0 if bond_target_after_gate is None else float(bond_target_after_gate)
    if e1 > e0 + 1e-12 or b1 > b0 + 1e-12:
        raise UnitQAError("intrawweek hard gate may reduce/hold exposure only; weekly allocator alone can raise caps")
    if not (0 <= e1 <= emax and 0 <= b1 <= bmax):
        raise UnitQAError("hard-gate target outside weekly bounds")
    cash = 1.0 - e1 - b1
    if cash + 1e-12 < cmin:
        raise AssertionError("cash below weekly floor after hard gate")
    return {
        "equity_actual": e1,
        "bond_actual": b1,
        "cash_actual": cash,
        "equity_max": emax,
        "bond_max": bmax,
        "cash_min": cmin,
    }
