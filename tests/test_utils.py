from unittest import mock

from django.http import HttpResponse
from django.test import RequestFactory, TestCase, override_settings

from social_django.utils import (
    RedirectParamName,
    apply_framing_protection,
    check_fetch_metadata,
    get_allowed_redirect_hosts,
    get_backend_issuer,
    is_safe_url,
    is_valid_https_url,
    resolve_redirect_uri,
    validate_app_launch_origin,
    validate_idp_issuer,
)


class TestUtils(TestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def test_is_safe_url(self):
        cases = [
            # Safe relative paths
            ("/dashboard", {"example.com"}, False, True),
            ("/profile?user=1", {"example.com"}, False, True),
            # Safe allowed absolute URLs
            ("https://example.com/profile", {"example.com"}, True, True),
            ("http://example.com/profile", {"example.com"}, False, True),
            # Unsafe disallowed hosts
            ("https://evil.com/phishing", {"example.com"}, False, False),
            ("//evil.com/phishing", {"example.com"}, False, False),
            # Unsafe schemes
            ("javascript:alert(1)", {"example.com"}, False, False),
            ("data:text/html,<script>alert(1)</script>", {"example.com"}, False, False),
            # Backslash bypass attempts
            ("/\\evil.com", {"example.com"}, False, False),
            ("\\evil.com", {"example.com"}, False, False),
            # Require HTTPS enforcement
            ("http://example.com/profile", {"example.com"}, True, False),
            # Absolute URL with no allowed_hosts specified
            ("https://example.com/profile", None, False, False),
            # Malformed URL causing ValueError in urlsplit
            ("http://[::1", {"example.com"}, False, False),
            ("http://[::1]:bad_port/", {"example.com"}, False, False),
            # None or invalid types
            (None, {"example.com"}, False, False),
            ("", {"example.com"}, False, False),
        ]
        for url, allowed_hosts, require_https, expected in cases:
            with self.subTest(url=url, allowed_hosts=allowed_hosts, require_https=require_https):
                self.assertEqual(
                    is_safe_url(url, allowed_hosts=allowed_hosts, require_https=require_https),
                    expected,
                )

    def test_is_valid_https_url(self):
        cases = [
            # Valid HTTPS URLs
            ("https://example.com", True),
            ("https://example.com/", True),
            ("https://example.com/path/to/resource", True),
            ("https://subdomain.example.com:8443/path?query=value#fragment", True),
            ("https://127.0.0.1/", True),
            ("https://localhost/", True),
            # Non-HTTPS schemes
            ("http://example.com", False),
            ("ftp://example.com", False),
            ("javascript:alert(1)", False),
            ("file:///path/to/file", False),
            # Malformed / Invalid URLs
            ("/path/to/resource", False),
            ("//example.com", False),
            ("example.com", False),
            ("", False),
            ("https://example .com", False),
            ("https://example.com:not_a_port", False),
            (None, False),
        ]
        for url, expected in cases:
            with self.subTest(url=url):
                self.assertEqual(is_valid_https_url(url), expected)

    def test_check_fetch_metadata(self):
        # Top-level document navigation (happy path)
        request = self.factory.get("/", headers={"Sec-Fetch-Dest": "document", "Sec-Fetch-Mode": "navigate"})
        auto_submit, warnings = check_fetch_metadata(request, "test_view")
        self.assertTrue(auto_submit)
        self.assertEqual(warnings, [])

        # Non-document destination
        request = self.factory.get("/", headers={"Sec-Fetch-Dest": "image"})
        auto_submit, warnings = check_fetch_metadata(request, "test_view")
        self.assertFalse(auto_submit)
        self.assertTrue(any("Unexpected Sec-Fetch-Dest" in w for w in warnings))

        # Framed / embedded mode
        for mode in ("iframe", "frame", "embed"):
            with self.subTest(mode=mode):
                request = self.factory.get("/", headers={"Sec-Fetch-Mode": mode})
                auto_submit, warnings = check_fetch_metadata(request, "test_view")
                self.assertFalse(auto_submit)
                self.assertTrue(any("Framed/embedded Sec-Fetch-Mode" in w for w in warnings))

    def test_validate_app_launch_origin(self):
        # Valid same-origin request with safe referer
        request = self.factory.get(
            "/",
            headers={"Sec-Fetch-Site": "same-origin", "Referer": "http://testserver/dashboard"},
        )
        is_valid, error = validate_app_launch_origin(request)
        self.assertTrue(is_valid)
        self.assertIsNone(error)

        # Cross-site request rejected
        request = self.factory.get("/", headers={"Sec-Fetch-Site": "cross-site"})
        is_valid, error = validate_app_launch_origin(request)
        self.assertFalse(is_valid)
        assert error is not None  # noqa: S101
        self.assertIn("Cross-site launch rejected", error)

        # Untrusted referer rejected
        request = self.factory.get(
            "/",
            headers={"Sec-Fetch-Site": "same-origin", "Referer": "https://malicious.example.com"},
        )
        is_valid, error = validate_app_launch_origin(request)
        self.assertFalse(is_valid)
        assert error is not None  # noqa: S101
        self.assertIn("Untrusted Referer origin rejected", error)

        # Missing both Sec-Fetch-Site and Referer rejected
        request = self.factory.get("/")
        is_valid, error = validate_app_launch_origin(request)
        self.assertFalse(is_valid)
        assert error is not None  # noqa: S101
        self.assertIn("Missing same-origin indicator", error)

        # Valid referer without Sec-Fetch-Site accepted
        request = self.factory.get("/", headers={"Referer": "http://testserver/home"})
        is_valid, error = validate_app_launch_origin(request)
        self.assertTrue(is_valid)
        self.assertIsNone(error)

    def test_get_backend_issuer(self):
        backend = mock.MagicMock()
        backend.id_token_issuer.return_value = "https://idp.example.com"
        issuers, error = get_backend_issuer(backend, "mock-backend")
        self.assertEqual(issuers, ["https://idp.example.com"])
        self.assertIsNone(error)

        # Backend returning list of issuers
        backend.id_token_issuer.return_value = ["https://idp1.example.com", "https://idp2.example.com"]
        issuers, error = get_backend_issuer(backend, "mock-backend")
        self.assertEqual(issuers, ["https://idp1.example.com", "https://idp2.example.com"])
        self.assertIsNone(error)

        # Backend returning tuple of issuers
        backend.id_token_issuer.return_value = ("https://idp1.example.com",)
        issuers, error = get_backend_issuer(backend, "mock-backend")
        self.assertEqual(issuers, ["https://idp1.example.com"])
        self.assertIsNone(error)

        # Backend returning invalid type
        backend.id_token_issuer.return_value = 123
        issuers, error = get_backend_issuer(backend, "mock-backend")
        self.assertIsNone(issuers)
        assert error is not None  # noqa: S101
        self.assertIn("must be a string or list of strings", error)

        # Backend missing id_token_issuer support
        backend = mock.MagicMock(spec=[])
        issuers, error = get_backend_issuer(backend, "unsupported")
        self.assertIsNone(issuers)
        assert error is not None  # noqa: S101
        self.assertIn("does not support ID token issuer validation", error)

        # Insecure / non-https issuer
        backend = mock.MagicMock()
        backend.id_token_issuer.return_value = "http://insecure.example.com"
        issuers, error = get_backend_issuer(backend, "mock-backend")
        self.assertIsNone(issuers)
        assert error is not None  # noqa: S101
        self.assertIn("is not a valid RFC-compliant HTTPS URL", error)

        # Insecure URL in list
        backend.id_token_issuer.return_value = ["https://idp1.example.com", "http://insecure.example.com"]
        issuers, error = get_backend_issuer(backend, "mock-backend")
        self.assertIsNone(issuers)
        assert error is not None  # noqa: S101
        self.assertIn("is not a valid RFC-compliant HTTPS URL", error)

    def test_validate_idp_issuer(self):
        backend = mock.MagicMock()
        backend.id_token_issuer.return_value = ["https://idp1.example.com", "https://idp2.example.com"]
        backend.setting.return_value = ["https://allowed.example.com"]

        # Valid matching first issuer
        iss, error = validate_idp_issuer(backend, "mock-backend", "https://idp1.example.com")
        self.assertEqual(iss, "https://idp1.example.com")
        self.assertIsNone(error)

        # Valid matching second issuer from backend list
        iss, error = validate_idp_issuer(backend, "mock-backend", "https://idp2.example.com")
        self.assertEqual(iss, "https://idp2.example.com")
        self.assertIsNone(error)

        # Valid matching allowed issuer from settings
        iss, error = validate_idp_issuer(backend, "mock-backend", "https://allowed.example.com")
        self.assertEqual(iss, "https://allowed.example.com")
        self.assertIsNone(error)

        # Missing iss parameter
        iss, error = validate_idp_issuer(backend, "mock-backend", None)
        self.assertIsNone(iss)
        assert error is not None  # noqa: S101
        self.assertIn("Missing required `iss` query parameter", error)

        # Non-HTTPS iss parameter
        iss, error = validate_idp_issuer(backend, "mock-backend", "http://insecure.example.com")
        self.assertIsNone(iss)
        assert error is not None  # noqa: S101
        self.assertIn("is not a valid RFC-compliant HTTPS URL", error)

        # Mismatched iss parameter
        iss, error = validate_idp_issuer(backend, "mock-backend", "https://other.example.com")
        self.assertIsNone(iss)
        assert error is not None  # noqa: S101
        self.assertIn("Invalid `iss` parameter", error)

    def test_get_allowed_redirect_hosts(self):
        request = self.factory.get("/")

        # Default allowed host is request host
        hosts = get_allowed_redirect_hosts(request)
        self.assertEqual(hosts, {request.get_host()})

        # Global setting as list
        with override_settings(SOCIAL_AUTH_ALLOWED_REDIRECT_HOSTS=["host1.example.com", "host2.example.com"]):
            hosts = get_allowed_redirect_hosts(request)
            self.assertEqual(hosts, {request.get_host(), "host1.example.com", "host2.example.com"})

        # Global setting as string
        with override_settings(SOCIAL_AUTH_ALLOWED_REDIRECT_HOSTS="single.example.com"):
            hosts = get_allowed_redirect_hosts(request)
            self.assertEqual(hosts, {request.get_host(), "single.example.com"})

        # Global setting with unsupported type (e.g. integer) is safely ignored (branch 248->252)
        with override_settings(SOCIAL_AUTH_ALLOWED_REDIRECT_HOSTS=12345):
            hosts = get_allowed_redirect_hosts(request)
            self.assertEqual(hosts, {request.get_host()})

        # Fallback to request.backend when backend is not passed explicitly
        mock_backend = mock.MagicMock()
        mock_backend.setting.return_value = ["req-backend.example.com"]
        request.backend = mock_backend
        hosts = get_allowed_redirect_hosts(request)
        self.assertEqual(hosts, {request.get_host(), "req-backend.example.com"})
        del request.backend

        # Backend setting as string
        backend = mock.MagicMock()
        backend.setting.return_value = "str-backend.example.com"
        hosts = get_allowed_redirect_hosts(request, backend=backend)
        self.assertEqual(hosts, {request.get_host(), "str-backend.example.com"})

        # Backend setting as tuple / set
        backend.setting.return_value = ("tuple-backend.example.com",)
        hosts = get_allowed_redirect_hosts(request, backend=backend)
        self.assertEqual(hosts, {request.get_host(), "tuple-backend.example.com"})

        # Backend setting with unsupported type (e.g. integer) is safely ignored (branch 260->263)
        backend.setting.return_value = 12345
        hosts = get_allowed_redirect_hosts(request, backend=backend)
        self.assertEqual(hosts, {request.get_host()})

    def test_resolve_redirect_uri(self):
        request = self.factory.get("/")
        # Safe relative path
        uri = resolve_redirect_uri(request, "/dashboard", RedirectParamName.NEXT, "test_view")
        self.assertEqual(uri, "/dashboard")

        # Unsafe external URL discarded
        uri = resolve_redirect_uri(request, "https://evil.com/phish", RedirectParamName.TARGET_LINK_URI, "test_view")
        self.assertIsNone(uri)

        # Empty / None
        uri = resolve_redirect_uri(request, None, RedirectParamName.NEXT, "test_view")
        self.assertIsNone(uri)

        # Global SOCIAL_AUTH_ALLOWED_REDIRECT_HOSTS setting honored (list)
        with override_settings(SOCIAL_AUTH_ALLOWED_REDIRECT_HOSTS=["frontend.example.com"]):
            uri = resolve_redirect_uri(
                request,
                "https://frontend.example.com/welcome",
                RedirectParamName.NEXT,
                "test_view",
            )
            self.assertEqual(uri, "https://frontend.example.com/welcome")

        # Global SOCIAL_AUTH_ALLOWED_REDIRECT_HOSTS setting honored (single string)
        with override_settings(SOCIAL_AUTH_ALLOWED_REDIRECT_HOSTS="single.example.com"):
            uri = resolve_redirect_uri(
                request,
                "https://single.example.com/app",
                RedirectParamName.NEXT,
                "test_view",
            )
            self.assertEqual(uri, "https://single.example.com/app")

        # Backend-specific ALLOWED_REDIRECT_HOSTS honored
        backend = mock.MagicMock()
        backend.setting.return_value = ["backend-host.example.com"]
        uri = resolve_redirect_uri(
            request,
            "https://backend-host.example.com/callback",
            RedirectParamName.NEXT,
            "test_view",
            backend=backend,
        )
        self.assertEqual(uri, "https://backend-host.example.com/callback")
        backend.setting.assert_called_with("ALLOWED_REDIRECT_HOSTS", [])

    def test_apply_framing_protection(self):
        response = HttpResponse("test")
        apply_framing_protection(response)
        self.assertEqual(response.headers.get("Content-Security-Policy"), "frame-ancestors 'none'")

        # Appending when CSP already has existing directives
        response_with_csp = HttpResponse("test")
        response_with_csp.headers["Content-Security-Policy"] = "default-src 'self'"
        apply_framing_protection(response_with_csp)
        self.assertEqual(
            response_with_csp.headers.get("Content-Security-Policy"),
            "default-src 'self'; frame-ancestors 'none'",
        )

        # Does not duplicate frame-ancestors if already present
        apply_framing_protection(response_with_csp)
        self.assertEqual(
            response_with_csp.headers.get("Content-Security-Policy"),
            "default-src 'self'; frame-ancestors 'none'",
        )
