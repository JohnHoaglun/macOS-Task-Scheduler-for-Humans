"""Unit tests for the managed job catalog (JobService, Increment 8)."""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

import pytest
from tests.conftest import FIXED_JOB_ID, make_job

from task_scheduler.application import (
    JobConflictError,
    JobNotFoundError,
    JobService,
)
from task_scheduler.application.job_service import (
    MANAGED_LABEL_PREFIX,
    default_job_logs_root,
    managed_label,
)
from task_scheduler.domain import (
    CalendarSchedule,
    ExecutableCommand,
    JobDefinition,
    PythonCommand,
    ShellCommand,
    Weekday,
)

OTHER_ID = UUID("87654321-4321-4321-4321-432143214321")


def seed(root: Path, *jobs: object) -> None:
    service = JobService(root)
    for job in jobs:
        service.import_job(job)  # type: ignore[arg-type]


def test_list_jobs_missing_root_returns_empty(tmp_path: Path) -> None:
    assert JobService(tmp_path / "nope").list_jobs() == []


def test_list_jobs_empty_root_returns_empty(tmp_path: Path) -> None:
    (tmp_path / "jobs").mkdir()
    assert JobService(tmp_path / "jobs").list_jobs() == []


def test_list_jobs_ignores_non_json_and_subdirectories(tmp_path: Path) -> None:
    root = tmp_path / "jobs"
    root.mkdir()
    (root / "notes.txt").write_text("not a job")
    (root / "nested").mkdir()
    (root / "nested" / f"{FIXED_JOB_ID}.json").write_text("{}")
    assert JobService(root).list_jobs() == []


def test_list_jobs_sorted_by_label(tmp_path: Path) -> None:
    root = tmp_path / "jobs"
    first = make_job(id=OTHER_ID, label="io.github.mactaskscheduler.user.b")
    second = make_job(label="io.github.mactaskscheduler.user.a")
    seed(root, first, second)
    jobs = JobService(root).list_jobs()
    assert [job.label for job in jobs] == [second.label, first.label]


def test_find_returns_job_or_none(tmp_path: Path) -> None:
    root = tmp_path / "jobs"
    job = make_job()
    seed(root, job)
    service = JobService(root)
    assert service.find(job.label) == job
    assert service.find("other.label") is None


def test_resolve_raises_for_unknown_label(tmp_path: Path) -> None:
    root = tmp_path / "jobs"
    seed(root, make_job())
    with pytest.raises(JobNotFoundError) as exc:
        JobService(root).resolve("missing.label")
    assert exc.value.label == "missing.label"


def test_import_job_creates_catalog_record(tmp_path: Path) -> None:
    service = JobService(tmp_path / "jobs")
    job = make_job()
    path = service.import_job(job)
    assert path == service.root / f"{FIXED_JOB_ID}.json"
    assert path.is_file()
    assert service.find(job.label) == job


def test_import_job_conflicts_on_existing_id(tmp_path: Path) -> None:
    root = tmp_path / "jobs"
    service = JobService(root)
    service.import_job(make_job())
    with pytest.raises(JobConflictError) as exc:
        service.import_job(make_job())
    assert exc.value.label == make_job().label
    assert exc.value.path == root / f"{FIXED_JOB_ID}.json"


def test_remove_is_idempotent(tmp_path: Path) -> None:
    service = JobService(tmp_path / "jobs")
    job = make_job()
    service.import_job(job)
    assert service.remove(job.id) is True
    assert service.remove(job.id) is False
    assert service.find(job.label) is None


def test_root_property_accepts_str_and_path(tmp_path: Path) -> None:
    assert JobService(str(tmp_path / "jobs")).root == tmp_path / "jobs"


def _python_command(tmp_path: Path, script_name: str = "backup.py") -> PythonCommand:
    return PythonCommand(
        interpreter=tmp_path / "bin" / "python",
        script=tmp_path / "scripts" / script_name,
    )


def _schedule() -> CalendarSchedule:
    return CalendarSchedule(times=["07:30"], weekdays={Weekday.MONDAY})


class TestManagedLabel:
    def test_daily_backup_uses_fixed_uuid_suffix(self) -> None:
        assert managed_label("Daily Backup", FIXED_JOB_ID) == (
            f"io.github.macos-task-scheduler.user.daily-backup-{FIXED_JOB_ID.hex[:8]}"
        )

    def test_punctuation_runs_collapse_to_single_dash(self) -> None:
        assert managed_label("My--Backup!! 2024", FIXED_JOB_ID) == (
            f"{MANAGED_LABEL_PREFIX}my-backup-2024-{FIXED_JOB_ID.hex[:8]}"
        )

    def test_blank_name_falls_back_to_task_slug(self) -> None:
        assert managed_label("   ", FIXED_JOB_ID) == (
            f"{MANAGED_LABEL_PREFIX}task-{FIXED_JOB_ID.hex[:8]}"
        )

    def test_non_ascii_letters_become_dashes_then_edge_trimmed(self) -> None:
        assert managed_label("Café", FIXED_JOB_ID) == (
            f"{MANAGED_LABEL_PREFIX}caf-{FIXED_JOB_ID.hex[:8]}"
        )


class TestNewManagedJob:
    def test_python_command_job_fields_and_paths(self, tmp_path: Path) -> None:
        service = JobService(tmp_path / "jobs")
        script = tmp_path / "scripts" / "backup.py"
        command = PythonCommand(
            interpreter=tmp_path / "bin" / "python",
            script=script,
            arguments=["--mode", "daily"],
        )
        job = service.new_managed_job(
            "Daily Backup", command, _schedule(), job_id=FIXED_JOB_ID
        )
        assert job.id == FIXED_JOB_ID
        assert job.label == managed_label("Daily Backup", FIXED_JOB_ID)
        assert job.name == "Daily Backup"
        assert job.enabled is True
        assert job.schema_version == 2
        assert job.working_directory == script.parent
        assert job.environment.variables == {}
        assert job.logging.stdout_path == (
            default_job_logs_root() / FIXED_JOB_ID.hex / "stdout.log"
        )
        assert job.logging.stderr_path == (
            default_job_logs_root() / FIXED_JOB_ID.hex / "stderr.log"
        )

    def test_nothing_is_persisted(self, tmp_path: Path) -> None:
        service = JobService(tmp_path / "jobs")
        job = service.new_managed_job(
            "Daily Backup",
            _python_command(tmp_path),
            _schedule(),
            job_id=FIXED_JOB_ID,
        )
        assert job.logging.stdout_path is not None
        assert not service.root.exists()
        assert not (default_job_logs_root() / FIXED_JOB_ID.hex).exists()

    def test_shell_and_executable_commands_have_no_working_directory(
        self, tmp_path: Path
    ) -> None:
        service = JobService(tmp_path / "jobs")
        commands = (
            ShellCommand(executable=tmp_path / "bin" / "zsh", arguments=["-c", "echo ok"]),
            ExecutableCommand(executable=tmp_path / "bin" / "tool"),
        )
        for command in commands:
            job = service.new_managed_job(
                "Job", command, _schedule(), job_id=FIXED_JOB_ID
            )
            assert job.working_directory is None

    def test_generated_ids_and_labels_differ(self, tmp_path: Path) -> None:
        service = JobService(tmp_path / "jobs")
        command = _python_command(tmp_path)
        first = service.new_managed_job("Same Name", command, _schedule())
        second = service.new_managed_job("Same Name", command, _schedule())
        assert first.id != second.id
        assert first.label != second.label

    def test_blank_name_raises_value_error(self, tmp_path: Path) -> None:
        service = JobService(tmp_path / "jobs")
        with pytest.raises(ValueError, match="name must not be blank"):
            service.new_managed_job("   ", _python_command(tmp_path), _schedule())


class TestSave:
    def test_save_creates_catalog_record(self, tmp_path: Path) -> None:
        service = JobService(tmp_path / "jobs")
        job = make_job()
        path = service.save(job)
        assert path == service.root / f"{FIXED_JOB_ID}.json"
        assert path.is_file()
        assert service.find(job.label) == job

    def test_save_overwrites_own_record_and_resolves_updated_name(
        self, tmp_path: Path
    ) -> None:
        service = JobService(tmp_path / "jobs")
        job = make_job()
        service.save(job)
        updated = job.model_copy(update={"name": "Daily Backup v2"})
        service.save(updated)
        files = [p.name for p in service.root.iterdir() if p.name.endswith(".json")]
        assert files == [f"{FIXED_JOB_ID}.json"]
        assert service.resolve(job.label).name == "Daily Backup v2"

    def test_save_conflicts_when_another_id_claims_the_label(self, tmp_path: Path) -> None:
        service = JobService(tmp_path / "jobs")
        job_a = make_job()
        service.save(job_a)
        job_b = job_a.model_copy(update={"id": OTHER_ID, "name": "Other"})
        assert job_b.label == job_a.label
        path_a = service.root / f"{FIXED_JOB_ID}.json"
        before = path_a.read_bytes()
        with pytest.raises(JobConflictError) as exc:
            service.save(job_b)
        assert exc.value.label == job_a.label
        assert path_a.read_bytes() == before
        files = [p.name for p in service.root.iterdir() if p.name.endswith(".json")]
        assert files == [path_a.name]

    def test_save_same_id_is_not_a_conflict(self, tmp_path: Path) -> None:
        service = JobService(tmp_path / "jobs")
        job_a = make_job()
        service.save(job_a)
        renamed = job_a.model_copy(update={"name": "A2"})
        path = service.save(renamed)
        assert path == service.root / f"{FIXED_JOB_ID}.json"
        files = [p for p in service.root.iterdir() if p.name.endswith(".json")]
        assert len(files) == 1
        assert service.resolve(job_a.label).name == "A2"

    def test_invalid_label_rejected_on_construction(self) -> None:
        # Pydantic v2 model_copy does not run validators, so the pinned
        # A.model_copy(update={"label": "bad label"}) case is asserted
        # through the equivalent JobDefinition construction of A's fields.
        job_a = make_job()
        fields = job_a.model_dump()
        fields["label"] = "bad label"
        with pytest.raises(ValueError, match="whitespace"):
            JobDefinition(**fields)
