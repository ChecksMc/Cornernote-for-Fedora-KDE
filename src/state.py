"""Draft data and the small, explicit interaction state machine."""

from dataclasses import dataclass
from enum import Enum, auto


class Mode(Enum):
    TITLE = auto()
    CONTENT = auto()
    DISCARD_CONFIRM = auto()


@dataclass(slots=True)
class Draft:
    """Store an in-memory draft independently of window visibility."""

    title: str = ""
    content: str = ""
    date_tag: str = ""
    folder: str = ""
    append_mode: bool = False

    def has_content(self) -> bool:
        """Return whether any user-authored draft field is nonempty."""
        return bool(self.title.strip() or self.content.strip())

    def clear(self) -> None:
        """Erase all draft fields after commit or confirmed discard."""
        self.title = ""
        self.content = ""
        self.date_tag = ""
        self.folder = ""
        self.append_mode = False


class NoteState:
    """Represent note-editing transitions shared by GTK handlers."""

    def __init__(self) -> None:
        self.draft = Draft()
        self.mode = Mode.TITLE
        self.forced_open = False

    def begin_content(self) -> None:
        """Move from title entry to content editing."""
        if self.mode != Mode.DISCARD_CONFIRM:
            self.mode = Mode.CONTENT

    def ask_discard(self) -> bool:
        """Enter confirmation mode; return whether confirmation is needed."""
        if not self.draft.has_content():
            return False
        self.mode = Mode.DISCARD_CONFIRM
        return True

    def cancel_discard(self) -> None:
        """Return to the editing mode appropriate for the current draft."""
        self.mode = Mode.CONTENT if self.draft.content else Mode.TITLE

    def confirm_discard(self) -> None:
        """Clear the draft after the user confirms discard."""
        self.draft.clear()
        self.mode = Mode.TITLE

    def committed(self) -> None:
        """Reset draft state after successful persistence."""
        self.draft.clear()
        self.mode = Mode.TITLE
        self.forced_open = False
