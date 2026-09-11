"""Application services for scheduled jobs (catalog, logs, testing, facade)."""

from __future__ import annotations

from task_scheduler.application.external_edit_models import (
    ExternalEditPhase,
    ExternalEditPreview,
    ExternalEditResult,
)
from task_scheduler.application.external_import import ExternalPlistImportPreview
from task_scheduler.application.job_service import (
    JobConflictError,
    JobNotFoundError,
    JobService,
    default_job_catalog_root,
)
from task_scheduler.application.log_service import JobLogs, LogService, LogStream
from task_scheduler.application.managed_json_transfer import (
    ManagedJsonImportPreview,
    StrictJsonDecodeError,
)
from task_scheduler.application.task_command_service import (
    InspectReport,
    InstallPhase,
    InstallResult,
    ListingKind,
    TaskCommandService,
    TaskListing,
    UninstallResult,
)
from task_scheduler.application.test_service import DirectTestResult, DirectTestService

__all__ = [
    "DirectTestResult",
    "DirectTestService",
    "ExternalEditPhase",
    "ExternalEditPreview",
    "ExternalEditResult",
    "ExternalPlistImportPreview",
    "InspectReport",
    "InstallPhase",
    "InstallResult",
    "JobConflictError",
    "JobLogs",
    "JobNotFoundError",
    "JobService",
    "ListingKind",
    "LogService",
    "LogStream",
    "ManagedJsonImportPreview",
    "StrictJsonDecodeError",
    "TaskCommandService",
    "TaskListing",
    "UninstallResult",
    "default_job_catalog_root",
]
