# 08-research_candidate_dashboard — UI And Recommendation Dashboard

This module shows research results to users.

## What It Does

- Home Q&A for follow-up questions about recommendations and risks.
- Dashboard list for today’s recommended stocks.
- Detail pages for score, evidence, risk, and Agent decisions.
- Settings pages for providers, scope, data policy, and schedules.
- Agent progress UI for today’s research run.

## How It Runs

```text
Analysis Mart / Agent output
  -> Dashboard API aggregation
  -> frontend list and detail pages
  -> user Q&A calls MainAgent
```

The frontend should not read raw/source data directly. It displays aggregated API results.

## Main Entry Points

- `src/margin/dashboard/`
- `src/margin/api/routes/dashboard.py`
- `web/app/`
- `web/components/`

## Who Uses It

Users use it to start research, inspect recommendations, read evidence, and ask follow-up questions.
