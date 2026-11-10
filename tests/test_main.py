"""Starting the app when its port is already taken."""
import contextlib
import io
import socket
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from collector import __main__ as app_main
from collector import config as config_mod
from collector import web
from collector.choices import Choices
from collector.credentials import CredentialStore


def make_cfg(port: int) -> config_mod.Config:
    tmp = Path(tempfile.mkdtemp())
    path = tmp / "config.toml"
    path.write_text(f'[export]\ndir = "{tmp / "Exports"}"\n[server]\nhost = "127.0.0.1"\nport = {port}\n')
    return config_mod.load(path)


def start_collector(test: unittest.TestCase) -> int:
    """A real TheCollector server on a free port, with its files in a temp folder."""
    cfg = make_cfg(0)
    d = Path(tempfile.mkdtemp())
    app = web.App(cfg, config_path=d / "config.toml", store=CredentialStore(d / "credentials.json"),
                  choices=Choices(d / "choices.json"), v1_token_file=d / "no-token.json")
    server = web.serve(cfg, app)
    test.addCleanup(server.server_close)
    threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True).start()
    test.addCleanup(server.shutdown)
    return server.server_address[1]


def run_main(cfg: config_mod.Config, argv: list[str]) -> tuple[int, str, str, mock.Mock]:
    out, err = io.StringIO(), io.StringIO()
    with mock.patch.object(app_main.config, "load", return_value=cfg), \
            mock.patch.object(app_main.webbrowser, "open") as opened, \
            contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = app_main.main(argv)
    return code, out.getvalue(), err.getvalue(), opened


class PortInUse(unittest.TestCase):
    def test_other_program_on_port_gives_plain_message(self):
        holder = socket.socket()
        holder.bind(("127.0.0.1", 0))
        holder.listen()
        self.addCleanup(holder.close)
        port = holder.getsockname()[1]

        code, out, err, opened = run_main(make_cfg(port), [])

        self.assertEqual(code, 1)
        self.assertIn(f"another program is using port {port}", err)
        self.assertNotIn("Traceback", err)
        opened.assert_not_called()

    def test_collector_already_running_opens_it(self):
        port = start_collector(self)

        code, out, err, opened = run_main(make_cfg(port), [])

        self.assertEqual(code, 0)
        self.assertIn(f"already running at http://127.0.0.1:{port}/", out)
        opened.assert_called_once_with(f"http://127.0.0.1:{port}/")

    def test_already_running_respects_no_browser(self):
        port = start_collector(self)

        code, out, err, opened = run_main(make_cfg(port), ["--no-browser"])

        self.assertEqual(code, 0)
        opened.assert_not_called()


if __name__ == "__main__":
    unittest.main()
