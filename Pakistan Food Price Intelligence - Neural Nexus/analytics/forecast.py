"""Price forecasting in pure Python (no numpy/pandas).

Method: monthly average price -> log scale -> candidate models:
  * damped-trend Holt exponential smoothing
  * the same with a monthly seasonal adjustment
  * naive (last value carried forward)
The best candidate is chosen by a rolling-origin backtest (6-month-ahead errors over the last ~2 years).
80% intervals come from the model's one-step errors, widened with the square root of the horizon.
"""
import math
from functools import lru_cache

from . import data

Z80 = 1.2816
H_BT = 6  # backtest horizon (months)
GRID = [(a, b, p) for a in (0.2, 0.4, 0.6, 0.8) for b in (0.05, 0.15, 0.3) for p in (0.8, 0.9, 0.98)]
LABELS = {"holt": "Damped-trend Holt (log scale)", "seasonal": "Damped-trend Holt + monthly seasonality (log scale)",
          "naive": "Naive (last value)"}


def _label(i):
    return f"{i // 12}-{i % 12 + 1:02d}"


def monthly_series(commodity, market=None, metric="price"):
    """Return (start_index, values, n_observed). start_index = year*12 + month-1. Gaps are interpolated."""
    b = {}
    for r in data.rows():
        if r["commodity"] == commodity and (not market or r["market"] == market):
            b.setdefault(int(r["date"][:4]) * 12 + int(r["date"][5:7]) - 1, []).append(r[metric])
    if not b:
        return None
    obs = {k: data.avg(v) for k, v in b.items()}
    s, e = min(obs), max(obs)
    out = []
    for i in range(s, e + 1):
        if i in obs:
            out.append(obs[i])
        else:
            lo = max(j for j in obs if j < i)
            hi = min(j for j in obs if j > i)
            out.append(obs[lo] + (obs[hi] - obs[lo]) * (i - lo) / (hi - lo))
    return s, out, len(obs)


def _holt_fit(y, a, b, phi):
    l, t, errs = y[0], y[1] - y[0], []
    for v in y[1:]:
        f = l + phi * t
        errs.append(v - f)
        l_new = f + a * (v - f)
        t = b * (l_new - l) + (1 - b) * phi * t
        l = l_new
    return l, t, errs


def _holt_best(y):
    best = None
    for a, b, p in GRID:
        l, t, errs = _holt_fit(y, a, b, p)
        sse = sum(e * e for e in errs[-60:])
        if best is None or sse < best[0]:
            best = (sse, a, b, p, l, t, errs)
    return best


def _season(ly, start):
    n = len(ly)
    if n < 36:
        return None
    s = {m: [] for m in range(12)}
    for i in range(6, n - 6):
        ma = (0.5 * ly[i - 6] + sum(ly[i - 5:i + 6]) + 0.5 * ly[i + 6]) / 12
        s[(start + i) % 12].append(ly[i] - ma)
    if any(len(v) < 2 for v in s.values()):
        return None
    idx = [data.avg(s[m]) for m in range(12)]
    mu = data.avg(idx)
    return [x - mu for x in idx]


def _model_forecast(ly, start, h, method):
    """Return (log_points, sigma, params) or None when the method cannot be fitted."""
    n = len(ly)
    if method == "naive":
        d = [ly[i] - ly[i - 1] for i in range(max(1, n - 60), n)]
        return [ly[-1]] * h, math.sqrt(sum(x * x for x in d) / len(d)), {}
    s = _season(ly, start) if method == "seasonal" else None
    if method == "seasonal" and s is None:
        return None
    z = [ly[i] - (s[(start + i) % 12] if s else 0) for i in range(n)]
    _, a, b, p, l, t, errs = _holt_best(z)
    pts, cum = [], 0.0
    for i in range(1, h + 1):
        cum += p ** i
        pts.append(l + cum * t + (s[(start + n + i - 1) % 12] if s else 0))
    recent = errs[-60:]
    return pts, math.sqrt(sum(e * e for e in recent) / len(recent)), {"alpha": a, "beta": b, "phi": p}


@lru_cache(maxsize=128)
def _analyse(commodity, market, metric):
    start, vals, nobs = monthly_series(commodity, market, metric)
    ly = [math.log(v) for v in vals]
    n = len(ly)
    errs = {m: [] for m in LABELS}
    origins = [o for o in (n - H_BT - 3 * k for k in range(8)) if o >= 30]
    for o in origins:
        for m in LABELS:
            r = _model_forecast(ly[:o], start, H_BT, m)
            if r:
                errs[m] += [abs(math.exp(p - a) - 1) for p, a in zip(r[0], ly[o:o + H_BT])]
    mape = {m: round(data.avg(v) * 100, 1) for m, v in errs.items() if v}
    method = min(mape, key=mape.get) if mape else "holt"
    return start, vals, nobs, mape, method, len(origins)


def forecast(commodity, horizon=6, market=None, metric="price", history_months=48):
    names = data._match(commodity) if commodity else []
    if len(names) != 1:
        return {"error": "Specify exactly one commodity.", "choices": names or data.commodity_names()}
    c = names[0]
    mk = next((m for m in data.markets() if market and m.lower() == str(market).lower()), None)
    metric = metric if metric in ("price", "usd") else "price"
    ser = monthly_series(c, mk, metric)
    if not ser or len(ser[1]) < 30:
        return {"error": f"Not enough monthly history for {c}" + (f" in {mk}" if mk else "") + " (need 30+ months)."}
    horizon = max(1, min(int(horizon or 6), 24))
    start, vals, nobs, mape, method, norig = _analyse(c, mk, metric)
    ly = [math.log(v) for v in vals]
    pts, sig, params = _model_forecast(ly, start, horizon, method)
    end = start + len(vals) - 1
    fc = []
    for i, p in enumerate(pts, 1):
        w = Z80 * sig * math.sqrt(i)
        fc.append({"month": _label(end + i), "point": round(math.exp(p), 2),
                   "low80": round(math.exp(p - w), 2), "high80": round(math.exp(p + w), 2)})
    last_all = max(r["date"][:7] for r in data.rows())
    warns = [f"Forecast starts after the last observation in the data ({_label(end)}); it is a statistical extrapolation, "
             "not a guarantee. Shocks such as floods, policy changes or currency crises are not predicted."]
    if _label(end) < last_all:
        warns.append(f"This series ends in {_label(end)} (earlier than the rest of the dataset), so the forecast is stale.")
    if mape.get(method, 0) > 15:
        warns.append(f"Backtest error is high ({mape[method]}% over {H_BT} months): treat this as a rough guide.")
    if mk:
        warns.append(f"Based on {mk} only; interpolated months: {len(vals) - nobs}.")
    return {
        "commodity": c, "unit": next(r["unit"] for r in data.rows() if r["commodity"] == c),
        "scope": mk or "National average of available cities", "metric": "PKR (nominal)" if metric == "price" else "USD",
        "method": LABELS[method], "model_params": params, "last_observed": _label(end), "last_value": round(vals[-1], 2),
        "history": [{"month": _label(start + i), "value": round(v, 2)} for i, v in enumerate(vals)][-history_months:],
        "forecast": fc, "change_pct_at_end": round((fc[-1]["point"] / vals[-1] - 1) * 100, 1),
        "backtest": {"horizon_months": H_BT, "origins": norig, "mape_pct_by_method": {LABELS[k]: v for k, v in mape.items()},
                     "chosen_mape_pct": mape.get(method), "naive_mape_pct": mape.get("naive")},
        "warnings": warns,
    }


@lru_cache(maxsize=16)
def outlook(horizon=6, metric="price"):
    """Compact forecast for every commodity (used by the dashboard table and the AI)."""
    rows = []
    for c in data.commodity_names():
        f = forecast(c, horizon, None, metric, history_months=0)
        if "error" in f:
            continue
        e = f["forecast"][-1]
        rows.append({"commodity": c, "unit": f["unit"], "last_observed": f["last_observed"], "last_value": f["last_value"],
                     "forecast_month": e["month"], "forecast": e["point"], "low80": e["low80"], "high80": e["high80"],
                     "change_pct": f["change_pct_at_end"], "method": f["method"], "backtest_mape_pct": f["backtest"]["chosen_mape_pct"],
                     "stale": any("stale" in w for w in f["warnings"])})
    return sorted(rows, key=lambda r: -r["change_pct"])
