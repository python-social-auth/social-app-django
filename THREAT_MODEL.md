# Threat model for social-auth-app-django

## 1. Document status

- **Project:** `social-auth-app-django`
- **Project version:** 7.1.0 plus commit `a9323f27` (2026-10-14)
- **Model date:** 2026-10-14
- **Authors:** Python Social Auth maintainers
- **Status:** Accepted, 2026-10-14
- **Version binding:** This model is versioned with the project. Reports against
  a released version are evaluated against the model shipped for that version,
  rather than the current `master` branch. (maintainer, 2026-10-14)
- **Reporting:** Report violations of a property claimed in §8 through the
  [Python Social Auth security policy](https://github.com/python-social-auth/.github/security/policy).
  Reports covered by an explicit exclusion in §3 or disclaimer in §9 may be
  closed by citing this document. (maintainer, 2026-10-14)
- **Provenance:** `(documented)` cites published project documentation;
  `(maintainer)` records a position ratified by the maintainers; `(inferred)`
  would require a matching question in §14.
- **Confidence:** Approximately 34 documented / 77 maintainer / 0 inferred
  claims.

`social-auth-app-django` is an in-process Django integration for the
`social-auth-core` authentication ecosystem. It supplies HTTP views, Django
strategy and storage implementations, middleware, templates, models,
migrations, and related helpers used to authenticate, register, associate, and
disconnect external identities in server-side Django applications.
(documented; [Django Framework](https://python-social-auth.readthedocs.io/en/latest/configuration/django.html))

## 2. Scope and intended use

The intended deployment is a server-side Django web application using a
supported Python and Django release. Browser-based login, registration,
authenticated account linking, account disconnection, and supported partial
pipelines are the primary use cases. (maintainer, 2026-10-14)

The embedding application and its operator are trusted to select backends,
pipelines, settings, templates, storage, and deployment controls. Remote users
and their HTTP inputs are not trusted. Data returned by a provider may contain
attacker-controlled profile values even after `social-auth-core` has
authenticated the protocol response. (maintainer, 2026-10-14)

| Component family | Representative entry points | External effects | Status |
| --- | --- | --- | --- |
| Authentication HTTP views | `social:begin`, `social:complete`, `social:disconnect` | HTTP requests and responses, sessions, upstream backend calls, authentication state | In scope (documented) |
| Launch bridges | `social:idp_launch`, `social:app_launch` | HTTP headers, rendered POST bridge, redirects | In scope when explicitly enabled (documented) |
| Django integration | `DjangoStrategy`, `SocialAuthExceptionMiddleware`, bundled templates and context processors | Sessions, authentication, rendering, redirects, messages, and logging | In scope (documented) |
| Persistent storage | Django models, storage mixins, identifier migrations, `clearsocial` | Database reads, writes, locks, and deletion of expired records | In scope (documented) |
| Framework conveniences | Admin integration, static icon finder, app configuration | Django admin and static-file discovery | In scope, with no independent authentication boundary (maintainer, 2026-10-14) |
| Extension surface | Custom strategies, storage, pipelines, backends, templates, and middleware subclasses | Defined by the embedding application | Only the built-in contract is in scope; custom behavior is trusted integrator code (maintainer, 2026-10-14) |
| Development material | Tests, CI configuration, and development scripts | Development environment only | Out of scope (maintainer, 2026-10-14) |

The documented component rows are described in
[Django Framework](https://python-social-auth.readthedocs.io/en/latest/configuration/django.html)
and [Storage](https://python-social-auth.readthedocs.io/en/latest/storage.html).

## 3. Out of scope

The following are explicit non-goals:

- Protocol and provider-backend implementation inside `social-auth-core`; this
  package relies on the selected backend to validate state, signatures, tokens,
  issuers, audiences, nonces, and provider responses. (maintainer, 2026-10-14)
- Security against a deliberately dishonest configured identity provider, a
  compromised provider signing key, a malicious application administrator, or
  an attacker controlling the Django process, settings, database, session
  store, or host. (maintainer, 2026-10-14)
- Client-side-only use, unsupported Python or Django versions, unsupported
  framework integrations, and custom forks or overrides that violate the
  documented extension contracts. (maintainer, 2026-10-14)
- Arbitrary custom pipeline, backend, strategy, storage, middleware, template,
  user-model, or database-router behavior. These are application code and must
  be threat-modeled by the integrator. (maintainer, 2026-10-14)
- Tests, CI and release automation, packaging infrastructure, and development
  scripts. Database migrations and the `clearsocial` command are not excluded
  because they affect production authentication state. (maintainer, 2026-10-14)
- Supply-chain controls, release signing, dependency freshness, and general
  Django or host hardening. These are important but are not properties supplied
  by this package. (maintainer, 2026-10-14)

## 4. Trust boundaries and data flow

The package boundary is its public integration surface: HTTP routes, request
and session data, Django settings, pipeline inputs, provider results delivered
by `social-auth-core`, and persisted authentication state. These inputs have
different trust levels and must not be treated uniformly. (maintainer,
2026-10-14)

A normal flow crosses these boundaries:

1. An untrusted browser request passes through the deployment proxy and Django
   middleware to a package view. (maintainer, 2026-10-14)
2. The Django strategy delegates protocol initiation or completion to a
   configured `social-auth-core` backend. The backend may communicate with an
   external provider and is responsible for protocol validation. (maintainer,
   2026-10-14)
3. Authenticated provider identity and untrusted profile attributes enter the
   configured pipeline. Trusted application pipeline code decides whether to
   select, create, update, or associate a local user. (maintainer, 2026-10-14)
4. The Django storage layer reads or changes associations, partial state,
   verification codes, nonces, and provider data in the application database.
   (documented; [Storage](https://python-social-auth.readthedocs.io/en/latest/storage.html))
5. Successful completion logs in the selected Django user, mutates the session,
   and redirects according to application and backend configuration.
   (documented; [Django Framework](https://python-social-auth.readthedocs.io/en/latest/configuration/django.html))

Reachability determines whether a report is in scope:

- A view or middleware issue must be reachable through a packaged route and
  supported middleware ordering with attacker-controlled request material.
  (maintainer, 2026-10-14)
- A storage or model issue must be reachable through a supported packaged flow
  or public storage contract. Behavior reachable only through arbitrary direct
  database modification is out of scope. (maintainer, 2026-10-14)
- A migration issue must affect a supported upgrade using documented historical
  identifier configuration. Custom data rewrites are out of scope.
  (documented; [Identifier migration](https://python-social-auth.readthedocs.io/en/latest/configuration/identifier-migration.html))
- A template or extension issue must be present in the bundled implementation;
  application overrides are trusted integrator code. (maintainer, 2026-10-14)

## 5. Assumptions about the environment

- The deployment uses supported Python and Django releases and a compatible
  `social-auth-core` release. (documented; [Django Framework](https://python-social-auth.readthedocs.io/en/latest/configuration/django.html))
- Production traffic uses TLS. Proxy-derived scheme and host information is
  accepted only from trusted proxies, and Django `ALLOWED_HOSTS` contains only
  intended hosts. (documented; [Security considerations](https://python-social-auth.readthedocs.io/en/latest/security.html))
- Django session, authentication, CSRF, and message middleware are correctly
  ordered where the selected flow requires them. Session cookies and server-side
  session data have integrity and confidentiality. (maintainer, 2026-10-14)
- Multi-instance deployments use shared session storage for flows that restore
  an initiating session, and the same browser retains the flow context.
  (documented; [SAML](https://python-social-auth.readthedocs.io/en/latest/backends/saml.html))
- The database enforces the schema's constraints and transactions correctly.
  Database contents, backups, and credentials are protected from unauthorized
  access, while string comparison behavior may vary by supported database.
  (maintainer, 2026-10-14)
- Clocks are sufficiently accurate for session, nonce, association, and email
  validation expiry. (maintainer, 2026-10-14)
- Application settings, registered backends, redirect destinations, pipelines,
  templates, and administrative command invocations are trusted operator input.
  (maintainer, 2026-10-14)

The package reads Django settings and request data; mutates sessions,
authentication state, and ORM records; renders responses; redirects; and logs.
The `clearsocial` command deletes expired or old package records. The package
does not itself spawn processes or install signal handlers. Provider network
I/O belongs to `social-auth-core` and its dependencies. (maintainer,
2026-10-14)

### 5a. Build-time and configuration variants

| Variant | Default or supported posture | Effect on the model |
| --- | --- | --- |
| Python, Django, and `social-auth-core` versions | Versions declared by package metadata; `social-auth-core >= 6.1, < 7` at this revision | Unsupported combinations are outside §3 (documented) |
| `SOCIAL_AUTH_ENABLE_LAUNCH_BRIDGES` | Disabled | Each enabled bridge adds the corresponding GET entry point and §8 bridge guarantees (documented) |
| `SOCIAL_AUTH_SANITIZE_REDIRECTS` | `True` in supported `social-auth-core` releases | Request-derived authentication and disconnection redirects are restricted to the current or explicitly allowed hosts and allowed schemes; explicitly setting `False` removes the corresponding §8 property (documented) |
| Global or backend `ALLOWED_REDIRECT_HOSTS` | Application configured | Expands the destinations accepted by enabled redirect validation and must contain only trusted destinations (documented) |
| `ALLOW_UNVERIFIED_LEGACY_UID_MIGRATION` variants | Backend-dependent compatibility policy; explicit `True` is an unsafe escape hatch | Permits specifically documented identity migrations without stored evidence; the accepted risk is disclaimed in §9 (documented) |
| Custom strategy, storage, pipeline, backend, template, middleware, or user model | Built-ins are modeled | Custom implementations can invalidate the model and are trusted integrator code (maintainer, 2026-10-14) |
| Session engine and proxy/HTTPS settings | Secure, correctly shared and forwarded production configuration | Incorrect settings can break request correlation, callback URLs, cookie delivery, and host validation (documented) |
| Exception transport, metadata, error URL, `DEBUG`, and `RAISE_EXCEPTIONS` | Messages transport and production `DEBUG=False` posture | Changes whether safe errors are rendered, redirected, placed in messages/query parameters, or re-raised (documented) |
| `ACTIVE_USERS_FILTER`, user model, identifier keys, and historical identifier overrides | Documented defaults or application-reviewed overrides | Changes which users and provider identifiers can participate in authentication and migration (documented) |

The documented configuration rows are described in
[Settings](https://python-social-auth.readthedocs.io/en/latest/configuration/settings.html),
[Django Framework](https://python-social-auth.readthedocs.io/en/latest/configuration/django.html),
and [Identifier migration](https://python-social-auth.readthedocs.io/en/latest/configuration/identifier-migration.html).

## 6. Assumptions about inputs

| Entry point | Input | Attacker-controllable? | Caller or dependency must enforce | Provenance |
| --- | --- | --- | --- | --- |
| `POST social:begin` | `backend` route value | Yes | Backend must be registered; unknown backends fail closed | (maintainer, 2026-10-14) |
| `POST social:begin` | Form/query values, including `next` | Yes | CSRF middleware protects initiation; supported `social-auth-core` sanitizes request-derived redirects by default, and the application keeps that default enabled with trusted allowlists | (maintainer, 2026-10-14) |
| `social:complete` | `backend` and provider callback parameters such as code, state, token, SAML response, or `RelayState` | Yes | Selected `social-auth-core` backend validates the applicable protocol and binds it to saved flow state | (maintainer, 2026-10-14) |
| `social:complete` | Session and partial-pipeline state | Browser selects a cookie but cannot forge protected contents under §5 | Django session integrity; package/core partial-resume ownership and confirmation rules | (maintainer, 2026-10-14) |
| `GET social:idp_launch` | `backend`, `iss`, `target_link_uri` | Yes | Bridge enabled; HTTPS issuer allowlist and redirect host checks pass | (maintainer, 2026-10-14) |
| `GET social:app_launch` | `backend`, optional `iss`, `next` | Yes | Bridge enabled; supported issuer, origin indicators when present, and redirect host checks pass | (maintainer, 2026-10-14) |
| Launch bridges | `Host`, `Referer`, and `Sec-Fetch-*` headers | Yes or absent | §5 host/proxy controls; Fetch Metadata is defense-in-depth, not authentication | (maintainer, 2026-10-14) |
| `POST social:disconnect` | `backend`, optional association ID | Yes, by an authenticated user | Django authentication and CSRF; disconnection remains scoped to the current user, and the default guard requires a usable password or another association row without checking whether that row's backend remains configured or usable | (maintainer, 2026-10-14) |
| Partial pipeline resume | Token, verification data, confirmation POST and nonce | Yes | Token validity plus session ownership or explicit session-bound external confirmation | (maintainer, 2026-10-14) |
| Exception middleware | Structured exception and configured error transport | Normally package/backend generated; custom code is trusted | Upstream exceptions provide safe public messages/metadata; custom exceptions and overrides preserve that contract | (maintainer, 2026-10-14) |
| Storage and strategy APIs | Provider, UID, identifier key, user, model values, session values | Trusted caller, though values can originate in validated provider flows | Pipeline/backend validates identity; integrator does not call trusted APIs with arbitrary unauthenticated choices | (maintainer, 2026-10-14) |
| Persisted `extra_data` and profile fields | Often derived from a remote user/provider | Yes in content | Consumers escape output and do not treat profile data or access tokens as authorization policy without validation | (maintainer, 2026-10-14) |
| Django configuration | Settings and custom extension paths | No | Trusted operator controls deployment and reviews changes | (maintainer, 2026-10-14) |
| `clearsocial` | `--age` | No | Trusted administrator chooses retention interval and database target | (maintainer, 2026-10-14) |

The package defines field and request parsing bounds but makes no quantitative
guarantee about request rate, total database size, provider latency, or aggregate
CPU and memory use. (maintainer, 2026-10-14)

## 7. Adversary model

In-scope adversaries are unauthenticated remote users and authenticated users
who control their own browser requests, headers, callback submissions, chosen
provider account, and provider-supplied profile fields. They may attempt login
or association CSRF, wrong-account binding, unauthorized disconnection, unsafe
redirection, flow replay, session confusion, or disclosure of authentication
state. (maintainer, 2026-10-14)

An in-scope attacker may hold a valid account at a configured provider, but
cannot make that honest provider issue a cryptographically valid assertion for
another identity. The attacker does not control trusted settings, extension
code, the Django process, signing keys, database, session store, proxy, or host.
(maintainer, 2026-10-14)

Compromised or deliberately dishonest identity providers, malicious operators,
local host attackers, and attackers already able to modify trusted application
code or persistence are outside the model because they already control a
load-bearing trust anchor. (maintainer, 2026-10-14)

## 8. Security properties the project provides

| Property and conditions | Violation symptom | Tier | Provenance |
| --- | --- | --- | --- |
| Association lookup requires exact provider, UID, and requested identifier-key matches, including on databases with case-insensitive comparisons. Identifier migration rejects conflicts and revalidates evidence under the association lock. | A provider identity resolves or migrates to a different local user's association. | Security-critical | (documented; [Identifier migration](https://python-social-auth.readthedocs.io/en/latest/configuration/identifier-migration.html)) |
| Standard authenticated linking and disconnection act on the current Django user. For built-in users, the default disconnection guard requires a usable password or another association row; it does not establish that the remaining association is usable. | One user links to or disconnects another user's association, or the default guard permits disconnection despite having neither a usable password nor another association row. | Security-critical for cross-user effects; correctness-only for guard-policy failures without an account/control-boundary impact | (maintainer, 2026-10-14) |
| Local initiation and disconnection are POST-only and CSRF-protected. External partial resumes require explicit, session-bound confirmation. Completion callbacks rely on the selected backend's protocol correlation rather than a browser CSRF token. | A cross-site request starts, resumes, links, or disconnects a protected flow without the required user intent or protocol proof. | Security-critical | (documented; [Django Framework](https://python-social-auth.readthedocs.io/en/latest/configuration/django.html)) |
| With redirect sanitization enabled, as it is by default in supported `social-auth-core` releases, and trusted redirect allowlists, request-derived authentication and disconnection redirects use the current or explicitly allowed hosts and allowed schemes. | A request-derived redirect reaches an attacker-controlled destination despite the supported configuration. | Security-critical | (documented; [Settings](https://python-social-auth.readthedocs.io/en/latest/configuration/settings.html)) |
| Enabled launch bridges accept only supported HTTPS issuers, constrain redirects to approved hosts, protect against framing, and convert GET initiation into a CSRF-protected POST. | An unapproved issuer or redirect is accepted, or a cross-site/framed launch silently initiates authentication contrary to the documented checks. | Security-critical | (documented; [Launch Bridge Endpoints](https://python-social-auth.readthedocs.io/en/latest/configuration/django.html#launch-bridge-endpoints)) |
| Restored server-side sessions are rotated before continued use, assuming the shared session and same-browser requirements in §5. | An attacker reuses the pre-restore session key to obtain the restored authenticated flow. | Security-critical | (documented; [SAML](https://python-social-auth.readthedocs.io/en/latest/backends/saml.html)) |
| Built-in structured authentication exceptions expose a safe default message and explicitly public metadata. Every 5xx failure handled by the middleware, whether rendered or redirected, emits an error log with the original traceback rather than placing it in response metadata. | Provider credentials, tokens, raw responses, or private exception details are disclosed by the built-in error response, or a handled 5xx failure omits the promised traceback log. | Security-critical for disclosure; correctness-only for missing server-side diagnostics | (documented; [Django Framework](https://python-social-auth.readthedocs.io/en/latest/configuration/django.html#django-exception-middleware)) |
| Invalid or expired package records and ordinary authentication errors fail with documented errors/statuses instead of authenticating a user. | A malformed request authenticates a user; an incorrect but non-authenticating status or message is otherwise an ordinary correctness defect. | Security-critical for unintended authentication; correctness-only otherwise | (documented; [Django Framework](https://python-social-auth.readthedocs.io/en/latest/configuration/django.html)) |

No availability or quantitative resource property is claimed beyond ordinary
termination for normal, bounded Django requests. (maintainer, 2026-10-14)

## 9. Security properties the project does not provide

- The package does not independently authenticate OAuth, OpenID Connect,
  OpenID, SAML, or provider-specific responses. Correct protocol validation is
  a `social-auth-core` backend responsibility. (maintainer, 2026-10-14)
- A configured provider is trusted to assert identities honestly. The package
  does not defend against a compromised IdP or signing key. (maintainer,
  2026-10-14)
- The default disconnection guard does not verify that a remaining association
  names a configured backend or that its provider account and credentials are
  still usable. An additional association row alone therefore does not
  guarantee future login access. (maintainer, 2026-10-14)
- If an integrator explicitly disables redirect sanitization, general
  authentication and disconnection redirects are not guaranteed to use an
  approved host and scheme. That non-default override removes the corresponding
  §8 property; launch-bridge redirect checks remain separate. (maintainer,
  2026-10-14)
- Provider tokens, association secrets, verification codes, partial data, and
  session data are not encrypted at rest by this package. Storage and backup
  confidentiality are deployment responsibilities. (maintainer, 2026-10-14)
- There is no quantitative per-request or aggregate CPU, memory, storage,
  database, provider-latency, or request-rate guarantee. Rate limiting and
  capacity management belong to the deployment. (maintainer, 2026-10-14)
- Built-in guarantees do not survive arbitrary custom pipelines, backends,
  storage, strategies, templates, middleware, user models, or settings.
  (maintainer, 2026-10-14)
- The package does not make untrusted provider profile fields safe for HTML,
  logs, SQL assembled outside the ORM, or application authorization decisions.
  Normal Django escaping and application validation remain required.
  (maintainer, 2026-10-14)
- Compatibility migration explicitly permitted without stored identifier
  evidence does not prove continuous identity ownership; its documented
  first-login race is an accepted compatibility risk.
  (documented; [Stable social account identifiers](https://python-social-auth.readthedocs.io/en/latest/security.html#stable-social-account-identifiers))

### False-friend properties

- `csrf_exempt` on `social:complete` permits cross-site provider callbacks; it
  is not a lack of flow validation. Protocol state, nonce, signature, issuer,
  and request correlation are supplied by the selected backend. (maintainer,
  2026-10-14)
- Fetch Metadata headers influence launch-bridge auto-submission but are not
  credentials. Browsers may omit them; issuer, redirect, CSRF, framing, and
  user-confirmation controls remain authoritative. (maintainer, 2026-10-14)
- Base64 storage of an association secret is serialization, not encryption.
  (maintainer, 2026-10-14)
- URL quoting in the login redirect context processor is output encoding, not
  redirect authorization. (maintainer, 2026-10-14)
- A database uniqueness constraint prevents duplicate stored keys but does not
  authenticate a provider response or make a mutable identifier stable.
  (maintainer, 2026-10-14)
- Safe structured error metadata does not make arbitrary custom exception text
  safe to expose. (maintainer, 2026-10-14)

## 10. Downstream responsibilities

The embedding application and operator must:

- Run supported releases and review relevant `social-auth-core` backend threat
  models and protocol requirements. (maintainer, 2026-10-14)
- Terminate TLS safely; validate host and forwarded headers; configure Django
  `ALLOWED_HOSTS`, secure cookies, CSRF, authentication, sessions, and proxy
  settings; and use shared server-side sessions when required.
  (documented; [Security considerations](https://python-social-auth.readthedocs.io/en/latest/security.html))
- Protect settings, client secrets, the database, session store, backups, logs,
  and provider tokens. (maintainer, 2026-10-14)
- Configure only trusted providers, issuer aliases, redirect hosts, error URLs,
  pipelines, and extension classes. Treat changes to them as security changes.
  (maintainer, 2026-10-14)
- Enable `associate_by_email` only where provider email ownership is trusted,
  and use stable, non-reassignable provider identifiers for authorization
  bindings. (documented; [Security considerations](https://python-social-auth.readthedocs.io/en/latest/security.html))
- Review identifier migration evidence and explicitly decide whether any
  unverified compatibility transition is acceptable before serving upgraded
  authentication traffic.
  (documented; [Identifier migration](https://python-social-auth.readthedocs.io/en/latest/configuration/identifier-migration.html))
- Keep redirect sanitization enabled and restrict allowed hosts and schemes to
  trusted destinations. If it is deliberately disabled, apply equivalent
  validation before accepting an untrusted redirect value. (maintainer,
  2026-10-14)
- Provide a stricter disconnection policy when association rows can outlive
  configured backends or when the application requires proof that another
  login path remains operational. (maintainer, 2026-10-14)
- Escape and validate provider profile data at each application sink, and never
  place secrets in URLs, templates, client-visible messages, or unsafe logs.
  (maintainer, 2026-10-14)
- Apply rate limits, request-size limits, timeouts, monitoring, retention, and
  capacity controls appropriate to the deployment. (maintainer, 2026-10-14)
- Reassess this model for every custom backend, pipeline, strategy, storage,
  template, middleware, user model, or direct storage API use. (maintainer,
  2026-10-14)

## 11. Known misuse patterns

- Enabling `associate_by_email` for a provider that does not reliably verify
  unique email ownership can bind an attacker to an existing local account.
  Use stable provider identifiers and explicit authenticated linking instead.
  (documented; [Django Framework](https://python-social-auth.readthedocs.io/en/latest/configuration/django.html))
- Selecting a mutable email, username, UPN, or display name as the provider UID
  permits reassignment or renaming to affect authorization bindings. Use the
  provider's stable identifier and follow the migration procedure.
  (documented; [Security considerations](https://python-social-auth.readthedocs.io/en/latest/security.html))
- Treating a custom pipeline as data plumbing rather than trusted authorization
  code can bypass user selection, association, and update invariants. Review it
  as application security code. (maintainer, 2026-10-14)
- Restoring SAML flows with signed-cookie or unshared per-instance sessions can
  lose the initiating request context. Use a supported shared server-side
  session arrangement. (documented; [SAML](https://python-social-auth.readthedocs.io/en/latest/backends/saml.html))
- Overriding the bundled launch or confirmation templates without preserving
  CSRF fields, whitelisted parameters, and manual-confirmation behavior can
  remove the documented protections. (maintainer, 2026-10-14)
- Placing raw exception text or metadata in a third-party error URL can leak it
  through browser history and downstream logs. Use only safe structured values
  and trusted destinations. (maintainer, 2026-10-14)
- Disabling `SOCIAL_AUTH_SANITIZE_REDIRECTS` without equivalent application
  validation permits untrusted redirect values to select destinations outside
  the default boundary. Keep the secure default unless another layer enforces
  the same policy. (maintainer, 2026-10-14)
- Calling model/storage deletion APIs directly bypasses the configured
  disconnection pipeline and its policy checks.
  (documented; [Disconnecting social accounts in code](https://python-social-auth.readthedocs.io/en/latest/configuration/django.html#disconnecting-social-accounts-in-code))

### 11a. Known non-findings

| Report pattern | Why it is not a defect under this model |
| --- | --- |
| `social:complete` is `csrf_exempt` | Provider callbacks cannot generally carry a Django CSRF token; §8 instead requires backend protocol correlation and protected local transitions. (maintainer, 2026-10-14) |
| Launch requests without `Sec-Fetch-*` headers are not rejected | Fetch Metadata is optional defense-in-depth; the authoritative controls are listed in §8. (maintainer, 2026-10-14) |
| A general `next` redirect is external after the integrator explicitly disabled sanitization | The non-default override and loss of the general redirect property are explicit in §5a and §9; launch-bridge targets remain protected. (maintainer, 2026-10-14) |
| Tokens or association secrets are readable in a database dump | Encryption at rest is disclaimed in §9 and database confidentiality is required by §5. A package-caused disclosure to an untrusted requester remains valid. (maintainer, 2026-10-14) |
| A trusted storage or strategy method accepts a value that an HTTP view would validate | Direct callers and custom extensions are trusted under §6 and must preserve the documented preconditions. (maintainer, 2026-10-14) |
| A finding exists only in tests, CI, or development scripts | Those components are outside §3. Production migrations and management commands remain in scope. (maintainer, 2026-10-14) |
| Slow or expensive behavior has no demonstrated account/control-boundary impact | §8 provides no quantitative resource guarantee. A resource report may still be accepted as discretionary hardening. (maintainer, 2026-10-14) |

## 12. Conditions that would change this model

Review and version this model when the project adds or changes a public route,
accepted callback or input format, identity/association rule, session restore
mechanism, persistent secret, production command, deployment context,
security-relevant setting default, supported extension contract, or
`social-auth-core` major-version contract. (maintainer, 2026-10-14)

Also review it when published documentation changes a load-bearing assumption,
a formerly external component moves into this repository, or a report cannot be
routed to exactly one §13 disposition. An unroutable report is a `MODEL-GAP`,
not grounds for an ad hoc outcome. (maintainer, 2026-10-14)

Internal refactoring that preserves the public security contract does not by
itself require a model revision. (maintainer, 2026-10-14)

## 13. Triage dispositions

The following dispositions form a closed set for this model. (maintainer,
2026-10-14)

| Disposition | Meaning | Licensed by |
| --- | --- | --- |
| `VALID` | An in-scope adversary and input violate a claimed security property. | §6, §7, §8 |
| `VALID-HARDENING` | No §8 property is violated, but a §11 misuse is sufficiently easy that maintainers elect to harden it; normally no CVE. | §11 |
| `OUT-OF-MODEL: trusted-input` | Exploitation requires attacker control of an input §6 marks trusted. | §6 |
| `OUT-OF-MODEL: adversary-not-in-scope` | Exploitation requires a capability excluded by §7. | §7 |
| `OUT-OF-MODEL: unsupported-component` | The affected component or deployment is excluded by §3. | §3 |
| `OUT-OF-MODEL: non-default-build` | The issue exists only under a discouraged configuration that §5a explicitly places outside the supported posture. | §5a |
| `BY-DESIGN: property-disclaimed` | The report concerns a property explicitly not provided. | §9 |
| `KNOWN-NON-FINDING` | The report matches a recurring pattern already discharged by the model. | §11a |
| `MODEL-GAP` | No other disposition applies; revise this model before deciding the report. | §12 |

The security-critical threshold is an account or control-boundary violation:
wrong-account access or association, a forged protected transition, bypass of a
claimed redirect boundary, or package-caused authentication-secret disclosure.
Authentication usability, response wording/status, and resource behavior are
ordinary defects unless they cross one of those boundaries. (maintainer,
2026-10-14)

## 14. Open questions for maintainers

Not applicable. The scope, trust, adversary, resource, redirect, persistence,
extension, severity, deployment, callback, side-effect, and publication
positions in this version were ratified by maintainers on 2026-10-14. There are
no `(inferred)` claims. (maintainer, 2026-10-14)

## 15. Machine-readable companion

Not applicable. This Markdown document is the sole canonical model; no derived
YAML sidecar is currently maintained. (maintainer, 2026-10-14)

## Appendix A. Existing security-policy back-map

The existing documentation remains deployment guidance. This document is the
canonical package-specific threat model used for triage. (maintainer,
2026-10-14)

| Existing statement | Threat-model coverage |
| --- | --- |
| Stable, non-reassignable social identifiers are required for authorization bindings | §5a, §8, §10, §11 |
| Unverified legacy migration accepts a first-login race | §5a, §9, §10 |
| Host and forwarded headers must be validated | §5, §6, §10 |
| Django `ALLOWED_HOSTS` must be restrictive in production | §5, §10 |
| General redirect sanitization is enabled by default and configurable | §5a, §6, §8, §9, §10, §11, §11a |
| Launch bridges provide opt-in issuer, origin, framing, redirect, and CSRF controls | §2, §5a, §6, §8 |
| Shared server-side sessions are required for restorable cross-site SAML flows | §5, §8, §11 |
| Security reports use private GitHub vulnerability reporting and only the latest release is guaranteed fixes | §1; disclosure and support policy remain in the shared `SECURITY.md` |
