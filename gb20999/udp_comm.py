# -*- coding: utf-8 -*-
"""UDP 通信层。"""
from __future__ import annotations

import socket
import threading
from typing import Callable

from .protocol import format_hex_display, parse_hex


class UdpComm:
    def __init__(
        self,
        local_port: int = 5051,
        remote_host: str = "192.168.40.85",
        remote_port: int = 4050,
    ):
        self.local_port = local_port
        self.remote_host = remote_host
        self.remote_port = remote_port
        self._sock: socket.socket | None = None
        self._thread: threading.Thread | None = None
        self._running = False
        self.on_receive: Callable[[bytes, tuple], None] | None = None
        self.on_log: Callable[[str], None] | None = None

    def _log(self, msg: str) -> None:
        if self.on_log:
            self.on_log(msg)

    @property
    def is_running(self) -> bool:
        return self._running and self._sock is not None

    def start(self) -> None:
        self.stop()
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("", self.local_port))
        sock.settimeout(0.5)
        self._sock = sock
        self._running = True
        self._thread = threading.Thread(target=self._recv_loop, daemon=True)
        self._thread.start()
        self._log(f"UDP 已启动，本机端口 {self.local_port}，目标 {self.remote_host}:{self.remote_port}")

    def stop(self) -> None:
        self._running = False
        if self._sock:
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.0)
        self._thread = None

    def update_target(self, remote_host: str, remote_port: int) -> None:
        self.remote_host = remote_host
        self.remote_port = remote_port

    def update_local_port(self, port: int) -> None:
        if port != self.local_port:
            self.local_port = port
            if self.is_running:
                self.start()

    def send(self, data: bytes) -> None:
        if not self._sock:
            raise RuntimeError("UDP 未启动")
        self._sock.sendto(data, (self.remote_host, self.remote_port))
        self._log(f"发 -> {self.remote_host}:{self.remote_port} | {format_hex_display(data)}")

    def send_hex(self, text: str) -> None:
        self.send(parse_hex(text))

    def _recv_loop(self) -> None:
        while self._running and self._sock:
            try:
                data, addr = self._sock.recvfrom(65535)
            except socket.timeout:
                continue
            except OSError:
                break
            if not data:
                continue
            self._log(f"收 <- {addr[0]}:{addr[1]} | {format_hex_display(data)}")
            if self.on_receive:
                self.on_receive(data, addr)
