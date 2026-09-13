import ast
import json
import re
from pathlib import Path

ENGINE = Path('formal_benchmark_engine_v3.py')
LEGACY_WORKFLOW = Path('.github/workflows/formal_backtest.yml')
LOCK = Path('formal_candidate_universe_lock.json')
DEPLOYMENT_LOCK = Path('formal_v82_deployment_lock.json')
OUT = Path('formal_backtest_contract_status.json')
EXPECTED_V82_LADDER = [10, 20, 30, 45, 60, 75, 85, 95, 100]


def extract_const(text: str, name: str):
    m = re.search(rf"(?:^|[;\n])\s*{re.escape(name)}\s*=\s*['\"]([^'\"]+)['\"]", text)
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
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == name for t in node.targets):
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
    deployment_lock = json.loads(DEPLOYMENT_LOCK.read_text(encoding='utf-8')) if DEPLOYMENT_LOCK.exists() else {}

    start = extract_const(engine, 'START') or ('2005-01-01' if '2005-01-01..2026-08-31' in engine else None)
    end = extract_const(engine, 'END') or ('2026-09-01' if '2005-01-01..2026-08-31' in engine else None)
    pools = lock.get('generic_priority_candidate_pools', {})
    roles = lock.get('asset_roles', {})
    gov = lock.get('governance', {})
    eq = pools.get('equity_examples', [])
    bond_primary = pools.get('bond_primary_examples', [])
    engine_stocks = extract_literal_dict_keys(engine, 'STOCKS')
    engine_bonds = extract_literal_dict_keys(engine, 'BONDS')
    deployment_ladder = deployment_lock.get('deployment_completion_ladder', [])
    deployment_gov = deployment_lock.get('governance', {})

    stale_legacy_window = contains_any(workflow, ['Restrict formal evaluation window to 2019-2026', "start=pd.Timestamp('2019-01-01')", "end=pd.Timestamp('2026-08-26')"])
    case1_blocked = contains_any(engine, ['BLOCKED_MISSING_COMPLETE_PIT_T1_DYNAMIC_EXECUTION_PIPELINE', "'status': 'BLOCKED", '"status":"BLOCKED'])

    checks = {
        'candidate_lock_present': bool(lock),
        'mentor_v36_is_strategic_and_candidate_source': lock.get('source_of_truth', {}).get('file') == 'Mentor.md' and lock.get('source_of_truth', {}).get('source_version') == 'v3.6.0',
        'mentor_owns_S0_B0': gov.get('strategic_allocator_rule') == 'Mentor.md',
        'v70_2_html_is_tactical_executable_source': gov.get('tactical_allocator_executable_rule') == 'V70_2.html',
        'v70_16_is_tactical_explanatory_source': gov.get('tactical_allocator_explanatory_rule') == 'V70_16白皮書.md',
        'v70_does_not_select_individual_assets': gov.get('v70_may_select_individual_assets') is False,
        'v82_is_equity_execution_source': gov.get('equity_execution_rule') == 'V82.md',
        'bondv75_is_bond_execution_source': gov.get('bond_execution_rule') == '債券V75.md',
        'mentor_does_not_hardcode_current_bond_weights': gov.get('mentor_may_hardcode_current_run_bond_weights') is False,
        'sgov_dual_role_explicit': roles.get('parking_logical_asset') == 'SGOV_DRY_POWDER_BUCKET' and roles.get('bond_bucket_sgov_logical_asset') == 'SGOV_BOND_BUCKET' and roles.get('parking_ticker') == 'SGOV' and roles.get('bond_bucket_sgov_ticker') == 'SGOV',
        'mother_backtest_source_resolved': gov.get('backtest_design_file_status') != 'NOT_FOUND_IN_CURRENT_DRIVE_ROOT_REQUIRES_RELOCATION_OR_CONFIRMATION',
        'v82_deployment_lock_present': bool(deployment_lock),
        'v82_deployment_ladder_matches_latest_formal_rule': deployment_ladder == EXPECTED_V82_LADDER,
        'v82_owns_formal_deployment_ratios': deployment_gov.get('v82_owns_formal_deployment_ratios') is True,
        'mother_backtest_cannot_optimize_v82_ratios': deployment_gov.get('mother_backtest_may_optimize_formal_ratios') is False,
        'deployment_ratios_are_cumulative': deployment_gov.get('ratios_are_cumulative_not_incremental') is True,
        'main_start_2005_or_earlier': bool(start and start <= '2005-01-01'),
        'main_end_2026_08_31_or_later': bool(end and end >= '2026-09-01'),
        'legacy_workflow_not_formal_authority': stale_legacy_window,
        'engine_equity_universe_matches_mentor_examples': engine_stocks == eq,
        'engine_supported_bonds_are_subset_of_mentor_primary': set(engine_bonds).issubset({'SGOV_BOND_BUCKET','SPSB','BNDW'}) and {'SGOV','SPSB','BNDW'}.issubset(set(bond_primary)),
        'taiwan_primary_bond_candidates_recorded': {'00859B','00860B'}.issubset(set(bond_primary)),
        'no_fixed_mentor_bond_weights_in_lock': 'target_weights_within_subbucket' not in lock,
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
    }

    helper = Path('backtest_33_models_v2.py').read_text(encoding='utf-8') if Path('backtest_33_models_v2.py').exists() else ''
    metric_map = {
        'xirr_or_mwr_output': ['xirr', 'mwr'], 'twr_output': ['twr'], 'mdd_output': ['mdd'],
        'sharpe_output': ['sharpe'], 'sortino_output': ['sortino'], 'calmar_output': ['calmar'], 'recovery_output': ['recovery'],
    }
    for key, variants in metric_map.items():
        checks[key] = contains_any(engine, variants) or contains_any(helper, variants)

    readiness_checks = {k: v for k, v in checks.items() if k != 'legacy_workflow_not_formal_authority'}
    status = {
        'schema_version': 6,
        'formal_backtest_ready': all(readiness_checks.values()),
        'engine': str(ENGINE),
        'observed_engine_start': start,
        'observed_engine_end_exclusive': end,
        'locked_equity_candidate_examples': eq,
        'locked_bond_primary_examples': bond_primary,
        'locked_v82_deployment_ladder_pct': deployment_ladder,
        'observed_engine_equity_assets': engine_stocks,
        'observed_engine_bond_assets': engine_bonds,
        'checks': checks,
        'failed_checks': [k for k, v in readiness_checks.items() if not v],
        'policy': (
            'Mentor v3.6 owns strategic S0/B0, candidate universes and client constraints; V70_2.html owns tactical C/T and total equity/bond/dry-powder budgets only; '
            'V82 owns equity security-level execution; BondV75 owns bond security-level execution. SGOV bond and dry-powder roles are separate. '
            'No fixed current-run bond weights may be attributed to Mentor. The missing standalone 母規則回測.md is a formal certification blocker; '
            'only formal_backtest_ready=true authorizes final strategy performance conclusions.'
        )
    }
    OUT.write_text(json.dumps(status, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print('FORMAL_BACKTEST_CONTRACT_QA_EXECUTED')
    print('formal_backtest_ready=', status['formal_backtest_ready'])
    print('failed_checks=', ','.join(status['failed_checks']))


if __name__ == '__main__':
    main()
