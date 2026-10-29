"""Configuration loading and compact pixel-art GTK styling."""

from __future__ import annotations

import configparser
import json
import os
import tempfile
from pathlib import Path
from typing import Any, Callable

Config = dict[str, Any]
Palette = dict[str, str]

CONFIG_DIR = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "cornernote"
CONFIG_PATH = CONFIG_DIR / "config.json"
DEFAULTS: Config = {
    "width": 380, "height": 340, "idle_fraction": 0.04,
    "margin_right": 20,
    "position_horizontal": "right", "position_vertical": "top",
    "offset_x": 0, "offset_y": 0,
    "monitor": "primary",
    "socket_path": "${XDG_RUNTIME_DIR}/cornernote.sock",
    "default_vault_path": "~/Documents",
    "note_filename": "QuickNotes.md", "date_format": "%Y-%m-%d",
    "font_family": "Monospace", "font_size": 11, "anim_ms": 320,
    "collapse_delay_ms": 700, "theme_source": "plasma",
    "theme_fallback": "catppuccin_mocha", "folders": [],
}
PALETTES: dict[str, Palette] = {
    "catppuccin_mocha": {"background": "#1e1e2e", "foreground": "#cdd6f4",
                          "accent": "#89b4fa", "muted": "#6c7086", "card": "#313244"},
    "retro_green": {"background": "#0a0f0a", "foreground": "#b8ffb8",
                    "accent": "#42e66c", "muted": "#4d8055", "card": "#101b12"},
}


def _expand(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    if "${XDG_RUNTIME_DIR}" in value and not os.environ.get("XDG_RUNTIME_DIR"):
        value = value.replace("${XDG_RUNTIME_DIR}", f"/tmp/cornernote-{os.getuid()}")
    return os.path.expandvars(os.path.expanduser(value))


def load_config(path: str | Path | None = None) -> Config:
    config = dict(DEFAULTS)
    path = Path(path or CONFIG_PATH)
    supplied: Config = {}
    try:
        with path.open(encoding="utf-8") as stream:
            supplied = json.load(stream)
        if not isinstance(supplied, dict):
            raise ValueError("configuration root must be a JSON object")
        config.update(supplied)
    except FileNotFoundError:
        pass
    except (json.JSONDecodeError, OSError, ValueError) as exc:
        raise ValueError(f"Cannot read configuration {path}: {exc}") from exc
    if "collapse_delay_ms" not in supplied and config["anim_ms"] == 140:
        config["anim_ms"] = 320
    if "position_horizontal" not in supplied and config["idle_fraction"] == 0.10:
        config["idle_fraction"] = 0.04
    config["socket_path"] = _expand(config["socket_path"])
    config["default_vault_path"] = _expand(config["default_vault_path"])
    for key in ("width", "height", "font_size", "anim_ms"):
        config[key] = int(config[key])
        if config[key] <= 0:
            raise ValueError(f"{key} must be greater than zero")
    config["idle_fraction"] = min(0.5, max(0.01, float(config["idle_fraction"])))
    if config.get("position_horizontal") not in ("left", "center", "right"):
        config["position_horizontal"] = "right"
    if config.get("position_vertical") not in ("top", "center", "bottom"):
        config["position_vertical"] = "top"
    config["offset_x"] = int(config.get("offset_x", 0))
    config["offset_y"] = int(config.get("offset_y", 0))
    monitor = str(config.get("monitor", "primary")).strip()
    if monitor != "primary":
        try:
            if int(monitor) < 0:
                raise ValueError
        except ValueError:
            monitor = "primary"
    config["monitor"] = monitor
    config["collapse_delay_ms"] = max(0, int(config.get("collapse_delay_ms", 700)))
    if config.get("theme_source") not in ("plasma", "pywal", "fallback"):
        config["theme_source"] = "plasma"
    config["folders"] = list(config.get("folders") or [])
    return config


def save_config(config: Config, path: str | Path = CONFIG_PATH) -> None:
    """Write settings atomically so a partial write cannot corrupt config.json."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    safe = {key: value for key, value in config.items() if not key.startswith("_")}
    fd, temporary = tempfile.mkstemp(prefix=".config.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(safe, stream, indent=2, ensure_ascii=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except Exception:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def _valid_color(value: Any) -> str | None:
    if isinstance(value, str) and len(value) == 7 and value.startswith("#"):
        try:
            int(value[1:], 16)
            return value
        except ValueError:
            return None
    return None


def _plasma_palette() -> Palette | None:
    """Read the active Plasma color scheme from kdeglobals."""
    parser = configparser.ConfigParser(interpolation=None)
    kde_path = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "kdeglobals"
    try:
        parser.read(kde_path, encoding="utf-8")
        view = parser["Colors:View"]
        window = parser["Colors:Window"]

        def rgb(section: configparser.SectionProxy, key: str, fallback: str) -> str:
            parts = [int(n.strip()) for n in section.get(key, "").split(",")]
            return ("#%02x%02x%02x" % tuple(max(0, min(255, n)) for n in parts[:3])
                    if len(parts) >= 3 else fallback)

        return {"background": rgb(view, "BackgroundNormal", "#1e1e2e"),
                "foreground": rgb(view, "ForegroundNormal", "#cdd6f4"),
                "accent": rgb(window, "DecorationFocus", "#89b4fa"),
                "muted": rgb(view, "ForegroundInactive", "#6c7086"),
                "card": rgb(view, "BackgroundAlternate", "#313244")}
    except (OSError, KeyError, ValueError):
        return None


def _pywal_palette() -> Palette | None:
    wal_path = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "wal/colors.json"
    try:
        data = json.loads(wal_path.read_text(encoding="utf-8"))
        special, colors = data.get("special", {}), data.get("colors", {})
        palette = {
            "background": special.get("background"), "foreground": special.get("foreground"),
            "accent": colors.get("color4"), "muted": colors.get("color8"),
            "card": colors.get("color0"),
        }
        if all(_valid_color(color) for color in palette.values()):
            return palette
    except (OSError, ValueError, TypeError, AttributeError):
        return None
    return None


def get_palette(config: Config) -> Palette:
    source = config.get("theme_source", "plasma")
    order: tuple[Callable[[], Palette | None], ...] = {
        "plasma": (_plasma_palette, _pywal_palette),
        "pywal": (_pywal_palette, _plasma_palette),
        "fallback": (),
    }.get(source, (_plasma_palette, _pywal_palette))
    for loader in order:
        palette = loader()
        if palette:
            return palette
    return PALETTES.get(config.get("theme_fallback"), PALETTES["catppuccin_mocha"])


def _contrast_color(color: str, background: str) -> str:
    """Guard text legibility if a Plasma scheme provides an unusual pair."""
    def luminance(value: str) -> float:
        channels = [int(value[index:index + 2], 16) / 255 for index in (1, 3, 5)]
        linear = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
                  for c in channels]
        return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]
    try:
        a, b = luminance(color), luminance(background)
        if (max(a, b) + 0.05) / (min(a, b) + 0.05) >= 4.5:
            return color
        return "#ffffff" if b < 0.45 else "#111111"
    except (TypeError, ValueError):
        return color


def build_css(config: Config) -> str:
    palette = get_palette(config)
    palette = dict(palette)
    palette["foreground"] = _contrast_color(palette["foreground"], palette["card"])
    font = str(config.get("font_family", "Monospace")).replace('"', "")
    size = int(config.get("font_size", 11))
    return f"""
window, .corner-note-root {{ background-color: {palette['background']}; color: {palette['foreground']};
  font-family: "{font}", monospace; font-size: {size}px; border-radius: 0; }}
.corner-note-root {{ border: 3px solid {palette['muted']}; padding: 5px;
  background-image: linear-gradient(45deg, alpha({palette['foreground']}, 0.025) 25%, transparent 25%, transparent 75%, alpha({palette['foreground']}, 0.025) 75%); }}
.cn-header {{ padding: 2px 5px 5px; }}
.cn-day {{ color: {palette['accent']}; font-weight: bold; font-size: {size + 2}px; }}
.cn-date, .cn-time {{ color: {palette['muted']}; font-size: {max(8, size - 2)}px; }}
.cn-separator {{ background-color: {palette['accent']}; min-height: 2px; }}
.cn-title, .cn-date-entry, entry, entry text {{ color: {palette['foreground']}; background-color: {palette['card']}; border: 2px solid {palette['muted']}; border-radius: 0; box-shadow: none; padding: 5px; caret-color: {palette['accent']}; }}
.cn-title {{ font-weight: bold; font-size: {size + 2}px; }}
.cn-content, .cn-content text, textview, textview text {{ color: {palette['foreground']}; background-color: {palette['card']}; caret-color: {palette['accent']}; }}
.cn-folder, .cn-folder menu, .cn-folder menuitem {{ color: {palette['foreground']}; background-color: {palette['card']}; }}
.cn-save {{ background-color: {palette['accent']}; color: {palette['background']}; border: 2px solid {palette['foreground']}; border-radius: 0; font-weight: bold; }}
.cn-muted {{ color: {palette['muted']}; }}
.cn-dialog {{ background-color: {palette['card']}; border: 2px dashed {palette['accent']}; padding: 5px; }}
.cn-status {{ color: {palette['accent']}; padding: 2px 5px; }}
.cn-settings label {{ color: {palette['foreground']}; }}
"""
