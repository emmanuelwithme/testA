import ast
import json
import re
from pathlib import Path

ENGINE = Path('backtest_33_models_v2.py')
LEGACY_WORKFLOW = Path('.github/workflows/formal_backtest.yml')
LOCK = Path('formal_candidate_universe_lock.json')
OUT = Path('formal_backtest_contract_status.json')


def extract_const(text: str, name: str):
    m = re.search(rf"^{re.escape(name)}\s*=\s*['\"]([^'\"]+)['\"]", text, flags=re.M)
    return m.group(1) if m else None


def contains_any(text: str, variants):
    low = text.lower()
    return any(v.lower() in low for v in variants)


def extract_literal_dict_keys(text: str, name: str):
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return []
    for node in tree.body:
        if isinstance(node, ast.Assign):
            if any(isinstance(t, ast.Name) and t.id == name for t in node.targets):
                try:
                    value = ast.literal_eval(node.value)
                except Exception:
                    return []
                return list(value) if isinstance(value, dict) else []
    return []


def main():
    engine = ENGINE.read_text(encoding='utf-8') if ENGINE.exists() else ''
    workflow = LEGACY_WORKFLOW.read_text(encoding='utf-8') if LEGACY_WORKFLOW.exists() else ''
    lock = json.loads(LOCK.read_text(encoding='utf-8')) if LOCK.exists() else {}

    start = extract_const(engine, 'START')
    end = extract_const(engine, 'END')
    pools = lock.get('generic_priority_candidate_pools', {})
    roles = lock.get('asset_roles', {})
    eq = pools.get('equity', [])
    us_bonds = pools.get('us_bond', [])
    tw_bonds = pools.get('taiwan_retirement_bond', [])
    parking = roles.get('parking_assets', ['SGOV'])
    expected_us_risk_bonds = roles.get(
        'us_bond_risk_assets_for_equal_weight_benchmark',
        [x for x in us_bonds if x not in parking],
    )

    engine_stocks = extract_literal_dict_keys(engine, 'STOCKS')
    engine_bonds = extract_literal_dict_keys(engine, 'BONDS')

    stale_legacy_window = contains_any(
        workflow,
        [
            'Restrict formal evaluation window to 2019-2026',
            "start=pd.Timestamp('2019-01-01')",
            "end=pd.Timestamp('2026-08-26')",
        ],
    )
    case1_blocked = contains_any(
        engine,
        [
            'BLOCKED_MISSING_VALIDATED_DEPLOYMENT_CALIBRATION_AND_PIT_DATA',
            "'status':'BLOCKED",
            '"status":"BLOCKED',
        ],
    )

    checks = {
        'candidate_lock_present': bool(lock),
        'mentor_is_candidate_source': lock.get('source_of_truth', {}).get('file') == 'Mentor.md',
        'v82_is_equity_execution_source': lock.get('governance', {}).get('equity_execution_rule') == 'V82.md',
        'bondv75_is_bond_execution_source': lock.get('governance', {}).get('bond_execution_rule') == '債券V75.md',
        'v70_2_is_upper_allocator': lock.get('governance', {}).get('upper_allocator_rule') == 'V70_2缺估值白皮書.md',
        'unused_bucket_capacity_cannot_cross': lock.get('governance', {}).get('unused_bucket_capacity_may_cross_buckets') is False,
        'sgov_parking_role_explicit': 'SGOV' in parking,
        'main_start_2005_or_earlier': bool(start and start <= '2005-01-01'),
        'main_end_2026_08_31_or_later': bool(end and end >= '2026-09-01'),
        'legacy_workflow_not_formal_authority': stale_legacy_window,
        'engine_equity_universe_matches_mentor_lock': engine_stocks == eq,
        'engine_us_risk_bond_universe_matches_mentor_lock': engine_bonds == expected_us_risk_bonds,
        'taiwan_retirement_bond_pool_recorded': tw_bonds == ['00859B', '00719B', '00860B'],
        'case1_dynamic_portfolio_implemented': not case1_blocked,
        'explicit_buy_and_hold_comparator': contains_any(engine, ['Case2_AnnualSingle', 'annual_equal', 'Buy & Hold', 'buy_and_hold']),
        'explicit_dca_comparator': contains_any(engine, ['Case4_MonthlySingle', 'monthly_equal', 'DCA']),
        'single_etf_layer': contains_any(engine, ['AnnualSingle', 'MonthlySingle']),
        'portfolio_level_layer': contains_any(engine, ['dynamic_common_pool', 'AnnualEqual', 'MonthlyEqual']),
        'opportunity_cost_output': contains_any(engine, ['opportunity cost', 'opportunity_cost']),
        'capital_conservation_qa': contains_any(engine, ['capital conservation', 'capital_conservation', 'nav_identity']),
        'pit_control': contains_any(engine, ['PIT', 'point-in-time', 'point_in_time']),
        't_plus_1_control': contains_any(engine, ['T+1', 't_plus_1']),
        'is_oos_validation': contains_any(engine, ['IS/OOS', 'in-sample', 'out-of-sample', 'out_of_sample']),
        'walk_forward_validation': contains_any(engine, ['Walk-Forward', 'walk_forward']),
        'sensitivity_validation': contains_any(engine, ['sensitivity']),
        'stress_2008': '2008' in engine,
        'stress_2020': '2020' in engine,
        'stress_2022': '2022' in engine,
        'xirr_or_mwr_output': contains_any(engine, ['xirr', 'mwr']),
        'twr_output': contains_any(engine, ['twr']),
        'mdd_output': contains_any(engine, ['mdd', 'max drawdown', 'max_drawdown']),
        'sharpe_output': contains_any(engine, ['sharpe']),
        'sortino_output': contains_any(engine, ['sortino']),
        'calmar_output': contains_any(engine, ['calmar']),
        'recovery_output': contains_any(engine, ['recovery']),
    }

    # The old formal_backtest.yml is intentionally treated as legacy while it still
    # hard-restricts 2019-2026-08-26. A green legacy workflow never authorizes a
    # formal conclusion. Readiness is driven by the current engine plus the full contract.
    readiness_checks = {k: v for k, v in checks.items() if k != 'legacy_workflow_not_formal_authority'}
    status = {
        'schema_version': 2,
        'formal_backtest_ready': all(readiness_checks.values()),
        'engine': str(ENGINE),
        'legacy_workflow': str(LEGACY_WORKFLOW),
        'observed_engine_start': start,
        'observed_engine_end_exclusive': end,
        'locked_equity_candidates': eq,
        'locked_us_bond_candidates': us_bonds,
        'locked_us_risk_bond_benchmark_assets': expected_us_risk_bonds,
        'locked_taiwan_retirement_bond_candidates': tw_bonds,
        'parking_assets': parking,
        'observed_engine_equity_assets': engine_stocks,
        'observed_engine_bond_assets': engine_bonds,
        'legacy_workflow_has_stale_2019_window': stale_legacy_window,
        'checks': checks,
        'failed_checks': [k for k, v in readiness_checks.items() if not v],
        'policy': 'Mentor owns candidate universes; V82/BondV75 own execution; V70.2 owns bucket caps. Only formal_backtest_ready=true authorizes formal performance conclusions.',
    }
    OUT.write_text(json.dumps(status, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

    print('FORMAL_BACKTEST_CONTRACT_QA_EXECUTED')
    print('engine=', ENGINE)
    print('formal_backtest_ready=', status['formal_backtest_ready'])
    print('engine_equity=', ','.join(engine_stocks))
    print('mentor_equity=', ','.join(eq))
    print('engine_bonds=', ','.join(engine_bonds))
    print('mentor_us_risk_bonds=', ','.join(expected_us_risk_bonds))
    print('failed_checks=', ','.join(status['failed_checks']))


if __name__ == '__main__':
    main()
