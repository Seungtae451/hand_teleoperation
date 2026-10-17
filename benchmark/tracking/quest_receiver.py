"""HTTPS/WSS receiver modeled on the existing humanoid bridge, independent of Isaac."""

import asyncio
import json
import ssl
import time
import uuid
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from websockets.asyncio.server import serve
from websockets.datastructures import Headers
from websockets.exceptions import ConnectionClosed
from websockets.http11 import Response

from benchmark.tracking.receiver_state import ReceiverState
from benchmark.tracking.webxr_protocol import protocol_description

WEB_ROOT = Path(__file__).with_name("web")


def tls_context(cert, key):
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.load_cert_chain(str(cert), str(key))
    return context


def _json(text):
    def invalid(constant):
        raise ValueError(f"Nonfinite JSON constant: {constant}")

    return json.loads(text, parse_constant=invalid)


class QuestReceiver:
    def __init__(self, state=None):
        self.state = state if state is not None else ReceiverState()
        self.clients = set()
        self.source = None
        self.server = self.status_task = None

    def http_request(self, connection, request):
        url = urlsplit(request.path)
        if url.path == "/ws":
            role = parse_qs(url.query).get("role", ["viewer"])[0]
            if role not in ("source", "viewer"):
                return connection.respond(400, "Unknown connection role\n")
            origin = request.headers.get("Origin")
            if origin and origin != f"https://{request.headers.get('Host')}":
                return connection.respond(403, "Use the page served by this receiver\n")
            return None
        if url.path == "/status":
            body = json.dumps(self.state.status(time.monotonic()), allow_nan=False).encode()
            content_type = "application/json"
        elif url.path == "/protocol.json":
            body = json.dumps(protocol_description()).encode()
            content_type = "application/json"
        else:
            files = {
                "/": ("index.html", "text/html; charset=utf-8"),
                "/client.js": ("client.js", "text/javascript; charset=utf-8"),
                "/style.css": ("style.css", "text/css; charset=utf-8"),
            }
            if url.path not in files:
                return connection.respond(404, "Not found\n")
            filename, content_type = files[url.path]
            body = (WEB_ROOT / filename).read_bytes()
        headers = Headers(
            {
                "Content-Type": content_type,
                "Content-Length": str(len(body)),
                "Cache-Control": "no-store",
            }
        )
        return Response(200, "OK", headers, body)

    async def handler(self, connection):
        role = parse_qs(urlsplit(connection.request.path).query).get("role", ["viewer"])[0]
        if len(self.clients) >= 8:
            await connection.close(code=1013, reason="Receiver viewer limit reached")
            return
        session_id = uuid.uuid4().hex
        if role == "source":
            if self.source is not None:
                await connection.send(
                    json.dumps({"type": "error", "message": "Another Quest source is connected"})
                )
                await connection.close(code=1008, reason="Source already connected")
                return
            self.source = connection
            self.state.connect(session_id, time.monotonic())
        self.clients.add(connection)
        try:
            await connection.send(
                json.dumps(
                    {
                        "type": "session",
                        "session_id": session_id,
                        "role": role,
                        "protocol": protocol_description(),
                    }
                )
            )
            async for message in connection:
                if role != "source":
                    await connection.close(code=1008, reason="Viewers cannot send tracking input")
                    break
                rejected_before = self.state.rejected_packets
                try:
                    if not isinstance(message, str):
                        raise ValueError("Expected a UTF-8 JSON text packet")
                    self.state.accept(_json(message), session_id, time.monotonic())
                except (ValueError, TypeError) as exc:
                    if self.state.rejected_packets == rejected_before:
                        self.state.rejected_packets += 1
                        self.state.emit(
                            {
                                "event": "rejected_packet",
                                "reason": str(exc),
                                "receive_time_s": time.monotonic(),
                            }
                        )
                    await connection.send(json.dumps({"type": "error", "message": str(exc)}))
        except ConnectionClosed:
            pass
        finally:
            self.clients.discard(connection)
            if self.source is connection:
                self.state.disconnect(time.monotonic())
                self.source = None

    async def status_loop(self):
        while True:
            status = json.dumps(self.state.status(time.monotonic()), allow_nan=False)
            for connection in list(self.clients):
                try:
                    await asyncio.wait_for(connection.send(status), timeout=0.15)
                except (ConnectionClosed, asyncio.TimeoutError):
                    self.clients.discard(connection)
                    await connection.close(code=1013, reason="Status consumer is too slow")
            await asyncio.sleep(0.1)

    async def start(self, host="127.0.0.1", port=0, context=None):
        self.server = await serve(
            self.handler,
            host,
            port,
            ssl=context,
            process_request=self.http_request,
            max_size=32768,
            max_queue=2,
            compression=None,
            ping_interval=10,
            ping_timeout=10,
            close_timeout=1,
        )
        self.status_task = asyncio.create_task(self.status_loop())
        return self.server.sockets[0].getsockname()[1]

    async def close(self):
        if self.status_task:
            self.status_task.cancel()
            try:
                await self.status_task
            except asyncio.CancelledError:
                pass
        if self.server:
            self.server.close()
            await self.server.wait_closed()
