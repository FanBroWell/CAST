from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.optimize import linprog


def compute_paper_sigma_l(
    weights: np.ndarray,
    F_matrices: list[np.ndarray],
    L: int,
) -> np.ndarray:
    R = len(weights)
    max_dim = max(F.shape[0] for F in F_matrices)
    F_padded = []
    for F in F_matrices:
        d = F.shape[0]
        Fp = np.zeros((max_dim, max_dim))
        Fp[:d, :d] = F
        F_padded.append(Fp)
    F_bar = sum(weights[i] * F_padded[i] for i in range(R))

    Fj = np.eye(max_dim)
    accumulated = 0.0
    out = np.empty(L)
    for l in range(1, L + 1):
        accumulated += float(Fj[0, 0]) ** 2
        Fj = F_bar @ Fj
        out[l - 1] = float(np.sqrt(max(accumulated, 0.0)))
    return out


@dataclass
class PaperMPC:
    horizon: int
    lam: float = 0.1
    b: float = 0.5

    def solve(
        self,
        u_current: float,
        price_pred: np.ndarray,
        sigma_l_paper: np.ndarray,
        capital: float,
    ) -> np.ndarray:
        L = self.horizon
        if len(price_pred) < L or len(sigma_l_paper) < L:
            raise ValueError(f"need length-{L} arrays")
        n = L - 1
        d_pred = np.diff(price_pred[:L])
        c = np.concatenate([-d_pred, self.lam * sigma_l_paper[:n]])
        A_eq = np.concatenate([np.ones(n), np.zeros(n)]).reshape(1, -1)
        b_eq = np.array([-u_current])
        I = np.eye(n)
        A_ub = np.block([[I, -I], [-I, -I]])
        b_ub = np.zeros(2 * n)
        cap_per_l = self.b * capital / np.maximum(price_pred[:n], 1e-9)
        u_bounds = [(-c_l, c_l) for c_l in cap_per_l]
        z_bounds = [(0.0, c_l) for c_l in cap_per_l]
        bounds = u_bounds + z_bounds
        res = linprog(c=c, A_ub=A_ub, b_ub=b_ub, A_eq=A_eq, b_eq=b_eq,
                      bounds=bounds, method="highs")
        if not res.success:
            return np.zeros(n)
        return res.x[:n]
