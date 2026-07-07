#coding:gbk
r"""Minimal QMT Python probe for Hermes internal HTTP.

Paste this into a temporary QMT Python model. It does not trade. It only:
1. writes D:\HermesQMTBridge\audit\probe_started.txt from init()
2. starts a tiny raw HTTP server on 127.0.0.1:18767
3. paints HERMES_PROBE=1 on handlebar()
"""

import json
import os
import socket
import threading
import time


ROOT_DIR = r"D:\HermesQMTBridge"
AUDIT_DIR = os.path.join(ROOT_DIR, "audit")
HOST = "127.0.0.1"
PORT = 18767

STATE = {
    "started": False,
    "server_error": "",
    "started_at": "",
    "hits": 0,
}


def _now():
    return time.strftime("%Y-%m-%dT%H:%M:%S+08:00", time.localtime())


def _mkdirs():
    if not os.path.exists(ROOT_DIR):
        os.makedirs(ROOT_DIR)
    if not os.path.exists(AUDIT_DIR):
        os.makedirs(AUDIT_DIR)


def _write(name, text):
    try:
        _mkdirs()
        with open(os.path.join(AUDIT_DIR, name), "a") as f:
            f.write(text + "\n")
    except Exception:
        pass


def _response_body(path):
    STATE["hits"] += 1
    return json.dumps({
        "status": "ok",
        "path": path,
        "started": STATE["started"],
        "started_at": STATE["started_at"],
        "hits": STATE["hits"],
        "server_error": STATE["server_error"],
        "timestamp": _now(),
    })


def _serve():
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((HOST, PORT))
        sock.listen(5)
        STATE["started"] = True
        _write("probe_started.txt", "LISTEN %s:%s %s" % (HOST, PORT, _now()))
        while True:
            conn, addr = sock.accept()
            try:
                req = conn.recv(2048)
                first = req.split(b"\r\n", 1)[0].decode("latin1", "ignore")
                parts = first.split(" ")
                path = parts[1] if len(parts) > 1 else "/"
                body = _response_body(path).encode("utf-8")
                header = (
                    "HTTP/1.1 200 OK\r\n"
                    "Content-Type: application/json; charset=utf-8\r\n"
                    "Content-Length: %d\r\n"
                    "Connection: close\r\n"
                    "\r\n"
                ) % len(body)
                conn.sendall(header.encode("latin1") + body)
            except Exception as exc:
                _write("probe_error.txt", "REQUEST_ERROR %s %s" % (_now(), exc))
            try:
                conn.close()
            except Exception:
                pass
    except Exception as exc:
        STATE["server_error"] = str(exc)
        _write("probe_error.txt", "SERVER_ERROR %s %s" % (_now(), exc))


def init(ContextInfo):
    STATE["started_at"] = _now()
    _write("probe_started.txt", "INIT %s" % STATE["started_at"])
    t = threading.Thread(target=_serve)
    t.daemon = True
    t.start()


def handlebar(ContextInfo):
    try:
        ContextInfo.paint("HERMES_PROBE", 1 if STATE["started"] else 0, -1, 0)
    except Exception as exc:
        _write("probe_error.txt", "PAINT_ERROR %s %s" % (_now(), exc))
