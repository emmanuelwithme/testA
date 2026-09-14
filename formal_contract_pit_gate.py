from __future__ import annotations

import json
from pathlib import Path

STATUS = Path('formal_backtest_contract_status.json')
PIT_LOCK = Path('formal_pit_data_lock.json')
REQUIRED = ['TGA', 'WALCL', 'RRP', '5Y_BREAKEVEN', 'REAL_10Y', 'SAHM_RULE']


def main() -> int:
    if not STATUS.exists():
        raise SystemExit(f'CONTRACT_STATUS_MISSING: {STATUS}')
    data = json.loads(STATUS.read_text(encoding='utf-8'))
    lock = json.loads(PIT_LOCK.read_text(encoding='utf-8')) if PIT_LOCK.exists() else {}
    mapping = lock.get('formal_pit_ready', {})

    lock_present = bool(lock)
    required_set_matches = lock.get('required_inputs') == REQUIRED
    all_ready = lock.get('all_required_pit_ready') is True and all(mapping.get(k) is True for k in REQUIRED)

    checks = data.setdefault('checks', {})
    checks['formal_pit_data_lock_present'] = lock_present
    checks['formal_pit_required_input_set_locked'] = required_set_matches
    checks['all_required_pit_inputs_ready'] = all_ready

    failed = [k for k, v in checks.items() if k != 'legacy_workflow_not_formal_authority' and not v]
    data['failed_checks'] = failed
    data['locked_pit_data_status'] = lock
    data['formal_backtest_ready'] = len(failed) == 0
    data['schema_version'] = max(int(data.get('schema_version', 0)), 11)
    data['policy'] = str(data.get('policy', '')) + (
        ' Formal PIT readiness is separately hard-gated by formal_pit_data_lock.json; '
        'all six required PIT inputs must be verified before formal_backtest_ready may become true.'
    )

    STATUS.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print('FORMAL_CONTRACT_PIT_GATE_APPLIED')
    print('pit_ready_count=', lock.get('ready_count'))
    print('pit_required_count=', lock.get('required_count'))
    print('formal_backtest_ready=', data['formal_backtest_ready'])
    print('failed_checks=', ','.join(failed))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
