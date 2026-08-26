from __future__ import annotations

from dataclasses import dataclass, field
from math import comb

import numpy as np


def irw_state_space(order: int) -> tuple[np.ndarray, np.ndarray]:
    if order < 1:
        raise ValueError(f"order must be >= 1, got {order}")

    f = np.array([(-1) ** i * comb(order, i) for i in range(1, order + 1)], dtype=float)
    coeffs_first_row = -f

    F = np.zeros((order, order))
    F[0, :] = coeffs_first_row
    if order > 1:
        F[1:, :-1] = np.eye(order - 1)
    H = np.zeros((1, order))
    H[0, 0] = 1.0
    return F, H


@dataclass
class KalmanIRW:
    order: int
    sigma_v: float
    sigma_w: float
    x: np.ndarray = field(init=False)
    P: np.ndarray = field(init=False)
    F: np.ndarray = field(init=False)
    H: np.ndarray = field(init=False)
    V: np.ndarray = field(init=False)

    def __post_init__(self) -> None:
        self.F, self.H = irw_state_space(self.order)
        self.V = np.zeros((self.order, self.order))
        self.V[0, 0] = self.sigma_v ** 2
        self.x = np.zeros(self.order)
        self.P = np.eye(self.order) * 1e6

    def init_state(self, first_price: float) -> None:
        self.x = np.full(self.order, first_price, dtype=float)
        self.P = np.eye(self.order) * 1e3

    def predict(self) -> None:
        self.x = self.F @ self.x
        self.P = self.F @ self.P @ self.F.T + self.V

    def update(self, observation: float) -> float:
        innovation = observation - float((self.H @ self.x).item())
        innov_var = float((self.H @ self.P @ self.H.T).item()) + self.sigma_w ** 2
        gain = (self.P @ self.H.T).flatten() / innov_var
        self.x = self.x + gain * innovation
        self.P = self.P - innov_var * np.outer(gain, gain)
        return innovation

    def predict_l_steps(self, L: int) -> np.ndarray:
        x_l = self.x.copy()
        out = np.empty(L)
        for l in range(L):
            x_l = self.F @ x_l
            out[l] = float((self.H @ x_l).item())
        return out

    def l_step_pred_std(self, L: int) -> np.ndarray:
        Fi = np.eye(self.order)
        out = np.empty(L)
        accumulated = 0.0
        for l in range(1, L + 1):
            accumulated += Fi[0, 0] ** 2
            Fi = self.F @ Fi
            var = self.sigma_w ** 2 + (self.sigma_v ** 2) * accumulated
            out[l - 1] = float(np.sqrt(max(var, 0.0)))
        return out


@dataclass
class CollaborativeKF:
    orders: tuple[int, ...]
    sigma_v_list: tuple[float, ...]
    sigma_w: float
    horizon: int
    filters: list[KalmanIRW] = field(init=False)
    weights: np.ndarray = field(init=False)
    _trajectory_buffer: list[np.ndarray] = field(default_factory=list, init=False)
    _truth_buffer: list[float] = field(default_factory=list, init=False)

    def __post_init__(self) -> None:
        if len(self.orders) != len(self.sigma_v_list):
            raise ValueError("orders and sigma_v_list must have equal length")
        self.filters = [
            KalmanIRW(order=r, sigma_v=sv, sigma_w=self.sigma_w)
            for r, sv in zip(self.orders, self.sigma_v_list)
        ]
        self.weights = np.full(len(self.filters), 1.0 / len(self.filters))

    @property
    def n_models(self) -> int:
        return len(self.filters)

    def init(self, first_price: float) -> None:
        for kf in self.filters:
            kf.init_state(first_price)

    def step(self, observation: float) -> dict:
        for kf in self.filters:
            kf.predict()

        one_step = np.array([float((kf.H @ kf.x).item()) for kf in self.filters])

        innovations = np.array([kf.update(observation) for kf in self.filters])

        l_step = np.stack([kf.predict_l_steps(self.horizon) for kf in self.filters], axis=0)
        self._trajectory_buffer.append(l_step)
        self._truth_buffer.append(observation)

        if len(self._trajectory_buffer) > self.horizon:
            old_traj = self._trajectory_buffer[-(self.horizon + 1)]
            recent_truth = np.array(self._truth_buffer[-self.horizon:])
            err_sq = (recent_truth[None, :] - old_traj) ** 2
            score = err_sq.sum(axis=1) + 1e-12
            log_eta = -0.5 * self.horizon * np.log(score)
            log_eta -= log_eta.max()
            eta = np.exp(log_eta)
            self.weights = eta / eta.sum()

            self._trajectory_buffer.pop(0)

        return {
            "one_step_per_model": one_step,
            "innovations":        innovations,
            "weights":            self.weights.copy(),
        }

    def aggregate_l_step(self) -> np.ndarray:
        per_model = np.stack(
            [kf.predict_l_steps(self.horizon) for kf in self.filters],
            axis=0,
        )
        return self.weights @ per_model

    def aggregate_l_step_std(self) -> np.ndarray:
        per_model_std = np.stack(
            [kf.l_step_pred_std(self.horizon) for kf in self.filters],
            axis=0,
        )
        return np.sqrt(self.weights @ (per_model_std ** 2))


def calibrate_sigma_raw(prices, order: int = 1):
    prices = np.asarray(prices, dtype=float)
    diffs = np.diff(prices)
    base = float(np.std(diffs))

    grid_v = base * np.array([0.25, 0.5, 1.0, 2.0])
    grid_w = base * np.array([0.05, 0.1, 0.25, 0.5])

    best = (base, base * 0.1, np.inf)
    for sv in grid_v:
        for sw in grid_w:
            kf = KalmanIRW(order=order, sigma_v=float(sv), sigma_w=float(sw))
            kf.init_state(float(prices[0]))
            sse = 0.0
            for k in range(1, len(prices)):
                kf.predict()
                pred = float((kf.H @ kf.x).item())
                kf.update(float(prices[k]))
                sse += (prices[k] - pred) ** 2
            rmse = (sse / max(len(prices) - 1, 1)) ** 0.5
            if rmse < best[2]:
                best = (float(sv), float(sw), float(rmse))
    return best[0], best[1]
