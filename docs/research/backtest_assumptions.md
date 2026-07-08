# Backtest and Research-Result Assumptions

Margin strategy outputs are historical research validation artifacts. They are
not investment advice, not a promise of future results, and not an instruction
to place trades.

Any future strategy-performance statement should be treated as incomplete unless
it includes the assumptions below.

## Minimum Required Information

- Universe: eligible securities, exclusions, index membership rules, and whether
  the universe is point-in-time.
- Date range: start date, end date, and any warm-up period.
- Rebalance frequency: calendar, execution timing, and how missing rebalance
  dates are handled.
- Execution price assumption: close, next open, VWAP, or another explicitly
  defined price.
- Transaction costs: commission, taxes, fees, and whether costs are one-way or
  round-trip.
- Slippage: model, fixed basis points, or reason it is not included.
- Suspension handling: how non-tradable securities are retained, skipped, or
  valued.
- Limit-up/limit-down handling: whether blocked entries or exits are simulated.
- ST/delisting handling: exclusion timing and whether delisted securities remain
  in historical data.
- Survivorship-bias handling: how historical inactive securities are represented.
- Point-in-time data assumptions: feature availability, announcement dates,
  publication dates, fetch times, and decision times.
- Benchmark comparisons: benchmark names, total-return assumptions, and the
  comparison date range.
- Parameter-search range: parameters tried, objective function, and selection
  rule.
- Out-of-sample or walk-forward procedure: train/test windows, retraining
  cadence, and whether the final configuration was frozen before evaluation.
- Multiple-testing correction: whether many model or parameter attempts were
  adjusted for, or explicitly not adjusted for.

## Wording Rules

- Describe results as historical offline research metrics.
- State whether live-provider data, execution constraints, and forward paper
  validation were included.
- Do not imply that historical results will repeat.
- Do not present AI-generated analysis as authoritative.
- Do not omit material assumptions needed to reproduce the result.

## Current README Metrics

The README includes a compact historical offline result so users can understand
the project maturity level. Treat that table as a research-status snapshot until
the full assumptions above are attached to a reproducible run manifest.
