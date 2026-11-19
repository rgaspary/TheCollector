"""Just enough of the D-Bus protocol to ask the desktop portal for a folder picker.

The portal answers a request with a signal sent only to the connection that asked, so asking and
listening must happen on one connection. Python has no D-Bus module, and the command-line tools
(busctl, gdbus) can't do both at once, hence this small client: connect, authenticate, call
methods, read signals. Types covered: y b u i s o g v a{..} a.. (..).
"""
import os
import socket
import struct
import time
from urllib.parse import unquote

CALL, REPLY, ERROR, SIGNAL = 1, 2, 3, 4
_ALIGN = {"y": 1, "g": 1, "v": 1, "b": 4, "u": 4, "i": 4, "s": 4, "o": 4, "a": 4, "x": 8, "t": 8, "d": 8,
          "(": 8, "{": 8}
_FIELDS = {"path": (1, "o"), "interface": (2, "s"), "member": (3, "s"), "error": (4, "s"),
           "reply_serial": (5, "u"), "destination": (6, "s"), "sender": (7, "s"), "signature": (8, "g")}
_FIELD_NAMES = {code: name for name, (code, _) in _FIELDS.items()}


class DBusError(Exception):
    pass


def _end(sig: str, i: int) -> int:
    """Index just past the complete type that starts at sig[i]."""
    c = sig[i]
    if c == "a":
        return _end(sig, i + 1)
    if c in "({":
        close = ")" if c == "(" else "}"
        i += 1
        while sig[i] != close:
            i = _end(sig, i)
        return i + 1
    return i + 1


def split(sig: str) -> list[str]:
    out, i = [], 0
    while i < len(sig):
        j = _end(sig, i)
        out.append(sig[i:j])
        i = j
    return out


class Writer:
    def __init__(self):
        self.buf = bytearray()

    def pad(self, n: int) -> None:
        self.buf += b"\0" * (-len(self.buf) % n)

    def write(self, sig: str, value) -> None:
        c = sig[0]
        self.pad(_ALIGN[c])
        if c == "y":
            self.buf.append(value)
        elif c == "b":
            self.buf += struct.pack("<I", 1 if value else 0)
        elif c == "u":
            self.buf += struct.pack("<I", value)
        elif c == "i":
            self.buf += struct.pack("<i", value)
        elif c in "so":
            data = value.encode()
            self.buf += struct.pack("<I", len(data)) + data + b"\0"
        elif c == "g":
            data = value.encode()
            self.buf += bytes([len(data)]) + data + b"\0"
        elif c == "v":
            inner_sig, inner = value
            self.write("g", inner_sig)
            self.write(inner_sig, inner)
        elif c == "a":
            elem = sig[1:]
            at = len(self.buf)
            self.buf += b"\0\0\0\0"
            self.pad(_ALIGN[elem[0]])
            start = len(self.buf)
            items = value.items() if elem[0] == "{" else value
            for item in items:
                self.write(elem, item)
            struct.pack_into("<I", self.buf, at, len(self.buf) - start)
        elif c in "({":
            for part, v in zip(split(sig[1:-1]), value):
                self.write(part, v)
        else:
            raise DBusError(f"Can't write D-Bus type {c!r}")


class Reader:
    def __init__(self, data: bytes, little: bool = True, pos: int = 0):
        self.data, self.pos, self.end = data, pos, "<" if little else ">"

    def _take(self, fmt: str):
        size = struct.calcsize(fmt)
        value = struct.unpack_from(self.end + fmt, self.data, self.pos)[0]
        self.pos += size
        return value

    def read(self, sig: str):
        c = sig[0]
        self.pos += -self.pos % _ALIGN[c]
        if c == "y":
            self.pos += 1
            return self.data[self.pos - 1]
        if c == "b":
            return self._take("I") != 0
        if c in "ui":
            return self._take("I" if c == "u" else "i")
        if c in "xt":
            return self._take("q" if c == "x" else "Q")
        if c == "d":
            return self._take("d")
        if c in "so":
            n = self._take("I")
            text = self.data[self.pos:self.pos + n].decode("utf-8", "replace")
            self.pos += n + 1
            return text
        if c == "g":
            n = self.data[self.pos]
            text = self.data[self.pos + 1:self.pos + 1 + n].decode()
            self.pos += n + 2
            return text
        if c == "v":
            return self.read(self.read("g"))
        if c == "a":
            elem = sig[1:]
            n = self._take("I")
            self.pos += -self.pos % _ALIGN[elem[0]]
            stop = self.pos + n
            if elem == "y":
                self.pos = stop
                return bytes(self.data[stop - n:stop])
            items = []
            while self.pos < stop:
                items.append(self.read(elem))
            return dict(items) if elem[0] == "{" else items
        if c in "({":
            return tuple(self.read(part) for part in split(sig[1:-1]))
        raise DBusError(f"Can't read D-Bus type {c!r}")

    def read_all(self, sig: str) -> list:
        return [self.read(part) for part in split(sig)]


def encode(kind: int, serial: int, body_sig: str = "", body: tuple = (), **fields) -> bytes:
    payload = Writer()
    for part, value in zip(split(body_sig), body):
        payload.write(part, value)
    if body_sig:
        fields["signature"] = body_sig
    header = Writer()
    header.buf += struct.pack("<cBBBII", b"l", kind, 0, 1, len(payload.buf), serial)
    header.write("a(yv)", [(_FIELDS[k][0], (_FIELDS[k][1], v)) for k, v in fields.items() if v is not None])
    header.pad(8)
    return bytes(header.buf + payload.buf)


def decode(data: bytes) -> dict:
    """A whole message as {"type", "serial", fields..., "body": [...]}."""
    little = data[0:1] == b"l"
    r = Reader(data, little, 4)
    body_len, serial = r._take("I"), r._take("I")
    fields = {_FIELD_NAMES.get(code, code): value for code, value in r.read("a(yv)")}
    r.pos += -r.pos % 8
    body = Reader(data[r.pos:r.pos + body_len], little).read_all(fields.get("signature", ""))
    return {"type": data[1], "serial": serial, **fields, "body": body}


def _message_size(head: bytes) -> int:
    fmt = "<" if head[0:1] == b"l" else ">"
    body_len, _, fields_len = struct.unpack_from(fmt + "III", head, 4)
    header = 16 + fields_len
    return header + (-header % 8) + body_len


def session_bus_path(env: dict | None = None) -> str:
    """The session bus socket: a filesystem path, or "\\0name" for an abstract socket."""
    env = os.environ if env is None else env
    for address in (env.get("DBUS_SESSION_BUS_ADDRESS") or "").split(";"):
        kind, _, rest = address.partition(":")
        if kind != "unix":
            continue
        params = dict(p.split("=", 1) for p in rest.split(",") if "=" in p)
        if "path" in params:
            return unquote(params["path"])
        if "abstract" in params:
            return "\0" + unquote(params["abstract"])
    runtime = env.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"
    return os.path.join(runtime, "bus")


class Connection:
    def __init__(self, sock: socket.socket):
        self.sock, self.serial, self.buffer, self.pending = sock, 0, b"", []
        self.unique_name = ""

    @classmethod
    def session(cls, timeout: float = 5) -> "Connection":
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        try:
            sock.connect(session_bus_path())
            conn = cls(sock)
            conn.authenticate()
            conn.unique_name = conn.call("org.freedesktop.DBus", "/org/freedesktop/DBus",
                                         "org.freedesktop.DBus", "Hello")[0]
        except (OSError, DBusError):
            sock.close()
            raise
        return conn

    def authenticate(self) -> None:
        self.sock.sendall(b"\0AUTH EXTERNAL " + str(os.getuid()).encode().hex().encode() + b"\r\n")
        line = b""
        while not line.endswith(b"\r\n"):
            chunk = self.sock.recv(256)
            if not chunk:
                raise DBusError("The bus closed the connection")
            line += chunk
        if not line.startswith(b"OK"):
            raise DBusError("The bus refused the connection")
        self.sock.sendall(b"BEGIN\r\n")

    def close(self) -> None:
        self.sock.close()

    def send(self, kind: int, body_sig: str = "", body: tuple = (), **fields) -> int:
        self.serial += 1
        self.sock.sendall(encode(kind, self.serial, body_sig, body, **fields))
        return self.serial

    def receive(self, deadline: float) -> dict:
        while True:
            if len(self.buffer) >= 16:
                size = _message_size(self.buffer)
                if len(self.buffer) >= size:
                    data, self.buffer = self.buffer[:size], self.buffer[size:]
                    return decode(data)
            left = deadline - time.monotonic()
            if left <= 0:
                raise TimeoutError("No answer from the bus")
            self.sock.settimeout(left)
            chunk = self.sock.recv(65536)
            if not chunk:
                raise DBusError("The bus closed the connection")
            self.buffer += chunk

    def call(self, destination: str, path: str, interface: str, member: str, body_sig: str = "",
             body: tuple = (), timeout: float = 15) -> list:
        serial = self.send(CALL, body_sig, body, path=path, interface=interface, member=member,
                           destination=destination)
        deadline = time.monotonic() + timeout
        while True:
            msg = self.receive(deadline)
            if msg.get("reply_serial") == serial:
                if msg["type"] == ERROR:
                    raise DBusError(f"{msg.get('error')}: {(msg['body'] or [''])[0]}")
                return msg["body"]
            self.pending.append(msg)  # a signal that arrived first; keep it

    def wait_for_signal(self, path: str, interface: str, member: str, timeout: float) -> list:
        deadline = time.monotonic() + timeout
        while True:
            msg = self.pending.pop(0) if self.pending else self.receive(deadline)
            if (msg["type"] == SIGNAL and msg.get("path") == path and msg.get("interface") == interface
                    and msg.get("member") == member):
                return msg["body"]
