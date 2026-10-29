#!/usr/bin/env python3
"""CornerNote GTK 3 / gtk-layer-shell daemon for KDE Plasma on Wayland."""

from __future__ import annotations

import datetime as dt
import os
import signal
import sys
import time
from pathlib import Path
from typing import Any

try:
    import gi
    gi.require_version("Gtk", "3.0")
    gi.require_version("Gdk", "3.0")
    gi.require_version("GtkLayerShell", "0.1")
    from gi.repository import Gdk, Gio, GLib, Gtk, GtkLayerShell as LayerShell
except (ImportError, ValueError) as exc:
    print("CornerNote requires PyGObject GTK 3 and gtk-layer-shell. "
          "On Fedora install python3-gobject python3-cairo gtk-layer-shell.",
          file=sys.stderr)
    raise SystemExit(1) from exc

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from ipc import start_server
from obsidian import append_to_file, write_note
from state import Mode, NoteState
from style import CONFIG_PATH, build_css, load_config, save_config
from style_editor import StyleEditor

Config = dict[str, Any]


class CornerNote(Gtk.Window):
    """Single overlay window; GTK owns all event and animation scheduling."""

    def __init__(self, config: Config) -> None:
        super().__init__(type=Gtk.WindowType.TOPLEVEL)
        self.config = config
        self.config_path = Path(os.environ.get("CORNERNOTE_CONFIG", CONFIG_PATH))
        self.state = NoteState()
        self.pointer_inside = False
        self.dropdown_open = False
        self.file_chooser_open = False
        self.expanded = False
        self.animation_source: int | None = None
        self.collapse_source: int | None = None
        self.theme_refresh_source: int | None = None
        self.animation_start = 0.0
        self.animation_from = 0
        self.animation_to = 0
        self.position_vertical_edge = LayerShell.Edge.TOP
        self.position_vertical_base = 0
        self.active_monitor: Any | None = None
        self.style_editor: StyleEditor | None = None
        self._updating_append_controls = False
        self._title_was_filepath = False

        self.set_title("CornerNote")
        self.set_name("cornernote")
        self.set_decorated(False)
        self.set_resizable(False)
        self.set_default_size(config["width"], config["height"])
        self.set_size_request(config["width"], config["height"])
        self.set_app_paintable(True)

        LayerShell.init_for_window(self)
        LayerShell.set_namespace(self, "cornernote")
        LayerShell.set_layer(self, LayerShell.Layer.OVERLAY)
        self._apply_position(initial=True)
        LayerShell.set_keyboard_interactivity(self, False)

        self._build_ui()
        self._install_css()
        self.add_events(Gdk.EventMask.ENTER_NOTIFY_MASK | Gdk.EventMask.LEAVE_NOTIFY_MASK)
        self.connect("enter-notify-event", self._on_enter)
        self.connect("leave-notify-event", self._on_leave)
        self.connect("key-press-event", self._on_key)
        self.connect("delete-event", self._on_delete)
        self.connect("realize", lambda *_: self._refresh_clock())
        self.show_all()
        self.dialog_box.hide()
        self.status_label.hide()
        self._watch_theme_files()
        self._clock_source = GLib.timeout_add_seconds(30, self._refresh_clock)

    def idle_margin(self) -> int:
        """Return the layer-shell margin that leaves the configured tab visible."""
        peek = round(self.config["height"] * self.config["idle_fraction"])
        return self.position_vertical_base - (self.config["height"] - peek)

    def _monitor_selection(self) -> tuple[Any | None, Any | None, int]:
        """Resolve the configured display and return its GDK index."""
        display = Gdk.Display.get_default()
        if display is None:
            return None, None, -1
        count = display.get_n_monitors()
        primary = display.get_primary_monitor()
        selected = self.config.get("monitor", "primary")
        if selected == "primary":
            monitor = primary or (display.get_monitor(0) if count else None)
        else:
            try:
                monitor = display.get_monitor(int(selected))
            except (TypeError, ValueError):
                monitor = None
            if monitor is None:
                monitor = primary or (display.get_monitor(0) if count else None)
        index = next((i for i in range(count) if display.get_monitor(i) == monitor), -1)
        return display, monitor, index

    def _populate_monitor_choices(self) -> None:
        """Refresh the settings list with currently connected displays."""
        combo = self.setting_widgets.get("monitor")
        if combo is None:
            return
        combo.remove_all()
        display = Gdk.Display.get_default()
        if display is None:
            combo.append("primary", "Primary display")
            return
        count = display.get_n_monitors()
        for index in range(count):
            monitor = display.get_monitor(index)
            if monitor is None:
                continue
            geometry = monitor.get_geometry()
            manufacturer = monitor.get_manufacturer() or ""
            model = monitor.get_model() or "Display"
            model_name = " ".join(part for part in (manufacturer, model) if part).strip()
            primary = monitor.is_primary()
            label = f"Screen {index + 1}: {model_name} · {geometry.width}×{geometry.height}"
            if primary:
                label += " · primary"
            combo.append(str(index), label)
        if count == 0:
            combo.append("primary", "Primary display")

    def _apply_position(self, initial: bool = False) -> None:
        """Anchor to a 3x3 screen reference, then apply signed pixel offsets."""
        if hasattr(self, "animation_source"):
            self._stop_animation()
        display, monitor, _monitor_index = self._monitor_selection()
        if monitor is not None:
            if initial or monitor != self.active_monitor:
                LayerShell.set_monitor(self, monitor)
                self.active_monitor = monitor
            geometry = monitor.get_geometry()
            screen_width, screen_height = geometry.width, geometry.height
        else:
            screen = Gdk.Screen.get_default()
            screen_width = screen.get_width() if screen else self.config["width"]
            screen_height = screen.get_height() if screen else self.config["height"]

        edges = (LayerShell.Edge.TOP, LayerShell.Edge.BOTTOM,
                 LayerShell.Edge.LEFT, LayerShell.Edge.RIGHT)
        for edge in edges:
            LayerShell.set_anchor(self, edge, False)
            LayerShell.set_margin(self, edge, 0)

        horizontal = self.config.get("position_horizontal", "right")
        if horizontal == "left":
            x_edge = LayerShell.Edge.LEFT
            x_margin = self.config.get("offset_x", 0)
        elif horizontal == "center":
            x_edge = LayerShell.Edge.LEFT
            x_margin = round((screen_width - self.config["width"]) / 2) + self.config.get("offset_x", 0)
        else:
            x_edge = LayerShell.Edge.RIGHT
            x_margin = self.config.get("margin_right", 20) - self.config.get("offset_x", 0)
        LayerShell.set_anchor(self, x_edge, True)
        LayerShell.set_margin(self, x_edge, int(x_margin))

        vertical = self.config.get("position_vertical", "top")
        if vertical == "top":
            y_edge = LayerShell.Edge.TOP
            y_margin = self.config.get("offset_y", 0)
        elif vertical == "center":
            y_edge = LayerShell.Edge.TOP
            y_margin = round((screen_height - self.config["height"]) / 2) + self.config.get("offset_y", 0)
        else:
            y_edge = LayerShell.Edge.BOTTOM
            y_margin = -self.config.get("offset_y", 0)
        LayerShell.set_anchor(self, y_edge, True)
        self.position_vertical_edge = y_edge
        self.position_vertical_base = int(y_margin)
        LayerShell.set_margin(self, y_edge,
                              self.idle_margin() if initial or not self.expanded
                              else self.position_vertical_base)

    def _build_ui(self) -> None:
        """Construct the note editor, status area, and root layout."""
        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        root.get_style_context().add_class("corner-note-root")

        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        header.get_style_context().add_class("cn-header")
        self.day_label = Gtk.Label(xalign=0)
        self.day_label.get_style_context().add_class("cn-day")
        header.pack_start(self.day_label, False, False, 2)
        header.pack_start(Gtk.Box(), True, True, 0)
        date_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.date_label = Gtk.Label(xalign=1)
        self.time_label = Gtk.Label(xalign=1)
        self.date_label.get_style_context().add_class("cn-date")
        self.time_label.get_style_context().add_class("cn-time")
        date_box.pack_start(self.date_label, False, False, 0)
        date_box.pack_start(self.time_label, False, False, 0)
        header.pack_end(date_box, False, False, 2)
        self.settings_button = Gtk.Button(label="[ ⚙ ]")
        self.settings_button.set_tooltip_text("CornerNote settings")
        self.settings_button.connect("clicked", lambda *_: self._show_settings())
        header.pack_end(self.settings_button, False, False, 4)
        root.pack_start(header, False, False, 0)

        separator = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        separator.get_style_context().add_class("cn-separator")
        root.pack_start(separator, False, False, 0)

        self.page_stack = Gtk.Stack()
        self.page_stack.set_transition_type(Gtk.StackTransitionType.NONE)
        root.pack_start(self.page_stack, True, True, 0)
        note_page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)

        self.title_entry = Gtk.Entry()
        self.title_entry.set_placeholder_text("Title…  (Enter for body)")
        self.title_entry.get_style_context().add_class("cn-title")
        self.title_entry.connect("activate", self._on_title_enter)
        self.title_entry.connect("changed", self._on_title_changed)
        note_page.pack_start(self.title_entry, False, False, 3)

        self.content_buffer = Gtk.TextBuffer()
        self.content_view = Gtk.TextView(buffer=self.content_buffer)
        self.content_view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self.content_view.set_left_margin(5)
        self.content_view.set_right_margin(5)
        self.content_view.get_style_context().add_class("cn-content")
        self.content_buffer.connect("changed", self._sync_draft)
        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroller.set_shadow_type(Gtk.ShadowType.IN)
        scroller.add(self.content_view)
        note_page.pack_start(scroller, True, True, 2)

        controls = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        self.date_mode_combo = Gtk.ComboBoxText()
        self.date_mode_combo.append("date", "Date")
        self.date_mode_combo.append("none", "No date")
        self.date_mode_combo.set_active_id("date")
        self.date_mode_combo.connect("changed", self._on_date_mode_changed)
        self.date_mode_combo.connect("notify::popup-shown", self._on_folder_popup)
        controls.pack_start(self.date_mode_combo, False, False, 0)
        self.date_entry = Gtk.Entry()
        self.date_entry.set_placeholder_text("today / tomorrow / 14.10 / none")
        self.date_entry.get_style_context().add_class("cn-date-entry")
        self.date_entry.connect("changed", self._on_date_entry_changed)
        controls.pack_start(self.date_entry, True, True, 0)
        self.folder_combo = Gtk.ComboBoxText()
        self.folder_combo.get_style_context().add_class("cn-folder")
        self.folder_combo.append_text("(root)")
        vault = Path(self.config["default_vault_path"])
        folders = set(self.config.get("folders", []))
        try:
            folders.update(child.name for child in vault.iterdir() if child.is_dir())
        except OSError:
            pass
        self.available_folders = sorted(
            f for f in folders if Path(f).name == f and f not in (".", ".."))
        for folder in self.available_folders:
            self.folder_combo.append_text(folder)
        self.folder_combo.set_active(0)
        self.folder_combo.connect("changed", self._sync_draft)
        self.folder_combo.connect("notify::popup-shown", self._on_folder_popup)
        controls.pack_start(self.folder_combo, False, False, 0)
        note_page.pack_start(controls, False, False, 1)

        append_options = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.append_mode_check = Gtk.CheckButton(label="Append mode")
        self.append_mode_check.set_tooltip_text(
            "Treat the title as a Markdown filepath inside your vault")
        self.append_mode_check.connect("toggled", self._on_append_checkbox_toggled)
        append_options.pack_start(self.append_mode_check, False, False, 0)
        note_page.pack_start(append_options, False, False, 0)

        footer = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        self.status_label = Gtk.Label(xalign=0)
        self.status_label.get_style_context().add_class("cn-status")
        footer.pack_start(self.status_label, True, True, 0)
        self.submit_mode_combo = Gtk.ComboBoxText()
        self.submit_mode_combo.append("note", "Vault note")
        self.submit_mode_combo.append("append", "Append to file")
        self.submit_mode_combo.set_active_id("note")
        self.submit_mode_combo.set_tooltip_text("Choose how this draft is submitted")
        self.submit_mode_combo.connect("changed", self._on_submit_mode_changed)
        footer.pack_end(self.submit_mode_combo, False, False, 0)
        self.save_button = Gtk.Button(label="[ Submit · Ctrl+Enter ]")
        self.save_button.get_style_context().add_class("cn-save")
        self.save_button.connect("clicked", lambda *_: self.commit_note())
        footer.pack_end(self.save_button, False, False, 0)
        note_page.pack_start(footer, False, False, 0)

        self.dialog_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.dialog_box.get_style_context().add_class("cn-dialog")
        self.dialog_box.pack_start(Gtk.Label(label="Discard draft?"), True, True, 2)
        self.discard_yes = Gtk.Button(label="[ Yes ]")
        no = Gtk.Button(label="[ No ]")
        self.discard_yes.connect("clicked", lambda *_: self._resolve_discard(True))
        no.connect("clicked", lambda *_: self._resolve_discard(False))
        self.dialog_box.pack_end(no, False, False, 0)
        self.dialog_box.pack_end(self.discard_yes, False, False, 0)
        note_page.pack_start(self.dialog_box, False, False, 0)
        self.page_stack.add_named(note_page, "note")
        self._build_settings_page()
        self.add(root)

    def _build_settings_page(self) -> None:
        """Construct the configuration editor page."""
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=7)
        page.get_style_context().add_class("cn-settings")
        heading = Gtk.Label(label="CornerNote Settings", xalign=0)
        heading.get_style_context().add_class("cn-day")
        page.pack_start(heading, False, False, 2)
        grid = Gtk.Grid(column_spacing=8, row_spacing=6)
        settings_scroll = Gtk.ScrolledWindow()
        settings_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        settings_scroll.add(grid)
        page.pack_start(settings_scroll, True, True, 0)
        self.setting_widgets: dict[str, Any] = {}

        def add_row(row: int, label: str, key: str, widget: Any) -> None:
            """Add a labeled control to the settings grid."""
            text = Gtk.Label(label=label, xalign=0)
            text.set_size_request(112, -1)
            grid.attach(text, 0, row, 1, 1)
            grid.attach(widget, 1, row, 1, 1)
            self.setting_widgets[key] = widget

        monitor_choice = Gtk.ComboBoxText()
        monitor_choice.get_style_context().add_class("cn-folder")
        monitor_choice.connect("notify::popup-shown", self._on_folder_popup)
        add_row(0, "Screen", "monitor", monitor_choice)
        horizontal = Gtk.ComboBoxText()
        horizontal.get_style_context().add_class("cn-folder")
        horizontal.connect("notify::popup-shown", self._on_folder_popup)
        for value, label in (("left", "Left"), ("center", "Center"), ("right", "Right")):
            horizontal.append(value, label)
        add_row(1, "Horizontal", "position_horizontal", horizontal)
        vertical = Gtk.ComboBoxText()
        vertical.get_style_context().add_class("cn-folder")
        vertical.connect("notify::popup-shown", self._on_folder_popup)
        for value, label in (("top", "Top"), ("center", "Center"), ("bottom", "Bottom")):
            vertical.append(value, label)
        add_row(2, "Vertical", "position_vertical", vertical)
        offset_x = Gtk.SpinButton.new_with_range(-5000, 5000, 10)
        offset_x.set_numeric(True)
        add_row(3, "X offset (px)", "offset_x", offset_x)
        offset_y = Gtk.SpinButton.new_with_range(-5000, 5000, 10)
        offset_y.set_numeric(True)
        add_row(4, "Y offset (px)", "offset_y", offset_y)
        width = Gtk.SpinButton.new_with_range(240, 1600, 20)
        width.set_numeric(True)
        add_row(5, "Width (px)", "width", width)
        height = Gtk.SpinButton.new_with_range(180, 1200, 20)
        height.set_numeric(True)
        add_row(6, "Height (px)", "height", height)
        peek = Gtk.SpinButton.new_with_range(1, 50, 1)
        peek.set_numeric(True)
        add_row(7, "Idle tab (%)", "idle_percent", peek)
        vault_entry = Gtk.Entry()
        vault_entry.set_placeholder_text("Path to your Obsidian vault")
        add_row(8, "Obsidian vault", "default_vault_path", vault_entry)
        filename_entry = Gtk.Entry()
        add_row(9, "Markdown filename", "note_filename", filename_entry)
        date_entry = Gtk.Entry()
        add_row(10, "Date format", "date_format", date_entry)
        animation = Gtk.SpinButton.new_with_range(100, 1200, 50)
        animation.set_numeric(True)
        add_row(11, "Slide speed (ms)", "anim_ms", animation)
        delay = Gtk.SpinButton.new_with_range(0, 3000, 100)
        delay.set_numeric(True)
        add_row(12, "Hide delay (ms)", "collapse_delay_ms", delay)
        style_button = Gtk.Button(label="[ Open style editor… ]")
        style_button.connect("clicked", lambda *_: self._open_style_editor())
        add_row(13, "Appearance", "style_editor", style_button)

        actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.settings_status = Gtk.Label(xalign=0)
        self.settings_status.get_style_context().add_class("cn-status")
        actions.pack_start(self.settings_status, True, True, 0)
        cancel = Gtk.Button(label="[ Cancel ]")
        cancel.connect("clicked", lambda *_: self._show_note_page())
        save = Gtk.Button(label="[ Save settings ]")
        save.get_style_context().add_class("cn-save")
        save.connect("clicked", lambda *_: self._save_settings())
        actions.pack_end(cancel, False, False, 0)
        actions.pack_end(save, False, False, 0)
        self.select_vault_button = Gtk.Button(label="[ Select vault folder… ]")
        self.select_vault_button.connect("clicked", lambda *_: self._choose_vault_folder())
        page.pack_end(self.select_vault_button, False, False, 0)
        page.pack_end(actions, False, False, 0)
        self.page_stack.add_named(page, "settings")

    def _show_settings(self) -> None:
        """Populate setting controls from the active configuration."""
        fields = self.setting_widgets
        self._populate_monitor_choices()
        _display, _monitor, monitor_index = self._monitor_selection()
        fields["monitor"].set_active_id(str(monitor_index) if monitor_index >= 0 else "primary")
        fields["default_vault_path"].set_text(self.config["default_vault_path"])
        fields["note_filename"].set_text(self.config["note_filename"])
        fields["date_format"].set_text(self.config["date_format"])
        fields["anim_ms"].set_value(self.config["anim_ms"])
        fields["collapse_delay_ms"].set_value(self.config["collapse_delay_ms"])
        fields["idle_percent"].set_value(round(self.config["idle_fraction"] * 100))
        fields["position_horizontal"].set_active_id(
            self.config.get("position_horizontal", "right"))
        fields["position_vertical"].set_active_id(
            self.config.get("position_vertical", "top"))
        fields["offset_x"].set_value(self.config.get("offset_x", 0))
        fields["offset_y"].set_value(self.config.get("offset_y", 0))
        fields["width"].set_value(self.config["width"])
        fields["height"].set_value(self.config["height"])
        self.settings_status.set_text("")
        self.page_stack.set_visible_child_name("settings")
        fields["default_vault_path"].grab_focus()

    def _show_note_page(self) -> None:
        """Return to the note editor and restore the active editing focus."""
        self.page_stack.set_visible_child_name("note")
        (self.content_view if self.state.mode == Mode.CONTENT else self.title_entry).grab_focus()

    def _save_settings(self) -> None:
        """Validate and persist settings before applying them to the window."""
        fields = self.setting_widgets
        new_config = dict(self.config)
        new_config["default_vault_path"] = os.path.expanduser(
            fields["default_vault_path"].get_text().strip())
        new_config["note_filename"] = fields["note_filename"].get_text().strip()
        new_config["date_format"] = fields["date_format"].get_text().strip()
        new_config["anim_ms"] = fields["anim_ms"].get_value_as_int()
        new_config["collapse_delay_ms"] = fields["collapse_delay_ms"].get_value_as_int()
        new_config["idle_fraction"] = fields["idle_percent"].get_value_as_int() / 100.0
        new_config["position_horizontal"] = fields["position_horizontal"].get_active_id() or "right"
        new_config["position_vertical"] = fields["position_vertical"].get_active_id() or "top"
        new_config["offset_x"] = fields["offset_x"].get_value_as_int()
        new_config["offset_y"] = fields["offset_y"].get_value_as_int()
        new_config["width"] = fields["width"].get_value_as_int()
        new_config["height"] = fields["height"].get_value_as_int()
        new_config["monitor"] = fields["monitor"].get_active_id() or "primary"
        if not new_config["default_vault_path"] or not new_config["note_filename"].endswith(".md"):
            self.settings_status.set_text("Enter a vault path and a .md filename.")
            return
        try:
            save_config(new_config, self.config_path)
        except OSError as exc:
            self.settings_status.set_text(f"Could not save settings: {exc}")
            return
        self.config.update(new_config)
        self.set_default_size(new_config["width"], new_config["height"])
        self.set_size_request(new_config["width"], new_config["height"])
        self.resize(new_config["width"], new_config["height"])
        self._apply_position()
        self._refresh_folder_choices()
        self._refresh_css()
        self.settings_status.set_text("Settings saved.")

    def _open_style_editor(self) -> None:
        """Present the independent appearance editor window."""
        if self.style_editor is None:
            self.style_editor = StyleEditor(self, self.config, self._apply_style_config)
        else:
            self.style_editor.set_config(self.config)
        self.style_editor.show_all()
        self.style_editor.present()

    def _apply_style_config(self, updated: Config) -> None:
        """Persist appearance settings and refresh the overlay stylesheet."""
        save_config(updated, self.config_path)
        self.config.update(updated)
        self._refresh_css()

    def _choose_vault_folder(self) -> None:
        """Use GTK's native folder chooser; Plasma routes it through its KDE portal."""
        dialog = Gtk.FileChooserNative.new(
            "Select Obsidian vault folder", self, Gtk.FileChooserAction.SELECT_FOLDER,
            "Select", "Cancel")
        current = self.setting_widgets["default_vault_path"].get_text().strip()
        if current and Path(current).is_dir():
            dialog.set_current_folder(current)
        self.file_chooser_open = True

        def response(native: Any, result: int) -> None:
            self.file_chooser_open = False
            if result == Gtk.ResponseType.ACCEPT:
                selected = native.get_filename()
                if selected:
                    self.setting_widgets["default_vault_path"].set_text(selected)
            native.destroy()
            if not self.pointer_inside and not self.state.forced_open:
                self._schedule_collapse()

        dialog.connect("response", response)
        self.active_folder_chooser = dialog
        dialog.show()

    def _refresh_folder_choices(self) -> None:
        """Refresh the optional direct-child vault folder selector."""
        active = self.folder_combo.get_active_text() or "(root)"
        model = self.folder_combo.get_model()
        model.clear()
        self.folder_combo.append_text("(root)")
        vault = Path(self.config["default_vault_path"])
        folders = set(self.config.get("folders", []))
        try:
            folders.update(child.name for child in vault.iterdir() if child.is_dir())
        except OSError:
            pass
        self.available_folders = sorted(
            f for f in folders if Path(f).name == f and f not in (".", ".."))
        for folder in self.available_folders:
            self.folder_combo.append_text(folder)
        self.folder_combo.set_active(0)
        for index, name in enumerate(["(root)"] + self.available_folders):
            if name == active:
                self.folder_combo.set_active(index)
                break

    def _on_folder_popup(self, combo: Any, _property: Any) -> None:
        """Keep the overlay open while a native combo menu is active."""
        self.dropdown_open = bool(combo.get_property("popup-shown"))
        if self.dropdown_open:
            self._cancel_collapse()
        elif not self.pointer_inside and not self.state.forced_open:
            self._schedule_collapse()

    def _watch_theme_files(self) -> None:
        """Watch KDE and Pywal palette files without polling."""
        self.theme_monitors: list[Any] = []
        config_home = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
        cache_home = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
        for directory in (config_home, cache_home / "wal"):
            if not directory.is_dir():
                continue
            try:
                monitor = Gio.File.new_for_path(str(directory)).monitor_directory(
                    Gio.FileMonitorFlags.WATCH_MOVES, None)
                monitor.connect("changed", self._on_theme_file_changed)
                self.theme_monitors.append(monitor)
            except GLib.Error:
                pass

    def _on_theme_file_changed(self, _monitor: Any, file: Any, *_args: Any) -> None:
        """Schedule a coalesced style refresh after a palette change."""
        if file and file.get_basename() in ("kdeglobals", "colors.json"):
            if getattr(self, "theme_refresh_source", None):
                GLib.source_remove(self.theme_refresh_source)
            self.theme_refresh_source = GLib.timeout_add(180, self._refresh_css_debounced)

    def _refresh_css_debounced(self) -> bool:
        """Refresh CSS once after a short palette-write debounce."""
        self.theme_refresh_source = None
        self._refresh_css()
        return GLib.SOURCE_REMOVE

    def _refresh_css(self) -> bool:
        """Rebuild CSS from current theme configuration."""
        self.css_provider.load_from_data(build_css(self.config).encode("utf-8"))
        return GLib.SOURCE_REMOVE

    def _install_css(self) -> None:
        """Install the initial theme on the default GDK screen."""
        self.css_provider = Gtk.CssProvider()
        self.css_provider.load_from_data(build_css(self.config).encode("utf-8"))
        Gtk.StyleContext.add_provider_for_screen(
            Gdk.Screen.get_default(), self.css_provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

    def _refresh_clock(self) -> bool:
        """Update the compact local date and time labels."""
        now = dt.datetime.now()
        self.day_label.set_text(now.strftime("%a"))
        self.date_label.set_text(now.strftime("%d.%m.%y"))
        self.time_label.set_text(now.strftime("%H:%M"))
        return GLib.SOURCE_CONTINUE

    def _sync_draft(self, *_args: Any) -> None:
        """Copy the editable GTK controls into persistent in-memory state."""
        draft = self.state.draft
        draft.title = self.title_entry.get_text()
        start, end = self.content_buffer.get_bounds()
        draft.content = self.content_buffer.get_text(start, end, True)
        draft.date_tag = self.date_entry.get_text()
        draft.folder = self.folder_combo.get_active_text() or "(root)"
        draft.append_mode = (self.append_mode_check.get_active()
                             or self._is_filepath_title(draft.title))
        self.status_label.hide()

    def _is_filepath_title(self, title: str) -> bool:
        """Recognize Markdown file paths entered in the title field."""
        return Path(os.path.expandvars(os.path.expanduser(title.strip()))).suffix.lower() == ".md"

    def _on_title_changed(self, _entry: Gtk.Entry) -> None:
        """Automatically enable append mode when the title is a Markdown path."""
        is_filepath = self._is_filepath_title(self.title_entry.get_text())
        if is_filepath:
            self._set_append_mode(True)
        elif self._title_was_filepath:
            self._set_append_mode(False)
        self._title_was_filepath = is_filepath
        self._sync_draft()

    def _set_append_mode(self, enabled: bool) -> None:
        """Keep the append checkbox and submit selector synchronized."""
        self._updating_append_controls = True
        self.append_mode_check.set_active(enabled)
        self.submit_mode_combo.set_active_id("append" if enabled else "note")
        self._updating_append_controls = False
        self._sync_draft()

    def _on_append_checkbox_toggled(self, _button: Gtk.CheckButton) -> None:
        """Mirror checkbox changes in the submit mode selector."""
        if not self._updating_append_controls:
            self._set_append_mode(self.append_mode_check.get_active())

    def _on_submit_mode_changed(self, combo: Gtk.ComboBoxText) -> None:
        """Mirror the selected submit action in the append checkbox."""
        if not self._updating_append_controls:
            self._set_append_mode(combo.get_active_id() == "append")

    def _on_date_mode_changed(self, combo: Gtk.ComboBoxText) -> None:
        """Set the date field to an explicit date or the no-date value."""
        no_date = combo.get_active_id() == "none"
        self.date_entry.set_sensitive(not no_date)
        expected = "none" if no_date else "today"
        current = self.date_entry.get_text().strip().casefold()
        if (current in ("none", "no date")) != no_date:
            self.date_entry.set_text(expected)
        self._sync_draft()

    def _on_date_entry_changed(self, _entry: Gtk.Entry) -> None:
        """Keep the date selector aligned when users type `none`."""
        value = self.date_entry.get_text().strip().casefold()
        expected = "none" if value in ("none", "no date") else "date"
        if self.date_mode_combo.get_active_id() != expected:
            self.date_mode_combo.set_active_id(expected)
        self._sync_draft()

    def _clear_editor(self) -> None:
        """Clear controls and return submission options to their defaults."""
        self.title_entry.set_text("")
        self.content_buffer.set_text("")
        self.date_mode_combo.set_active_id("date")
        self.date_entry.set_text("")
        self.folder_combo.set_active(0)
        self._set_append_mode(False)

    def _on_title_enter(self, _entry: Any) -> None:
        """Move focus from title to body when Enter is pressed."""
        self.state.begin_content()
        self.content_view.grab_focus()

    def _on_enter(self, _widget: Any, event: Any) -> bool:
        """Expand the note when the pointer enters its layer surface."""
        if event.detail == Gdk.NotifyType.INFERIOR:
            return False
        self.pointer_inside = True
        self._cancel_collapse()
        self.expand(focus=not self.expanded)
        return False

    def _on_leave(self, _widget: Any, event: Any) -> bool:
        """Schedule collapse after pointer and transient menus leave."""
        if event.detail == Gdk.NotifyType.INFERIOR:
            return False
        self.pointer_inside = False
        if (not self.dropdown_open and not self.file_chooser_open and not self.state.forced_open
                and self.state.mode != Mode.DISCARD_CONFIRM):
            self._schedule_collapse()
        return False

    def _animate_to(self, target: int) -> None:
        """Animate the active edge margin using GTK timeout callbacks."""
        self._stop_animation()
        edge = self.position_vertical_edge
        current = LayerShell.get_margin(self, edge)
        self.animation_from = current
        self.animation_to = target
        self.animation_start = time.monotonic()
        duration = max(1, self.config["anim_ms"]) / 1000.0

        def frame() -> bool:
            """Advance one animation frame and stop at the final position."""
            progress = min(1.0, (time.monotonic() - self.animation_start) / duration)
            eased = 1.0 - (1.0 - progress) ** 3
            value = round(self.animation_from + (self.animation_to - self.animation_from) * eased)
            LayerShell.set_margin(self, edge, value)
            if progress >= 1.0:
                self.animation_source = None
                return GLib.SOURCE_REMOVE
            return GLib.SOURCE_CONTINUE

        self.animation_source = GLib.timeout_add(16, frame)

    def _stop_animation(self) -> None:
        """Cancel a running margin animation if one exists."""
        if self.animation_source is not None:
            GLib.source_remove(self.animation_source)
            self.animation_source = None

    def _cancel_collapse(self) -> None:
        """Cancel a pending hide callback."""
        if self.collapse_source is not None:
            GLib.source_remove(self.collapse_source)
            self.collapse_source = None

    def _schedule_collapse(self) -> None:
        """Schedule a deferred collapse after pointer leave."""
        self._cancel_collapse()

        def finish() -> bool:
            """Collapse only if no pointer or forced-open state prevents it."""
            self.collapse_source = None
            if (not self.pointer_inside and not self.dropdown_open
                    and not self.file_chooser_open and not self.state.forced_open):
                self.collapse()
            return GLib.SOURCE_REMOVE

        delay = int(self.config.get("collapse_delay_ms", 700))
        if delay <= 0:
            finish()
        else:
            self.collapse_source = GLib.timeout_add(delay, finish)

    def expand(self, focus: bool = False) -> None:
        """Reveal the overlay and optionally focus the active editor."""
        self.expanded = True
        LayerShell.set_keyboard_interactivity(self, True)
        self._animate_to(self.position_vertical_base)
        if not focus or self.page_stack.get_visible_child_name() == "settings":
            return
        if self.state.mode == Mode.CONTENT:
            self.content_view.grab_focus()
        elif self.state.mode != Mode.DISCARD_CONFIRM:
            self.title_entry.grab_focus()

    def collapse(self) -> None:
        """Hide the overlay to its idle tab without changing the draft."""
        if self.dropdown_open:
            return
        self._cancel_collapse()
        self.expanded = False
        LayerShell.set_keyboard_interactivity(self, False)
        self._animate_to(self.idle_margin())

    def force_open(self) -> None:
        """Open the overlay and retain it until toggled closed."""
        self.state.forced_open = True
        LayerShell.set_keyboard_interactivity(self, True)
        self.present()
        self.expand(focus=True)

    def force_close(self) -> None:
        """Clear forced-open mode and collapse when the pointer is outside."""
        self.state.forced_open = False
        if not self.pointer_inside:
            self.collapse()

    def toggle(self) -> None:
        """Toggle the forced-open state for IPC commands."""
        self.force_close() if self.state.forced_open else self.force_open()

    def _on_key(self, _widget: Any, event: Any) -> bool:
        """Handle confirmation, escape, and Ctrl+Enter shortcuts."""
        key = event.keyval
        modifiers = event.state
        if self.state.mode == Mode.DISCARD_CONFIRM:
            if key in (Gdk.KEY_y, Gdk.KEY_Y):
                self._resolve_discard(True)
            elif key in (Gdk.KEY_n, Gdk.KEY_N, Gdk.KEY_Escape):
                self._resolve_discard(False)
            return True
        if key == Gdk.KEY_Escape:
            self._open_discard_prompt()
            return True
        if key in (Gdk.KEY_Return, Gdk.KEY_KP_Enter) and modifiers & Gdk.ModifierType.CONTROL_MASK:
            self.commit_note()
            return True
        return False

    def _open_discard_prompt(self) -> None:
        """Ask for confirmation before clearing a nonempty draft."""
        self._sync_draft()
        if not self.state.ask_discard():
            self.force_close()
            return
        self.dialog_box.show_all()
        self.discard_yes.grab_focus()

    def _resolve_discard(self, discard: bool) -> None:
        """Apply the chosen discard response and restore editor focus."""
        if discard:
            self.state.confirm_discard()
            self._clear_editor()
            self.force_close()
        else:
            self.state.cancel_discard()
            if self.state.mode == Mode.CONTENT:
                self.content_view.grab_focus()
            else:
                self.title_entry.grab_focus()
        self.dialog_box.hide()

    def commit_note(self) -> None:
        """Persist the current draft and clear it only after success."""
        self._sync_draft()
        draft = self.state.draft
        if not draft.has_content():
            self._show_status("Nothing to save.")
            return
        try:
            if draft.append_mode:
                destination = append_to_file(self.config, draft.title, draft.content,
                                              draft.date_tag, draft.folder)
            else:
                destination = write_note(self.config, draft.title, draft.content,
                                         draft.date_tag, draft.folder)
        except (OSError, ValueError, KeyError) as exc:
            self._show_status(f"Save failed: {exc}")
            print(f"[cornernote] save failed: {exc}", file=sys.stderr)
            return
        print(f"[cornernote] saved {destination}")
        self.state.committed()
        self._clear_editor()
        self.force_close()

    def _show_status(self, message: str) -> None:
        """Show an inline save result in the note footer."""
        self.status_label.set_text(message)
        self.status_label.show()

    def _on_delete(self, *_args: Any) -> bool:
        """Hide the persistent overlay instead of terminating the daemon."""
        self.force_close()
        return True


def main() -> int:
    """Start the GTK daemon and run its event loop."""
    if os.environ.get("XDG_SESSION_TYPE") not in (None, "wayland"):
        print("CornerNote requires a Wayland session (gtk-layer-shell).", file=sys.stderr)
        return 1
    try:
        config = load_config(os.environ.get("CORNERNOTE_CONFIG", CONFIG_PATH))
        window = CornerNote(config)
        socket_server = start_server(config["socket_path"], window.toggle)
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"[cornernote] startup failed: {exc}", file=sys.stderr)
        return 1

    def shutdown(*_args: Any) -> bool:
        """Release IPC resources and stop GTK on process termination."""
        try:
            socket_server.close()
            path = Path(config["socket_path"])
            if path.is_socket():
                path.unlink()
        except OSError:
            pass
        Gtk.main_quit()
        return GLib.SOURCE_REMOVE

    GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGINT, shutdown)
    GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGTERM, shutdown)
    Gtk.main()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
