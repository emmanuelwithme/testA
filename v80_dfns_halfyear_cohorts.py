"""Exact half-year cohort benchmark including DFNS with partial inception history explicitly marked."""
import pandas as pd
import v80_dfns_backtest as dfns_runner  # patches core ASSETS/PARAM/cross factors
import v80_halfyear_cohorts as h

# v80_halfyear_cohorts imported the original dict objects; make the intended
# formal universe explicit for readability and validation.
h.ASSETS = dfns_runner.core.ASSETS
h.PARAM = dfns_runner.core.PARAM


def main():
    h.main()
    p = h.OUT / 'halfyear_cohort_benchmark.csv'
    d = pd.read_csv(p)
    stress = d[d.period.isin(['2020_H1','2022_H1','2022_H2'])].copy()
    stress.to_csv(h.OUT / 'halfyear_stress_2020_2022.csv', index=False)

    dfns = d[d.asset == 'DFNS'].copy()
    if len(dfns) == 0 or '2023_H2' not in set(dfns.period):
        raise SystemExit('INVALID DFNS cohort coverage: first full half 2023_H2 missing')

    # DFNS inception is 2023-03-31. 2023H1 may exist only as a partial inception
    # cohort and must be explicitly marked incomplete; no pre-inception backfill is allowed.
    h1 = dfns[dfns.period == '2023_H1']
    if len(h1):
        if not bool(h1.is_incomplete_period.iloc[0]):
            raise SystemExit('INVALID DFNS 2023H1: partial inception cohort not marked incomplete')
        if int(h1.observed_trading_months.iloc[0]) >= 6:
            raise SystemExit('INVALID DFNS 2023H1: fabricated six-month history detected')
    pre = dfns[dfns.period < '2023_H1']
    if len(pre):
        raise SystemExit('INVALID DFNS cohort coverage: pre-inception cohort present')

    full = dfns[~dfns.is_incomplete_period.astype(bool)]
    if len(full) == 0 or full.period.iloc[0] != '2023_H2':
        raise SystemExit('INVALID DFNS cohort coverage: first complete half must be 2023_H2')

    print('DFNS cohorts:', len(dfns), 'first=', dfns.period.iloc[0], 'first_full=', full.period.iloc[0])
    print('DFNS 2023H1 retained only as an explicitly incomplete inception cohort; no history was fabricated.')


if __name__ == '__main__':
    main()
