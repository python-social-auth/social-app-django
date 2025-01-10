from django.test import RequestFactory, TestCase, override_settings

from social_django.context_processors import login_redirect


@override_settings(REDIRECT_FIELD_NAME="next")
class TestContextProcessors(TestCase):
    def setUp(self):
        self.request_factory = RequestFactory()

    def test_login_redirect_unicode_quote(self):
        request = self.request_factory.get("/", data={"next": "profile/sjó"})
        result = login_redirect(request)
        self.assertEqual(
            result,
            {
                "REDIRECT_FIELD_NAME": "next",
                "REDIRECT_FIELD_VALUE": "profile/sj%C3%B3",
                "REDIRECT_QUERYSTRING": "next=profile/sj%C3%B3",
            },
        )

    def test_login_redirect_malformed_post(self):
        request = self.request_factory.post("/", data="no boundary", content_type="multipart/form-data")
        result = login_redirect(request)
        self.assertEqual(
            result,
            {
                "REDIRECT_FIELD_NAME": "next",
                "REDIRECT_FIELD_VALUE": None,
                "REDIRECT_QUERYSTRING": "",
            },
        )
