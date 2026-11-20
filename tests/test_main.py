"""Starting the app: a taken port, a staged update, and a restart on request."""
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
from collector import updates, web
from collector.choices import Choices
from collector.credentials import CredentialStore


def make_cfg(port: int) -> config_mod.Config:
    tmp = Path(tempfile.mkdtemp())
    path = tmp / "config.toml"
    path.write_text(f'[export]\ndir = "{tmp / "Exports"}"\n[server]\nhost = "127.0.0.1"\nport = {port}\n')
    return config_mod.load(path)


def make_app(cfg: config_mod.Config) -> web.App:
    """An App whose files are all in a temp folder."""
    d = Path(tempfile.mkdtemp())
    return web.App(cfg, config_path=d / "config.toml", store=CredentialStore(d / "credentials.json"),
                   choices=Choices(d / "choices.json"), v1_token_file=d / "no-token.json")


def start_collector(test: unittest.TestCase) -> int:
    """A real TheCollector server on a free port, with its files in a temp folder."""
    cfg = make_cfg(0)
    app = make_app(cfg)
    server = web.serve(cfg, app)
    test.addCleanup(server.server_close)
    threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True).start()
    test.addCleanup(server.shutdown)
    return server.server_address[1]


def run_main(cfg: config_mod.Config, argv: list[str]) -> tuple[int, str, str, mock.Mock]:
    out, err = io.StringIO(), io.StringIO()
    # The updater is switched off so these tests never touch the real install folder.
    with mock.patch.object(app_main.config, "load", return_value=cfg), \
            mock.patch.object(updates, "apply_staged", return_value=False), \
            mock.patch.object(updates, "cleanup_previous"), \
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


class Restarted(Exception):
    """Stands in for os.execv, which never returns."""


class Updates(unittest.TestCase):
    def test_staged_update_restarts_before_serving(self):
        with mock.patch.object(updates, "apply_staged", return_value=True) as applied, \
                mock.patch.object(updates, "restart", side_effect=Restarted) as restart, \
                mock.patch.object(updates, "cleanup_previous") as cleanup, \
                mock.patch.object(app_main, "serve") as serve, \
                mock.patch.object(app_main.config, "load") as load, \
                self.assertRaises(Restarted):
            app_main.main(["--no-browser"])
        applied.assert_called_once_with(config_mod.ROOT)
        restart.assert_called_once_with(["--no-browser"])
        serve.assert_not_called()
        cleanup.assert_not_called()
        load.assert_not_called()

    def test_restart_requested_execs_after_shutdown(self):
        cfg = make_cfg(0)
        made, bound = [], threading.Event()

        def serve(cfg, app):
            server = web.serve(cfg, app)
            made.append((server, app))
            bound.set()
            return server

        result = []
        with mock.patch.object(app_main.config, "load", return_value=cfg), \
                mock.patch.object(updates, "apply_staged", return_value=False), \
                mock.patch.object(updates, "restart") as restart, \
                mock.patch.object(updates, "cleanup_previous") as cleanup, \
                mock.patch.object(app_main, "App", side_effect=make_app), \
                mock.patch.object(app_main, "serve", side_effect=serve), \
                contextlib.redirect_stdout(io.StringIO()):
            thread = threading.Thread(target=lambda: result.append(app_main.main(["--no-browser"])), daemon=True)
            thread.start()
            self.assertTrue(bound.wait(5))
            server, app = made[0]
            cleanup.assert_called_once_with(config_mod.ROOT)
            restart.assert_not_called()
            app.restart_requested = True
            server.shutdown()
            thread.join(5)
        self.assertFalse(thread.is_alive())
        restart.assert_called_once_with(["--no-browser"])
        self.assertEqual(result, [0])
        self.assertEqual(server.socket.fileno(), -1)  # closed before restarting

    def test_plain_shutdown_does_not_restart(self):
        cfg = make_cfg(0)
        made, bound = [], threading.Event()

        def serve(cfg, app):
            made.append(web.serve(cfg, app))
            bound.set()
            return made[0]

        with mock.patch.object(app_main.config, "load", return_value=cfg), \
                mock.patch.object(updates, "apply_staged", return_value=False), \
                mock.patch.object(updates, "restart") as restart, \
                mock.patch.object(updates, "cleanup_previous"), \
                mock.patch.object(app_main, "App", side_effect=make_app), \
                mock.patch.object(app_main, "serve", side_effect=serve), \
                contextlib.redirect_stdout(io.StringIO()):
            thread = threading.Thread(target=app_main.main, args=(["--no-browser"],), daemon=True)
            thread.start()
            self.assertTrue(bound.wait(5))
            made[0].shutdown()
            thread.join(5)
        restart.assert_not_called()

    def test_app_does_not_ask_for_restart_by_default(self):
        self.assertIs(make_app(make_cfg(0)).restart_requested, False)


if __name__ == "__main__":
    unittest.main()
