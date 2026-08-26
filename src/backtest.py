from __future__ import annotations

from typing import Callable

import numpy as np

from src.metrics import (
    annualized_return,
    annualized_sharpe,
    calmar_ratio,
    max_drawdown,
    sortino_ratio,
    win_rate,
)
from src.filter.single_ckf import irw_state_space
from src.mpc import PaperMPC, compute_paper_sigma_l
from src.filter.single_ckf import CollaborativeKF
from src.filter.cokf import CrossAssetCollaborativeKF


def _apply_no_leverage_clip(u_committed, cur_N, price, V_k):
    hi = V_k / price - cur_N
    lo = -V_k / price - cur_N
    return np.clip(u_committed, lo, hi)


def _solve_one_step(
    predictor,
    mpc: PaperMPC,
    u_current: float,
    capital: float,
) -> float:
    L = mpc.horizon
    if isinstance(predictor, CollaborativeKF):
        price_pred = predictor.aggregate_l_step()
        F_matrices = [kf.F for kf in predictor.filters]
        sigma_l = compute_paper_sigma_l(predictor.weights, F_matrices, L)
    else:
        price_pred = predictor.predict_l_steps(L)
        sigma_l = compute_paper_sigma_l(np.array([1.0]), [predictor.F], L)

    plan = mpc.solve(u_current, price_pred, sigma_l, capital)
    return float(plan[0]) if len(plan) > 0 else 0.0


def backtest_single_asset_raw(
    predictor,
    mpc: PaperMPC,
    raw_prices: np.ndarray,
    test_start_idx: int,
    V_0: float = 1000.0,
    margin_floor_frac: float = 0.2,
) -> dict:
    T = len(raw_prices)
    V = np.full(T, V_0)
    one_step_preds = np.full(T, np.nan)

    cur_N = 0.0
    cur_cash = V_0
    busted = False
    margin_floor = margin_floor_frac * V_0
    u_committed = 0.0
    u_last_applied = 0.0

    if isinstance(predictor, CollaborativeKF):
        predictor.init(float(raw_prices[0]))
    else:
        predictor.init_state(float(raw_prices[0]))

    for k in range(1, T):
        cur_N += u_committed
        cur_cash -= u_committed * raw_prices[k]
        u_last_applied = u_committed

        V_k = cur_N * raw_prices[k] + cur_cash
        if not busted and V_k < margin_floor:
            cur_cash += cur_N * raw_prices[k]
            cur_N = 0.0
            V_k = cur_cash
            busted = True
        V[k] = V_k

        if isinstance(predictor, CollaborativeKF):
            out = predictor.step(float(raw_prices[k]))
            one_step_preds[k] = float(out["weights"] @ out["one_step_per_model"])
        else:
            predictor.predict()
            one_step_preds[k] = float((predictor.H @ predictor.x).item())
            predictor.update(float(raw_prices[k]))

        if not busted and k < T - 1 and k >= test_start_idx:
            u_committed = _solve_one_step(
                predictor, mpc, u_last_applied, capital=max(V_k, 1e-3),
            )
            u_committed = float(_apply_no_leverage_clip(
                u_committed, cur_N, raw_prices[k], V_k,
            ))
        else:
            u_committed = 0.0

    return {"V": V, "one_step_preds": one_step_preds}


def backtest_panel_raw(
    predictor_factory: Callable[[int], object],
    mpc_factory: Callable[[], PaperMPC],
    raw_panel: np.ndarray,
    test_start_idx: int,
    V_0_per_asset: float = 1000.0,
) -> dict:
    T, M = raw_panel.shape
    V_per_asset = np.full((T, M), V_0_per_asset)
    one_step_per_asset = np.full((T, M), np.nan)
    for i in range(M):
        pred = predictor_factory(i)
        mpc = mpc_factory()
        res = backtest_single_asset_raw(
            pred, mpc, raw_panel[:, i], test_start_idx, V_0_per_asset,
        )
        V_per_asset[:, i] = res["V"]
        one_step_per_asset[:, i] = res["one_step_preds"]
    return {
        "V_per_asset":        V_per_asset,
        "V_portfolio":        V_per_asset.mean(axis=1),
        "one_step_per_asset": one_step_per_asset,
    }


def backtest_cokf_raw(
    cokf: CrossAssetCollaborativeKF,
    mpc_factory: Callable[[], PaperMPC],
    raw_panel: np.ndarray,
    test_start_idx: int,
    V_0_per_asset: float = 1000.0,
    margin_floor_frac: float = 0.2,
) -> dict:
    T, M = raw_panel.shape
    L = cokf.horizon
    V_per_asset = np.full((T, M), V_0_per_asset)
    one_step_per_asset = np.full((T, M), np.nan)

    cur_N = np.zeros(M)
    cur_cash = np.full(M, V_0_per_asset)
    u_committed = np.zeros(M)
    u_last_applied = np.zeros(M)
    busted = np.zeros(M, dtype=bool)
    margin_floor = margin_floor_frac * V_0_per_asset

    F_per_order = [irw_state_space(r)[0] for r in cokf.orders]

    mpcs = [mpc_factory() for _ in range(M)]
    cokf.init(raw_panel[0])

    for k in range(1, T):
        cur_N += u_committed
        cur_cash -= u_committed * raw_panel[k]
        u_last_applied = u_committed.copy()

        V_k = cur_N * raw_panel[k] + cur_cash
        for i in range(M):
            if not busted[i] and V_k[i] < margin_floor:
                cur_cash[i] += cur_N[i] * raw_panel[k, i]
                cur_N[i] = 0.0
                V_k[i] = cur_cash[i]
                busted[i] = True
        V_per_asset[k] = V_k

        out = cokf.step(raw_panel[k])
        one_step_per_asset[k] = np.einsum(
            "mr,rm->m", out["weights"], out["one_step_per_order"],
        )

        if k < T - 1 and k >= test_start_idx:
            l_step = cokf.aggregate_l_step()
            new_committed = np.zeros(M)
            for i in range(M):
                if busted[i]:
                    continue
                sigma_l_i = compute_paper_sigma_l(
                    out["weights"][i], F_per_order, L,
                )
                plan = mpcs[i].solve(
                    u_current=float(u_last_applied[i]),
                    price_pred=l_step[i],
                    sigma_l_paper=sigma_l_i,
                    capital=max(float(V_k[i]), 1e-3),
                )
                new_committed[i] = float(plan[0]) if len(plan) > 0 else 0.0
            u_committed = _apply_no_leverage_clip(
                new_committed, cur_N, raw_panel[k], V_k,
            )
        else:
            u_committed = np.zeros(M)

    return {
        "V_per_asset":        V_per_asset,
        "V_portfolio":        V_per_asset.mean(axis=1),
        "one_step_per_asset": one_step_per_asset,
    }


def metric_row(V_test: np.ndarray) -> dict:
    V_test = np.asarray(V_test, dtype=float)
    ratio_keys = [
        "sharpe", "sortino", "max_dd", "calmar",
        "ann_return", "win_rate",
    ]
    busted = bool((V_test <= 0).any())
    final_value = float(V_test[-1]) if len(V_test) else float("nan")

    if busted or len(V_test) < 2:
        out = {k: float("nan") for k in ratio_keys}
        out["final_value"] = final_value
        out["busted"] = busted
        return out

    return {
        "sharpe":      annualized_sharpe(V_test),
        "sortino":     sortino_ratio(V_test),
        "max_dd":      max_drawdown(V_test),
        "calmar":      calmar_ratio(V_test),
        "ann_return":  annualized_return(V_test),
        "win_rate":    win_rate(V_test),
        "final_value": final_value,
        "busted":      False,
    }


