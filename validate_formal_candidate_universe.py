import json
from pathlib import Path

LOCK = Path('formal_candidate_universe_lock.json')

EXPECTED_EQUITY = ['VT', 'VOO', 'QQQ', '0050', 'SOXX', 'PPH', 'NATO']
EXPECTED_BOND_PRIMARY = ['SGOV', 'SPSB', '00859B', '00860B']
EXPECTED_EXTENDED_BOND = {'BNDW', 'SHY', 'IEF', 'SPIB', 'TLT', 'SPLB', '00719B'}
EXPECTED_US_WEIGHTS = {'SGOV_BOND_BUCKET': 0.70, 'SPSB': 0.30}
EXPECTED_TW_WEIGHTS = {'00859B': 0.80, '00860B': 0.20}
EXPECTED_LIFE_STAGE_SPLITS = {
    '1': [50, 50], '2': [70, 30], '3': [50, 50], '4': [60, 40],
    '5': [30, 70], '6': [20, 80], '7': [50, 50], '8': [50, 50],
    '9': [40, 60], '10': [40, 60],
}


def fail(msg: str) -> None:
    raise SystemExit(f'FORMAL_CANDIDATE_UNIVERSE_QA_FAIL: {msg}')


def main() -> None:
    if not LOCK.exists():
        fail(f'missing {LOCK}')
    data = json.loads(LOCK.read_text(encoding='utf-8'))

    src = data.get('source_of_truth', {})
    if src.get('file') != 'Mentor.md':
        fail('candidate universe source must be Mentor.md')
    if src.get('source_version') != 'v3.7.0':
        fail(f"unexpected Mentor version: {src.get('source_version')}")
    if src.get('authority') != 'strategic_S0_B0_candidate_universe_and_client_constraints':
        fail('Mentor authority marker is invalid')

    gov = data.get('governance', {})
    expected = {
        'strategic_allocator_rule': 'Mentor.md',
        'tactical_allocator_executable_rule': 'V70_2.html',
        'tactical_allocator_output_contract_version': 'v1.1.1',
        'tactical_allocator_explanatory_rule': 'V70_16白皮書.md',
        'tactical_allocator_explanatory_version': 'v3.5.0',
        'equity_execution_rule': 'V82.md',
        'bond_execution_rule': '債券V75.md',
        'bond_execution_version': 'v2.5.0',
        'v70_may_select_individual_assets': False,
        'mentor_may_hardcode_current_run_bond_weights': False,
        'bondv75_owns_bond_subbucket_and_security_target_weights': True,
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
    if 'BNDW' in set(pools.get('bond_primary_examples', [])):
        fail('BNDW must not remain in generic new-allocation primary pool')

    if 'target_weights_within_subbucket' in data:
        fail('Mentor v3.7 lock must not hardcode current-run bond target weights')

    bond_policy = data.get('bond_v75_execution_policy', {})
    if bond_policy.get('source_file') != '債券V75.md' or bond_policy.get('source_version') != 'v2.5.0':
        fail('BondV75 execution policy source/version mismatch')
    if bond_policy.get('life_stage_us_taiwan_bond_subbucket_pct') != EXPECTED_LIFE_STAGE_SPLITS:
        fail('BondV75 life-stage US/Taiwan subbucket map mismatch')
    if bond_policy.get('us_bond_subbucket_target_weights') != EXPECTED_US_WEIGHTS:
        fail('BondV75 US bond target weights mismatch')
    if bond_policy.get('taiwan_bond_subbucket_target_weights') != EXPECTED_TW_WEIGHTS:
        fail('BondV75 Taiwan bond target weights mismatch')
    if bond_policy.get('bndw_generic_new_allocation_allowed') is not False:
        fail('BNDW generic new-allocation flag must be false')
    if bond_policy.get('bndw_existing_holding_management_only') is not True:
        fail('BNDW existing-holding management flag must be true')
    if bond_policy.get('deployment_still_subject_to_bond_v75_market_safety_and_wait_rules') is not True:
        fail('BondV75 target map must remain subject to market-safety/deployment rules')

    v70_contract = data.get('v70_output_contract', {})
    if v70_contract.get('version') != 'v1.1.1':
        fail('V70 output contract must be v1.1.1')
    if v70_contract.get('run_id_supported') is not True:
        fail('V70 output contract run_id support missing')
    if v70_contract.get('life_stage_metadata_required') != ['lifeStageCode', 'lifeStageLabel']:
        fail('V70 life-stage metadata contract mismatch')
    if v70_contract.get('v70_outputs_only_total_budgets') is not True:
        fail('V70 must output only total tactical budgets')

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
    print('V70 output contract: v1.1.1; V70 explanatory spec: v3.5.0')
    print('Equity examples:', ','.join(EXPECTED_EQUITY))
    print('Primary bond examples:', ','.join(EXPECTED_BOND_PRIMARY))
    print('BondV75 v2.5 US targets: SGOV 70%, SPSB 30%; Taiwan targets: 00859B 80%, 00860B 20%')
    print('BNDW status: existing-holding management only; no generic new allocation')
    print('Architecture: Mentor S0/B0 -> V70_2 total tactical budgets -> V82/BondV75 security-level execution')
    print('SGOV roles separated: bond=SGOV_BOND_BUCKET; dry_powder=SGOV_DRY_POWDER_BUCKET')


if __name__ == '__main__':
    main()
