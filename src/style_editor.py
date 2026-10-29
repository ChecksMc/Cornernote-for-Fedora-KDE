"""Embedded GTK controls for editing and previewing CornerNote appearance."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from gi.repository import Gdk, Gtk, Pango

from style import Config, PALETTES, build_preview_css, get_palette, palette_options

COLOR_FIELDS: tuple[tuple[str, str], ...] = (
    ("background", "Paper"),
    ("foreground", "Text"),
    ("accent", "Accent"),
    ("muted", "Border and labels"),
    ("card", "Editor surface"),
)


class StyleEditor(Gtk.Box):
    """Embed theme, color, image, and font controls in the settings page."""

    def __init__(self, config: Config, on_apply: Callable[[Config], None],
                 on_popup_changed: Callable[[Any, Any], None],
                 on_chooser_changed: Callable[[bool], None]) -> None:
        """Create an inline editor and connect popup visibility handling."""
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.config = dict(config)
        self.on_apply = on_apply
        self.on_popup_changed = on_popup_changed
        self.on_chooser_changed = on_chooser_changed
        self._loading = False
        self.color_buttons: dict[str, Gtk.ColorButton] = {}
        self.preview_provider: Gtk.CssProvider | None = None

        self.set_border_width(10)
        self._build_ui()
        self._load_config()

    def _build_ui(self) -> None:
        """Build theme controls, color selectors, preview, and actions."""
        outer = self

        heading = Gtk.Label(label="CornerNote Style Editor", xalign=0)
        heading.get_style_context().add_class("cn-style-heading")
        outer.pack_start(heading, False, False, 0)

        grid = Gtk.Grid(column_spacing=10, row_spacing=7)
        outer.pack_start(grid, False, False, 0)

        self.source_combo = Gtk.ComboBoxText()
        for source, label in (("plasma", "Plasma colors"),
                              ("pywal", "Pywal colors"),
                              ("fallback", "Built-in theme"),
                              ("custom", "Custom colors")):
            self.source_combo.append(source, label)
        self.source_combo.connect("changed", self._on_source_changed)
        self.source_combo.connect("notify::popup-shown", self.on_popup_changed)
        self._add_control(grid, 0, "Color source", self.source_combo)

        self.palette_combo = Gtk.ComboBoxText()
        for palette_id, label in palette_options():
            self.palette_combo.append(palette_id, label)
        self.palette_combo.connect("changed", self._on_palette_changed)
        self.palette_combo.connect("notify::popup-shown", self.on_popup_changed)
        self._add_control(grid, 1, "Built-in palette", self.palette_combo)

        for row, (key, label) in enumerate(COLOR_FIELDS, start=2):
            color_button = Gtk.ColorButton()
            color_button.set_use_alpha(False)
            color_button.connect("color-set", self._on_color_changed)
            self.color_buttons[key] = color_button
            self._add_control(grid, row, label, color_button)

        self.font_button = Gtk.FontButton()
        self.font_button.set_use_size(False)
        self.font_button.connect("font-set", self._on_font_changed)
        self._add_control(grid, 7, "Font family", self.font_button)
        self.font_size = Gtk.SpinButton.new_with_range(8, 28, 1)
        self.font_size.set_numeric(True)
        self.font_size.connect("value-changed", self._on_font_changed)
        self._add_control(grid, 8, "Font size", self.font_size)

        image_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.image_entry = Gtk.Entry()
        self.image_entry.set_placeholder_text("Optional local backdrop image")
        self.image_entry.connect("changed", self._on_image_changed)
        image_row.pack_start(self.image_entry, True, True, 0)
        browse = Gtk.Button(label="Browse…")
        browse.connect("clicked", self._on_browse_image)
        image_row.pack_end(browse, False, False, 0)
        self._add_control(grid, 9, "Backdrop image", image_row)

        self.rounded_toggle = Gtk.CheckButton(label="Use rounded paper corners")
        self.rounded_toggle.connect("toggled", self._on_rounding_changed)
        self._add_control(grid, 10, "Paper shape", self.rounded_toggle)

        preview_frame = Gtk.Frame(label="Live preview")
        outer.pack_start(preview_frame, True, True, 0)
        self.preview = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.preview.get_style_context().add_class("cn-style-preview")
        self.preview.set_border_width(12)
        preview_frame.add(self.preview)
        self.preview_title = Gtk.Label(label="Thu · 29.10.26", xalign=0)
        self.preview_title.get_style_context().add_class("cn-style-accent")
        self.preview.pack_start(self.preview_title, False, False, 0)
        self.preview_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.preview_card.get_style_context().add_class("cn-style-card")
        self.preview.pack_start(self.preview_card, True, True, 0)
        self.preview_card.pack_start(Gtk.Label(label="Quick note title", xalign=0), False, False, 0)
        self.preview_card.pack_start(
            Gtk.Label(label="A small preview of your paper and editor colors.", xalign=0),
            False, False, 0)
        self.preview_status = Gtk.Label(label="Ctrl+Enter · Save note", xalign=0)
        self.preview_status.get_style_context().add_class("cn-style-accent")
        self.preview.pack_start(self.preview_status, False, False, 0)

        self.status = Gtk.Label(xalign=0)
        outer.pack_start(self.status, False, False, 0)
        actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        outer.pack_end(actions, False, False, 0)
        apply_button = Gtk.Button(label="Apply style")
        apply_button.get_style_context().add_class("cn-style-apply")
        apply_button.connect("clicked", self._on_apply)
        actions.pack_end(apply_button, False, False, 0)

    def _add_control(self, grid: Gtk.Grid, row: int, label: str,
                     widget: Gtk.Widget) -> None:
        """Attach a labeled control to the editor grid."""
        text = Gtk.Label(label=label, xalign=0)
        text.set_size_request(145, -1)
        grid.attach(text, 0, row, 1, 1)
        grid.attach(widget, 1, row, 1, 1)

    def _load_config(self) -> None:
        """Populate all editor controls from the saved configuration."""
        self._loading = True
        self.source_combo.set_active_id(str(self.config.get("theme_source", "plasma")))
        self.palette_combo.set_active_id(str(self.config.get("theme_fallback", "catppuccin_mocha")))
        current_palette = get_palette(self.config)
        for key, button in self.color_buttons.items():
            rgba = Gdk.RGBA()
            rgba.parse(str(current_palette.get(key, PALETTES["catppuccin_mocha"][key])))
            button.set_rgba(rgba)
        self.font_button.set_font_name(str(self.config.get("font_family", "Monospace")))
        self.font_size.set_value(int(self.config.get("font_size", 11)))
        self.image_entry.set_text(str(self.config.get("background_image", "")))
        self.rounded_toggle.set_active(bool(self.config.get("rounded_corners", False)))
        self._loading = False
        self._update_enabled_controls()
        self._refresh_preview()

    def set_config(self, config: Config) -> None:
        """Replace the editor baseline with the overlay's latest settings."""
        self.config = dict(config)
        self._load_config()

    def _current_palette(self) -> dict[str, str]:
        """Return color values currently shown in the editor controls."""
        palette: dict[str, str] = {}
        for key, button in self.color_buttons.items():
            rgba = button.get_rgba()
            red, green, blue = (round(channel * 255) for channel in
                                (rgba.red, rgba.green, rgba.blue))
            palette[key] = f"#{red:02x}{green:02x}{blue:02x}"
        return palette

    def _editor_config(self) -> Config:
        """Build the temporary config used to render the live preview."""
        config = dict(self.config)
        config["theme_source"] = self.source_combo.get_active_id() or "plasma"
        config["theme_fallback"] = self.palette_combo.get_active_id() or "catppuccin_mocha"
        config["custom_palette"] = self._current_palette()
        font_name = self.font_button.get_font_name() or "Monospace"
        font_description = Pango.FontDescription.from_string(font_name)
        config["font_family"] = font_description.get_family() or "Monospace"
        config["font_size"] = self.font_size.get_value_as_int()
        config["background_image"] = self.image_entry.get_text().strip()
        config["rounded_corners"] = self.rounded_toggle.get_active()
        return config

    def _refresh_preview(self) -> None:
        """Apply scoped CSS to the preview without changing the overlay."""
        screen = self.preview.get_screen()
        if screen is None:
            screen = Gdk.Screen.get_default()
        if screen is None:
            return
        if self.preview_provider is not None:
            Gtk.StyleContext.remove_provider_for_screen(screen, self.preview_provider)
        provider = Gtk.CssProvider()
        provider.load_from_data(build_preview_css(self._editor_config()).encode("utf-8"))
        Gtk.StyleContext.add_provider_for_screen(
            screen, provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION + 1)
        self.preview_provider = provider

    def _update_enabled_controls(self) -> None:
        """Enable palette controls only for built-in and custom sources."""
        source = self.source_combo.get_active_id()
        self.palette_combo.set_sensitive(source == "fallback")
        for button in self.color_buttons.values():
            button.set_sensitive(source == "custom")

    def _on_source_changed(self, _combo: Gtk.ComboBoxText) -> None:
        """Update source-specific controls and refresh the preview."""
        if self._loading:
            return
        self._update_enabled_controls()
        self._refresh_preview()

    def _on_palette_changed(self, _combo: Gtk.ComboBoxText) -> None:
        """Load the selected preset colors and preview the built-in theme."""
        if self._loading:
            return
        palette_id = self.palette_combo.get_active_id() or "catppuccin_mocha"
        self._loading = True
        for key, button in self.color_buttons.items():
            rgba = Gdk.RGBA()
            rgba.parse(PALETTES[palette_id][key])
            button.set_rgba(rgba)
        self.source_combo.set_active_id("fallback")
        self._loading = False
        self._update_enabled_controls()
        self._refresh_preview()

    def _on_color_changed(self, _button: Gtk.ColorButton) -> None:
        """Switch to custom colors after the user edits a palette color."""
        if self._loading:
            return
        self.source_combo.set_active_id("custom")
        self._update_enabled_controls()
        self._refresh_preview()

    def _on_font_changed(self, _widget: Gtk.Widget) -> None:
        """Update the preview after the selected installed font changes."""
        if not self._loading:
            self._refresh_preview()

    def _on_image_changed(self, _entry: Gtk.Entry) -> None:
        """Refresh the backdrop preview when its image path changes."""
        if not self._loading:
            self._refresh_preview()

    def _on_rounding_changed(self, _button: Gtk.CheckButton) -> None:
        """Refresh the preview when paper corner rounding changes."""
        if not self._loading:
            self._refresh_preview()

    def _on_browse_image(self, _button: Gtk.Button) -> None:
        """Open a native image selector for the paper backdrop."""
        parent = self.get_toplevel()
        dialog = Gtk.FileChooserDialog(
            title="Select paper backdrop", parent=parent,
            action=Gtk.FileChooserAction.OPEN,
            buttons=("Cancel", Gtk.ResponseType.CANCEL,
                     "Select", Gtk.ResponseType.ACCEPT))
        dialog.set_modal(True)
        current = self.image_entry.get_text().strip()
        if current:
            candidate = Path(current).expanduser()
            if candidate.is_file():
                dialog.set_filename(str(candidate))
            elif candidate.parent.is_dir():
                dialog.set_current_folder(str(candidate.parent))
        image_filter = Gtk.FileFilter()
        image_filter.set_name("Images")
        image_filter.add_pixbuf_formats()
        dialog.add_filter(image_filter)
        self.on_chooser_changed(True)

        def response(chooser: Gtk.FileChooserDialog, result: int) -> None:
            """Store the selected image path and close the GTK picker."""
            if result == Gtk.ResponseType.ACCEPT:
                selected = chooser.get_filename()
                if selected:
                    self.image_entry.set_text(selected)
            self.on_chooser_changed(False)
            chooser.destroy()

        dialog.connect("response", response)
        self.active_file_chooser = dialog
        dialog.show_all()

    def _on_apply(self, _button: Gtk.Button) -> None:
        """Persist edited appearance and report write failures inline."""
        updated = self._editor_config()
        try:
            self.on_apply(updated)
        except (OSError, ValueError) as exc:
            self.status.set_text(f"Could not apply style: {exc}")
            return
        self.config.update(updated)
        self.status.set_text("Style saved.")
