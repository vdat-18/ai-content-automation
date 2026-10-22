"""JSON serialization for Creator outreach runs."""

from typing import cast

from pydantic import TypeAdapter

from ..domain.models import CreatorOutreachRun

_RUN_ADAPTER = TypeAdapter(CreatorOutreachRun)


def run_to_dict(run: CreatorOutreachRun) -> dict[str, object]:
    return cast(dict[str, object], _RUN_ADAPTER.dump_python(run, mode="json"))


def run_from_dict(data: dict[str, object]) -> CreatorOutreachRun:
    return _RUN_ADAPTER.validate_python(data)


__all__ = ["run_from_dict", "run_to_dict"]
