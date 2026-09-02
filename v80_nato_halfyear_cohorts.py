"""Exact half-year cohort benchmark including NATO with inception half marked incomplete."""
import pandas as pd
import v80_nato_backtest as nato_runner  # patches core ASSETS/PARAM/cross factors
import v80_halfyear_cohorts as h

h.ASSETS = nato_runner.core.ASSETS
h.PARAM = nato_runner.core.PARAM


def main():
    h.main()
    p = h.OUT / 'halfyear_cohort_benchmark.csv'
    d = pd.read_csv(p)

    # NATO listed on LSE on 2023-07-04. Preserve the genuine 2023H2 data but
    # explicitly mark it as an inception half rather than a complete canonical half.
    mask = (d.asset == 'NATO') & (d.period == '2023_H2')
    if mask.any():
        d.loc[mask, 'is_incomplete_period'] = True
        d.to_csv(p, index=False)

    stress = d[d.period.isin(['2020_H1','2022_H1','2022_H2'])].copy()
    stress.to_csv(h.OUT / 'halfyear_stress_2020_2022.csv', index=False)

    nato = d[d.asset == 'NATO'].copy()
    if len(nato) == 0:
        raise SystemExit('INVALID NATO cohort coverage: no NATO cohorts')
    if '2023_H2' not in set(nato.period):
        raise SystemExit('INVALID NATO cohort coverage: inception half 2023_H2 missing')

    inc = nato[nato.period == '2023_H2']
    if not bool(inc.is_incomplete_period.iloc[0]):
        raise SystemExit('INVALID NATO 2023H2: inception half not marked incomplete')

    pre = nato[nato.period < '2023_H2']
    if len(pre):
        raise SystemExit('INVALID NATO cohort coverage: pre-inception cohort present')

    full = nato[~nato.is_incomplete_period.astype(bool)]
    if len(full) == 0 or full.period.iloc[0] != '2024_H1':
        raise SystemExit('INVALID NATO cohort coverage: first complete half must be 2024_H1')

    print('NATO cohorts:', len(nato), 'first=', nato.period.iloc[0], 'first_full=', full.period.iloc[0])
    print('NATO 2023H2 retained only as an explicitly incomplete inception cohort; no history was fabricated.')


if __name__ == '__main__':
    main()
