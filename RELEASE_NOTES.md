# v0.1.0 — Initial public release

CornerNote is a GTK 3 quick-note overlay for KDE Plasma on Wayland. It keeps a
draft in memory while collapsed and appends notes to Markdown files in an
Obsidian vault.

## Requirements

- Fedora KDE Plasma running a Wayland session
- Python 3, PyGObject, GTK 3, Cairo, and gtk-layer-shell
- An Obsidian vault writable by your user

On Fedora, install the system packages with:

```sh
sudo dnf install python3 python3-gobject python3-cairo gtk-layer-shell
```

## Known limitations

- KWin's `wlr-layer-shell` implementation has known quirks: overlay surfaces
  may not suppress fullscreen windows on all Plasma versions, and behavior may
  differ between Plasma 5.x and 6.x. See the [KDE bug tracker query for
  `wlr-layer-shell`](https://bugs.kde.org/buglist.cgi?quicksearch=wlr-layer-shell).
- GTK 3 is in maintenance mode; a GTK 4 or Qt port is a long-term consideration.
- X11 is unsupported.

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
