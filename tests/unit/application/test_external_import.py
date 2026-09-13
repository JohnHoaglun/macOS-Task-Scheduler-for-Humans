"""Unit tests for external plist import (Stage 0 shared service surface).

Covers the read-only preview, the acknowledgement gate, the fresh-UUID catalog
commit, label-conflict rejection, and the create-only ``import_job`` guard.
Every case proves the source plist is untouched and nothing is deployed.
"""

from __future__ import annotations
