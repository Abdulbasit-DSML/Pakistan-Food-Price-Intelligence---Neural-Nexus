import json
import os

from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_POST

from django.views.decorators.http import require_GET

from . import ai, data, forecast


@ensure_csrf_cookie
def index(request):
    return render(request, "analytics/index.html", {"data": data.dashboard_data()})


@require_POST
def analyze(request):
    need = os.environ.get("ACCESS_CODE")  # optional: protects your API quota
    if need and request.headers.get("x-access-code") != need:
        return JsonResponse({"error": "Access code required or incorrect."}, status=401)
    try:
        msgs = json.loads(request.body or b"{}").get("messages") or []
    except ValueError:
        return JsonResponse({"error": "Invalid JSON."}, status=400)
    clean = [{"role": "assistant" if m.get("role") == "assistant" else "user", "content": str(m.get("content", ""))[:2000]}
             for m in msgs[-8:] if isinstance(m, dict)]
    while clean and clean[0]["role"] != "user":
        clean.pop(0)
    if not clean or clean[-1]["role"] != "user":
        return JsonResponse({"error": "Send a user message."}, status=400)
    try:
        return JsonResponse(ai.run_analyst(clean))
    except ai.AIError as e:
        return JsonResponse({"error": str(e)}, status=502)
    except Exception:
        return JsonResponse({"error": "Analysis failed. Please try again."}, status=500)


def _int(v, d):
    try:
        return int(v)
    except (TypeError, ValueError):
        return d


@require_GET
def forecast_view(request):
    g = request.GET
    res = forecast.forecast(g.get("commodity", ""), _int(g.get("horizon"), 6), g.get("market") or None, g.get("metric", "price"))
    return JsonResponse(res, status=400 if "error" in res else 200)


@require_GET
def outlook_view(request):
    g = request.GET
    h = max(1, min(_int(g.get("horizon"), 6), 24))
    return JsonResponse({"horizon": h, "rows": forecast.outlook(h, g.get("metric", "price") if g.get("metric") in ("price", "usd") else "price")})
