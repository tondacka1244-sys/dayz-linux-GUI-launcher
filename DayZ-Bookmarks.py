import gi
import subprocess
import json
import os
import re
import threading
import concurrent.futures
from gi.repository import GLib

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk

CONFIG_FILE = "config.json"


def safe_int(text, default):
    text = (text or "").strip()
    try:
        return int(text)
    except ValueError:
        return default


PING_TIME_RE = re.compile(r"time[=<]\s*([0-9]*\.?[0-9]+)\s*ms", re.IGNORECASE)

def parse_ping_time(output_text: str) -> int:
    for line in output_text.splitlines():
        m = PING_TIME_RE.search(line)
        if m:
            try:
                return int(float(m.group(1)))
            except Exception:
                pass
    for line in output_text.splitlines():
        if "min/avg/max" in line or "mdev" in line:
            try:
                parts = line.split("=")[1].strip().split("/")
                avg_ms = float(parts[1])
                return int(avg_ms)
            except Exception:
                pass
    return 0


def ping_host(host: str, timeout_sec: int = 1) -> int:
    try:
        proc = subprocess.run(
            ["ping", "-n", "-c", "1", "-W", str(timeout_sec), host],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        if proc.returncode != 0:
            return 0
        return parse_ping_time(proc.stdout)
    except Exception:
        return 0


class AddServerDialog(Gtk.Dialog):
    def __init__(self, parent):
        super().__init__(title="Add server", transient_for=parent, flags=0)
        self.set_default_size(380, 250)
        self.add_buttons(
            Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL,
            Gtk.STOCK_OK, Gtk.ResponseType.OK
        )

        content = self.get_content_area()
        grid = Gtk.Grid(column_spacing=10, row_spacing=10, margin=10)
        content.add(grid)

        self.entry_name = Gtk.Entry()
        self.entry_address = Gtk.Entry()
        self.entry_game_port = Gtk.Entry()
        self.entry_query_port = Gtk.Entry()

        self.entry_name.set_placeholder_text("Server name")
        self.entry_address.set_placeholder_text("IP or hostname")
        self.entry_game_port.set_placeholder_text("Game port (default 2302)")
        self.entry_query_port.set_placeholder_text("Query port (default 27016)")

        labels = [
            ("Server name:", self.entry_name),
            ("Address:", self.entry_address),
            ("Game port:", self.entry_game_port),
            ("Query port:", self.entry_query_port),
        ]

        for i, (text, widget) in enumerate(labels):
            lbl = Gtk.Label(label=text)
            lbl.set_xalign(0)
            grid.attach(lbl, 0, i, 1, 1)
            grid.attach(widget, 1, i, 1, 1)

        self.show_all()



    def get_data(self):
        name = self.entry_name.get_text().strip()
        address = self.entry_address.get_text().strip()
        game_port = safe_int(self.entry_game_port.get_text(), 2302)
        query_port = safe_int(self.entry_query_port.get_text(), 27016)
        return {
            "name": name,
            "address": address,
            "game_port": game_port,
            "query_port": query_port,
            "players": 0,
            "ping": 0,
            "map": "",
        }


class BookmarksWindow(Gtk.Window):
    def __init__(self):
        super().__init__(title="DayZ Bookmarks")
        self.set_default_size(850, 670)  # zvětšeno o 120 px

        self.config = self.load_config()

        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        vbox.set_margin_top(10)
        vbox.set_margin_bottom(10)
        vbox.set_margin_start(10)
        vbox.set_margin_end(10)
        self.add(vbox)

        # Refresh button above table
        refresh_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        self.btn_refresh = Gtk.Button(label="Refresh servers")
        self.btn_refresh.connect("clicked", self.on_refresh)
        refresh_box.pack_start(self.btn_refresh, False, False, 0)
        vbox.pack_start(refresh_box, False, False, 0)

        # Main list – 7 sloupců včetně mapy
        self.store = Gtk.ListStore(str, str, int, int, int, int, str)
        self.treeview = Gtk.TreeView(model=self.store)
        self.treeview.set_headers_visible(True)

        def add_column(title, col_id):
            renderer = Gtk.CellRendererText()
            column = Gtk.TreeViewColumn(title, renderer, text=col_id)
            column.set_resizable(True)
            column.set_sort_column_id(col_id)
            self.treeview.append_column(column)

        add_column("Name", 0)
        add_column("Address", 1)
        add_column("Players", 2)
        add_column("Ping", 3)
        add_column("Game port", 4)
        add_column("Query port", 5)
        add_column("Map", 6)

        scrolled = Gtk.ScrolledWindow()
        scrolled.add(self.treeview)
        vbox.pack_start(scrolled, True, True, 0)

        # Buttons row
        btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)

        self.btn_connect = Gtk.Button(label="Connect")
        self.btn_search = Gtk.Button(label="Search for server")
        self.btn_add = Gtk.Button(label="Add server manually")
        self.btn_remove = Gtk.Button(label="Remove selected")

        self.btn_connect.connect("clicked", self.on_connect)
        self.btn_search.connect("clicked", self.on_search)
        self.btn_add.connect("clicked", self.on_add_server)
        self.btn_remove.connect("clicked", self.on_remove_selected)

        btn_box.pack_start(self.btn_connect, False, False, 0)
        btn_box.pack_start(self.btn_search, False, False, 0)
        btn_box.pack_start(self.btn_add, False, False, 0)
        btn_box.pack_start(self.btn_remove, False, False, 0)

        # Profile name on the far right
        self.entry_profile = Gtk.Entry()
        self.entry_profile.set_placeholder_text("Player name")
        profile_value = self.config.get("profile", "")
        self.entry_profile.set_text(profile_value)
        self.entry_profile.connect("changed", self.on_profile_changed)
        btn_box.pack_end(self.entry_profile, False, False, 0)

        vbox.pack_start(btn_box, False, False, 0)

        # Fill servers from config
        for srv in self.config.get("servers", []):
            self.store.append([
                srv.get("name", ""),
                srv.get("address", ""),
                int(srv.get("players", 0)),
                int(srv.get("ping", 0)),
                int(srv.get("game_port", 2302)),
                int(srv.get("query_port", 27016)),
                srv.get("map", ""),
            ])

        # Ping all servers on startup
        self.on_refresh()

        # Console output area at the bottom
        self.console_view = Gtk.TextView()
        self.console_view.set_editable(False)
        self.console_view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self.console_buffer = self.console_view.get_buffer()

        console_scrolled = Gtk.ScrolledWindow()
        console_scrolled.set_size_request(-1, 120)  # výška 120 px
        console_scrolled.add(self.console_view)

        vbox.pack_start(console_scrolled, False, False, 0)

        self.show_all()

    def log_to_console(self, text: str):
        end_iter = self.console_buffer.get_end_iter()
        self.console_buffer.insert(end_iter, text + "\n")

    def run_with_output(self, cmd):
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1
        )

        def reader():
            for line in process.stdout:
                GLib.idle_add(self.log_to_console, line.strip())
            process.stdout.close()
            process.wait()

        threading.Thread(target=reader, daemon=True).start()

    # --- sem patří zbytek metod: load_config, save_config, on_add_server, on_remove_selected,
    # on_connect, on_profile_changed, on_search, on_refresh, show_info ---



    def load_config(self):
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, "r") as f:
                    cfg = json.load(f)
            except Exception:
                cfg = {}
        else:
            cfg = {}
        cfg.setdefault("profile", "")
        cfg.setdefault("servers", [])
        return cfg

    def save_config(self):
        servers = []
        for row in self.store:
            servers.append({
                "name": row[0],
                "address": row[1],
                "players": int(row[2]),
                "ping": int(row[3]),
                "game_port": int(row[4]),
                "query_port": int(row[5]),
                "map": row[6],
            })
        self.config["servers"] = servers
        self.config["profile"] = self.entry_profile.get_text().strip()
        try:
            with open(CONFIG_FILE, "w") as f:
                json.dump(self.config, f, indent=2)
        except Exception as e:
            self.show_info(f"Failed to save config:\n{e}")

    def get_selected_iter(self):
        selection = self.treeview.get_selection()
        model, treeiter = selection.get_selected()
        return model, treeiter

    def on_add_server(self, _button):
        dialog = AddServerDialog(self)
        response = dialog.run()
        if response == Gtk.ResponseType.OK:
            data = dialog.get_data()
            if not data["name"] or not data["address"]:
                self.show_info("Please fill in at least Server name and Address.")
            else:
                self.store.append([
                    data["name"], data["address"],
                    int(data["players"]), int(data["ping"]),
                    int(data["game_port"]), int(data["query_port"]),
                    data["map"],
                ])
                self.save_config()
        dialog.destroy()

    def on_remove_selected(self, _button):
        model, treeiter = self.get_selected_iter()
        if not treeiter:
            return
        confirm = Gtk.MessageDialog(
            transient_for=self,
            flags=0,
            message_type=Gtk.MessageType.QUESTION,
            buttons=Gtk.ButtonsType.YES_NO,
            text="Do you really want to remove the selected server?"
        )
        response = confirm.run()
        confirm.destroy()
        if response == Gtk.ResponseType.YES:
            model.remove(treeiter)
            self.save_config()

    def on_connect(self, _button):
        model, treeiter = self.get_selected_iter()
        if not treeiter:
            self.show_info("Please select a server from the list.")
            return
        address = model[treeiter][1]
        game_port = int(model[treeiter][4])
        query_port = int(model[treeiter][5])
        profile = self.entry_profile.get_text().strip() or "Player"

        server_arg = f"{address}:{game_port}"
        cmd = ["./dayz-launcher.sh", "-l", "-n", profile, "-s", server_arg, "-p", str(query_port)]
        try:
            self.run_with_output(cmd)


        except Exception as e:
            self.show_info(f"Failed to start launcher:\n{e}")

    def on_profile_changed(self, _entry):
        self.save_config()

    def on_search(self, _button):
        try:
            self.run_with_output(["python3", "search.py"])

        except Exception as e:
            self.show_info(f"Failed to start search.py:\n{e}")
    def log_to_console(self, text: str):
        end_iter = self.console_buffer.get_end_iter()
        self.console_buffer.insert(end_iter, text + "\n")


    def on_refresh(self, _button=None):
        """
        Ping all servers concurrently without blocking the UI.
        """
        tasks = []
        for row in self.store:
            address = row[1]
            host = address.split(":")[0].strip()
            if host:
                tasks.append((row.iter, host))

        if not tasks:
            return

        def update_row_latency(treeiter, latency_ms):
            try:
                self.store[treeiter][3] = int(latency_ms)  # Ping column
            except Exception:
                pass
            return False

        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
            futures = [(treeiter, executor.submit(ping_host, host, 1)) for treeiter, host in tasks]
            for treeiter, fut in futures:
                try:
                    latency = fut.result()
                except Exception:
                    latency = 0
                GLib.idle_add(update_row_latency, treeiter, latency)

        self.save_config()

    def show_info(self, message):
        dialog = Gtk.MessageDialog(
            transient_for=self,
            flags=0,
            message_type=Gtk.MessageType.INFO,
            buttons=Gtk.ButtonsType.OK,
            text=message
        )
        dialog.run()
        dialog.destroy()


if __name__ == "__main__":
    win = BookmarksWindow()
    win.connect("destroy", Gtk.main_quit)
    win.show_all()
    Gtk.main()
