import json
from pathlib import Path

LOCK = Path('formal_candidate_universe_lock.json')

EXPECTED_EQUITY = ['VT', 'VOO', 'QQQ', '0050', 'SOXX', 'PPH', 'NATO']
EXPECTED_BOND_PRIMARY = ['SGOV', 'SPSB', 'BNDW', '00859B', '00860B']
EXPECTED_EXTENDED_BOND = {'SHY', 'IEF', 'SPIB', 'TLT', 'SPLB', '00719B'}


def fail(msg: str) -> None:
    raise SystemExit(f'FORMAL_CANDIDATE_UNIVERSE_QA_FAIL: {msg}')


def main() -> None:
    if not LOCK.exists():
        fail(f'missing {LOCK}')
    data = json.loads(LOCK.read_text(encoding='utf-8'))

    src = data.get('source_of_truth', {})
    if src.get('file') != 'Mentor.md':
        fail('candidate universe source must be Mentor.md')
    if src.get('source_version') != 'v3.6.0':
        fail(f"unexpected Mentor version: {src.get('source_version')}")
    if src.get('authority') != 'strategic_S0_B0_candidate_universe_and_client_constraints':
        fail('Mentor authority marker is invalid')

    gov = data.get('governance', {})
    expected = {
        'strategic_allocator_rule': 'Mentor.md',
        'tactical_allocator_executable_rule': 'V70_2.html',
        'tactical_allocator_explanatory_rule': 'V70_16白皮書.md',
        'equity_execution_rule': 'V82.md',
        'bond_execution_rule': '債券V75.md',
        'v70_may_select_individual_assets': False,
        'mentor_may_hardcode_current_run_bond_weights': False,
        'sgov_bond_and_dry_powder_must_be_separate': True,
    }
    for k, v in expected.items():
        if gov.get(k) != v:
            fail(f'governance mismatch {k}: {gov.get(k)!r} != {v!r}')

    pools = data.get('generic_priority_candidate_pools', {})
    if pools.get('equity_examples') != EXPECTED_EQUITY:
        fail(f"equity candidate examples mismatch: {pools.get('equity_examples')!r}")
    if pools.get('bond_primary_examples') != EXPECTED_BOND_PRIMARY:
        fail(f"bond primary examples mismatch: {pools.get('bond_primary_examples')!r}")

    ext = set(data.get('existing_holding_or_extended_candidates', {}).get('bond', []))
    if not EXPECTED_EXTENDED_BOND.issubset(ext):
        fail(f'missing extended/existing bond candidates: {sorted(EXPECTED_EXTENDED_BOND - ext)}')

    if 'target_weights_within_subbucket' in data:
        fail('Mentor v3.6 lock must not hardcode current-run bond target weights')

    roles = data.get('asset_roles', {})
    if roles.get('parking_logical_asset') != 'SGOV_DRY_POWDER_BUCKET':
        fail('parking logical role mismatch')
    if roles.get('parking_ticker') != 'SGOV':
        fail('parking ticker must remain SGOV')
    if roles.get('bond_bucket_sgov_logical_asset') != 'SGOV_BOND_BUCKET':
        fail('bond SGOV logical role missing')
    if roles.get('bond_bucket_sgov_ticker') != 'SGOV':
        fail('bond SGOV ticker must remain SGOV')

    state = data.get('formal_state_contract', {})
    required = {
        'STOCK_ALLOCATION_FINAL', 'BOND_ALLOCATION_FINAL', 'SGOV_BOND_BUCKET',
        'V70_ORIGINAL_DRY_POWDER', 'V82_UNDEPLOYED_TO_SGOV', 'V75_UNDEPLOYED_TO_SGOV',
        'SGOV_DRY_POWDER_BUCKET', 'CASH_DRY_POWDER_BUCKET', 'TOTAL_DRY_POWDER'
    }
    if not required.issubset(set(state.get('required_fields', []))):
        fail('Latest State Contract fields incomplete')
    if state.get('double_count_sgov_forbidden') is not True:
        fail('SGOV double-count prohibition missing')

    print('FORMAL_CANDIDATE_UNIVERSE_QA_PASS')
    print('Mentor snapshot:', src.get('source_last_modified_taipei'), src.get('source_version'))
    print('Equity examples:', ','.join(EXPECTED_EQUITY))
    print('Primary bond examples:', ','.join(EXPECTED_BOND_PRIMARY))
    print('Architecture: Mentor S0/B0 -> V70_2 total tactical budgets -> V82/BondV75 security-level execution')
    print('SGOV roles separated: bond=SGOV_BOND_BUCKET; dry_powder=SGOV_DRY_POWDER_BUCKET')


if __name__ == '__main__':
    main()
