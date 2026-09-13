import json
from pathlib import Path

LOCK = Path('formal_v82_deployment_lock.json')
OUT = Path('formal_v82_deployment_lock_status.json')
EXPECTED = [10, 20, 30, 45, 60, 75, 85, 95, 100]


def main():
    data = json.loads(LOCK.read_text(encoding='utf-8'))
    ladder = data.get('deployment_completion_ladder', [])
    gov = data.get('governance', {})
    src = data.get('source_of_truth', {})

    checks = {
        'source_is_v82': src.get('file') == 'V82.md',
        'latest_fine_ladder_locked': ladder == EXPECTED,
        'strictly_increasing': all(a < b for a, b in zip(ladder, ladder[1:])),
        'ends_at_100': bool(ladder and ladder[-1] == 100),
        'ratios_are_cumulative': gov.get('ratios_are_cumulative_not_incremental') is True,
        'v82_owns_ratios': gov.get('v82_owns_formal_deployment_ratios') is True,
        'mother_rule_cannot_optimize': gov.get('mother_backtest_may_optimize_formal_ratios') is False,
        'project_lower_cap_allowed': gov.get('project_specific_lower_cap_may_override') is True,
    }
    status = {
        'schema_version': 1,
        'deployment_lock_ready': all(checks.values()),
        'deployment_completion_ladder': ladder,
        'checks': checks,
        'failed_checks': [k for k, v in checks.items() if not v],
        'policy': 'V82 owns formal deployment ratios; backtest validates but does not optimize or replace them.'
    }
    OUT.write_text(json.dumps(status, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(status, ensure_ascii=False))
    if not status['deployment_lock_ready']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
