# Public surface policy

This project is public by design, but **not every useful internal capability belongs in the public repository**.

The publication rule is simple: expose enough for people to understand, test and use the verifier safely; keep live operational control, private data and proprietary runbooks out of the stable public package.

## Public by design

The following are appropriate public surfaces:

- evaluator outcome semantics and evidence requirements;
- the read-only Action Verification SDK;
- authenticated **read-only** remote-state verifiers;
- privacy-minimal observation/evidence schemas and fixed reason codes;
- deterministic local benchmarks and failure-injection cases;
- confined local sandbox examples;
- fake transports, synthetic fixtures and reproducible non-sensitive tests;
- aggregate metrics, limitations and clearly bounded research claims;
- installation, API and contribution documentation needed for legitimate use.

## Not part of the stable public surface

Do not publish these in the stable package or public release documentation:

- provider write/mutation controllers or live-action orchestration;
- credentials, tokens, authorization headers or secret material;
- automatic secret discovery from environment variables, local stores or account metadata;
- production/disposable target identifiers, repository IDs, branch names, object IDs or private denylist contents;
- private experiment configuration, private traces, raw model/provider bodies or personal/customer data;
- exact operational runbooks for live experiments, cleanup, target selection or credential separation;
- internal prompts, unpublished commercial strategy or other material that is not required to use the public verifier;
- infrastructure topology or security configuration that would unnecessarily increase attack surface.

## Provider-integration rule

New public provider integrations default to **read-only observation**. A write-capable integration is treated as operational infrastructure and must not silently enter the stable public package.

The stable package must fail closed when authentication, authorization, provider identity, freshness or remote state is ambiguous. Public evidence remains privacy-minimal by default.

## Release gate

`tests/test_public_surface.py` enforces a conservative release boundary. It checks that:

- the private research/experiment namespace is absent from the stable source tree;
- known live R1 design/runbook files are absent;
- Python source does not issue literal `POST`, `PUT`, `PATCH` or `DELETE` requests;
- the stable source tree does not discover credentials through common environment/local-secret mechanisms;
- the security and public-surface policy files remain present.

A future exception requires an explicit review of this policy rather than weakening the test incidentally.

## Historical material

Git history and old pull requests are not secret storage. Once material has been committed publicly, assume it may have been copied. Removing a capability from the current stable tree reduces future exposure but does not retroactively make old commits private.

If actual credentials or personal secrets are ever exposed, rotate/revoke them immediately and handle history cleanup separately.