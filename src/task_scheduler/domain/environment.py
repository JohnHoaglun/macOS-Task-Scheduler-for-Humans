"""Environment configuration for scheduled jobs."""

from pydantic import BaseModel, Field


class EnvironmentConfig(BaseModel):
    """Environment variables injected into the job process.

    Empty by default. The application never populates these automatically,
    and no secrets support is provided.
    """

    variables: dict[str, str] = Field(default_factory=dict)
