import gi
import requests
import os
import json

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk

API_URL = "https://api.battlemetrics.com/servers"
API_TOKEN = os.getenv("BATTLEMETRICS_TOKEN", "")  # načti token z prostředí
CONFIG_FILE = "config.json"


class SearchWindow(Gtk.Window):
    def __init__(self):
        super().__init__(title="Search DayZ Servers")
        self.set_default_size(850, 550)

        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        vbox.set_margin_top(10)
        vbox.set_margin_bottom(10)
        vbox.set_margin_start(10)
        vbox.set_margin_end(10)
        self.add(vbox)

        # Search bar
        search_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        self.entry_query = Gtk.Entry()
        self.entry_query.set_placeholder_text("Search by name...")
        self.btn_search = Gtk.Button(label="Search")
        self.btn_search.connect("clicked", self.on_search_clicked)
        search_box.pack_start(self.entry_query, True, True, 0)
        search_box.pack_start(self.btn_search, False, False, 0)
        vbox.pack_start(search_box, False, False, 0)

        # Results table – 7 sloupců včetně mapy
        self.store = Gtk.ListStore(str, str, int, int, int, int, str)
        self.treeview = Gtk.TreeView(model=self.store)
        self.treeview.set_headers_visible(True)

        def add_column(title, col_id):
            renderer = Gtk.CellRendererText()
            column = Gtk.TreeViewColumn(title, renderer, text=col_id)
            column.set_resizable(True)
            column.set_sort_column_id(col_id)  # umožní řazení kliknutím
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

        # Actions row
        actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        self.btn_save = Gtk.Button(label="Save selected to config")
        self.btn_save.connect("clicked", self.on_save_selected)
        actions.pack_start(self.btn_save, False, False, 0)
        vbox.pack_start(actions, False, False, 0)

        self.show_all()

    def on_search_clicked(self, _button):
        query = self.entry_query.get_text().strip()
        if not query:
            self.show_info("Enter a search term.")
            return

        if not API_TOKEN:
            self.show_info("Missing API token. Set BATTLEMETRICS_TOKEN environment variable.")
            return

        headers = {
            "Authorization": f"Bearer {API_TOKEN}",
            "Accept": "application/json",
        }
        params = {
            "filter[game]": "dayz",
            "filter[search]": query,
            "page[size]": 50,
        }

        try:
            resp = requests.get(API_URL, headers=headers, params=params, timeout=10)
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            self.show_info(f"Failed to fetch servers:\n{e}")
            return

        self.store.clear()
        for srv in data.get("data", []):
            attr = srv.get("attributes", {})
            details = attr.get("details", {})

            name = attr.get("name", "")
            address = attr.get("ip", "")
            game_port = attr.get("port", 2302)
            query_port = attr.get("queryPort", 27016)
            players = attr.get("players", 0)
            map_name = details.get("map", "")
            ping = 0  # API ping není dostupný

            self.store.append([
                name,
                address,
                int(players),
                int(ping),
                int(game_port),
                int(query_port),
                map_name,
            ])

    def get_selected_iter(self):
        selection = self.treeview.get_selection()
        model, treeiter = selection.get_selected()
        return model, treeiter

    def on_save_selected(self, _button):
        model, treeiter = self.get_selected_iter()
        if not treeiter:
            self.show_info("Please select a server from the list.")
            return

        server = {
            "name": model[treeiter][0],
            "address": model[treeiter][1],
            "players": int(model[treeiter][2]),
            "ping": int(model[treeiter][3]),
            "game_port": int(model[treeiter][4]),
            "query_port": int(model[treeiter][5]),
            "map": model[treeiter][6],
        }

        # načti existující config
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, "r") as f:
                    cfg = json.load(f)
            except Exception:
                cfg = {}
        else:
            cfg = {}

        cfg.setdefault("servers", [])
        cfg["servers"].append(server)

        try:
            with open(CONFIG_FILE, "w") as f:
                json.dump(cfg, f, indent=2)
            self.show_info("Server saved to config.json.")
        except Exception as e:
            self.show_info(f"Failed to save config:\n{e}")

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
    win = SearchWindow()
    win.connect("destroy", Gtk.main_quit)
    Gtk.main()
