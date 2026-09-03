# Security policy

## Public repository boundary

This repository is intended to publish **verification and evaluation tooling**, not operational write infrastructure.

The stable public package may include read-only provider observations, privacy-minimal evidence models, deterministic local benchmarks, local sandbox tooling, and documentation needed to understand those interfaces.

The stable public package must not contain live provider-mutation controllers, private experiment runbooks, credentials, tokens, secret-discovery logic, production target configuration, customer/personal traces, private prompts, or deployment/security topology.

See `docs/PUBLIC_SURFACE.md` for the publication rules enforced by the release tests.

## Reporting a security issue

Do not post credentials, private identifiers, exploit details, customer data, or other sensitive material in a public issue or pull request.

Use GitHub's private vulnerability-reporting feature when it is available for this repository. If it is not available, use an already-established private channel with the repository owner and keep the initial report minimal until a private route is confirmed.

## Secret handling

Assume anything committed to this public repository can be copied permanently. Secrets must be rotated rather than merely deleted if they are ever exposed.

The verifier's authenticated read boundary accepts credentials from caller-owned code at runtime; credentials are not discovered from environment variables or local secret stores by the stable package and are excluded from default public evidence.

## Scope

Security reports are especially useful for:

- credential or caller-controlled identifier leakage;
- fail-open verification behavior;
- unsafe path or symlink handling;
- remote-state confusion or repository-identity mistakes;
- release artifacts that expose private inputs;
- accidental addition of provider write capability to the stable public package.

This policy does not claim that a verifier match proves causality, user authorization, intent, permanence, or production safety.