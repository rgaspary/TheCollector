"""A small desktop window for TheCollector (GTK 3 + WebKitGTK), like NextUp's.

Run: python3 collector/window.py [url]

It has its own app ID (dev.thecollector.TheCollector), so the taskbar matches it to
dev.thecollector.TheCollector.desktop and shows TheCollector's icon. Links that leave the app
(Spotify sign-in, obsidian://, websites) open in their own apps.
Needs python-gobject and webkit2gtk-4.1 on the system; uses no other TheCollector code.
"""
import sys
from pathlib import Path
from urllib.parse import urlparse

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")  # must match Gtk 3, or Gdk 4 gets loaded and the import fails
gi.require_version("WebKit2", "4.1")
from gi.repository import Gtk  # noqa: E402  (Gtk first, so its Gdk 3 is the one loaded)
from gi.repository import Gdk, Gio, GLib, WebKit2  # noqa: E402

APP_ID = "dev.thecollector.TheCollector"
ICON = Path(__file__).resolve().parent.parent / "static" / "icon.svg"
URL = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8766"
ORIGIN = urlparse(URL)


def is_app(uri: str) -> bool:
    u = urlparse(uri)
    return (u.scheme, u.hostname, u.port) == (ORIGIN.scheme, ORIGIN.hostname, ORIGIN.port)


def open_outside(uri: str):
    try:
        Gio.AppInfo.launch_default_for_uri(uri, None)
    except GLib.Error as e:
        print(f"Couldn't open {uri}: {e.message}", file=sys.stderr)


class CollectorWindow(Gtk.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title="TheCollector")
        self.set_default_size(980, 900)
        if ICON.exists():
            self.set_icon_from_file(str(ICON))

        data_dir = Path(GLib.get_user_data_dir()) / "thecollector" / "webview"
        manager = WebKit2.WebsiteDataManager(
            base_data_directory=str(data_dir),
            base_cache_directory=str(Path(GLib.get_user_cache_dir()) / "thecollector"))
        context = WebKit2.WebContext.new_with_website_data_manager(manager)
        self.view = WebKit2.WebView.new_with_context(context)
        settings = self.view.get_settings()
        settings.set_enable_developer_extras(True)
        settings.set_javascript_can_open_windows_automatically(True)

        self.view.connect("decide-policy", self.on_decide_policy)
        self.view.connect("create", self.on_create)
        self.view.connect("load-failed", self.on_load_failed)
        self.add(self.view)
        self.connect("key-press-event", self.on_key)
        self.view.load_uri(URL)

    def on_key(self, _win, event):
        # F5 or Ctrl+R reloads.
        ctrl = event.state & Gdk.ModifierType.CONTROL_MASK
        if event.keyval == Gdk.KEY_F5 or (ctrl and event.keyval in (Gdk.KEY_r, Gdk.KEY_R)):
            self.view.reload_bypass_cache()
            return True
        return False

    def on_decide_policy(self, view, decision, kind):
        if kind == WebKit2.PolicyDecisionType.NAVIGATION_ACTION:
            uri = decision.get_navigation_action().get_request().get_uri()
            if not is_app(uri) and not uri.startswith("about:"):
                decision.ignore()
                open_outside(uri)
                return True
        elif kind == WebKit2.PolicyDecisionType.NEW_WINDOW_ACTION:
            decision.ignore()
            open_outside(decision.get_navigation_action().get_request().get_uri())
            return True
        return False

    def on_create(self, view, action):
        # target=_blank / window.open(): hand it to the default browser instead of a new webview.
        open_outside(action.get_request().get_uri())
        return None

    def on_load_failed(self, view, event, uri, error):
        # The server may still be starting; try again shortly.
        if is_app(uri):
            GLib.timeout_add(1000, lambda: (view.load_uri(URL), False)[1])
        return False


class CollectorApp(Gtk.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.FLAGS_NONE)
        self.window = None

    def do_activate(self):
        # A second launch brings the existing window forward.
        if not self.window:
            self.window = CollectorWindow(self)
            self.window.show_all()
        self.window.present()


if __name__ == "__main__":
    GLib.set_prgname(APP_ID)
    GLib.set_application_name("TheCollector")
    sys.exit(CollectorApp().run([sys.argv[0]]))
