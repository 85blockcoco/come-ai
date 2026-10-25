# Feature Specification: Deterministic Extractor Performance

## Requirements

- Extractors remain offline, bounded and approximately linear.
- Benchmarks warm up before measurement and report median/best samples.
- Functional correctness is never weakened to satisfy timing.
- CI uses a stable regression budget rather than a machine-sensitive 5 ms cliff.

## Acceptance

Salary extraction remains correct on 50,000 characters and passes the documented performance budget.
