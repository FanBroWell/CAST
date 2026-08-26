from __future__ import annotations

import numpy as np

TRADING_DAYS_PER_YEAR = 252


def annualized_sharpe(portfolio_value: np.ndarray, risk_free_rate: float = 0.0) -> float:
    v = np.asarray(portfolio_value, dtype=float)
    v = v[np.isfinite(v)]
    if len(v) < 2:
        return float("nan")
    daily_return = np.diff(v) / v[:-1]
    daily_rf = risk_free_rate / TRADING_DAYS_PER_YEAR
    excess = daily_return - daily_rf
    sigma = excess.std(ddof=1)
    if sigma == 0.0:
        return float("nan")
    return float(np.sqrt(TRADING_DAYS_PER_YEAR) * excess.mean() / sigma)


def annualized_return(portfolio_value: np.ndarray) -> float:
    v = np.asarray(portfolio_value, dtype=float)
    v = v[np.isfinite(v)]
    if len(v) < 2 or v[0] <= 0.0:
        return float("nan")
    n_years = (len(v) - 1) / TRADING_DAYS_PER_YEAR
    return float((v[-1] / v[0]) ** (1.0 / n_years) - 1.0)


def max_drawdown(portfolio_value: np.ndarray) -> float:
    v = np.asarray(portfolio_value, dtype=float)
    v = v[np.isfinite(v)]
    if len(v) < 2:
        return float("nan")
    running_max = np.maximum.accumulate(v)
    drawdown = (running_max - v) / running_max
    return float(drawdown.max())


def sortino_ratio(portfolio_value: np.ndarray, risk_free_rate: float = 0.0) -> float:
    v = np.asarray(portfolio_value, dtype=float)
    v = v[np.isfinite(v) & (v > 0)]
    if len(v) < 2:
        return float("nan")
    daily_return = np.diff(v) / v[:-1]
    daily_rf = risk_free_rate / TRADING_DAYS_PER_YEAR
    excess = daily_return - daily_rf
    downside = excess[excess < 0]
    if len(downside) == 0:
        return float("inf")
    downside_std = float(np.sqrt(np.mean(downside ** 2)))
    if downside_std == 0.0:
        return float("nan")
    return float(np.sqrt(TRADING_DAYS_PER_YEAR) * excess.mean() / downside_std)


def calmar_ratio(portfolio_value: np.ndarray) -> float:
    ar = annualized_return(portfolio_value)
    dd = max_drawdown(portfolio_value)
    if not np.isfinite(ar) or not np.isfinite(dd) or dd == 0:
        return float("nan")
    return float(ar / dd)


def win_rate(portfolio_value: np.ndarray) -> float:
    v = np.asarray(portfolio_value, dtype=float)
    v = v[np.isfinite(v) & (v > 0)]
    if len(v) < 2:
        return float("nan")
    daily_return = np.diff(v) / v[:-1]
    return float((daily_return > 0).mean())
