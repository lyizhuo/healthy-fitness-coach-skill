import gzip
import io
import json
import unittest
import urllib.error
from unittest.mock import patch

from coach.http import ApiError, get_json, post_json


class FakeResponse:
    def __init__(self, payload, encoding="gzip"):
        self._raw = gzip.compress(json.dumps(payload).encode()) if encoding == "gzip" else json.dumps(payload).encode()
        self.headers = {"Content-Encoding": encoding} if encoding else {}

    def read(self):
        return self._raw

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class HttpTests(unittest.TestCase):
    def test_post_json_decodes_gzip(self):
        with patch("urllib.request.urlopen", return_value=FakeResponse({"status": "ok", "res": {"trains": []}})):
            result = post_json("https://example.test/api", {"x": 1}, headers={"Authorization": "Bearer test"})
        self.assertEqual(result["res"]["trains"], [])

    def test_get_json_adds_query_params(self):
        captured = {}

        def fake_urlopen(request, timeout=30):
            captured["url"] = request.full_url
            return FakeResponse({"ok": True}, encoding=None)

        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            result = get_json("https://example.test/api", params={"a": "b", "skip": None})
        self.assertTrue(captured["url"].endswith("?a=b"))
        self.assertEqual(result, {"ok": True})

    def test_http_error_maps_to_structured_api_error(self):
        body = gzip.compress(json.dumps({"error": {"message": "too frequent", "retry_after_ms": 1500}}).encode())
        error = urllib.error.HTTPError(
            "https://example.test/api",
            429,
            "Too Many Requests",
            {"Content-Encoding": "gzip"},
            io.BytesIO(body),
        )
        with patch("urllib.request.urlopen", side_effect=error):
            with self.assertRaises(ApiError) as context:
                post_json("https://example.test/api", {})
        self.assertEqual(context.exception.code, "too_frequent")
        self.assertEqual(context.exception.retry_after_ms, 1500)
        self.assertEqual(context.exception.status, 429)


if __name__ == "__main__":
    unittest.main()
