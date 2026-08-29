"""Exact half-year cohort benchmark including DFNS from first full half 2023H2."""
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
    # DFNS inception is 2023-03-31. 2023H1 is only a partial inception window,
    # so it is not a fair six-month fresh-money cohort and must not be reported
    # as a complete half-year benchmark.
    d = d[~((d.asset == 'DFNS') & (d.period == '2023_H1'))].copy()
    d.to_csv(p, index=False)
    stress = d[d.period.isin(['2020_H1','2022_H1','2022_H2'])].copy()
    stress.to_csv(h.OUT / 'halfyear_stress_2020_2022.csv', index=False)
    dfns = d[d.asset == 'DFNS']
    if len(dfns) == 0 or '2023_H2' not in set(dfns.period):
        raise SystemExit('INVALID DFNS cohort coverage: first full half 2023_H2 missing')
    if (dfns.period < '2023_H2').any():
        raise SystemExit('INVALID DFNS cohort coverage: pre-full-history cohort present')
    print('DFNS exact half-year cohorts:', len(dfns), 'first=', dfns.period.iloc[0])
    print('No pre-inception or partial-inception DFNS half-year history was fabricated.')


if __name__ == '__main__':
    main()
