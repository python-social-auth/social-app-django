# Threat model for social-auth-app-django

## Purpose and applicability

social-auth-app-django is the in-process Django integration for social-auth-core.
This model records its runtime security boundaries and vulnerability triage
policy. Integration, configuration, deployment, and upgrade instructions belong
in the [project documentation](https://python-social-auth.readthedocs.io/en/latest/configuration/django.html).
Protocol validation and shared pipeline/interface guarantees belong to the
[core threat model](https://github.com/python-social-auth/social-core/blob/master/THREAT_MODEL.md).

This model is versioned with the package. Evaluate releases against the model
shipped with that version, rather than the current branch. The model does not
retroactively govern releases shipped without it. Report suspected violations
privately through the
[security policy](https://github.com/python-social-auth/.github/security/policy);
disclosure and release-support policy remain there.

## Scope, actors, and trust boundaries

In scope are packaged authentication, association, disconnection, and enabled
launch-bridge views; Django strategy, middleware, bundled templates and context
processors; models, storage mixins, production migrations, and the cleanup
command. Admin integration, app configuration, and static discovery are runtime
code but supply no independent authentication boundary. Tests, CI, packaging,
development scripts, supply-chain, and release-administration controls are out
of scope.

The intended deployment is a server-side Django application using supported
Python, Django, and core versions. Client-only deployments and custom forks or
overrides violating extension contracts are unsupported. Protocol and provider
implementation defects belong to core; defects in how this integration supplies
its contracts remain in scope here.

Attackers may be anonymous or authenticated users controlling requests,
headers, callbacks, their own provider accounts, and profile values. They may
attempt replay, session confusion, login/association CSRF, unauthorized
disconnection, redirect bypass, or disclosure of authentication state. They do
not control the process, host, trusted proxy, settings, signing keys, database,
session store, or trusted extension code. Dishonest providers and compromised
provider signing authorities are outside this model.

The normal flow crosses these boundaries:

1. Browser requests pass through the deployment and Django middleware to a view.
2. The strategy delegates protocol validation to the selected core backend.
3. Validated identity and still-untrusted profile values enter the pipeline.
4. Django storage reads or updates associations, partials, codes, and nonce data.
5. Completion logs in the selected local user, updates the session, and redirects.

| Input or surface | Trust and responsibility |
| --- | --- |
| Routes, form/query fields, callback bodies, resume links, and request headers | Attacker-controlled or absent; packaged entry points enforce their documented preconditions |
| Authenticated user and protected session context | Supplied by Django; preserve ownership and flow bindings |
| Provider identity delivered by core | Trusted only after the selected backend's applicable validation |
| Provider profile fields and persisted request/provider values | Retain source provenance; storage does not make contents trusted or safe for output |
| Settings, extension classes, templates, middleware, and command arguments | Trusted application/operator input |
| Direct storage/strategy API calls | Trusted callers must preserve public contract preconditions; record contents may still be untrusted |

View/middleware issues must be reachable through packaged routes and supported
middleware ordering. Storage issues must be reachable through supported flows
or public contracts. Migration findings must affect supported upgrades using
documented historical configuration. Arbitrary database rewrites and defects
solely in application overrides are outside the model.

## Assumptions and security properties

The deployment supplies supported dependencies, sufficiently accurate clocks,
TLS, trusted proxy headers, Host validation, correctly ordered Django
middleware, and protected cookies/session data. Restorable flows require the
same browser and shared server-side sessions; OAuth2 nonce claims share a
persistent store across workers. The database supplies constraints and
transactions; supported database string comparisons need not be case-sensitive.
Operators protect configuration, persistence, backups, and administrative access.

Built-in guarantees assume conforming extensions, required checks, enabled
redirect sanitization with trusted allowlists, and production error handling.
Launch bridges are opt-in. Explicitly weakening the supported posture removes
the affected guarantee; supported configuration details belong in
[Django configuration](https://python-social-auth.readthedocs.io/en/latest/configuration/django.html).

| Property | Security violation |
| --- | --- |
| Association lookup matches provider, UID, and requested identifier key exactly, including under case-insensitive database comparisons; migrations preserve uniqueness, reject conflicts, and revalidate evidence under lock | A provider identity resolves or migrates to another user's association |
| Standard linking and disconnection preserve the current authenticated local user | One user links to or disconnects another user's association |
| Local initiation, disconnection, and legacy login-form completion require a CSRF-protected POST; provider callbacks instead rely on core protocol validation | A protected transition succeeds without required intent or protocol proof |
| External partial resumes require explicit session-bound confirmation and preserve saved ownership | An attacker resumes or rebinds another user's flow without the required confirmation |
| Request-derived authentication/disconnection redirects obey core sanitization and trusted host/scheme allowlists | A redirect escapes the supported boundary |
| Enabled launch bridges constrain issuers to supported HTTPS identities and targets to approved destinations, protect against framing, and bridge initiation into a CSRF-protected POST | An unapproved issuer/target or cross-site/framed launch bypasses the documented controls |
| Restored server-side sessions are rotated before continued use under the shared-session and same-browser assumptions | An attacker reuses the old session key to obtain the restored flow |
| Built-in error presentation exposes safe default messages and explicitly public metadata, without provider credentials, raw responses, or private exception details | A packaged response discloses authentication secrets or private diagnostics |
| Invalid/expired records and ordinary authentication errors do not authenticate a user | Malformed or rejected data establishes an authenticated session |

Core relies on this integration for local-user continuity, session integrity,
confirmation rendering/verification, and atomic storage operations. These are
integration responsibilities, not reasons to exclude an otherwise reachable
cross-package flow defect. See [Strategies](https://python-social-auth.readthedocs.io/en/latest/strategies.html),
[Storage](https://python-social-auth.readthedocs.io/en/latest/storage.html),
and [Partial pipelines](https://python-social-auth.readthedocs.io/en/latest/pipeline.html#partial-pipeline).

The default disconnection guard checks for a usable password or another
association with a configured backend that is not association-only. This is
not proof that another provider account or its credentials remain usable.
Guard-policy failures are correctness defects unless they cross an account or
control boundary. See [Disconnection](https://python-social-auth.readthedocs.io/en/latest/configuration/django.html#disconnecting-social-accounts-in-code).

Security-critical impact means wrong-account access/association, a forged
protected transition, a claimed redirect-boundary bypass, or package-caused
authentication-secret disclosure. Incorrect non-authenticating statuses,
messages, and missing server-side diagnostics are correctness defects. Handled
server failures retain traceback logging as documented, but that diagnostic
behavior is not an independent security guarantee.

## Limits and downstream responsibilities

Protocol checks, backend-specific correlation exceptions, and accepted legacy
migration ownership races are defined by the compatible core contract. This
integration does not independently authenticate provider assertions or make
missing migration evidence prove continuous ownership. Operators must review
[Identifier migration](https://python-social-auth.readthedocs.io/en/latest/configuration/identifier-migration.html)
before serving affected upgrades.

The application supplies authorization, recovery, deployment hardening, and
review of trusted extensions. Provider profile values require escaping and
validation at their output or policy sinks. Email association requires explicit
trust in verified ownership. Built-in guarantees do not sandbox custom code or
make arbitrary custom exception text safe to expose.

The package does not encrypt tokens, secrets, partials, codes, or sessions at
rest. Database and backup confidentiality belong to the deployment. No
quantitative request-rate, CPU, memory, storage, database, provider-latency, or
availability guarantee is provided beyond ordinary termination for normal,
bounded requests. Deployment limits, retention, and monitoring remain required.

Launch-bridge redirect checks remain independent of general redirect
sanitization, even when the latter is disabled. Fetch Metadata affects bridge
behavior but is not a credential; its absence does not remove issuer, redirect,
CSRF, framing, or confirmation requirements. Direct record deletion bypasses
the disconnection pipeline and its policy/revocation steps.

The package mutates sessions and ORM data, renders, redirects, and logs; its
cleanup command deletes old/expired records. Provider network I/O belongs to
core and dependencies. The package does not spawn processes or install signal
handlers. See [Security considerations](https://python-social-auth.readthedocs.io/en/latest/security.html)
for deployment responsibilities and the
[SAML documentation](https://python-social-auth.readthedocs.io/en/latest/backends/saml.html)
for restoration requirements.

## Review and triage

Review changes to public routes/input formats, flow or association rules,
session restoration, persistent authentication data, production commands,
deployment modes, defaults, extension contracts, or the core dependency
contract. Edit this model only when a boundary, assumption, property, exception,
responsibility, or triage rule changes or leaves a gap. A fix restoring an
existing guarantee or an internal refactor needs no individual model entry.

Known misuse includes unverified email association, mutable provider identifiers,
custom pipelines bypassing authorization invariants, unsupported restoration
sessions, templates omitting confirmation/CSRF controls, raw exceptions sent to
error URLs, disabled redirect validation, and direct deletion bypassing the
disconnection pipeline. These patterns may justify discretionary hardening.

| Known non-finding | Boundary or qualification |
| --- | --- |
| Provider completion is CSRF-exempt | Core protocol checks supply callback validation; legacy local forms still require CSRF-protected POST |
| Launch requests omit Fetch Metadata | These headers are optional defense in depth, not credentials |
| General redirects are external after sanitization is explicitly disabled | The guarantee was removed; independent bridge checks remain |
| Database dumps expose stored tokens/secrets | At-rest encryption is not provided; package-caused requester disclosure remains valid |
| Trusted storage/strategy calls accept values an HTTP view would reject | Direct callers must preserve documented preconditions |
| A finding is confined to tests, CI, or development scripts | Excluded scope; production migrations and commands remain in scope |
| Slow/expensive behavior has no account/control-boundary impact | No quantitative resource guarantee; discretionary hardening remains possible |

Base64 secret storage is serialization, URL quoting is encoding, and database
uniqueness is an integrity constraint; none independently supplies encryption,
redirect authorization, or provider authentication.

The following dispositions remain a closed set. The table does not introduce
an ordering between overlapping exclusions. Assess the actual violated
property, attacker capability, and input origin; do not classify saved
attacker-controlled contents as trusted merely because storage returned them.

| Disposition | Condition |
| --- | --- |
| `VALID` | An in-scope adversary and input violate a claimed property |
| `VALID-HARDENING` | Maintainers elect to harden a known misuse without a property violation; normally no CVE |
| `OUT-OF-MODEL: trusted-input` | Exploitation requires control of an input classified as trusted |
| `OUT-OF-MODEL: adversary-not-in-scope` | Exploitation requires an excluded attacker capability |
| `OUT-OF-MODEL: unsupported-component` | The component or deployment is excluded |
| `OUT-OF-MODEL: non-default-build` | Exploitation requires discouraged configuration explicitly outside supported posture |
| `BY-DESIGN: property-disclaimed` | The property is explicitly not provided |
| `KNOWN-NON-FINDING` | The report matches a known non-finding above |
| `MODEL-GAP` | No other disposition applies; revise the model before deciding |

A report that cannot be routed to exactly one disposition is a model gap,
not grounds for an ad hoc assumption. Severity depends on concrete impact;
non-authenticating usability, response, and resource defects remain ordinary
correctness issues unless they cross a claimed boundary.
