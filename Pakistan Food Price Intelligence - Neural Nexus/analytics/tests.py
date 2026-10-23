from unittest import mock

from django.test import SimpleTestCase

from . import data, forecast


class FakeResp:
    def __init__(self, status, body):
        self.status_code, self._b, self.text = status, body, str(body)

    def json(self):
        return self._b


class Tests(SimpleTestCase):
    def test_data(self):
        self.assertEqual(len(data.rows()), 9996)
        w = [s for s in data.commodity_stats() if s["commodity"] == "Wheat flour"][0]
        self.assertEqual((w["multiple"], w["cagr_pct"], w["yoy_last_pct"]), (9.84, 12.8, 83.9))
        q = data.query(commodity="wheat flour", group_by="market", start="2023", end="2023")
        self.assertEqual(len(q["groups"]), 5)

    def test_index(self):
        r = self.client.get("/")
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Pakistan Food Price Intelligence")

    @mock.patch.dict("os.environ", {"GEMINI_API_KEY": "x"})
    def test_tool_loop(self):
        call = {"candidates": [{"content": {"role": "model", "parts": [{"functionCall": {
            "id": "abc", "name": "query_prices", "args": {"commodity": "sugar", "group_by": "year"}}, "thoughtSignature": "sig"}]}}]}
        final = {"candidates": [{"content": {"role": "model", "parts": [{"text": "## Sugar\n- up"}]}}]}
        with mock.patch("analytics.ai.requests.post", side_effect=[FakeResp(200, call), FakeResp(200, final)]) as p:
            r = self.client.post("/api/analyze/", {"messages": [{"role": "user", "content": "sugar?"}]}, content_type="application/json")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["answer"], "## Sugar\n- up")
        self.assertEqual(r.json()["calls"][0]["tool"], "query_prices")
        second = p.call_args_list[1].kwargs["json"]["contents"]
        self.assertEqual(second[1]["parts"][0]["thoughtSignature"], "sig")      # echoed verbatim
        self.assertEqual(second[2]["parts"][0]["functionResponse"]["id"], "abc")  # id echoed

    @mock.patch.dict("os.environ", {"GEMINI_API_KEY": "x", "ACCESS_CODE": "s3"})
    def test_access_code_and_errors(self):
        body = {"messages": [{"role": "user", "content": "hi"}]}
        self.assertEqual(self.client.post("/api/analyze/", body, content_type="application/json").status_code, 401)
        err = FakeResp(429, {"error": {"message": "quota"}})
        with mock.patch("analytics.ai.requests.post", return_value=err):
            r = self.client.post("/api/analyze/", body, content_type="application/json", headers={"x-access-code": "s3"})
        self.assertEqual(r.status_code, 502)
        self.assertIn("quota", r.json()["error"])

    def test_forecast(self):
        f = forecast.forecast("wheat flour", 12)
        self.assertEqual(len(f["forecast"]), 12)
        for r in f["forecast"]:
            self.assertLess(r["low80"], r["point"])
            self.assertLess(r["point"], r["high80"])
        self.assertEqual(f["last_observed"], "2023-12")
        self.assertIn("naive_mape_pct", f["backtest"])
        self.assertIn("error", forecast.forecast("rice", 6))  # ambiguous -> asks to be specific
        self.assertTrue(any("stale" in w for w in forecast.forecast("salt", 3)["warnings"]))

    def test_forecast_endpoints(self):
        r = self.client.get("/api/forecast/?commodity=Sugar&horizon=6&market=Lahore")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(r.json()["forecast"]), 6)
        self.assertEqual(self.client.get("/api/forecast/?commodity=nothing").status_code, 400)
        self.assertEqual(len(self.client.get("/api/outlook/?horizon=3").json()["rows"]), 17)

    @mock.patch.dict("os.environ", {"GEMINI_API_KEY": "x"})
    def test_ai_forecast_tool(self):
        call = {"candidates": [{"content": {"role": "model", "parts": [{"functionCall": {
            "name": "forecast_prices", "args": {"commodity": "Sugar", "horizon_months": 6}}}]}}]}
        final = {"candidates": [{"content": {"role": "model", "parts": [{"text": "ok"}]}}]}
        with mock.patch("analytics.ai.requests.post", side_effect=[FakeResp(200, call), FakeResp(200, final)]) as p:
            r = self.client.post("/api/analyze/", {"messages": [{"role": "user", "content": "predict sugar"}]}, content_type="application/json")
        self.assertEqual(r.json()["calls"][0]["tool"], "forecast_prices")
        fr = p.call_args_list[1].kwargs["json"]["contents"][2]["parts"][0]["functionResponse"]["response"]["result"]
        self.assertEqual(len(fr["forecast"]), 6)
