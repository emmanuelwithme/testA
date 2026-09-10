# Case 1｜V70.2 分桶資金仲裁正式契約

## 結論

`BLOCKED_UNPROGRAMMABLE_CROSS_ASSET_ALLOCATOR` 已解除。

原因：V70.2 Macro-only Weekly 在每週先決定股票桶、債券桶、SGOV／現金桶。V82 與債券V75只管理各自被V70.2分配的資金，不互相競爭對方資金。

## 正式資金流

1. 先以當週 `mSafe_final` 取得：
   - `equity_max`
   - `bond_max`
   - `cash_min`
2. 依當日NAV建立兩個獨立風險預算：
   - 股票預算上限 = `NAV × equity_max`
   - 債券預算上限 = `NAV × bond_max`
3. 股票預算只由最新版 `V82.md` 管理。
4. 債券預算只由最新版 `債券V75.md` 管理。
5. V82未使用的股票預算不得轉給債券V75；直接回到SGOV／正式短債停泊池。
6. 債券V75未使用的債券預算不得轉給V82；直接回到SGOV／正式短債停泊池。
7. 任何週中Hard Gate可使實際股票／債券曝險低於Weekly上限，但不得突破Weekly上限。
8. 資本守恆：`股票市值 + 債券市值 + SGOV/現金 + 已實現未部署現金 = NAV`。
9. 禁止負現金、融資、隱含槓桿與同一資金重複使用。

## 例子

若V70.2本週給：股票60%、債券30%、SGOV最低10%，而V82實際只用40%、債券V75實際只用18%，則最終為：

- 股票40%
- 債券18%
- SGOV／現金42%

未使用的20%股票額度與12%債券額度都回SGOV，兩個風險桶彼此不借額度。

## 對Formal Backtest的影響

原本Case 1的「股票／債券同時搶共同現金時如何仲裁」不再是未定義問題。正式回測應改成：

`V70.2 Weekly → 分桶 → V82股票子池 + 債券V75債券子池 → 未部署資金回SGOV → 合併NAV與資本守恆QA`

仍未完成的項目（如V70.2歷史PIT資料、完整債券V75回測引擎）應各自獨立標示，不得再使用 `BLOCKED_UNPROGRAMMABLE_CROSS_ASSET_ALLOCATOR` 作為Case 1阻擋理由。
