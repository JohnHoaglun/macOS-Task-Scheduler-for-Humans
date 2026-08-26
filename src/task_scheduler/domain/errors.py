"""Domain error types."""


class UnsupportedSchemaVersionError(Exception):
    """Raised when a job uses a schema version this build does not support.

    Inherits from Exception (not ValueError) so Pydantic propagates it
    unchanged instead of wrapping it in a ValidationError.
    """

    def __init__(self, found: int, supported: int) -> None:
        self.found = found
        self.supported = supported
        super().__init__(
            f"unsupported schema version {found}; this build supports version {supported}"
        )
