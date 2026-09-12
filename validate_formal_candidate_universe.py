import json
from pathlib import Path

LOCK = Path('formal_candidate_universe_lock.json')

REQUIRED_TOP_LEVEL = {
    'schema_version',
    'source_of_truth',
    'governance',
    'generic_priority_candidate_pools',
    'scope_notes',
}

EXPECTED_CORE = {
    'equity': ['VT', 'VOO', 'QQQ', '0050', 'SOXX', 'PPH', 'NATO'],
    'us_bond': ['SGOV', 'SHY', 'IEF', 'SPIB'],
}
EXPECTED_TAIWAN_BOND = ['00859B', '00719B', '00860B']


def fail(msg: str) -> None:
    raise SystemExit(f'FORMAL_CANDIDATE_UNIVERSE_QA_FAIL: {msg}')


def main() -> None:
    if not LOCK.exists():
        fail(f'missing {LOCK}')

    data = json.loads(LOCK.read_text(encoding='utf-8'))
    missing = REQUIRED_TOP_LEVEL - set(data)
    if missing:
        fail(f'missing top-level keys: {sorted(missing)}')

    src = data['source_of_truth']
    if src.get('file') != 'Mentor.md':
        fail('candidate universe source must be Mentor.md')
    if src.get('authority') != 'candidate_universe_only':
        fail('Mentor authority marker is invalid')

    gov = data['governance']
    required_governance = {
        'equity_execution_rule': 'V82.md',
        'bond_execution_rule': '債券V75.md',
        'backtest_design_rule': '母規則回測.md',
        'upper_allocator_rule': 'V70_2缺估值白皮書.md',
        'unused_capital_destination': 'SGOV_or_formal_short_bond_parking_pool',
        'unused_bucket_capacity_may_cross_buckets': False,
    }
    for key, expected in required_governance.items():
        if gov.get(key) != expected:
            fail(f'governance mismatch {key}: {gov.get(key)!r} != {expected!r}')

    pools = data['generic_priority_candidate_pools']
    allowed_keys = set(EXPECTED_CORE) | {'taiwan_retirement_bond'}
    if not set(EXPECTED_CORE).issubset(pools):
        fail(f'missing required candidate pool keys: {sorted(set(EXPECTED_CORE) - set(pools))}')
    if not set(pools).issubset(allowed_keys):
        fail(f'unexpected candidate pool keys: {sorted(set(pools) - allowed_keys)}')

    for name, expected in EXPECTED_CORE.items():
        actual = pools.get(name)
        if actual != expected:
            fail(f'{name} candidate order/content mismatch: {actual!r} != {expected!r}')
        if len(actual) != len(set(actual)):
            fail(f'duplicate candidates in {name}')

    if 'taiwan_retirement_bond' in pools:
        actual = pools['taiwan_retirement_bond']
        if actual != EXPECTED_TAIWAN_BOND:
            fail(f'taiwan_retirement_bond mismatch: {actual!r} != {EXPECTED_TAIWAN_BOND!r}')
        if len(actual) != len(set(actual)):
            fail('duplicate candidates in taiwan_retirement_bond')

    forbidden_equity = {'TLT', 'SPLB', 'SPSB', 'SHY', 'IEF', 'SPIB', 'SGOV', '00859B', '00719B', '00860B'}
    forbidden_bond = {'VT', 'VOO', 'QQQ', '0050', 'SOXX', 'PPH', 'NATO'}
    if forbidden_equity.intersection(pools['equity']):
        fail('bond instruments leaked into equity candidate pool')
    if forbidden_bond.intersection(pools['us_bond']):
        fail('equity instruments leaked into US bond candidate pool')
    if 'taiwan_retirement_bond' in pools and forbidden_bond.intersection(pools['taiwan_retirement_bond']):
        fail('equity instruments leaked into Taiwan retirement bond candidate pool')

    parking = data.get('asset_roles', {}).get('parking_assets', ['SGOV'])
    if 'SGOV' not in parking:
        fail('SGOV must remain a parking asset under V70.2 governance')

    print('FORMAL_CANDIDATE_UNIVERSE_QA_PASS')
    print('Mentor snapshot:', src.get('source_last_modified_taipei'))
    print('Equity candidates:', ','.join(pools['equity']))
    print('US bond candidates:', ','.join(pools['us_bond']))
    if 'taiwan_retirement_bond' in pools:
        print('Taiwan retirement bond candidates:', ','.join(pools['taiwan_retirement_bond']))
    print('Parking assets:', ','.join(parking))
    print('Governance: Mentor -> candidate universe; V82/BondV75 -> execution; V70.2 -> bucket caps')


if __name__ == '__main__':
    main()
