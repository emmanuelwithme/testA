import math
import pytest

from v70_macro_only_weekly import (
    GROUP_WEIGHTS, UnitQAError, apply_intrawweek_hard_gate,
    apply_lower_layer_demands, bucket_caps, gamma_risk, macro_zone
)


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


def test_unused_equity_does_not_cross_to_bond():
    r = apply_lower_layer_demands(60, 0.40, 0.50)
    assert r['equity_actual'] == 0.40
    assert r['bond_actual'] == 0.30
    assert math.isclose(r['cash_actual'], 0.30)


def test_parking_zone_allows_bond_only_to_20pct():
    r = apply_lower_layer_demands(30, 0.50, 0.50)
    assert r['equity_actual'] == 0.0
    assert r['bond_actual'] == 0.20
    assert r['cash_actual'] == 0.80


def test_intrawweek_gate_can_reduce_not_raise():
    r = apply_lower_layer_demands(60, 0.50, 0.20)
    r2 = apply_intrawweek_hard_gate(r, equity_target_after_gate=0.30)
    assert r2['equity_actual'] == 0.30
    assert r2['cash_actual'] == 0.50
    with pytest.raises(UnitQAError):
        apply_intrawweek_hard_gate(r, equity_target_after_gate=0.55)
