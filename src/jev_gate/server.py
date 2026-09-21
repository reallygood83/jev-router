import json
import os
import select
import socket
from collections import deque
from datetime import datetime, timezone
from http.client import HTTPConnection
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import ClassVar, cast
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from jev_router.jev import JevUnavailable

from . import GATE_VERSION
from .autostart import disable as autostart_disable
from .autostart import enable as autostart_enable
from .autostart import status as autostart_status
from .classify import classify_task
from .decide import decide
from .extract import extract_task, thread_key
from .install import install_mcp, install_skill, install_status
from .pack import load_pack, save_pack
from .secrets import key_is_set, save_key
from .ws import encode_frame, pop_frame, rewrite_model_payload


HOP_BY_HOP = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
    "transfer-encoding",
    "upgrade",
    "proxy-connection",
}
PATCH_PATHS = {"/v1/chat/completions", "/v1/responses"}
STATIC_DIR = Path(__file__).resolve().parent / "static"


class GateState:
    def __init__(self, upstream="http://127.0.0.1:10100", pack_path=None):
        parsed = urlparse(upstream)
        self.upstream_host = parsed.hostname or "127.0.0.1"
        self.upstream_port = parsed.port or 80
        self.pack_path = pack_path
        self.pack = load_pack(pack_path)
        self.sticky = {}
        self.events = deque(maxlen=20)
        self.catalog = set()
        self.reasoning_support = {}

    def reload_pack(self):
        self.pack = load_pack(self.pack_path)
        return self.pack

    def record(self, decision):
        item = {
            "at": datetime.now(timezone.utc).strftime("%H:%M:%S"),
            "status": decision.get("status"),
            "role": decision.get("role"),
            "confidence": round(float(decision.get("confidence") or 0), 2),
            "model_in": decision.get("model_in"),
            "model_out": decision.get("model_out"),
            "reasoning_effort": decision.get("reasoning_effort") or "",
        }
        self.events.appendleft(item)
        return item


def _filter_headers(headers):
    out = {}
    for key, value in headers.items():
        name = str(key)
        if name.lower() in HOP_BY_HOP or name.lower() == "host":
            continue
        out[name] = value
    return out


class GateHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    state: ClassVar[GateState]
    timeout = 600

    def log_message(self, format, *args):
        print("[jev-gate] " + (format % args))

    def _cors(self):
        origin = self.headers.get("Origin") or "http://127.0.0.1:10115"
        if origin.startswith("http://127.0.0.1") or origin.startswith("http://localhost"):
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Access-Control-Allow-Headers", self.headers.get("Access-Control-Request-Headers") or "*")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, PATCH, DELETE, OPTIONS")
            self.send_header("Access-Control-Expose-Headers", "X-Jev-Gate, X-Jev-Gate-Version, X-Jev-Role, X-Jev-Confidence, X-Jev-Model-In, X-Jev-Model-Out")

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.end_headers()

    def _route(self):
        return self.path.split("?", 1)[0]

    def do_GET(self):
        path = self._route()
        if path in {"/", "/index.html"}:
            return self._serve_index()
        if path == "/favicon.ico":
            self.send_response(204)
            self.end_headers()
            return
        if path == "/api/pack":
            return self._json(200, self.state.reload_pack())
        if path == "/api/events":
            return self._json(200, {"events": list(self.state.events)})
        if path == "/api/status":
            return self._json(200, self._status())
        if path == "/api/secrets":
            return self._json(200, {"jev_key_set": key_is_set()})
        if path == "/api/install":
            return self._json(200, install_status())
        if path == "/api/autostart":
            return self._json(200, autostart_status())
        if path.startswith("/api/"):
            return self._json(404, {"error": "unknown api"})
        if self._wants_websocket(path):
            return self._websocket_tunnel()
        if path.rstrip("/") == "/v1/responses":
            self.send_response(426, "Upgrade Required")
            self.send_header("Upgrade", "websocket")
            self.send_header("Connection", "Upgrade")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        return self._proxy()

    def do_PUT(self):
        path = self._route()
        if path == "/api/pack":
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length) if length else b"{}"
            try:
                payload = json.loads(raw.decode("utf-8"))
            except ValueError:
                return self._json(400, {"error": "invalid json"})
            try:
                pack = save_pack(payload, self.state.pack_path)
            except OSError as exc:
                return self._json(500, {"error": str(exc)})
            self.state.pack = pack
            return self._json(200, pack)
        if path == "/api/secrets":
            return self._save_secrets()
        if path.startswith("/api/"):
            return self._json(404, {"error": "unknown api"})
        return self._proxy()

    def do_POST(self):
        path = self._route()
        if path == "/api/secrets":
            return self._save_secrets()
        if path == "/api/install":
            return self._install()
        if path == "/api/autostart":
            return self._autostart()
        if path.startswith("/api/"):
            return self._json(404, {"error": "unknown api"})
        if self._wants_websocket(path):
            return self._websocket_tunnel()
        if path in PATCH_PATHS:
            return self._proxy(patch=True)
        return self._proxy()

    def do_PATCH(self):
        return self._proxy()

    def do_DELETE(self):
        return self._proxy()

    def _serve_index(self):
        html = (STATIC_DIR / "index.html").read_bytes()
        self.send_response(200)
        self._cors()
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(html)))
        self.end_headers()
        self.wfile.write(html)

    def _json(self, code, payload):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self._cors()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _status(self):
        info = {
            "opencodex_ok": False,
            "opencodex_version": "",
            "jev_key_set": key_is_set(),
            "gate_version": GATE_VERSION,
            "http": "1.1",
        }
        try:
            with urlopen(Request(f"http://{self.state.upstream_host}:{self.state.upstream_port}/healthz"), timeout=2) as res:
                payload = json.loads(res.read().decode("utf-8"))
            info["opencodex_ok"] = True
            info["opencodex_version"] = str(payload.get("version") or "")
        except Exception:
            pass
        return info

    def _refresh_catalog(self):
        try:
            with urlopen(Request(f"http://{self.state.upstream_host}:{self.state.upstream_port}/v1/models"), timeout=3) as res:
                payload = json.loads(res.read().decode("utf-8"))
            items = payload.get("data") or []
            self.state.catalog = {str(item.get("id")) for item in items if isinstance(item, dict) and item.get("id")}
            support = {}
            for item in items:
                if not isinstance(item, dict) or not item.get("id"):
                    continue
                value = item.get("supports_reasoning_effort")
                capabilities = item.get("capabilities")
                if value is None and isinstance(capabilities, dict):
                    value = capabilities.get("supports_reasoning")
                if isinstance(value, bool):
                    support[str(item["id"])] = value
            self.state.reasoning_support = support
        except Exception:
            pass

    def _classify_and_patch(self, raw):
        pack = self.state.reload_pack()
        try:
            body = json.loads(raw.decode("utf-8")) if raw else {}
        except ValueError:
            return raw, {"status": "pass", "role": "-", "confidence": 0, "model_in": "", "model_out": "", "reason": "non-json body"}
        if not isinstance(body, dict):
            return raw, {"status": "pass", "role": "-", "confidence": 0, "model_in": "", "model_out": "", "reason": "non-object body"}
        incoming = str(body.get("model") or "")
        key = thread_key(self.headers)
        stored = self.state.sticky.get(key) if key else ""
        if isinstance(stored, dict):
            sticky, sticky_effort = str(stored.get("model") or ""), str(stored.get("effort") or "")
        else:
            sticky, sticky_effort = str(stored or ""), ""
        task = extract_task(body)
        max_chars = int(str(pack.get("max_task_chars") or 2000))
        task = task[:max_chars]
        error = ""
        classification = None
        if pack.get("enabled") is True and incoming == pack.get("home_model") and not sticky and task:
            try:
                classification = classify_task(task, pack, timeout=3)
            except (JevUnavailable, ValueError) as exc:
                error = str(exc)
        decision = decide(
            pack,
            incoming,
            classification,
            sticky_model=sticky,
            sticky_effort=sticky_effort,
            error=error,
        )
        if decision["status"] == "rewrite":
            if not self.state.catalog:
                self._refresh_catalog()
            if self.state.catalog and decision["model_out"] not in self.state.catalog:
                decision = decide(pack, incoming, None, error="rewrite target not in catalog")
                decision["status"] = "pass"
                decision["model_out"] = incoming
                decision["reason"] = "rewrite target not in catalog"
            else:
                if decision.get("reasoning_effort") and self.state.reasoning_support.get(str(decision["model_out"])) is False:
                    decision["reasoning_effort"] = ""
                    decision["reason"] += "; target does not advertise reasoning support"
                raw = self._apply_decision(body, decision)
                if key:
                    self.state.sticky[key] = {
                        "model": decision["model_out"],
                        "effort": decision.get("reasoning_effort") or "",
                    }
        elif decision["status"] == "sticky" and key:
            raw = self._apply_decision(body, decision)
        self.state.record(decision)
        return raw, decision

    def _apply_decision(self, body, decision):
        body["model"] = decision["model_out"]
        effort = str(decision.get("reasoning_effort") or "").strip()
        if effort:
            if self._route() == "/v1/responses":
                reasoning = body.get("reasoning")
                if not isinstance(reasoning, dict):
                    reasoning = {}
                    body["reasoning"] = reasoning
                reasoning["effort"] = effort
                body.pop("reasoning_effort", None)
            else:
                body["reasoning_effort"] = effort
        return json.dumps(body, ensure_ascii=False).encode("utf-8")

    def _save_secrets(self):
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            payload = json.loads(raw.decode("utf-8"))
        except ValueError:
            return self._json(400, {"error": "invalid json"})
        if not isinstance(payload, dict):
            return self._json(400, {"error": "invalid json"})
        try:
            save_key(payload.get("typesafe_api_key"), clear=bool(payload.get("clear")))
        except OSError as exc:
            return self._json(500, {"error": str(exc), "jev_key_set": False})
        return self._json(200, {"jev_key_set": key_is_set()})

    def _install(self):
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            payload = json.loads(raw.decode("utf-8"))
        except ValueError:
            payload = {}
        kind = str((payload or {}).get("kind") or "skill")
        try:
            if kind == "mcp":
                result = install_mcp()
            else:
                result = install_skill()
        except Exception as exc:
            return self._json(500, {"ok": False, "error": str(exc)})
        return self._json(200, {**result, "status": install_status()})

    def _autostart(self):
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            payload = json.loads(raw.decode("utf-8"))
        except ValueError:
            payload = {}
        enabled = bool((payload or {}).get("enabled"))
        server = cast(ThreadingHTTPServer, self.server)
        address = server.server_address
        host, port = str(address[0]), int(address[1])
        upstream = f"http://{self.state.upstream_host}:{self.state.upstream_port}"
        try:
            if enabled:
                result = autostart_enable(host=host or "127.0.0.1", port=port, upstream=upstream)
            else:
                result = autostart_disable()
        except OSError as exc:
            return self._json(500, {"ok": False, "error": str(exc)})
        return self._json(200, result)

    def _read_body(self):
        encoding = (self.headers.get("Transfer-Encoding") or "").lower()
        if "chunked" in encoding:
            chunks = []
            while True:
                size_line = self.rfile.readline()
                if not size_line:
                    break
                size_text = size_line.split(b";", 1)[0].strip()
                try:
                    size = int(size_text, 16)
                except ValueError:
                    break
                if size == 0:
                    self.rfile.readline()
                    break
                chunks.append(self.rfile.read(size))
                self.rfile.read(2)
            return b"".join(chunks)
        length = int(self.headers.get("Content-Length") or 0)
        return self.rfile.read(length) if length else b""

    def _wants_websocket(self, path=None):
        del path
        if self.headers.get("Sec-WebSocket-Key"):
            return True
        upgrade = (self.headers.get("Upgrade") or "").lower()
        return "websocket" in upgrade

    def _rewrite_client_ws(self, data, buf):
        buf.extend(data)
        out = b""
        while True:
            frame, rest = pop_frame(buf)
            if frame is None:
                break
            buf[:] = rest
            if frame["opcode"] == 1 and frame["fin"]:
                def rewriter(body):
                    encoded, _decision = self._classify_and_patch(json.dumps(body).encode("utf-8"))
                    try:
                        return json.loads(encoded.decode("utf-8"))
                    except Exception:
                        return body
                payload = rewrite_model_payload(frame["payload"], rewriter)
                out += encode_frame(1, payload, masked=True, fin=True)
            else:
                out += frame["original"]
        return out

    def _websocket_tunnel(self):
        upstream = socket.create_connection(
            (self.state.upstream_host, self.state.upstream_port),
            timeout=10,
        )
        lines = [f"{self.command} {self.path} HTTP/1.1"]
        host = f"{self.state.upstream_host}:{self.state.upstream_port}"
        lines.append(f"Host: {host}")
        for key, value in self.headers.items():
            if str(key).lower() == "host":
                continue
            lines.append(f"{key}: {value}")
        upstream.sendall(("\r\n".join(lines) + "\r\n\r\n").encode("iso-8859-1"))
        leftover = b""
        try:
            buf = getattr(self.rfile, "_buffer", None)
            if buf:
                leftover = bytes(buf)
                if hasattr(buf, "clear"):
                    buf.clear()
        except Exception:
            leftover = b""
        client_buf = bytearray()
        if leftover:
            rewritten = self._rewrite_client_ws(leftover, client_buf)
            if rewritten:
                upstream.sendall(rewritten)
        print("[jev-gate] websocket", self.command, self.path)
        client = self.connection
        sockets = [client, upstream]
        try:
            while True:
                readable, _, failed = select.select(sockets, [], sockets, 600)
                if failed:
                    break
                if not readable:
                    continue
                for sock in readable:
                    data = sock.recv(65536)
                    if not data:
                        return
                    if sock is client:
                        data = self._rewrite_client_ws(data, client_buf)
                        if data:
                            upstream.sendall(data)
                    else:
                        client.sendall(data)
        finally:
            try:
                upstream.close()
            except OSError:
                pass
            self.close_connection = True

    def _proxy(self, patch=False):
        raw = self._read_body() if self.command in {"POST", "PUT", "PATCH"} else b""
        if patch:
            raw, _decision = self._classify_and_patch(raw)
        upstream = socket.create_connection(
            (self.state.upstream_host, self.state.upstream_port),
            timeout=10,
        )
        lines = [f"{self.command} {self.path} HTTP/1.1"]
        lines.append(f"Host: {self.state.upstream_host}:{self.state.upstream_port}")
        for key, value in self.headers.items():
            lower = str(key).lower()
            if lower in {"host", "content-length", "transfer-encoding", "connection"}:
                continue
            lines.append(f"{key}: {value}")
        if raw:
            lines.append(f"Content-Length: {len(raw)}")
        lines.append("Connection: close")
        upstream.sendall(("\r\n".join(lines) + "\r\n\r\n").encode("iso-8859-1") + (raw or b""))
        client = self.connection
        self.close_connection = True
        try:
            while True:
                data = upstream.recv(65536)
                if not data:
                    break
                client.sendall(data)
        finally:
            try:
                upstream.close()
            except OSError:
                pass


def make_server(host="127.0.0.1", port=10115, upstream="http://127.0.0.1:10100", pack_path=None):
    state = GateState(upstream=upstream, pack_path=pack_path)

    class BoundHandler(GateHandler):
        pass

    BoundHandler.state = state

    class ReuseServer(ThreadingHTTPServer):
        allow_reuse_address = True

    httpd = ReuseServer((host, port), BoundHandler)
    return httpd, state
