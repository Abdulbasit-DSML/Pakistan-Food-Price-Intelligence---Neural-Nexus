# Pakistan Food Price Intelligence - Neural Nexus

A Django web application for exploring Pakistan's food-price data from the World Food Programme (WFP), covering 2004–2023. It includes an interactive dashboard, AI-powered data analysis using the Gemini API, and monthly price forecasts.

## Features

- **Food-price dashboard:** Explore historical prices across five city markets and 17 recorded items.
- **Gemini AI analyst:** Ask questions about the dataset. The AI uses application tools to query the data before explaining results.
- **Price forecasting:** Forecast monthly prices 1–24 months ahead, view an 80% range, and compare expected changes across items.
- **Transparent analysis:** The interface displays the data queries run by the AI.

## Dataset

The included CSV contains 9,996 retail price records from January 2004 through December 2023, with prices in PKR and USD equivalents. It covers Karachi, Lahore, Multan, Peshawar, and Quetta.

Data coverage varies by item. Wheat flour and basmati rice begin in 2004, many other items begin between 2013 and 2015, and salt is recorded only from 2014 to 2018. The CSV includes an HDX `#hashtag` row beneath the header; the data loader handles it.

**Forecast limitation:** The included dataset ends in December 2023. Forecasts therefore extend beyond the last date in the supplied dataset, not necessarily beyond the present day. Forecasts are estimates, not guaranteed future prices, and cannot account for unexpected events or policy changes. Salt forecasts may be stale because its recorded series ends in 2018.

## Tech Stack

- Python 3.12
- Django
- Gemini API
- Chart.js
- `requests`

The application reads the CSV directly; it does not use a database. Data is cached in memory for each server instance.

## Project Structure

```text
manage.py
foodai/                         Django project settings and URL configuration
analytics/
  data.py                       CSV loading and data aggregations
  forecast.py                   Forecasting engine and backtesting
  ai.py                          Gemini REST client and tool-calling loop
  views.py                       Dashboard and API endpoints
  templates/analytics/index.html Dashboard and AI chat interface
  tests.py                       Unit tests (Gemini calls are mocked)
data/wfp_food_prices_pak.csv     Food-price dataset
vercel.json                      Vercel deployment configuration
requirements.txt                 Python dependencies
.python-version                  Python version configuration (3.12)
```

## Deploy to Vercel

### 1. Push the project to GitHub

Make sure the repository includes `manage.py`, the `foodai/` and `analytics/` directories, the `data/` CSV file, `requirements.txt`, `.python-version`, and `vercel.json`.

### 2. Import the repository into Vercel

1. Sign in to Vercel.
2. Select **Add New → Project**.
3. Import the GitHub repository containing this project.
4. Review the detected project settings and deployment configuration before deploying.

### 3. Add environment variables

In the Vercel project, open **Settings → Environment Variables** and add:

| Variable | Required? | Purpose |
|---|---|---|
| `GEMINI_API_KEY` | Yes, for AI analysis | Your Gemini API key. Keep it secret. |
| `SECRET_KEY` | Yes for production | A long, random Django secret key. |
| `GEMINI_MODEL` | Optional | Gemini model ID to use. The application has a default. |
| `ACCESS_CODE` | Optional | Enables the access-code feature described by the application. |

Apply the variables to the appropriate deployment environments. After changing environment variables, redeploy so the deployment uses the updated values.

**Important:** Do not set `DEBUG=1` in production. Confirm that Django's production settings, allowed hosts, and CSRF trusted origins are correctly configured for the deployed Vercel domain. The required settings depend on the current `foodai/settings.py` implementation.

### 4. Deploy

Click **Deploy** in Vercel and wait for the build to finish. Open the deployment URL and test the dashboard, forecasts, and AI chat. If deployment fails, check the Vercel build and function logs before changing configuration.

## How the AI Analyst Works

The browser sends chat requests to `POST /api/analyze/`. The Django application calls Gemini, which can use these data tools:

- **`get_overview`:** Returns dataset coverage and item-level statistics, including growth, year-over-year changes, volatility, PKR-to-USD comparisons, and city comparisons.
- **`query_prices`:** Queries prices using filters such as item, city, and date, with grouping by year, month, city, province, or item and a PKR or USD metric.

Gemini can call tools over multiple rounds, up to the limit implemented in the application. The AI's answer is based on the tool results returned by the application. The chat endpoint is CSRF-protected.

## How Forecasting Works

The forecasting engine in `analytics/forecast.py` uses monthly average prices on a log scale and evaluates three candidate approaches: damped-trend Holt smoothing, Holt smoothing with monthly seasonality, and a naive last-value baseline. It selects a model for each item using rolling backtesting of six-month-ahead errors over approximately the last two years of available data. The displayed forecast range widens with the forecast horizon.

Forecasts are intended as trend indicators, not exact prices. They cannot anticipate shocks such as floods, subsidy changes, policy decisions, or currency crises. Update the CSV with a compatible, more recent dataset and redeploy if you need forecasts based on newer observations.

## Configuration and Security

- **Gemini model:** Set `GEMINI_MODEL` to a model ID supported by your Google AI Studio API key if the default is unavailable or you encounter model or quota errors.
- **Access control:** Anyone who can access a public deployment may be able to use its Gemini quota. Configure `ACCESS_CODE` if appropriate and test that the access-code feature works as expected.
- **Usage limits:** Monitor API usage and configure a budget or quota alert in Google AI Studio. Consider rate limiting before a public launch.
- **Secrets:** Never commit `GEMINI_API_KEY`, `SECRET_KEY`, or other credentials to the repository.

## Troubleshooting

| Problem | What to check |
|---|---|
| `GEMINI_API_KEY is not set` | Add `GEMINI_API_KEY` in Vercel project environment variables, then redeploy. |
| Gemini returns a `400` or `404` model error | Check that `GEMINI_MODEL` is a valid model ID supported by your API key. |
| Gemini returns `429` | Check quota and usage limits; wait for the quota to reset or use an available model with suitable limits. |
| Requests time out | Review Vercel function logs and the timeout configured in `vercel.json`. Long AI reports may take longer to generate. |
| AI request returns CSRF `403` | Reload the page and check the deployed Django CSRF and host configuration, including any custom-domain settings. |
| Deployment fails | Read the Vercel build logs and function logs. Confirm that dependencies, required files, environment variables, and Django production settings are correct. |
