import json
from pathlib import Path

LOCK = Path('formal_candidate_universe_lock.json')

EXPECTED_EQUITY = ['VT', 'VOO', 'QQQ', '0050', 'SOXX', 'PPH', 'NATO']
EXPECTED_US_BOND = ['SGOV_BOND_BUCKET', 'SPSB', 'BNDW']
EXPECTED_TW_BOND = ['00859B', '00860B']
EXPECTED_US_WEIGHTS = {'SGOV_BOND_BUCKET': 0.50, 'SPSB': 0.35, 'BNDW': 0.15}
EXPECTED_TW_WEIGHTS = {'00859B': 0.80, '00860B': 0.20}


def fail(msg: str) -> None:
    raise SystemExit(f'FORMAL_CANDIDATE_UNIVERSE_QA_FAIL: {msg}')


def main() -> None:
    if not LOCK.exists():
        fail(f'missing {LOCK}')
    data = json.loads(LOCK.read_text(encoding='utf-8'))

    src = data.get('source_of_truth', {})
    if src.get('file') != 'Mentor.md':
        fail('candidate universe source must be Mentor.md')
    if src.get('source_version') != 'v3.0.0':
        fail(f"unexpected Mentor version: {src.get('source_version')}")
    if src.get('authority') != 'candidate_universe_and_target_roles':
        fail('Mentor authority marker is invalid')

    gov = data.get('governance', {})
    expected_gov = {
        'equity_execution_rule': 'V82.md',
        'bond_execution_rule': '債券V75.md',
        'backtest_design_rule': '母規則回測.md',
        'upper_allocator_rule': 'V70_2缺估值白皮書.md',
        'unused_bucket_capacity_may_cross_buckets': False,
    }
    for k, v in expected_gov.items():
        if gov.get(k) != v:
            fail(f'governance mismatch {k}: {gov.get(k)!r} != {v!r}')

    pools = data.get('generic_priority_candidate_pools', {})
    if pools.get('equity') != EXPECTED_EQUITY:
        fail(f"equity pool mismatch: {pools.get('equity')!r}")
    if pools.get('us_bond_core') != EXPECTED_US_BOND:
        fail(f"US bond core mismatch: {pools.get('us_bond_core')!r}")
    if pools.get('taiwan_bond_core') != EXPECTED_TW_BOND:
        fail(f"Taiwan bond core mismatch: {pools.get('taiwan_bond_core')!r}")

    weights = data.get('target_weights_within_subbucket', {})
    if weights.get('us_bond_core') != EXPECTED_US_WEIGHTS:
        fail(f"US bond weights mismatch: {weights.get('us_bond_core')!r}")
    if weights.get('taiwan_bond_core') != EXPECTED_TW_WEIGHTS:
        fail(f"Taiwan bond weights mismatch: {weights.get('taiwan_bond_core')!r}")
    if abs(sum(EXPECTED_US_WEIGHTS.values()) - 1.0) > 1e-12:
        fail('US bond weights do not sum to 1')
    if abs(sum(EXPECTED_TW_WEIGHTS.values()) - 1.0) > 1e-12:
        fail('Taiwan bond weights do not sum to 1')

    roles = data.get('asset_roles', {})
    if roles.get('parking_assets') != ['SGOV_DRY_POWDER_BUCKET']:
        fail('parking role must be SGOV_DRY_POWDER_BUCKET')
    if roles.get('parking_ticker') != 'SGOV':
        fail('parking ticker must remain SGOV')
    if roles.get('bond_bucket_sgov_logical_asset') != 'SGOV_BOND_BUCKET':
        fail('bond SGOV logical role missing')
    if roles.get('bond_bucket_sgov_ticker') != 'SGOV':
        fail('bond SGOV ticker must be SGOV')
    if roles.get('us_bond_core_assets') != EXPECTED_US_BOND:
        fail('US bond role list mismatch')
    if roles.get('taiwan_bond_core_assets') != EXPECTED_TW_BOND:
        fail('Taiwan bond role list mismatch')

    legacy = set(roles.get('legacy_research_or_existing_holding_only', []))
    required_legacy = {'00719B', 'SHY', 'IEF', 'SPIB', 'TLT', 'SPLB'}
    if not required_legacy.issubset(legacy):
        fail(f'missing legacy research/holding-only assets: {sorted(required_legacy - legacy)}')

    if set(EXPECTED_EQUITY) & set(EXPECTED_US_BOND + EXPECTED_TW_BOND):
        fail('equity/bond candidate leakage')

    print('FORMAL_CANDIDATE_UNIVERSE_QA_PASS')
    print('Mentor snapshot:', src.get('source_last_modified_taipei'), src.get('source_version'))
    print('Equity candidates:', ','.join(EXPECTED_EQUITY))
    print('US bond core:', ','.join(EXPECTED_US_BOND))
    print('Taiwan bond core:', ','.join(EXPECTED_TW_BOND))
    print('SGOV roles: bond=SGOV_BOND_BUCKET; parking=SGOV_DRY_POWDER_BUCKET; ticker=SGOV')


if __name__ == '__main__':
    main()
