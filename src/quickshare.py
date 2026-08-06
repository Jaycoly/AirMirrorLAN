"""Small authenticated LAN file server used by AirMirrorLAN Quick Share."""

from __future__ import annotations

import hashlib
import hmac
import html
import json
import mimetypes
import os
import re
import secrets
import threading
import time
from http.cookies import SimpleCookie
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Callable
from urllib.parse import parse_qs, quote, urlencode, urlsplit


MAX_UPLOAD_BYTES = 20 * 1024 * 1024 * 1024
CHUNK_SIZE = 1024 * 1024


def safe_path(root: Path, relative: str, *, must_exist: bool = True) -> Path:
    """Resolve a URL path below root, rejecting traversal and escaping symlinks."""
    root = root.resolve()
    relative = relative.replace("\\", "/").lstrip("/")
    candidate = (root / relative).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as error:
        raise ValueError("路径超出共享文件夹。") from error
    if must_exist and not candidate.exists():
        raise FileNotFoundError(relative)
    return candidate


def safe_filename(value: str) -> str:
    name = Path(value.replace("\\", "/")).name.strip()
    if not name or name in {".", ".."} or any(ord(char) < 32 for char in name):
        raise ValueError("文件名无效。")
    if name.rstrip(". ") != name:
        name = name.rstrip(". ")
    if not name:
        raise ValueError("文件名无效。")
    return name


def human_size(size: int) -> str:
    value = float(size)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{size} B"


class QuickShareHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(
        self,
        address: tuple[str, int],
        root: Path,
        token: str,
        log_callback: Callable[[str], None] | None = None,
    ) -> None:
        self.share_root = root.resolve()
        self.access_token = token
        self.log_callback = log_callback
        self.file_lock = threading.Lock()
        self.login_lock = threading.Lock()
        self.login_failures: dict[str, list[float]] = {}
        super().__init__(address, QuickShareRequestHandler)


class QuickShareRequestHandler(BaseHTTPRequestHandler):
    server: QuickShareHTTPServer
    protocol_version = "HTTP/1.0"

    def log_message(self, format: str, *args: object) -> None:
        return

    def do_GET(self) -> None:
        parsed, query = self._request_parts()
        if not self._authorized(query):
            if parsed.path == "/":
                self._send_login_page()
            else:
                self._send_text(HTTPStatus.FORBIDDEN, "请先返回快传首页并输入访问码。")
            return
        if parsed.path == "/":
            self._serve_listing(query)
        elif parsed.path == "/download":
            self._serve_download(query, head_only=False)
        else:
            self._send_text(HTTPStatus.NOT_FOUND, "未找到。")

    def do_HEAD(self) -> None:
        parsed, query = self._request_parts()
        if not self._authorized(query):
            self._send_text(HTTPStatus.FORBIDDEN, "访问码无效或已过期。", head_only=True)
            return
        if parsed.path == "/download":
            self._serve_download(query, head_only=True)
        else:
            self._send_text(HTTPStatus.NOT_FOUND, "未找到。", head_only=True)

    def do_PUT(self) -> None:
        parsed, query = self._request_parts()
        if not self._authorized(query):
            self._send_json(HTTPStatus.FORBIDDEN, {"error": "访问码无效或已过期。"})
            return
        if parsed.path != "/upload":
            self._send_json(HTTPStatus.NOT_FOUND, {"error": "未找到。"})
            return
        self._receive_upload(query)

    def do_POST(self) -> None:
        parsed, query = self._request_parts()
        if parsed.path == "/login":
            self._handle_login()
            return
        if not self._authorized(query):
            self._send_json(HTTPStatus.FORBIDDEN, {"error": "访问码无效或已过期。"})
            return
        if parsed.path != "/mkdir":
            self._send_json(HTTPStatus.NOT_FOUND, {"error": "未找到。"})
            return
        self._create_folder(query)

    def _request_parts(self):
        parsed = urlsplit(self.path)
        return parsed, parse_qs(parsed.query, keep_blank_values=True)

    def _authorized(self, query: dict[str, list[str]]) -> bool:
        supplied = query.get("token", [""])[0]
        if not supplied:
            cookie = SimpleCookie()
            try:
                cookie.load(self.headers.get("Cookie", ""))
                supplied = cookie.get("AirMirrorToken").value if cookie.get("AirMirrorToken") else ""
            except ValueError:
                supplied = ""
        return bool(supplied) and hmac.compare_digest(supplied, self.server.access_token)

    def _send_login_page(self, status: HTTPStatus = HTTPStatus.OK, error: str = "") -> None:
        error_html = f'<p class="error">{html.escape(error)}</p>' if error else ""
        page = f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>AirMirror 快传登录</title>
<style>*{{box-sizing:border-box}}body{{margin:0;background:#f3f6f9;color:#17202a;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}}
.box{{max-width:430px;margin:12vh auto;padding:26px;background:#fff;border-radius:18px;box-shadow:0 6px 24px #20304018}}
h1{{margin:0 0 8px}}p{{color:#65717e}}input{{width:100%;font-size:28px;letter-spacing:8px;text-align:center;padding:13px;border:1px solid #ccd6df;border-radius:11px}}
button{{width:100%;margin-top:14px;border:0;border-radius:11px;padding:13px;background:#1976d2;color:#fff;font-size:17px;font-weight:650}}.error{{color:#c43d3d}}</style></head>
<body><main class="box"><h1>AirMirror 快传</h1><p>请输入电脑软件窗口中显示的 6 位访问码。</p>{error_html}
<form method="post" action="/login"><input name="code" inputmode="numeric" pattern="[0-9]{{6}}" maxlength="6" autocomplete="one-time-code" required autofocus>
<button type="submit">进入共享文件夹</button></form></main></body></html>"""
        self._send_bytes(status, page.encode("utf-8"), "text/html; charset=utf-8")

    def _handle_login(self) -> None:
        client = self.client_address[0]
        now = time.monotonic()
        with self.server.login_lock:
            recent = [stamp for stamp in self.server.login_failures.get(client, []) if now - stamp < 60]
            self.server.login_failures[client] = recent
            if len(recent) >= 8:
                self._send_login_page(HTTPStatus.TOO_MANY_REQUESTS, "尝试次数过多，请一分钟后再试。")
                return
        length_text = self.headers.get("Content-Length", "")
        if not length_text.isdigit() or int(length_text) > 1024:
            self._send_login_page(HTTPStatus.BAD_REQUEST, "登录请求无效。")
            return
        body = self.rfile.read(int(length_text)).decode("utf-8", errors="replace")
        supplied = parse_qs(body).get("code", [""])[0]
        if not hmac.compare_digest(supplied, self.server.access_token):
            with self.server.login_lock:
                self.server.login_failures.setdefault(client, []).append(now)
            self._send_login_page(HTTPStatus.FORBIDDEN, "访问码不正确。")
            return
        with self.server.login_lock:
            self.server.login_failures.pop(client, None)
        self.send_response(HTTPStatus.SEE_OTHER)
        self.send_header("Location", "/")
        self.send_header("Set-Cookie", f"AirMirrorToken={self.server.access_token}; HttpOnly; SameSite=Strict; Path=/")
        self.send_header("Content-Length", "0")
        self._security_headers()
        self.end_headers()

    def _query_value(self, query: dict[str, list[str]], name: str) -> str:
        return query.get(name, [""])[0]

    def _directory(self, query: dict[str, list[str]]) -> tuple[Path, str]:
        relative = self._query_value(query, "dir").strip("/")
        target = safe_path(self.server.share_root, relative)
        if not target.is_dir():
            raise NotADirectoryError(relative)
        normalized = target.relative_to(self.server.share_root).as_posix()
        return target, "" if normalized == "." else normalized

    def _serve_listing(self, query: dict[str, list[str]]) -> None:
        try:
            directory, relative = self._directory(query)
            entries = sorted(directory.iterdir(), key=lambda item: (not item.is_dir(), item.name.casefold()))
        except (OSError, ValueError):
            self._send_text(HTTPStatus.NOT_FOUND, "文件夹不存在或不可访问。")
            return

        rows: list[str] = []
        if relative:
            parent = Path(relative).parent.as_posix()
            if parent == ".":
                parent = ""
            href = "/?" + urlencode({"dir": parent})
            rows.append(f'<a class="item folder" href="{html.escape(href, quote=True)}"><span>↩️ 上一级</span></a>')

        for entry in entries:
            try:
                resolved = entry.resolve()
                resolved.relative_to(self.server.share_root)
            except (OSError, ValueError):
                continue
            rel = entry.relative_to(self.server.share_root).as_posix()
            label = html.escape(entry.name)
            if entry.is_dir():
                href = "/?" + urlencode({"dir": rel})
                rows.append(f'<a class="item folder" href="{html.escape(href, quote=True)}"><span>📁 {label}</span></a>')
            elif entry.is_file():
                href = "/download?" + urlencode({"path": rel})
                try:
                    size = human_size(entry.stat().st_size)
                except OSError:
                    size = ""
                rows.append(
                    f'<a class="item" href="{html.escape(href, quote=True)}">'
                    f'<span>📄 {label}</span><small>{html.escape(size)}</small></a>'
                )

        path_label = "/" + html.escape(relative)
        rows_html = "\n".join(rows) or '<div class="empty">此文件夹为空，可从 iPhone 上传文件。</div>'
        relative_js = json.dumps(relative)
        page = f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>AirMirror 快传</title><style>
*{{box-sizing:border-box}}body{{margin:0;background:#f3f6f9;color:#17202a;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}}
.wrap{{max-width:760px;margin:auto;padding:20px}}.card{{background:#fff;border-radius:16px;padding:18px;box-shadow:0 6px 24px #20304016}}
h1{{font-size:26px;margin:0 0 4px}}.sub{{color:#65717e;margin:0 0 18px;word-break:break-all}}
.actions{{display:flex;gap:10px;flex-wrap:wrap;margin-bottom:16px}}button,.pick{{border:0;border-radius:11px;padding:12px 16px;font-size:16px;font-weight:600;cursor:pointer}}
.pick{{background:#1976d2;color:#fff;display:inline-block}}button{{background:#e8eef4;color:#17202a}}input[type=file]{{display:none}}
#status{{min-height:24px;color:#1b8a5a;margin:8px 0}}.item{{display:flex;justify-content:space-between;gap:12px;color:#17202a;text-decoration:none;padding:14px 4px;border-top:1px solid #e8edf2}}
.folder{{font-weight:650}}small{{color:#65717e;white-space:nowrap}}.empty{{padding:28px 0;color:#65717e;text-align:center}}
.note{{font-size:13px;color:#65717e;margin-top:16px;line-height:1.55}}
</style></head><body><main class="wrap"><section class="card">
<h1>AirMirror 快传</h1><p class="sub">当前文件夹：{path_label}</p>
<div class="actions"><label class="pick">选择并上传<input id="files" type="file" multiple></label><button id="mkdir">新建文件夹</button></div>
<div id="status"></div><div>{rows_html}</div>
<p class="note">文件只在本地局域网传输。相同名称的文件会自动改名，网页不提供删除功能。</p>
</section></main><script>
const currentDir={relative_js};
const status=document.getElementById('status');
document.getElementById('files').addEventListener('change',async e=>{{
 const files=[...e.target.files]; let done=0;
 for(const file of files){{
  status.textContent=`正在上传 ${{file.name}}（${{done+1}}/${{files.length}}）…`;
  const q=new URLSearchParams({{dir:currentDir,name:file.name}});
  try{{const r=await fetch('/upload?'+q,{{method:'PUT',body:file}});const data=await r.json();if(!r.ok)throw new Error(data.error||'上传失败');done++;}}
  catch(err){{status.textContent='上传失败：'+err.message;return;}}
 }}
 status.textContent=`已上传 ${{done}} 个文件。`;setTimeout(()=>location.reload(),500);
}});
document.getElementById('mkdir').addEventListener('click',async()=>{{
 const name=prompt('新文件夹名称');if(!name)return;
 const q=new URLSearchParams({{dir:currentDir,name}});
 const r=await fetch('/mkdir?'+q,{{method:'POST'}});const data=await r.json();
 if(!r.ok){{status.textContent='创建失败：'+(data.error||'未知错误');return}}location.reload();
}});
</script></body></html>"""
        self._send_bytes(HTTPStatus.OK, page.encode("utf-8"), "text/html; charset=utf-8")

    def _reserve_target(self, directory: Path, filename: str) -> tuple[Path, Path]:
        stem, suffix = Path(filename).stem, Path(filename).suffix
        with self.server.file_lock:
            for index in range(10_000):
                candidate_name = filename if index == 0 else f"{stem} ({index}){suffix}"
                candidate = directory / candidate_name
                try:
                    descriptor = os.open(candidate, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                except FileExistsError:
                    continue
                os.close(descriptor)
                temporary = directory / f".airmirror-upload-{secrets.token_hex(8)}.part"
                return candidate, temporary
        raise OSError("无法为文件生成不重复的名称。")

    def _receive_upload(self, query: dict[str, list[str]]) -> None:
        try:
            directory, _ = self._directory(query)
            filename = safe_filename(self._query_value(query, "name"))
            length_text = self.headers.get("Content-Length", "")
            if not length_text.isdigit():
                raise ValueError("上传请求缺少文件大小。")
            length = int(length_text)
            if length > MAX_UPLOAD_BYTES:
                raise ValueError("单个文件不能超过 20 GB。")
            target, temporary = self._reserve_target(directory, filename)
        except (OSError, ValueError) as error:
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": str(error) or "上传目标无效。"})
            return

        remaining = length
        try:
            with temporary.open("wb") as output:
                while remaining:
                    chunk = self.rfile.read(min(CHUNK_SIZE, remaining))
                    if not chunk:
                        raise ConnectionError("上传在完成前中断。")
                    output.write(chunk)
                    remaining -= len(chunk)
            temporary.replace(target)
        except (OSError, ConnectionError) as error:
            temporary.unlink(missing_ok=True)
            target.unlink(missing_ok=True)
            self._send_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": str(error) or "无法保存文件。"})
            return

        self._log_event(f"快传收到文件：{target.name}（{human_size(length)}）")
        self._send_json(HTTPStatus.CREATED, {"name": target.name, "size": length})

    def _create_folder(self, query: dict[str, list[str]]) -> None:
        try:
            directory, _ = self._directory(query)
            name = safe_filename(self._query_value(query, "name"))
            target = safe_path(directory, name, must_exist=False)
            target.mkdir()
        except (OSError, ValueError) as error:
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": str(error) or "无法创建文件夹。"})
            return
        self._log_event(f"快传创建文件夹：{target.name}")
        self._send_json(HTTPStatus.CREATED, {"name": target.name})

    def _serve_download(self, query: dict[str, list[str]], *, head_only: bool) -> None:
        try:
            target = safe_path(self.server.share_root, self._query_value(query, "path"))
            if not target.is_file():
                raise FileNotFoundError(target)
            size = target.stat().st_size
        except (OSError, ValueError):
            self._send_text(HTTPStatus.NOT_FOUND, "文件不存在。", head_only=head_only)
            return

        start, end = 0, max(0, size - 1)
        status = HTTPStatus.OK
        range_header = self.headers.get("Range")
        if range_header and size:
            match = re.fullmatch(r"bytes=(\d*)-(\d*)", range_header.strip())
            if not match:
                self.send_error(HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE)
                return
            left, right = match.groups()
            if left:
                start = int(left)
                end = int(right) if right else size - 1
            elif right:
                suffix_length = int(right)
                start = max(0, size - suffix_length)
                end = size - 1
            if start >= size or end < start:
                self.send_response(HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE)
                self.send_header("Content-Range", f"bytes */{size}")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            end = min(end, size - 1)
            status = HTTPStatus.PARTIAL_CONTENT

        length = 0 if size == 0 else end - start + 1
        content_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(length))
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Disposition", f"inline; filename*=UTF-8''{quote(target.name)}")
        if status == HTTPStatus.PARTIAL_CONTENT:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.end_headers()
        if head_only or not length:
            return
        with target.open("rb") as source:
            source.seek(start)
            remaining = length
            while remaining:
                chunk = source.read(min(CHUNK_SIZE, remaining))
                if not chunk:
                    break
                self.wfile.write(chunk)
                remaining -= len(chunk)

    def _security_headers(self) -> None:
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; img-src 'self' data:",
        )

    def _send_bytes(self, status: HTTPStatus, body: bytes, content_type: str, *, head_only: bool = False) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self._security_headers()
        self.end_headers()
        if not head_only:
            self.wfile.write(body)

    def _send_text(self, status: HTTPStatus, message: str, *, head_only: bool = False) -> None:
        self._send_bytes(status, message.encode("utf-8"), "text/plain; charset=utf-8", head_only=head_only)

    def _send_json(self, status: HTTPStatus, payload: dict[str, object]) -> None:
        self._send_bytes(status, json.dumps(payload, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

    def _log_event(self, message: str) -> None:
        callback = self.server.log_callback
        if callback:
            callback(message)


class QuickShareServer:
    def __init__(
        self,
        root: Path,
        host: str,
        port: int,
        log_callback: Callable[[str], None] | None = None,
        token: str | None = None,
    ) -> None:
        self.root = root.expanduser().resolve()
        self.host = host
        self.port = port
        self.token = token or f"{secrets.randbelow(1_000_000):06d}"
        self.log_callback = log_callback
        self._server: QuickShareHTTPServer | None = None
        self._thread: threading.Thread | None = None

    @property
    def url(self) -> str:
        return f"http://{self.host}:{self.port}/"

    @property
    def access_code(self) -> str:
        return self.token

    @property
    def running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def start(self) -> None:
        if self.running:
            return
        self.root.mkdir(parents=True, exist_ok=True)
        self._server = QuickShareHTTPServer((self.host, self.port), self.root, self.token, self.log_callback)
        self.port = int(self._server.server_address[1])
        self._thread = threading.Thread(target=self._server.serve_forever, name="AirMirrorQuickShare", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        server, thread = self._server, self._thread
        self._server = None
        self._thread = None
        if server:
            server.shutdown()
            server.server_close()
        if thread and thread is not threading.current_thread():
            thread.join(timeout=3)
