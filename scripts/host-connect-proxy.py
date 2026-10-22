#!/usr/bin/env python3
"""Tiny HTTP CONNECT proxy that tunnels via the host network stack.

Docker Desktop on some networks cannot complete TLS to Binance (SSL
WRONG_VERSION_NUMBER), while the macOS host can. Point collector at
http://host.docker.internal:<port> so REST/WS egress uses the host path.

Usage:
  python3 scripts/host-connect-proxy.py [port]   # default 18080
"""

from __future__ import annotations

import os
import select
import socket
import sys
import threading

LISTEN_HOST = "0.0.0.0"
DEFAULT_PORT = 18080


def _tunnel(a: socket.socket, b: socket.socket) -> None:
    try:
        while True:
            readable, _, _ = select.select([a, b], [], [], 120)
            if not readable:
                break
            for sock in readable:
                other = b if sock is a else a
                data = sock.recv(65536)
                if not data:
                    return
                other.sendall(data)
    except OSError:
        pass
    finally:
        for sock in (a, b):
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                sock.close()
            except OSError:
                pass


def _handle(client: socket.socket) -> None:
    upstream: socket.socket | None = None
    try:
        client.settimeout(30)
        buf = b""
        while b"\r\n\r\n" not in buf:
            chunk = client.recv(4096)
            if not chunk:
                return
            buf += chunk
            if len(buf) > 65536:
                client.sendall(b"HTTP/1.1 400 Bad Request\r\nConnection: close\r\n\r\n")
                return
        head = buf.split(b"\r\n\r\n", 1)[0]
        line = head.split(b"\r\n", 1)[0].decode("latin1", "replace")
        parts = line.split()
        if len(parts) < 2 or parts[0].upper() != "CONNECT":
            client.sendall(b"HTTP/1.1 405 Method Not Allowed\r\nConnection: close\r\n\r\n")
            return
        host_port = parts[1]
        if ":" in host_port:
            host, port_s = host_port.rsplit(":", 1)
            port = int(port_s)
        else:
            host, port = host_port, 443
        upstream = socket.create_connection((host, port), timeout=20)
        client.sendall(b"HTTP/1.1 200 Connection Established\r\n\r\n")
        client.settimeout(None)
        upstream.settimeout(None)
        threading.Thread(target=_tunnel, args=(client, upstream), daemon=True).start()
        _tunnel(upstream, client)
        upstream = None
        client = None  # type: ignore[assignment]
    except Exception as exc:
        try:
            client.sendall(
                f"HTTP/1.1 502 Bad Gateway\r\nConnection: close\r\n\r\n{exc}\n".encode()
            )
        except OSError:
            pass
    finally:
        if upstream is not None:
            try:
                upstream.close()
            except OSError:
                pass
        if client is not None:
            try:
                client.close()
            except OSError:
                pass


def main() -> None:
    port = int(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_PORT
    # Double-fork so Cursor/IDE process-group teardown does not kill the proxy.
    if os.environ.get("EL_PROXY_FOREGROUND") != "1":
        if os.fork() > 0:
            return
        os.setsid()
        if os.fork() > 0:
            os._exit(0)
        for fd in (0, 1, 2):
            try:
                os.close(fd)
            except OSError:
                pass
        log = open("/tmp/el-host-proxy.log", "a", buffering=1)
        os.dup2(log.fileno(), 1)
        os.dup2(log.fileno(), 2)

    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind((LISTEN_HOST, port))
    srv.listen(256)
    print(f"host-connect-proxy listening on {LISTEN_HOST}:{port}", flush=True)
    while True:
        try:
            conn, _addr = srv.accept()
            threading.Thread(target=_handle, args=(conn,), daemon=True).start()
        except Exception as exc:
            print(f"accept error: {exc}", flush=True)


if __name__ == "__main__":
    main()
