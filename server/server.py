#!/usr/bin/env python3
"""Static file server for notazizelse.xyz and every <slug>.notazizelse.xyz.

Routes by Host header (Cloudflare Tunnel passes the original hostname through):
    notazizelse.xyz          -> <root>/apex/
    www.notazizelse.xyz      -> 301 to notazizelse.xyz
    <slug>.notazizelse.xyz   -> <root>/p/<slug>/
    anything else            -> apex 404 page

Standard library only. Serves <file>.gz instead of <file> when the client accepts gzip
(make them with --precompress). /healthz answers "ok" for sitectl.

    python3 server.py --root ~/site/public --domain notazizelse.xyz --port 8795
    python3 server.py --root dist/public --domain localhost --port 8795      (local preview)
    python3 server.py --precompress ~/site/public
"""
import argparse
import email.utils
import gzip
import mimetypes
import os
import posixpath
import re
import shutil
import sys
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote, urlsplit

TYPES = {
    ".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8", ".js": "text/javascript; charset=utf-8",
    ".mjs": "text/javascript; charset=utf-8", ".json": "application/json; charset=utf-8",
    ".webmanifest": "application/manifest+json; charset=utf-8", ".svg": "image/svg+xml", ".webp": "image/webp",
    ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".gif": "image/gif", ".ico": "image/x-icon",
    ".wasm": "application/wasm", ".pck": "application/octet-stream", ".txt": "text/plain; charset=utf-8",
    ".xml": "application/xml; charset=utf-8", ".csv": "text/csv; charset=utf-8", ".zip": "application/zip",
    ".pdf": "application/pdf", ".woff2": "font/woff2", ".woff": "font/woff", ".mp3": "audio/mpeg", ".ogg": "audio/ogg",
    ".wav": "audio/wav", ".mp4": "video/mp4",
}
# Text-ish files revalidate every time (cheap 304s); binaries cache for an hour.
REVALIDATE = {".html", ".css", ".js", ".mjs", ".json", ".webmanifest", ".xml", ".txt"}
COMPRESSIBLE = {".html", ".css", ".js", ".mjs", ".json", ".webmanifest", ".svg", ".xml", ".txt", ".csv", ".wasm", ".pck"}
SLUG_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")


class Handler(BaseHTTPRequestHandler):
    server_version = "notazizelse"
    sys_version = ""
    protocol_version = "HTTP/1.1"

    root = ""      # set in main()
    domain = ""

    # ---- routing ----
    def site_root(self):
        host = (self.headers.get("Host") or "").split(":")[0].strip().lower().rstrip(".")
        d = self.domain
        if host in (d, "127.0.0.1", "localhost") or not host:
            return os.path.join(self.root, "apex")
        if host == "www." + d:
            return "www"
        if host.endswith("." + d):
            slug = host[: -len(d) - 1]
            if SLUG_RE.match(slug):
                path = os.path.join(self.root, "p", slug)
                if os.path.isdir(path):
                    return path
        return None

    def do_HEAD(self):
        self.handle_request(head=True)

    def do_GET(self):
        self.handle_request(head=False)

    def handle_request(self, head):
        url = urlsplit(self.path)
        if url.path == "/healthz":
            return self.send_bytes(HTTPStatus.OK, b"ok\n", "text/plain; charset=utf-8", head, cache="no-store")
        site = self.site_root()
        if site == "www":
            loc = f"https://{self.domain}{self.path}"
            return self.send_bytes(HTTPStatus.MOVED_PERMANENTLY, b"", "text/plain", head, extra={"Location": loc})
        if site is None:
            return self.not_found(None, head)

        rel = posixpath.normpath(unquote(url.path))
        parts = [p for p in rel.split("/") if p and p not in (".", "..")]
        full = os.path.realpath(os.path.join(site, *parts))
        site_real = os.path.realpath(site)
        if full != site_real and not full.startswith(site_real + os.sep):
            return self.not_found(site, head)
        if os.path.isdir(full):
            if not url.path.endswith("/"):
                loc = url.path + "/" + (("?" + url.query) if url.query else "")
                return self.send_bytes(HTTPStatus.MOVED_PERMANENTLY, b"", "text/plain", head, extra={"Location": loc})
            full = os.path.join(full, "index.html")
        if not os.path.isfile(full):
            return self.not_found(site, head)
        self.send_file(full, head)

    # ---- responses ----
    def common_headers(self):
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "strict-origin-when-cross-origin")

    def send_bytes(self, status, data, ctype, head, cache="no-cache", extra=None):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", cache)
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.common_headers()
        self.end_headers()
        if not head and data:
            self.wfile.write(data)

    def not_found(self, site, head):
        for candidate in ([os.path.join(site, "404.html")] if site else []) + [os.path.join(self.root, "apex", "404.html")]:
            if os.path.isfile(candidate):
                with open(candidate, "rb") as fh:
                    return self.send_bytes(HTTPStatus.NOT_FOUND, fh.read(), TYPES[".html"], head)
        self.send_bytes(HTTPStatus.NOT_FOUND, b"not found\n", "text/plain; charset=utf-8", head)

    def send_file(self, path, head):
        ext = os.path.splitext(path)[1].lower()
        ctype = TYPES.get(ext) or mimetypes.guess_type(path)[0] or "application/octet-stream"
        st = os.stat(path)
        etag = f'"{st.st_mtime_ns:x}-{st.st_size:x}"'
        cache = "no-cache" if ext in REVALIDATE or os.path.basename(path) == "sw.js" else "public, max-age=3600"
        if self.headers.get("If-None-Match") == etag:
            self.send_response(HTTPStatus.NOT_MODIFIED)
            self.send_header("ETag", etag)
            self.send_header("Cache-Control", cache)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return

        send_path, encoding = path, None
        if "gzip" in (self.headers.get("Accept-Encoding") or "") and os.path.isfile(path + ".gz"):
            gz = path + ".gz"
            if os.stat(gz).st_mtime_ns >= st.st_mtime_ns:
                send_path, encoding = gz, "gzip"
        size = os.stat(send_path).st_size

        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(size))
        self.send_header("Last-Modified", email.utils.formatdate(st.st_mtime, usegmt=True))
        self.send_header("ETag", etag)
        self.send_header("Cache-Control", cache)
        if ext in COMPRESSIBLE:
            self.send_header("Vary", "Accept-Encoding")
        if encoding:
            self.send_header("Content-Encoding", encoding)
        if os.path.basename(path) == "sw.js":
            self.send_header("Service-Worker-Allowed", "/")
        self.common_headers()
        self.end_headers()
        if head:
            return
        with open(send_path, "rb") as fh:
            shutil.copyfileobj(fh, self.wfile, 256 * 1024)

    # ---- quieter logging ----
    def log_message(self, fmt, *args):
        if self.path == "/healthz":
            return
        host = (self.headers.get("Host") or "-") if hasattr(self, "headers") and self.headers else "-"
        sys.stdout.write(f"{time.strftime('%Y-%m-%dT%H:%M:%S')} {host} {fmt % args}\n")
        sys.stdout.flush()


class Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def handle_error(self, request, client_address):
        exc = sys.exc_info()[1]
        if isinstance(exc, (BrokenPipeError, ConnectionResetError, TimeoutError)):
            return
        super().handle_error(request, client_address)


def precompress(root):
    made = 0
    for dirpath, _, files in os.walk(root):
        for name in files:
            path = os.path.join(dirpath, name)
            ext = os.path.splitext(name)[1].lower()
            if ext not in COMPRESSIBLE or os.path.getsize(path) < 1024:
                continue
            gz = path + ".gz"
            if os.path.isfile(gz) and os.stat(gz).st_mtime_ns >= os.stat(path).st_mtime_ns:
                continue
            with open(path, "rb") as fh:
                data = fh.read()
            packed = gzip.compress(data, compresslevel=9 if len(data) < 2_000_000 else 6, mtime=0)
            if len(packed) < len(data) * 0.9:
                with open(gz, "wb") as fh:
                    fh.write(packed)
                made += 1
    print(f"precompressed {made} files under {root}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "public"))
    ap.add_argument("--domain", default="notazizelse.xyz")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=int(os.environ.get("PORT", 8795)))
    ap.add_argument("--precompress", metavar="DIR")
    args = ap.parse_args()
    if args.precompress:
        return precompress(args.precompress)
    Handler.root = os.path.abspath(os.path.expanduser(args.root))
    Handler.domain = args.domain.lower()
    if not os.path.isdir(os.path.join(Handler.root, "apex")):
        sys.exit(f"{Handler.root}/apex not found")
    httpd = Server((args.host, args.port), Handler)
    print(f"serving {Handler.root} for {Handler.domain} on http://{args.host}:{args.port}", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
