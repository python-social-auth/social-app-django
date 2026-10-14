# Agent guidance for social-auth-app-django

This file captures agent-specific guidance for working in the Django integration
repository. Framework-agnostic authentication behavior lives in the
[social-core](https://github.com/python-social-auth/social-core) repository. The
full user and integrator documentation lives in
[social-docs](https://github.com/python-social-auth/social-docs) and is published
at <https://python-social-auth.readthedocs.io/>.

## Project overview

- `social-auth-app-django` is the Django integration for `social-auth-core`.
- The package provides Django views, strategy and storage implementations,
  middleware, models and migrations, templates, context processors, admin
  integration, and a management command.
- [social-core](https://github.com/python-social-auth/social-core) owns
  authentication protocols, provider backends, pipelines, structured
  exceptions, and the shared strategy and storage interfaces. Keep this
  repository framework-specific and implement shared behavior in core.
- The [social-docs documentation tree](https://github.com/python-social-auth/social-docs/tree/master/docs)
  is the source of the published documentation. Do not duplicate substantial
  integration or configuration guidance in this repository.
- Supported Python, Django, and `social-auth-core` versions are declared in
  `pyproject.toml` and tested through `tox.ini`.

## Code expectations

- Follow existing Django patterns and project conventions.
- Prefer the repository's configured Ruff formatting and linting rules. Use
  human-readable Ruff rule names in overrides, such as
  `# ruff: ignore[unused-function-argument]`, rather than cryptic rule codes.
- Add type hints to new or changed interfaces where practical. Use
  `from __future__ import annotations` and `TYPE_CHECKING` imports where they
  avoid runtime import cycles or premature Django app loading.
- Preserve compatibility across every supported Python, Django, database, and
  `social-auth-core` combination unless the change deliberately updates the
  declared support policy.
- Treat migrations as production code. Use historical models and migration-safe
  imports, declare dependencies for every accessed model, keep operations
  resumable where practical, and add populated forward and reverse migration
  tests for data migrations.
- Keep the default Django models, managers, and the storage mixins behaviorally
  aligned. Custom storage implementations depend on their shared contract.
- Review the corresponding interface and tests in
  [social-core](https://github.com/python-social-auth/social-core) before changing
  strategy, storage, pipeline, exception, or backend interactions. Coordinate
  changes across both repositories when neither side can remain backward
  compatible, including dependency bounds and integration tests.
- Keep sync and async middleware behavior aligned.
- Write commit messages using Conventional Commits, such as
  `fix(auth): reject mismatched provider identifiers` or
  `docs(security): clarify redirect responsibility`.

## Documentation expectations

- Update `README.md` for repository-level setup or policy changes and
  `CHANGELOG.md` for user-visible changes. Add follow-up entries to an
  unreleased section, creating it when needed; do not rewrite released-version
  history.
- Update the relevant page in the
  [social-docs documentation tree](https://github.com/python-social-auth/social-docs/tree/master/docs)
  when changing documented settings, endpoints, templates, middleware, models,
  storage behavior, extension contracts, or deployment requirements.
- Match the surrounding reStructuredText style in `social-docs`. Prefer Sphinx
  semantic references for internal documentation and use published
  `https://python-social-auth.readthedocs.io/en/latest/` links when citing the
  documentation from this repository.
- Keep documentation changes direct and scoped. Explain integrator-visible
  behavior and security responsibilities without duplicating implementation
  details.

## Security guardrails

- Treat authentication initiation, completion, account association and
  disconnection, partial pipelines, session restoration, redirects, and
  identifier migration as security-sensitive paths.
- Keep local state-changing initiation and disconnection flows POST-only and
  CSRF-protected. Provider completion callbacks intentionally use backend
  protocol validation instead of a Django CSRF token; do not weaken state,
  nonce, signature, issuer, audience, or request-correlation checks.
- Treat settings and custom backends, pipelines, strategies, storage classes,
  middleware, and templates as trusted extension code. Validate all HTTP and
  provider-derived data before it crosses into that trusted surface.
- Use stable, non-reassignable provider identifiers for account bindings.
  Preserve exact provider and identifier comparisons, conflict handling,
  transaction boundaries, and evidence checks during identifier migration.
- Do not expose client secrets, access or refresh tokens, association secrets,
  partial-pipeline state, verification codes, raw provider responses, or private
  exception details in responses, URLs, templates, or unsafe logs.
- Review `THREAT_MODEL.md` when changing public endpoints; authentication,
  account-linking, disconnection, partial-pipeline, session, error, or redirect
  behavior; persistent authentication data or migrations; deployment modes;
  supported extension contracts; or security-relevant dependency and setting
  defaults.
- Review does not necessarily require an edit. Update the threat model in the
  same change only when its scope, actors, trust boundaries, assumptions,
  claimed or disclaimed security properties, or triage dispositions change or
  leave a gap, following §12, "Conditions that would change this model."
  Features covered by the existing contract do not need individual entries.
  Keep feature-level endpoint, configuration, implementation, and limit details
  in the published documentation; link to them only when needed to explain a
  distinct boundary, exception, or triage outcome.

## Testing and linting instructions

- Install development dependencies with `uv sync --all-extras --dev` when the local
  environment is not already prepared.
- Run `uvx prek run --all-files` for the configured formatting,
  linting, spelling, metadata, and workflow checks.
- Run the default test suite with `uv run coverage run manage.py test`.
- Use the relevant `tox` environments for changes affected by Python, Django,
  database, or `social-auth-core` version differences.
- Add focused regression tests for every behavior change, including both
  accepted and rejected security-sensitive inputs. Prefer Django's test client,
  `override_settings`, and mocks for provider or network behavior.
- Run `uv run --all-extras mypy social_django tests/typecheck.py` when changing
  typed interfaces or Django model/manager behavior.
