import math
import pytest

from v70_macro_only_weekly import (
    GROUP_WEIGHTS, UnitQAError, apply_intrawweek_hard_gate,
    apply_lower_layer_demands, bucket_caps, gamma_risk, macro_zone,
    macro_score
)


def safe_values():
    return {
        'VIX':14.0, 'MOVE':80.0, 'HY_OAS':300.0,
        'CORE_CPI_YOY':0.0200, '5Y_BREAKEVEN':0.0200,
        '5Y_BREAKEVEN_DELTA_1M':0.0,
        'REAL_10Y':0.0100, '10Y_MINUS_2Y':0.0050,
        'NET_LIQUIDITY_DELTA_13W':300.0, 'DXY':98.0, 'WTI':75.0,
        'PMI_MANUFACTURING':55.0, 'PMI_SERVICES':55.0, 'LEI_YOY':0.0200,
    }


def safe_recession():
    return {
        'SAHM_RULE':0.0, 'U3_UNEMPLOYMENT':0.0350,
        'NFP_3M_AVG':200.0, 'LEI_YOY':0.0200, 'LEI_NEG_3M':False,
    }


def test_exact_weights_sum_to_one():
    assert float(sum(GROUP_WEIGHTS.values())) == 1.0


def test_unit_qa_catches_percentage_scale_error():
    with pytest.raises(UnitQAError):
        gamma_risk('10Y_MINUS_2Y', 0.5)  # should be 0.0050, not 0.5


def test_macro_zone_boundaries():
    assert macro_zone(70) == 'ATTACK'
    assert macro_zone(55) == 'STEADY'
    assert macro_zone(40) == 'DEFENSE'
    assert macro_zone(39.999) == 'PARK'


def test_bucket_caps():
    assert bucket_caps(75) == {'equity_max':0.70,'bond_max':0.20,'cash_min':0.10}
    assert bucket_caps(60) == {'equity_max':0.60,'bond_max':0.30,'cash_min':0.10}
    assert bucket_caps(50) == {'equity_max':0.40,'bond_max':0.40,'cash_min':0.20}
    assert bucket_caps(30) == {'equity_max':0.00,'bond_max':0.20,'cash_min':0.80}


def test_fully_safe_macro_is_attack():
    r = macro_score(safe_values(), safe_recession())
    assert math.isclose(r['mSafe_raw'], 100.0)
    assert math.isclose(r['mSafe_final'], 100.0)
    assert r['zone'] == 'ATTACK'


def test_panic_cap_60():
    v=safe_values(); v['VIX']=35.0
    r=macro_score(v,safe_recession())
    assert r['caps']['panic'] == 60.0
    assert r['mSafe_final'] <= 60.0


def test_two_crisis_triggers_cap_55():
    v=safe_values(); v['HY_OAS']=600.0; v['5Y_BREAKEVEN']=0.0260; v['5Y_BREAKEVEN_DELTA_1M']=0.0025
    r=macro_score(v,safe_recession())
    assert r['caps']['crisis_trigger_count'] == 2.0
    assert r['caps']['crisis'] == 55.0
    assert r['mSafe_final'] <= 55.0


def test_recession_cap_45_priority():
    rec=safe_recession(); rec['SAHM_RULE']=0.5
    r=macro_score(safe_values(),rec)
    assert r['caps']['recession'] == 45.0
    assert r['mSafe_final'] == 45.0


def test_unused_equity_does_not_cross_to_bond():
    r = apply_lower_layer_demands(60, 0.40, 0.50)
    assert math.isclose(r['equity_actual'], 0.40)
    assert math.isclose(r['bond_actual'], 0.30)
    assert math.isclose(r['cash_actual'], 0.30)


def test_unused_bond_does_not_cross_to_equity():
    r = apply_lower_layer_demands(60, 0.90, 0.10)
    assert math.isclose(r['equity_actual'], 0.60)
    assert math.isclose(r['bond_actual'], 0.10)
    assert math.isclose(r['cash_actual'], 0.30)


def test_independent_buckets_return_unused_cap_to_sgov():
    # In STEADY, V70.2 assigns separate maxima: 60% stock, 30% bond, 10% minimum SGOV/cash.
    # Each lower engine owns only its assigned bucket. Unused budget returns to SGOV,
    # and is never transferred to the other risk bucket.
    r = apply_lower_layer_demands(60, 0.25, 0.12)
    assert math.isclose(r['equity_actual'], 0.25)
    assert math.isclose(r['bond_actual'], 0.12)
    assert math.isclose(r['cash_actual'], 0.63)


def test_parking_zone_allows_bond_only_to_20pct():
    r = apply_lower_layer_demands(30, 0.50, 0.50)
    assert math.isclose(r['equity_actual'], 0.0)
    assert math.isclose(r['bond_actual'], 0.20)
    assert math.isclose(r['cash_actual'], 0.80)


def test_intrawweek_gate_can_reduce_not_raise():
    r = apply_lower_layer_demands(60, 0.50, 0.20)
    r2 = apply_intrawweek_hard_gate(r, equity_target_after_gate=0.30)
    assert math.isclose(r2['equity_actual'], 0.30)
    assert math.isclose(r2['cash_actual'], 0.50)
    with pytest.raises(UnitQAError):
        apply_intrawweek_hard_gate(r, equity_target_after_gate=0.55)
