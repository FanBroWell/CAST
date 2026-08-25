# Appendix A — Account Design & Capital Fairness

Decisions are made on one day's close and executed at the **next** day's close. 

## A.1 Thirty independent accounts, not one portfolio

Each of the `M = 30` assets in a panel is traded in its **own account**, funded
with `V_0 = $1000`, and the accounts never interact.


1. **No capital is ever transferred between assets.** An account that doubles
   does not fund an account that halves. The controller for asset `i` sees only
   `V_k^(i)`.
2. **There is no rebalancing.** Because each account is independent and never
   topped up, the method cannot earn the implicit mean-reversion premium that a
   periodically rebalanced equal-weight portfolio collects. 
3. **No FX assumption is required.** Global30 spans currencies, but since no cross-currency transfer ever occurs, the mean of 30 normalised account curves is well defined without an exchange-rate model.



## A.3 The constraint stack

Three constraints bind a position, at three levels:

| Constraint | Level | Formula | Where |
| --- | --- | --- | --- |
| Per-trade cap | transaction | `\|u_{k+l}\| · Ŝ_{k+l} ≤ β · V_k`, `β = 0.5` | inside the LP |
| No-leverage clip | position | `\|(N_k + u) · S_k\| ≤ V_k` | `_apply_no_leverage_clip` |
| Margin floor | account | liquidate and stop trading if `V_k < 0.2 · V_0` | accounting loop |


## A.4 What makes the comparison fair

Both arms run under an identical capital allocation and an identical constraint
stack — by construction, not by convention:

| | Shared? | How |
| --- | --- | --- |
| Starting capital | ✓ | `V_0 = $1000` × 30 accounts |
| Universe and trading days | ✓ | same panel, same `test_start_idx` |
| Execution timing | ✓ | same accounting loop (Appendix A) |
| Per-trade cap, clip, margin floor | ✓ | same code path, same constants |
| `σ_v`, `σ_w` | ✓ | calibrated once, then handed to both arms |
| `σ_l` multiplier | ✓ | same MPC class |
| `λ` grid and selection protocol | ✓ | same protocol on both arms |
| The filter | ✗ **by design** | this is the treatment |
