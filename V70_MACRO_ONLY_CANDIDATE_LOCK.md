# V70.2 Macro-only Weekly Candidate — Version Lock

- Authoritative whitepaper filename: `V70_2缺估值白皮書.md`
- Whitepaper last-modified line: `最後修改日期時間：2026/09/10 14:09（台灣時間）`
- SHA-256: `9eb507adb3f591f12ff0331c0b08d5ee0f20f41073e6e3e118d905cd53466ea2`
- Candidate name: `V70.2 Macro-only Weekly Candidate`
- Role: top-level weekly portfolio allocator only
- Equity execution: latest formal `V82.md`
- Bond execution: latest formal `債券V75.md`
- Parking: SGOV / formal short-Treasury parking pool

## Locked corrections

1. Exact computation weights use `18/90, 16/90, 14/90, 12/90, 16/90, 14/90`; rounded display percentages are never used for calculation.
2. Slow macro inputs use Last Known Valid PIT / As-of Carry Forward; no-new-release is not missing data.
3. Unit QA is a Hard Gate; no automatic percentage/bps/USD-bn scale guessing.
4. V70.2 weekly values are strategic maximum exposure caps. V82/Bond V75 may intrawweek reduce or stop exposure via their formal hard gates, but may not exceed the weekly caps. Unused/released capital returns to SGOV.
5. Valuation group and QQQ/SPY/VT TTM P/E are removed from this Candidate; this Candidate is not the original exact V70.2.

## Research integrity

This lock identifies the rule document used for implementation and backtest. Any substantive rule change requires a new Candidate/version lock and a full rerun. Do not silently tune this Candidate after observing results.
