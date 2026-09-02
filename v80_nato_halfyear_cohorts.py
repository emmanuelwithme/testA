"""Exact half-year cohort benchmark including NATO, with completeness determined from observed trading months."""
import pandas as pd
import v80_nato_backtest as nato_runner  # patches core ASSETS/PARAM/cross factors
import v80_halfyear_cohorts as h

h.ASSETS = nato_runner.core.ASSETS
h.PARAM = nato_runner.core.PARAM


def main():
    h.main()
    p = h.OUT / 'halfyear_cohort_benchmark.csv'
    d = pd.read_csv(p)

    stress = d[d.period.isin(['2020_H1','2022_H1','2022_H2'])].copy()
    stress.to_csv(h.OUT / 'halfyear_stress_2020_2022.csv', index=False)

    nato = d[d.asset == 'NATO'].copy()
    if len(nato) == 0:
        raise SystemExit('INVALID NATO cohort coverage: no NATO cohorts')
    if '2023_H2' not in set(nato.period):
        raise SystemExit('INVALID NATO cohort coverage: 2023H2 missing')

    pre = nato[nato.period < '2023_H2']
    if len(pre):
        raise SystemExit('INVALID NATO cohort coverage: pre-inception cohort present')

    inc = nato[nato.period == '2023_H2']
    if len(inc) != 1:
        raise SystemExit('INVALID NATO 2023H2 cohort cardinality')

    months = int(pd.to_numeric(inc.dca_months_invested, errors='coerce').iloc[0])
    incomplete = bool(inc.is_incomplete_period.astype(bool).iloc[0])
    # NATO.L history starts on 2023-07-04, which is still July. Under the formal
    # cohort rule, completeness is based on actual observed trading months, not
    # on whether listing occurred on the first calendar day of the half-year.
    if months == 6 and incomplete:
        raise SystemExit('INVALID NATO 2023H2: six observed trading months must not be force-marked incomplete')
    if months < 6 and not incomplete:
        raise SystemExit('INVALID NATO 2023H2: missing trading months must be marked incomplete')

    full = nato[~nato.is_incomplete_period.astype(bool)]
    expected_first_full = '2023_H2' if months == 6 else '2024_H1'
    if len(full) == 0 or full.period.iloc[0] != expected_first_full:
        raise SystemExit(f'INVALID NATO first full cohort: expected {expected_first_full}, got {full.period.tolist()}')

    print('NATO cohorts:', len(nato), 'first=', nato.period.iloc[0], 'first_full=', full.period.iloc[0], '2023H2_months=', months)
    print('NATO history uses only genuine post-listing data; cohort completeness is based on actual observed trading months.')


if __name__ == '__main__':
    main()
