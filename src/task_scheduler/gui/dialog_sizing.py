"""Pure sizing helper shared by modal GUI dialogs."""

from PySide6.QtCore import QSize


def bounded_preferred_size(preferred: QSize, available_size: QSize | None) -> QSize:
    """Return a preferred size clamped to known available display space."""
    if available_size is None:
        return preferred
    return preferred.boundedTo(available_size)
