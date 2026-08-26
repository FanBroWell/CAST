from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from src.filter.single_ckf import irw_state_space


@dataclass
class JointKF:
    M: int
    order: int
    sigma_v: np.ndarray
    sigma_w: np.ndarray
    rho: np.ndarray

    F_tilde: np.ndarray = field(init=False)
    H_tilde: np.ndarray = field(init=False)
    V: np.ndarray = field(init=False)
    W: np.ndarray = field(init=False)
    X: np.ndarray = field(init=False)
    P: np.ndarray = field(init=False)

    def __post_init__(self) -> None:
        sv = np.asarray(self.sigma_v, dtype=float).reshape(-1)
        sw = np.asarray(self.sigma_w, dtype=float).reshape(-1)
        rho = np.asarray(self.rho, dtype=float)
        if sv.shape != (self.M,) or sw.shape != (self.M,):
            raise ValueError(f"sigma_v / sigma_w must be shape ({self.M},)")
        if rho.shape != (self.M, self.M):
            raise ValueError(f"rho must be shape ({self.M},{self.M})")
        if not np.allclose(rho, rho.T, atol=1e-9):
            raise ValueError("rho must be symmetric")

        self.sigma_v = sv
        self.sigma_w = sw
        self.rho = rho

        F_single, _ = irw_state_space(self.order)
        r = self.order
        F_tilde = np.zeros((self.M * r, self.M * r))
        for i in range(self.M):
            F_tilde[i*r:(i+1)*r, i*r:(i+1)*r] = F_single
        self.F_tilde = F_tilde

        H_tilde = np.zeros((self.M, self.M * r))
        for i in range(self.M):
            H_tilde[i, i*r] = 1.0
        self.H_tilde = H_tilde

        V = np.zeros((self.M * r, self.M * r))
        for i in range(self.M):
            for j in range(self.M):
                V[i*r, j*r] = rho[i, j] * sv[i] * sv[j]
        self.V = V

        self.W = np.diag(sw ** 2)

        self.X = np.zeros(self.M * r)
        self.P = np.eye(self.M * r) * 1e6

    def init_state(self, first_prices: np.ndarray) -> None:
        first = np.asarray(first_prices, dtype=float).reshape(-1)
        if first.shape != (self.M,):
            raise ValueError(f"first_prices must be shape ({self.M},)")
        r = self.order
        X = np.zeros(self.M * r)
        for i in range(self.M):
            X[i*r:(i+1)*r] = first[i]
        self.X = X
        self.P = np.eye(self.M * r) * 1e3

    def predict(self) -> None:
        self.X = self.F_tilde @ self.X
        self.P = self.F_tilde @ self.P @ self.F_tilde.T + self.V

    def update(self, observations: np.ndarray) -> np.ndarray:
        S = np.asarray(observations, dtype=float).reshape(-1)
        innovation = S - self.H_tilde @ self.X
        innov_cov = self.H_tilde @ self.P @ self.H_tilde.T + self.W
        gain = np.linalg.solve(innov_cov, self.H_tilde @ self.P).T
        self.X = self.X + gain @ innovation
        self.P = self.P - gain @ self.H_tilde @ self.P
        self.P = 0.5 * (self.P + self.P.T)
        return innovation

    def predict_l_steps(self, L: int) -> np.ndarray:
        X_l = self.X.copy()
        out = np.empty((self.M, L))
        for l in range(L):
            X_l = self.F_tilde @ X_l
            out[:, l] = self.H_tilde @ X_l
        return out


@dataclass
class CrossAssetCollaborativeKF:
    M: int
    orders: tuple[int, ...]
    sigma_v_per_order: tuple[np.ndarray, ...]
    sigma_w: np.ndarray
    rho: np.ndarray
    horizon: int

    filters: list[JointKF] = field(init=False)
    weights: np.ndarray = field(init=False)
    _trajectory_buffer: list[np.ndarray] = field(default_factory=list, init=False)
    _truth_buffer: list[np.ndarray] = field(default_factory=list, init=False)

    def __post_init__(self) -> None:
        if len(self.orders) != len(self.sigma_v_per_order):
            raise ValueError("orders and sigma_v_per_order must have equal length")
        self.filters = [
            JointKF(
                M=self.M, order=r,
                sigma_v=self.sigma_v_per_order[k],
                sigma_w=self.sigma_w,
                rho=self.rho,
            )
            for k, r in enumerate(self.orders)
        ]
        self.weights = np.full((self.M, len(self.orders)), 1.0 / len(self.orders))

    @property
    def R(self) -> int:
        return len(self.orders)

    def init(self, first_prices: np.ndarray) -> None:
        for jkf in self.filters:
            jkf.init_state(first_prices)

    def step(self, observations: np.ndarray) -> dict:
        for jkf in self.filters:
            jkf.predict()

        one_step = np.stack(
            [self.filters[k].H_tilde @ self.filters[k].X for k in range(self.R)],
            axis=0,
        )

        for jkf in self.filters:
            jkf.update(observations)

        l_step = np.stack(
            [self.filters[k].predict_l_steps(self.horizon) for k in range(self.R)],
            axis=0,
        )
        self._trajectory_buffer.append(l_step)
        self._truth_buffer.append(np.asarray(observations, dtype=float).reshape(-1))

        if len(self._trajectory_buffer) > self.horizon:
            old = self._trajectory_buffer[-(self.horizon + 1)]
            recent_truth = np.stack(self._truth_buffer[-self.horizon:], axis=0)
            truth_ml = recent_truth.T
            err_sq = (old - truth_ml[None, :, :]) ** 2
            score = err_sq.sum(axis=2) + 1e-12
            log_eta = -0.5 * self.horizon * np.log(score)
            log_eta -= log_eta.max(axis=0, keepdims=True)
            eta = np.exp(log_eta)
            self.weights = (eta / eta.sum(axis=0, keepdims=True)).T

            self._trajectory_buffer.pop(0)

        return {
            "one_step_per_order": one_step,
            "weights":            self.weights.copy(),
        }

    def aggregate_l_step(self) -> np.ndarray:
        per_order = np.stack(
            [jkf.predict_l_steps(self.horizon) for jkf in self.filters],
            axis=0,
        )
        return np.einsum("mr,rml->ml", self.weights, per_order)

    def aggregate_one_step(self) -> np.ndarray:
        return self.aggregate_l_step()[:, 0]


def estimate_rho_raw(raw_panel, cal_end_idx=None):
    panel = np.asarray(raw_panel, dtype=float)
    cal = panel[:cal_end_idx] if cal_end_idx is not None else panel
    diffs = np.diff(cal, axis=0)
    rho = np.corrcoef(diffs, rowvar=False)
    rho = 0.5 * (rho + rho.T)
    rho = np.nan_to_num(rho, nan=0.0)
    np.fill_diagonal(rho, 1.0)
    return rho
