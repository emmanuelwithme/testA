# V70.2 Weekly Macro Allocator Candidate

Status: CANDIDATE / RESEARCH ONLY

Purpose: add a portfolio-level allocator above V82 (stocks) and Bond V75 (bonds) without changing either rulebook's asset-level buy/sell conditions.

## Source lock
- V70_2.html SHA256: f525f12afb22546669054423d30a00c23f691dd1772cdf9027425d417671b336
- V70_16白皮書Gemini.html SHA256: 6e75472c396a2a497bc3781f07f8ae065d24c4ce51cf327a263d720b913891c5
- V82.md: latest Library version at experiment start
- 母規則回測.md: latest Library version at experiment start
- 債券V75.md: latest Library version at experiment start

## Architecture
1. V70.2 = top-level weekly allocation layer only.
2. V82 = stock / stock-ETF decision engine inside the stock bucket.
3. Bond V75 = bond / bond-ETF decision engine inside the bond bucket.
4. SGOV / formal short-Treasury parking = residual undeployed capital.
5. No V70.2 stock H-Score is allowed to override V82 asset-level decisions in the formal combined model.
6. No V70.2 bond sub-allocation matrix is allowed to override Bond V75 asset-level decisions in the formal combined model.

## V70.2 top-level allocation states copied from the source whitepaper/code
- mSafe >= 70: Stock 70%, Bond 20%, Cash/Parking 10%
- 55 <= mSafe < 70: Stock 60%, Bond 30%, Cash/Parking 10%
- 40 <= mSafe < 55: Stock 40%, Bond 40%, Cash/Parking 20%
- mSafe < 40: Stock 0%; Bond 20% only when bScore > 6, otherwise Bond 0%; residual is Cash/Parking
- Emergency / meltdown state from V70.2: Stock 0%, Bond 0%, Cash/Parking 100%

## Macro groups copied from V70.2 whitepaper
- Panic/Volatility 18%
- Credit 16%
- Inflation 14%
- Rates 12%
- Liquidity 16%
- Growth 14%
- Valuation 10%

The exact indicator thresholds, gamma transforms, capping layers, accelerators and recession/crisis rules must come from the locked V70.2 sources. The backtest code may not silently alter, simplify, fill, reweight or reinterpret them.

## Weekly cadence
User-approved research direction: calculate the top-level macro allocation once per week rather than daily.

Formal execution anchor is NOT silently invented here. The backtest must either:
- read a formally locked weekly anchor from a rule file, or
- run the permitted anchor(s) as an explicit sensitivity experiment and label them as such.

All signal execution remains strict Point-in-Time and T+1. No same-close execution and no look-ahead.

## Capital conservation
Single common portfolio pool. Every date must satisfy:
ETF market value + SGOV/formal parking + cash + realized undeployed cash = NAV.
No duplicate use of capital, negative cash, financing or hidden leverage unless separately and explicitly authorized by a locked rule.

## Required formal comparisons
The candidate must be compared against the same mother-rule baselines using the same annual NT$1,000,000 external contribution, parking convention, costs and accounting:
- Buy & Hold
- DCA
- existing V82 / Bond V75 formal models where programmable
- V70.2 Weekly Macro Allocator diagnostic model
- V82 + Bond V75 + V70.2 Weekly Macro Allocator combined candidate when all required engines and PIT data are programmable

## Output requirements
At minimum preserve the mother-rule metrics: Total Cost, Ending Asset, Total Profit, Total Return, XIRR/MWR, TWR CAGR, unitized/TWR NAV MDD, Sharpe, Sortino, Calmar, Recovery Time, annual returns, worst year, worst 12 months, average stock exposure, average parking exposure, portfolio weight statistics, capital-conservation QA and Opportunity Cost.

## Hard research constraints
- 2005-01-01 through 2026-08-31 long-cycle test
- 2019-01-01 through 2026-08-31 modern subsample
- 2008, 2020, 2022 stress decomposition
- Actual ETF Only before listing = N/A
- NATO uses NATO.L actual post-listing history only; no pre-listing proxy; DFNS prohibited as substitute
- Extended Index Proxy only when the mother rule explicitly permits a formal Total Return Index with source/PIT/backfill/fee disclosure
- strict PIT publication lag; no look-ahead
- Gap Recheck / Signal Cluster dedup as required by the mother rule
- any V82, Bond V75 or V70.2 clause that cannot be reliably programmed from historical PIT data must be marked BLOCKED / UNPROGRAMMABLE, never manually filled
- no parameter rescue after seeing results; any strategy change requires a new named candidate and full rerun

## Current expected blocker
The repository already contains a V82-native historical engine, but a fully equivalent programmable Bond V75 engine and complete historical PIT implementation of every V70.2 input are not yet guaranteed. The combined candidate must remain blocked until those dependencies pass preflight. A top-level V70.2 diagnostic backtest may run only if its exact V70.2 inputs are available under the locked source definitions; otherwise it must report the missing series rather than substitute invented data.
