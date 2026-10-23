"""Gemini analyst: calls the Gemini REST API with function calling so the model queries the dataset itself."""
import os

import requests

from . import data, forecast

API_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
DEFAULT_MODEL = "gemini-3.5-flash"  # override with GEMINI_MODEL env var

SYSTEM = """You are a food-price data analyst for Pakistan. You analyse the WFP (World Food Programme) retail price dataset (2004-2023, 5 city markets, nominal PKR plus USD equivalents).

Rules:
- Never guess numbers. Call get_overview and/or query_prices first, then answer only from the returned data.
- Prices are NOMINAL (not inflation-adjusted). When discussing growth, mention that PKR depreciation drives much of it and compare PKR vs USD when relevant.
- Mention units (KG, L, Dozen, Day) and the period. Never compare averages across commodities with different units.
- Be honest about limits: only 5 cities, retail only, uneven start dates, Salt ends 2018. Offer causes (currency, fuel, floods, subsidies, global prices) only as hypotheses, not facts.
- For ANY question about future/upcoming prices, call forecast_prices (one item) or forecast_outlook (all items) and report: point forecast, the 80% range, % change vs last observed value, the backtest error and which model was chosen. Never invent forecasts yourself.
- Always state that forecasts are statistical extrapolations that start after the last month in the data (give that month), cannot predict shocks (floods, policy, currency moves), and are not financial advice. If the backtest barely beats the naive method, say that skill is modest.
- Format: concise markdown with short headings/bullets, concrete numbers and a clear takeaway. For report requests use: Summary, Key Findings, Regional Differences, Risks/Watch-outs, Recommendations."""

TOOLS = [{"functionDeclarations": [
    {"name": "get_overview",
     "description": "Dataset coverage plus per-commodity stats: first/last year average, multiple, CAGR, last YoY, volatility, cheapest/priciest city."},
    {"name": "query_prices",
     "description": "Aggregate prices (avg/min/max/count). Filter by commodity (partial name ok), market and dates; group by year, month, market, province, commodity or none.",
     "parameters": {"type": "object", "properties": {
         "commodity": {"type": "string", "description": "e.g. 'Wheat flour', 'Sugar', 'Milk'"},
         "market": {"type": "string", "enum": ["Karachi", "Lahore", "Multan", "Peshawar", "Quetta"]},
         "start": {"type": "string", "description": "YYYY or YYYY-MM"},
         "end": {"type": "string", "description": "YYYY or YYYY-MM"},
         "group_by": {"type": "string", "enum": ["year", "month", "market", "province", "commodity", "none"]},
         "metric": {"type": "string", "enum": ["price", "usd"]},
         "limit": {"type": "integer"}}}},
    {"name": "forecast_prices",
     "description": "Forecast future monthly prices of ONE commodity (point forecast + 80% interval, backtest accuracy, warnings). Use for any 'predict/upcoming/next months' question.",
     "parameters": {"type": "object", "properties": {
         "commodity": {"type": "string"},
         "horizon_months": {"type": "integer", "description": "1-24, default 6"},
         "market": {"type": "string", "enum": ["Karachi", "Lahore", "Multan", "Peshawar", "Quetta"], "description": "optional; default national average"},
         "metric": {"type": "string", "enum": ["price", "usd"]}}, "required": ["commodity"]}},
    {"name": "forecast_outlook",
     "description": "Forecast every commodity at once for the given horizon, sorted by expected % change (largest rise first). Use to compare which items will rise or fall most.",
     "parameters": {"type": "object", "properties": {"horizon_months": {"type": "integer", "description": "1-24, default 6"}}}},
]}]


class AIError(Exception):
    pass


def _call(body):
    key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not key:
        raise AIError("GEMINI_API_KEY is not set on the server.")
    model = os.environ.get("GEMINI_MODEL", DEFAULT_MODEL)
    try:
        r = requests.post(API_URL.format(model=model), json=body, timeout=50,
                          headers={"x-goog-api-key": key, "Content-Type": "application/json"})
    except requests.RequestException as e:
        raise AIError(f"Could not reach Gemini: {e.__class__.__name__}")
    if r.status_code != 200:
        try:
            msg = r.json()["error"]["message"]
        except Exception:
            msg = r.text
        hint = " (quota/rate limit - wait a minute or use a lighter model)" if r.status_code == 429 else ""
        raise AIError(f"Gemini error {r.status_code}: {msg[:250]}{hint}")
    return r.json()


def _run_tool(name, args):
    if name == "get_overview":
        return data.overview()
    if name == "query_prices":
        allowed = {"commodity", "market", "start", "end", "group_by", "metric", "limit"}
        return data.query(**{k: v for k, v in (args or {}).items() if k in allowed})
    if name == "forecast_prices":
        a = args or {}
        return forecast.forecast(a.get("commodity", ""), a.get("horizon_months", 6), a.get("market"), a.get("metric", "price"), history_months=12)
    if name == "forecast_outlook":
        return {"rows": forecast.outlook(max(1, min(int((args or {}).get("horizon_months") or 6), 24)), "price")}
    return {"error": f"unknown tool {name}"}


def run_analyst(history):
    """history: [{'role': 'user'|'assistant', 'content': str}, ...] ending with a user message."""
    contents = [{"role": "user" if m["role"] == "user" else "model", "parts": [{"text": m["content"]}]}
                for m in history]
    calls = []
    for _ in range(6):
        resp = _call({
            "systemInstruction": {"parts": [{"text": SYSTEM}]},
            "contents": contents, "tools": TOOLS,
            "generationConfig": {"temperature": 0.3, "maxOutputTokens": 8192},
        })
        cand = (resp.get("candidates") or [None])[0]
        if not cand or not cand.get("content"):
            reason = (cand or {}).get("finishReason") or (resp.get("promptFeedback") or {}).get("blockReason") or "empty"
            return {"answer": f"Gemini returned no answer ({reason}). Try rephrasing.", "calls": calls}
        content = cand["content"]
        content.setdefault("role", "model")
        parts = content.get("parts", [])
        fcs = [p["functionCall"] for p in parts if "functionCall" in p]
        if not fcs:
            text = "".join(p.get("text", "") for p in parts if not p.get("thought")).strip()
            return {"answer": text or "No text returned. Try again.", "calls": calls}
        contents.append(content)  # keep verbatim: preserves thought signatures required by Gemini 3
        out_parts = []
        for fc in fcs:
            calls.append({"tool": fc["name"], "input": fc.get("args", {})})
            try:
                result = _run_tool(fc["name"], fc.get("args"))
            except Exception as e:  # tool errors go back to the model
                result = {"error": str(e)}
            fr = {"name": fc["name"], "response": {"result": result}}
            if fc.get("id"):
                fr["id"] = fc["id"]  # Gemini 3.5+ requires the same id back
            out_parts.append({"functionResponse": fr})
        contents.append({"role": "user", "parts": out_parts})
    return {"answer": "I reached the tool-call limit. Please ask a narrower question.", "calls": calls}
