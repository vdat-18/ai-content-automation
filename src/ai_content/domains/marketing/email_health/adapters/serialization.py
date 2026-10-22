"""JSON serialization for Email Operations health records."""

from __future__ import annotations

from typing import cast

from pydantic import TypeAdapter

from ..domain.models import EmailHealthRun

_RUN_ADAPTER = TypeAdapter(EmailHealthRun)


def run_to_dict(run: EmailHealthRun) -> dict[str, object]:
    return cast(dict[str, object], _RUN_ADAPTER.dump_python(run, mode="json"))


def run_from_dict(data: dict[str, object]) -> EmailHealthRun:
    return _RUN_ADAPTER.validate_python(data)


__all__ = ["run_from_dict", "run_to_dict"]
