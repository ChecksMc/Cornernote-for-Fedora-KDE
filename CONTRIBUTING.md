# Contributing

Run CornerNote from a checkout in a supported Wayland session after installing
the dependencies listed in the README:

```sh
python3 src/main.py
```

Run the headless smoke tests with pytest:

```sh
python3 -m pytest tests/
```

The source modules are:

- `src/main.py` — GTK layer-shell overlay and daemon entry point.
- `src/state.py` — draft buffer and note interaction state machine.
- `src/obsidian.py` — Markdown path selection and append writer.
- `src/ipc.py` — GLib-integrated Unix socket server and client.
- `src/style.py` — configuration, palette loading, and GTK CSS.
- `src/style_editor.py` — appearance editor and live preview.

To contribute, fork the repository, create a branch, make and test your
changes, and open a pull request against `main`. Describe the change and how
you tested it; include screenshots for visible interface changes when useful.
