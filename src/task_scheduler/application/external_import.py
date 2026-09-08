"""External-plist import models: the read-only preview shared by CLI and GUI.

The preview carries the parser-normalized candidate job plus every warning and
unsupported key, so the caller can disclose them before importing. The
candidate's ``id`` is the parser's transient UUID and is never the durable
identity — commit regenerates it. Importing writes managed JSON only and never
touches the source plist (spec §61).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from task_scheduler.domain import JobDefinition


@dataclass(frozen=True, slots=True)
class ExternalPlistImportPreview:
    """A read-only preview of importing an external plist as a managed job.

    ``candidate`` is the parser-normalized job; its ``id`` is transient and is
    regenerated at commit. ``warnings`` and ``unsupported_keys`` are the full
    disclosure of everything the domain model could not represent; import
    requires explicit acknowledgement when either is non-empty.
    """

    source_path: Path
    candidate: JobDefinition
    warnings: tuple[str, ...]
    unsupported_keys: tuple[str, ...]
    requires_acknowledgement: bool
