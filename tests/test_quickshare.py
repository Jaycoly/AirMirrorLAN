from __future__ import annotations

import http.client
import json
import sys
import tempfile
import unittest
from pathlib import Path
from urllib.parse import urlencode

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from quickshare import QuickShareServer, safe_filename, safe_path  # noqa: E402


class PathSafetyTests(unittest.TestCase):
    def test_safe_path_stays_in_root(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            child = root / "child.txt"
            child.write_text("ok", encoding="utf-8")
            self.assertEqual(safe_path(root, "child.txt"), child.resolve())
            with self.assertRaises(ValueError):
                safe_path(root, "../outside.txt", must_exist=False)

    def test_safe_filename_removes_client_path(self) -> None:
        self.assertEqual(safe_filename("folder/photo.jpg"), "photo.jpg")
        self.assertEqual(safe_filename(r"folder\报告.pdf"), "报告.pdf")
        for invalid in ("", ".", "..", "bad\x00name"):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                safe_filename(invalid)


class QuickShareIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.server = QuickShareServer(self.root, "127.0.0.1", 0, token="test-token")
        self.server.start()

    def tearDown(self) -> None:
        self.server.stop()
        self.temporary.cleanup()

    def request(self, method: str, path: str, body: bytes | None = None, headers: dict[str, str] | None = None):
        connection = http.client.HTTPConnection("127.0.0.1", self.server.port, timeout=5)
        connection.request(method, path, body=body, headers=headers or {})
        response = connection.getresponse()
        payload = response.read()
        result = response.status, dict(response.getheaders()), payload
        connection.close()
        return result

    def test_login_page_and_session_cookie(self) -> None:
        status, _, page = self.request("GET", "/")
        self.assertEqual(status, 200)
        self.assertIn("6 位访问码".encode("utf-8"), page)

        body = urlencode({"code": "test-token"}).encode("ascii")
        status, headers, _ = self.request(
            "POST",
            "/login",
            body=body,
            headers={"Content-Type": "application/x-www-form-urlencoded", "Content-Length": str(len(body))},
        )
        self.assertEqual(status, 303)
        cookie = headers["Set-Cookie"].split(";", 1)[0]
        status, _, listing = self.request("GET", "/", headers={"Cookie": cookie})
        self.assertEqual(status, 200)
        self.assertIn("当前文件夹".encode("utf-8"), listing)

    def test_protected_endpoint_rejects_missing_code(self) -> None:
        status, _, _ = self.request("GET", "/download?path=missing.txt")
        self.assertEqual(status, 403)

    def test_upload_list_download_and_range(self) -> None:
        data = "局域网快传".encode("utf-8")
        query = urlencode({"token": "test-token", "name": "说明.txt", "dir": ""})
        status, _, payload = self.request(
            "PUT",
            "/upload?" + query,
            body=data,
            headers={"Content-Length": str(len(data))},
        )
        self.assertEqual(status, 201, payload)
        self.assertEqual((self.root / "说明.txt").read_bytes(), data)

        status, _, listing = self.request("GET", "/?" + urlencode({"token": "test-token"}))
        self.assertEqual(status, 200)
        self.assertIn("说明.txt".encode("utf-8"), listing)

        download = "/download?" + urlencode({"token": "test-token", "path": "说明.txt"})
        status, headers, payload = self.request("GET", download, headers={"Range": "bytes=0-2"})
        self.assertEqual(status, 206)
        self.assertEqual(payload, data[:3])
        self.assertEqual(headers["Content-Range"], f"bytes 0-2/{len(data)}")

    def test_duplicate_upload_gets_a_new_name(self) -> None:
        for content in (b"one", b"two"):
            query = urlencode({"token": "test-token", "name": "same.txt"})
            status, _, payload = self.request(
                "PUT",
                "/upload?" + query,
                body=content,
                headers={"Content-Length": str(len(content))},
            )
            self.assertEqual(status, 201, json.loads(payload))
        self.assertEqual((self.root / "same.txt").read_bytes(), b"one")
        self.assertEqual((self.root / "same (1).txt").read_bytes(), b"two")

    def test_create_folder(self) -> None:
        query = urlencode({"token": "test-token", "name": "来自 iPhone"})
        status, _, _ = self.request("POST", "/mkdir?" + query, body=b"", headers={"Content-Length": "0"})
        self.assertEqual(status, 201)
        self.assertTrue((self.root / "来自 iPhone").is_dir())


if __name__ == "__main__":
    unittest.main()
