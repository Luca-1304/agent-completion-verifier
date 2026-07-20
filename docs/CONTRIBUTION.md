# Contribution and evidence statement

## Luca Panayiotou

Luca originated and repeatedly refined the practical problem addressed here: an
AI system can confidently report completion even when the underlying action
failed, never ran, was later rolled back, or lacks sufficient evidence.

His contribution includes:

- defining evidence-grounded completion as the acceptance standard;
- requiring receipts or observable artefacts for external actions;
- distinguishing verified, partial, unverified, and failed outcomes;
- requiring retry, recovery, and later-regression behaviour to be tested;
- shaping cases around email, files, calendars, repositories, and other
  consequential workflows;
- insisting that deterministic test output not be represented as live model
  benchmark performance;
- identifying the broader research direction: measuring false-completion rates
  across models, scaffolds, tools, and controlled failures.

## AI assistance

AI assistance was used to translate those requirements into Python,
documentation, test cases, and release structure. This assistance is disclosed
because the repository is intended to demonstrate problem formulation,
evaluation judgment, transparent collaboration, and reproducible output—not to
misrepresent unaided software implementation.

## Verification performed

The implementation was checked through:

- 34 unit tests;
- Python bytecode compilation;
- CLI execution over the 16-case evaluation set;
- JSON-output execution over a minimal example set;
- a multi-version GitHub Actions workflow for Python 3.10–3.13.

## Reproducibility boundary

This is a compact public demonstration, not a complete private benchmark. It
makes no claim of changing model weights, improving model training, or reporting
performance from live external models.
