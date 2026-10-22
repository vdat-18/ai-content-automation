"""JSON serialization for Email production records."""

from typing import cast

from pydantic import TypeAdapter

from ..domain.models import EmailProductionJob

_JOB_ADAPTER = TypeAdapter(EmailProductionJob)


def job_to_dict(job: EmailProductionJob) -> dict[str, object]:
    return cast(dict[str, object], _JOB_ADAPTER.dump_python(job, mode="json"))


def job_from_dict(data: dict[str, object]) -> EmailProductionJob:
    return _JOB_ADAPTER.validate_python(data)


__all__ = ["job_from_dict", "job_to_dict"]
