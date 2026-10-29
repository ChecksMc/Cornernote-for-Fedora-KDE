# CornerNote

CornerNote is a small GTK 3 quick-note overlay for KDE Plasma on Wayland. It
peeks from the top-right edge, keeps a draft in memory while it is collapsed,
and appends notes to Markdown files in an Obsidian vault.

CornerNote requires a Wayland compositor with the `wlr-layer-shell` protocol.
Fedora KDE Spin with Plasma provides the supported session. Fedora Workstation
uses GNOME Shell/Mutter, which does not expose layer-shell or allow applications
to place ordinary windows at exact screen coordinates under Wayland; this
project does not claim support for GNOME Workstation overlays.

## Requirements

- Fedora KDE Plasma running a Wayland session
- Python 3, PyGObject, GTK 3, Cairo, and gtk-layer-shell
- An Obsidian vault writable by your user

On Fedora, install the system packages with:

```sh
sudo dnf install python3 python3-gobject python3-cairo gtk-layer-shell
```

The overlay cannot run as a layer-shell surface on X11. Check with
`printf '%s\n' "$XDG_SESSION_TYPE"` and use a Wayland Plasma session.

## Install

```sh
./install.sh
```

The installer checks dependencies, installs a user-level launcher and systemd
service, copies `config.example.json` to
`~/.config/cornernote/config.json` if no config exists, and enables the service
for the graphical session. Start it with `systemctl --user start cornernote`.
The service uses the current checkout, so keep this repository in place after
installing.

Remove the service and launchers with `./uninstall.sh`. This preserves your
settings by default; use `./uninstall.sh --purge-config` to delete them too.

Use `corner-note toggle` to open or close CornerNote. To bind a KDE global
shortcut, open **System Settings → Shortcuts → Add New → Command or URL** and
set the command to `corner-note toggle` with a shortcut such as Meta+N or F12.
This manual route works across Plasma versions.

## Use

- Hover the exposed paper tab to open it. Moving the pointer away collapses it.
- Press Meta+N (or your configured shortcut) to open and focus the note. The
  shortcut toggles the forced-open state.
- Enter in the title field moves focus to the note body.
- Ctrl+Enter appends the draft to the vault.
- Escape opens an inline discard confirmation. Confirm with Y/Yes or cancel
  with N/No/Escape.
- The gear button opens settings for the vault, filename/date format, timing,
  tab peek, and color source. Changes save to the user config immediately.

Collapsing the overlay never clears a draft. A draft is cleared only after a
successful write or a confirmed discard. Write failures remain visible in the
overlay and preserve the text for retry.

## Configuration

Open the overlay and press the gear button for the in-app settings page, or
edit `~/.config/cornernote/config.json`. Settings are written atomically. The
full template and defaults are in
[`config.example.json`](config.example.json). `note_filename` supports
`{date}` and `{title}` substitutions, for example `QuickNotes.md` or
`{date}.md`. Date tags accept `today`, `tomorrow`, weekday names, `in N days`,
and common numeric date forms. Position uses `position_horizontal` and
`position_vertical` (`left`/`center`/`right` and `top`/`center`/`bottom`);
`offset_x` and `offset_y` tune that reference point in pixels. Positive X
moves right and positive Y moves down. `monitor` selects `primary` or a
connected screen by its zero-based GDK display index; the settings page lists
each screen's model and resolution. The settings page also includes a folder
chooser; under Plasma, GTK uses the available KDE file chooser portal.

The default vault path is `~/Documents`. Change it in settings to the root of
your own Obsidian vault before saving notes.

By default, colors follow Plasma's `kdeglobals` palette. CornerNote watches
for Plasma palette changes while running. The settings page can instead select
Pywal colors or the configured built-in palette. Text contrast is corrected
when a selected palette would make note text hard to read. The hide delay and
slide duration are adjustable in settings; defaults are 700 ms and 320 ms.

## Files

- `src/main.py` — GTK layer-shell overlay and daemon entry point
- `src/state.py` — draft buffer and note interaction state machine
- `src/style.py` — config, Pywal/KDE palette loading, and GTK CSS
- `src/ipc.py` — GLib-integrated Unix socket server and CLI client
- `src/obsidian.py` — safe Markdown path selection and append writer
- `corner-note` — IPC command-line client
- `install.sh` — Fedora user installation
- `uninstall.sh` — removes user service and launchers, optionally config
- `packaging/bundle.py` — builds a distributable `CornerNote.zip`

## Development and troubleshooting

Run `python3 src/main.py` from the checkout to see errors in a terminal. In a
second terminal use `./corner-note toggle`. Inspect service logs with
`journalctl --user -u cornernote -f`. The socket defaults to
`$XDG_RUNTIME_DIR/cornernote.sock`, which is private to the login session.

Layer-shell overlay surfaces can cover panels and fullscreen windows by
design. Plasma may apply its own policy to overlay surfaces; the app does not
poll KWin state or promise fullscreen suppression.
