from unittest import mock

from django.http import HttpResponse
from django.test import RequestFactory, TestCase

from social_django.utils import (
    RedirectParamName,
    apply_framing_protection,
    build_url,
    check_fetch_metadata,
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

    def test_build_url(self):
        cases = [
            ("http://example.com/path", {"a": "1", "b": "test"}, "http://example.com/path?a=1&b=test"),
            (
                "http://example.com",
                {"next": "/protected/path/", "q": "hello world"},
                "http://example.com?next=%2Fprotected%2Fpath%2F&q=hello+world",
            ),
            ("http://example.com/path/", {"a": "1"}, "http://example.com/path/?a=1"),
            ("http://example.com/path", None, "http://example.com/path"),
            ("http://example.com/path", {}, "http://example.com/path"),
        ]
        for base_url, query_params, expected in cases:
            with self.subTest(base_url=base_url, query_params=query_params):
                self.assertEqual(build_url(base_url, query_params), expected)

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
