"""The desktop's own folder picker, opened for the Browse buttons."""
import os
import socket
import subprocess
import threading
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from collector import dbus
from collector import folder_picker as fp


def done(code: int, out: str = "") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess([], code, out, "")


class Start(unittest.TestCase):
    def test_walks_up_to_a_folder_that_exists(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(fp.existing_start(str(Path(d) / "not/yet/made")), Path(d))
            self.assertEqual(fp.existing_start(d), Path(d))
        self.assertEqual(fp.existing_start(""), Path.home())


class Protocol(unittest.TestCase):
    def test_types_round_trip(self):
        options = {"handle_token": ("s", "t1"), "directory": ("b", True), "current_folder": ("ay", b"/m\0")}
        data = dbus.encode(dbus.CALL, 7, "ssa{sv}u", ("", "Choose", options, 42), path="/p", member="M")
        msg = dbus.decode(data)
        self.assertEqual((msg["type"], msg["serial"], msg["path"], msg["member"]), (dbus.CALL, 7, "/p", "M"))
        self.assertEqual(msg["body"], ["", "Choose", {"handle_token": "t1", "directory": True,
                                                      "current_folder": b"/m\0"}, 42])

    def test_bus_address(self):
        self.assertEqual(dbus.session_bus_path({"DBUS_SESSION_BUS_ADDRESS": "unix:path=/run/user/1/bus"}),
                         "/run/user/1/bus")
        self.assertEqual(dbus.session_bus_path({"DBUS_SESSION_BUS_ADDRESS": "unix:abstract=/tmp/dbus-x,guid=1"}),
                         "\0/tmp/dbus-x")
        self.assertEqual(dbus.session_bus_path({"XDG_RUNTIME_DIR": "/r"}), "/r/bus")

    def test_response(self):
        self.assertEqual(fp.folder_from_response(0, {"uris": ["file:///home/me/My%20Music"]}), "/home/me/My Music")
        self.assertIsNone(fp.folder_from_response(1, {}))
        with self.assertRaises(fp.PickerUnavailable):
            fp.folder_from_response(2, {})
        self.assertEqual(fp.request_path(":1.77", "tok"), "/org/freedesktop/portal/desktop/request/1_77/tok")


class FakePortalBus(threading.Thread):
    """A session bus with a portal that 'chooses' a folder, speaking the real wire protocol."""

    def __init__(self, socket_path: str, answer: tuple):
        super().__init__(daemon=True)
        self.server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.server.bind(socket_path)
        self.server.listen(1)
        self.answer, self.calls = answer, []

    def run(self):
        conn, _ = self.server.accept()
        with conn:
            auth = b""
            while b"BEGIN\r\n" not in auth:
                chunk = conn.recv(1024)
                auth += chunk
                if chunk.startswith(b"\0AUTH") or b"AUTH EXTERNAL" in chunk:
                    conn.sendall(b"OK 0123456789abcdef\r\n")
            buffer = auth.split(b"BEGIN\r\n", 1)[1]
            serial = 100
            while True:
                while len(buffer) < 16 or len(buffer) < dbus._message_size(buffer):
                    chunk = conn.recv(65536)
                    if not chunk:
                        return
                    buffer += chunk
                size = dbus._message_size(buffer)
                msg, buffer = dbus.decode(buffer[:size]), buffer[size:]
                self.calls.append(msg)
                serial += 1
                if msg["member"] == "Hello":
                    conn.sendall(dbus.encode(dbus.REPLY, serial, "s", (":1.77",), reply_serial=msg["serial"]))
                elif msg["member"] == "AddMatch":
                    conn.sendall(dbus.encode(dbus.REPLY, serial, reply_serial=msg["serial"]))
                elif msg["member"] == "OpenFile":
                    token = msg["body"][2]["handle_token"]
                    handle = fp.request_path(":1.77", token)
                    conn.sendall(dbus.encode(dbus.REPLY, serial, "o", (handle,), reply_serial=msg["serial"]))
                    code, uris = self.answer
                    conn.sendall(dbus.encode(dbus.SIGNAL, serial + 1, "ua{sv}", (code, {"uris": ("as", uris)}),
                                             path=handle, interface=fp.REQUEST, member="Response"))


class Portal(unittest.TestCase):
    def ask(self, answer: tuple, start: Path) -> tuple:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        bus = FakePortalBus(os.path.join(tmp.name, "bus"), answer)
        self.addCleanup(bus.server.close)
        bus.start()
        with mock.patch.dict(os.environ, {"DBUS_SESSION_BUS_ADDRESS": f"unix:path={tmp.name}/bus"}):
            result = fp._portal(start)
        bus.join(2)
        return result, bus.calls

    def test_chosen_folder(self):
        result, calls = self.ask((0, ["file:///home/me/My%20Music"]), Path("/home/me"))
        self.assertEqual(result, "/home/me/My Music")
        open_file = next(c for c in calls if c["member"] == "OpenFile")
        self.assertEqual(open_file["destination"], "org.freedesktop.portal.Desktop")
        self.assertEqual(open_file["body"][2]["current_folder"], b"/home/me\0")
        self.assertTrue(open_file["body"][2]["directory"])

    def test_cancelled(self):
        self.assertIsNone(self.ask((1, []), Path("/"))[0])

    def test_no_bus(self):
        with mock.patch.dict(os.environ, {"DBUS_SESSION_BUS_ADDRESS": "unix:path=/nonexistent/bus"}):
            with self.assertRaises(fp.PickerUnavailable):
                fp._portal(Path("/"))


class Commands(unittest.TestCase):
    def which(self, *found):
        return lambda name: f"/usr/bin/{name}" if name in found else None

    def test_kde_prefers_kdialog(self):
        cmds = fp.fallback_commands(Path("/m"), "linux", {"XDG_CURRENT_DESKTOP": "KDE"},
                                    self.which("kdialog", "zenity"))
        self.assertEqual([c[0] for c in cmds], ["kdialog", "zenity"])
        self.assertIn("--getexistingdirectory", cmds[0])

    def test_other_desktops_prefer_zenity(self):
        cmds = fp.fallback_commands(Path("/m"), "linux", {"XDG_CURRENT_DESKTOP": "GNOME"},
                                    self.which("kdialog", "zenity", "yad"))
        self.assertEqual([c[0] for c in cmds], ["zenity", "kdialog", "yad"])
        self.assertIn("--directory", cmds[0])

    def test_windows_and_mac(self):
        self.assertEqual(fp.fallback_commands(Path("C:/m"), "win32", {}, self.which())[0][0], "powershell")
        self.assertEqual(fp.fallback_commands(Path("/m"), "darwin", {}, self.which())[0][0], "osascript")


class Choose(unittest.TestCase):
    def setUp(self):
        for name, value in (("_portal", mock.Mock(side_effect=fp.PickerUnavailable)),
                            ("fallback_commands", lambda *a: [["kdialog", "x"], ["zenity", "y"]])):
            p = mock.patch.object(fp, name, value)
            p.start()
            self.addCleanup(p.stop)

    def test_portal_answer_wins(self):
        with mock.patch.object(fp, "_portal", return_value="/picked"):
            self.assertEqual(fp.choose_folder("/tmp", "linux"), "/picked")

    def test_first_tool_that_answers(self):
        with mock.patch("subprocess.run", return_value=done(0, "/home/me/Docs\n")) as run:
            self.assertEqual(fp.choose_folder("/tmp", "linux"), "/home/me/Docs")
        self.assertEqual(run.call_args[0][0][0], "kdialog")

    def test_cancel_returns_none(self):
        with mock.patch("subprocess.run", return_value=done(1)):
            self.assertIsNone(fp.choose_folder("/tmp", "linux"))

    def test_broken_tool_tries_the_next(self):
        with mock.patch("subprocess.run", side_effect=[done(254), done(0, "/z")]):
            self.assertEqual(fp.choose_folder("/tmp", "linux"), "/z")

    def test_nothing_available(self):
        with mock.patch.object(fp, "fallback_commands", lambda *a: []):
            with self.assertRaises(fp.PickerUnavailable) as cm:
                fp.choose_folder("/tmp", "linux")
        self.assertIn("type the folder", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
