import json
import re
from pathlib import Path

ENGINE = Path('investment_backtest.py')
WORKFLOW = Path('.github/workflows/formal_backtest.yml')
LOCK = Path('formal_candidate_universe_lock.json')
OUT = Path('formal_backtest_contract_status.json')

REQUIRED_METRIC_TOKENS = [
    'Ending Asset', 'XIRR', 'TWR', 'MDD', 'Sharpe', 'Sortino', 'Calmar', 'Recovery',
    'Opportunity Cost',
]
REQUIRED_VALIDATION_TOKENS = [
    'PIT', 'T+1', 'Walk-Forward', 'sensitivity', 'IS/OOS', 'capital conservation',
]


def extract_const(text: str, name: str):
    m = re.search(rf"^{re.escape(name)}\s*=\s*['\"]([^'\"]+)['\"]", text, flags=re.M)
    return m.group(1) if m else None


def contains_any(text: str, variants):
    low = text.lower()
    return any(v.lower() in low for v in variants)


def main():
    engine = ENGINE.read_text(encoding='utf-8') if ENGINE.exists() else ''
    workflow = WORKFLOW.read_text(encoding='utf-8') if WORKFLOW.exists() else ''
    lock = json.loads(LOCK.read_text(encoding='utf-8')) if LOCK.exists() else {}

    start = extract_const(engine, 'START')
    end = extract_const(engine, 'END')
    eq = lock.get('generic_priority_candidate_pools', {}).get('equity', [])
    bonds = lock.get('generic_priority_candidate_pools', {}).get('us_bond', [])

    checks = {
        'candidate_lock_present': bool(lock),
        'mentor_is_candidate_source': lock.get('source_of_truth', {}).get('file') == 'Mentor.md',
        'main_start_2005_or_earlier': bool(start and start <= '2005-01-01'),
        'main_end_2026_08_31_or_later': bool(end and end >= '2026-08-31'),
        'workflow_not_hard_restricted_to_2019_2026_08_26': not contains_any(
            workflow,
            ['Restrict formal evaluation window to 2019-2026', "start=pd.Timestamp('2019-01-01')", "end=pd.Timestamp('2026-08-26')"],
        ),
        'engine_has_all_locked_equity_candidates': all(t in engine for t in eq),
        'bond_candidates_available_for_portfolio_layer': all(t in (engine + workflow) for t in bonds),
        'explicit_buy_and_hold_comparator': contains_any(engine + workflow, ['buy & hold', 'buy_and_hold', 'buyhold', 'b&h']),
        'explicit_dca_comparator': contains_any(engine + workflow, ['dca', 'monthly dca']),
        'single_etf_layer': contains_any(engine + workflow, ['single-etf', 'single_etf', 'single etf']),
        'portfolio_level_layer': contains_any(engine + workflow, ['portfolio-level', 'portfolio_level', 'portfolio level']),
        'opportunity_cost_output': contains_any(engine + workflow, ['opportunity cost', 'opportunity_cost']),
        'capital_conservation_qa': contains_any(engine + workflow, ['capital conservation', 'capital_conservation', 'nav_identity']),
        'pit_control': contains_any(engine + workflow, ['point-in-time', 'point_in_time', 'pit']),
        't_plus_1_control': contains_any(engine + workflow, ['t+1', 't_plus_1']),
        'is_oos_validation': contains_any(engine + workflow, ['is/oos', 'in-sample', 'out-of-sample', 'out_of_sample']),
        'walk_forward_validation': contains_any(engine + workflow, ['walk-forward', 'walk_forward']),
        'sensitivity_validation': contains_any(engine + workflow, ['sensitivity']),
        'stress_2008': '2008' in (engine + workflow),
        'stress_2020': '2020' in (engine + workflow),
        'stress_2022': '2022' in (engine + workflow),
        'xirr_or_mwr_output': contains_any(engine + workflow, ['xirr', 'mwr']),
        'twr_output': contains_any(engine + workflow, ['twr']),
        'mdd_output': contains_any(engine + workflow, ['mdd', 'max drawdown', 'max_drawdown']),
        'sharpe_output': contains_any(engine + workflow, ['sharpe']),
        'sortino_output': contains_any(engine + workflow, ['sortino']),
        'calmar_output': contains_any(engine + workflow, ['calmar']),
        'recovery_output': contains_any(engine + workflow, ['recovery']),
    }

    status = {
        'schema_version': 1,
        'formal_backtest_ready': all(checks.values()),
        'engine': str(ENGINE),
        'workflow': str(WORKFLOW),
        'observed_engine_start': start,
        'observed_engine_end': end,
        'locked_equity_candidates': eq,
        'locked_us_bond_candidates': bonds,
        'checks': checks,
        'failed_checks': [k for k, v in checks.items() if not v],
        'policy': 'A green QA workflow means the readiness diagnostic executed successfully; only formal_backtest_ready=true authorizes formal performance conclusions.',
    }
    OUT.write_text(json.dumps(status, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

    print('FORMAL_BACKTEST_CONTRACT_QA_EXECUTED')
    print('formal_backtest_ready=', status['formal_backtest_ready'])
    print('failed_checks=', ','.join(status['failed_checks']))


if __name__ == '__main__':
    main()
