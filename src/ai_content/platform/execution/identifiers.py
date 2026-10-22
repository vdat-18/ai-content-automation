"""Deterministic identities for execution commands and dispatch attempts."""

from __future__ import annotations

import hashlib
import json
from uuid import NAMESPACE_URL, uuid5


def canonical_payload(payload: dict[str, object]) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def command_id_for(dedupe_key: str) -> str:
    return str(uuid5(NAMESPACE_URL, f"execution-command:{dedupe_key}"))


def execution_id_for(command_id: str, dispatch_generation: int) -> str:
    return str(uuid5(NAMESPACE_URL, f"celery-task:{command_id}:{dispatch_generation}"))


def outbox_id_for(command_id: str, dispatch_generation: int) -> str:
    return str(uuid5(NAMESPACE_URL, f"execution-outbox:{command_id}:{dispatch_generation}"))


def payload_checksum(payload: dict[str, object]) -> str:
    return hashlib.sha256(canonical_payload(payload).encode()).hexdigest()


__all__ = [
    "canonical_payload",
    "command_id_for",
    "execution_id_for",
    "outbox_id_for",
    "payload_checksum",
]
