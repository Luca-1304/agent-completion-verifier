# R1 post-merge review hardening

PR #27 merged before its automated Codex review completed. This branch treats the late review as a new adversarial verification cycle rather than rewriting history or running the live pilot prematurely.

Current gate: RED regressions only. No live GitHub experiment mutation is permitted from this branch until the verified review findings are fixed, exact-head release/wheel/stress gates pass again, and the hardening PR is reviewed and merged.

The review targets: permit target binding and single-use semantics, runner-owned S7 rollback, persistence of ordinary controller failures without fabricated remote evidence, accepted-but-unaddressable PR cleanup reconciliation, complete artifact-tree and public-config-digest verification, trusted in-process scaffold-adapter boundaries, pre-mutation output reservation, and measured verifier latency.
