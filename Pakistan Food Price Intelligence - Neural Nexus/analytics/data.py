"""Loads the WFP CSV and provides aggregations (used by the dashboard AND the AI tools)."""
import csv
import math
from functools import lru_cache
from pathlib import Path

CSV_PATH = Path(__file__).resolve().parent.parent / "data" / "wfp_food_prices_pak.csv"


@lru_cache(maxsize=1)
def rows():
    out = []
    with open(CSV_PATH, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r["date"].startswith("#"):  # HDX files have a #hashtag row under the header
                continue
            out.append({
                "date": r["date"], "y": int(r["date"][:4]), "market": r["market"], "province": r["admin1"],
                "category": r["category"], "commodity": r["commodity"], "unit": r["unit"],
                "price": float(r["price"]), "usd": float(r["usdprice"]),
            })
    return out


def avg(v):
    return sum(v) / len(v)


def std(v):
    m = avg(v)
    return math.sqrt(avg([(x - m) ** 2 for x in v]))


def rnd(x, d=2):
    return round(x, d)


def markets():
    return sorted({r["market"] for r in rows()})


def commodity_names():
    return sorted({r["commodity"] for r in rows()})


def _match(name):
    n = name.lower()
    exact = [c for c in commodity_names() if c.lower() == n]
    return exact or [c for c in commodity_names() if n in c.lower()]


def query(commodity=None, market=None, start=None, end=None, group_by="year", metric="price", limit=60):
    """Aggregate prices. start/end accept YYYY or YYYY-MM."""
    metric = metric if metric in ("price", "usd") else "price"
    names = _match(commodity) if commodity else None
    if end:
        end = end + "-12-31" if len(end) == 4 else end + "-31" if len(end) == 7 else end
    sel = [r for r in rows()
           if (names is None or r["commodity"] in names)
           and (not market or r["market"].lower() == market.lower())
           and (not start or r["date"] >= start) and (not end or r["date"] <= end)]
    if not sel:
        return {"matched_rows": 0, "note": "No rows matched. Check spelling.",
                "commodities": commodity_names(), "markets": markets()}
    keyf = {"year": lambda r: str(r["y"]), "month": lambda r: r["date"][:7], "none": lambda r: "all"}.get(
        group_by, lambda r: r.get(group_by, "all"))
    groups = {}
    for r in sel:
        groups.setdefault(keyf(r), []).append(r[metric])
    out = [{"key": k, "avg": rnd(avg(v)), "min": min(v), "max": max(v), "n": len(v)} for k, v in groups.items()]
    out.sort(key=(lambda g: g["key"]) if group_by in ("year", "month") else (lambda g: -g["avg"]))
    units = sorted({r["unit"] for r in sel})
    res = {"matched_rows": len(sel), "metric": "PKR (nominal)" if metric == "price" else "USD",
           "units": units, "groups": out[: min(int(limit or 60), 200)]}
    if len(units) > 1:
        res["note"] = "Mixed units - do not compare averages across commodities directly."
    return res


def _yearly(c, metric):
    m = {}
    for r in rows():
        if r["commodity"] == c:
            m.setdefault(r["y"], []).append(r[metric])
    return [(y, avg(v)) for y, v in sorted(m.items())]


def commodity_stats():
    stats = []
    for c in commodity_names():
        rs = [r for r in rows() if r["commodity"] == c]
        ys, yu = _yearly(c, "price"), _yearly(c, "usd")
        (fy, fa), (ly, la) = ys[0], ys[-1]
        prev = dict(ys).get(ly - 1)
        monthly = {}
        for r in rs:
            monthly.setdefault(r["date"][:7], []).append(r["price"])
        mk = sorted((k, avg(v)) for k, v in monthly.items())
        ch = []
        for (k1, v1), (k2, v2) in zip(mk, mk[1:]):
            (a, b), (c2, d) = map(int, k1.split("-")), map(int, k2.split("-"))
            if (c2 - a) * 12 + (d - b) == 1:
                ch.append((v2 / v1 - 1) * 100)
        by_mkt = sorted(
            ((m, avg([r["price"] for r in rs if r["market"] == m and r["y"] == ly]))
             for m in markets() if any(r["market"] == m and r["y"] == ly for r in rs)), key=lambda x: x[1])
        span = ly - fy
        stats.append({
            "commodity": c, "category": rs[0]["category"], "unit": rs[0]["unit"], "records": len(rs),
            "first_year": fy, "last_year": ly, "first_avg_pkr": rnd(fa), "last_avg_pkr": rnd(la),
            "multiple": rnd(la / fa), "cagr_pct": rnd(((la / fa) ** (1 / span) - 1) * 100, 1) if span else 0,
            "yoy_last_pct": rnd((la / prev - 1) * 100, 1) if prev else None,
            "usd_multiple": rnd(yu[-1][1] / yu[0][1]),
            "monthly_volatility_pct": rnd(std(ch), 1) if ch else None,
            "cheapest_market_last_year": {"market": by_mkt[0][0], "avg": rnd(by_mkt[0][1])} if by_mkt else None,
            "priciest_market_last_year": {"market": by_mkt[-1][0], "avg": rnd(by_mkt[-1][1])} if by_mkt else None,
        })
    return stats


def overview():
    dates = [r["date"] for r in rows()]
    return {
        "records": len(rows()), "date_range": [min(dates), max(dates)], "markets": markets(),
        "commodities": len(commodity_names()), "currency": "PKR (nominal, not inflation-adjusted)",
        "coverage_notes": [
            "Only 5 city markets (Karachi, Lahore, Multan, Peshawar, Quetta), retail prices only.",
            "Most commodities start 2013-2015; wheat flour & basmati rice start 2004. Salt only 2014-2018.",
            "'Wage' is daily non-agricultural labour wage, not a food price.",
        ],
        "commodity_stats": commodity_stats(),
    }


@lru_cache(maxsize=1)
def dashboard_data():
    mk, rs_all = markets(), rows()
    yearly, latest = {}, {}
    for c in commodity_names():
        rs = [r for r in rs_all if r["commodity"] == c]
        years = sorted({r["y"] for r in rs})
        yearly[c] = {}
        for metric in ("price", "usd"):
            series = []
            for y in years:
                o = {"year": y, "National": rnd(avg([r[metric] for r in rs if r["y"] == y]))}
                for m in mk:
                    v = [r[metric] for r in rs if r["y"] == y and r["market"] == m]
                    if v:
                        o[m] = rnd(avg(v))
                series.append(o)
            yearly[c][metric] = series
        ly = years[-1]
        items = []
        for m in mk:
            v = [r for r in rs if r["y"] == ly and r["market"] == m]
            if v:
                items.append({"market": m, "price": rnd(avg([r["price"] for r in v])),
                              "usd": rnd(avg([r["usd"] for r in v]))})
        latest[c] = {"year": ly, "unit": rs[0]["unit"], "items": items}
    o = overview()
    return {"records": o["records"], "from": o["date_range"][0], "to": o["date_range"][1], "markets": mk,
            "commodities": commodity_names(), "stats": o["commodity_stats"], "yearly": yearly, "latest": latest}
