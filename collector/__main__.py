"""python3 -m collector [--no-browser]"""
import sys
import threading
import webbrowser

from . import config
from .web import serve


def main():
    cfg = config.load()
    server = serve(cfg)
    url = f"http://{cfg.host}:{cfg.port}/"
    print(f"TheCollector running at {url}  (Ctrl+C to stop)")
    if "--no-browser" not in sys.argv:
        threading.Timer(0.5, webbrowser.open, [url]).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
