# 06-multi_agent_research — Multi-Agent Research

This module lets Agents combine quant output, evidence, risk review, and user questions.

## What It Does

- MainAgent plans, dispatches, and performs final review.
- ExpertAgents handle data checks, quant analysis, news acquisition, stock analysis, and Q&A.
- Guardrails control what Agents can read, write, and when they must fail.
- Context Store records run state and artifact references.

## How It Runs

```text
user or scheduled trigger
  -> MainAgent plan
  -> ExpertAgent steps
  -> read Analysis Mart and Evidence
  -> write review output and Dashboard projection
  -> MainAgent final check
```

Agents should not read raw/source tables directly or bypass Evidence and Analysis Mart.

## Main Entry Points

- `src/margin/agent_runtime/`
- `src/margin/research/`
- `src/margin/prompts/`
- `src/margin/api/routes/agent_runtime.py`

## Who Uses It

Dashboard shows Agent state and adjusted recommendations. The home page Q&A reads Agent output and evidence references.
