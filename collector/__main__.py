"""python3 -m collector [--no-browser]"""
import errno
import json
import sys
import threading
import urllib.request
import webbrowser

from . import config, updates
from .web import App, serve


def _is_collector(url: str) -> bool:
    """True when the server at url answers like TheCollector."""
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(url + "api/status", timeout=2) as response:
            return "version" in json.load(response)
    except (OSError, ValueError):
        return False


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    # Before anything else, so a staged update is in place before any of the old code is used.
    if updates.apply_staged(config.ROOT):
        updates.restart(argv)
    browser = "--no-browser" not in argv
    cfg = config.load()
    url = f"http://{cfg.host}:{cfg.port}/"
    app = App(cfg)
    try:
        server = serve(cfg, app)
    except OSError as e:
        if e.errno != errno.EADDRINUSE:
            raise
        if _is_collector(url):
            print(f"TheCollector is already running at {url}")
            if browser:
                webbrowser.open(url)
            return 0
        print(f"TheCollector can't start: another program is using port {cfg.port}.\n"
              f"Close that program and try again. You can also change the port under [server] in\n"
              f"{config.CONFIG_PATH}, but then the Spotify redirect URI must change to match.",
              file=sys.stderr)
        return 1

    # This copy is up and running, so the files it replaced are no longer needed.
    updates.cleanup_previous(config.ROOT)
    print(f"TheCollector running at {url}  (Ctrl+C to stop)")
    if browser:
        threading.Timer(0.5, webbrowser.open, [url]).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    if app.restart_requested:
        updates.restart(argv)
    return 0


if __name__ == "__main__":
    sys.exit(main())
