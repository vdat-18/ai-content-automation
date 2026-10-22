"""Typed Runpod Serverless queue client for non-generation GPU services."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError


class RunpodServerlessError(RuntimeError):
    """Raised when a Runpod Serverless job cannot return a valid result."""


class _SubmitResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str = Field(min_length=1)


class _JobResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    status: str = Field(min_length=1)
    output: dict[str, Any] | None = None
    error: str | None = None


class RunpodServerlessClient:
    """Submit one bounded async job and return its object output."""

    def __init__(
        self,
        endpoint_id: str,
        api_key: str,
        *,
        timeout_seconds: float,
        max_request_bytes: int = 9_000_000,
        poll_interval_seconds: float = 2.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._base_url = f"https://api.runpod.ai/v2/{endpoint_id}"
        self._api_key = api_key
        self._timeout_seconds = timeout_seconds
        self._max_request_bytes = max_request_bytes
        self._poll_interval_seconds = poll_interval_seconds
        self._transport = transport

    async def invoke(self, provider_input: dict[str, Any]) -> dict[str, Any]:
        body = json.dumps(
            {"input": provider_input}, separators=(",", ":"), ensure_ascii=True
        ).encode("utf-8")
        if len(body) > self._max_request_bytes:
            raise RunpodServerlessError("Runpod verifier request exceeds the 9 MB safety limit")
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        timeout = httpx.Timeout(self._timeout_seconds, connect=10)
        try:
            async with httpx.AsyncClient(
                base_url=self._base_url,
                headers=headers,
                timeout=timeout,
                transport=self._transport,
                follow_redirects=False,
                trust_env=False,
            ) as client:
                async with asyncio.timeout(self._timeout_seconds):
                    response = await client.post("/run", content=body)
                    response.raise_for_status()
                    job_id = _SubmitResponse.model_validate_json(response.content).id
                    while True:
                        await asyncio.sleep(self._poll_interval_seconds)
                        response = await client.get(f"/status/{job_id}")
                        response.raise_for_status()
                        job = _JobResponse.model_validate_json(response.content)
                        status = job.status.upper()
                        if status == "COMPLETED":
                            if job.output is None:
                                raise RunpodServerlessError(
                                    "Runpod verifier completed without an output object"
                                )
                            return job.output
                        if status in {"CANCELLED", "FAILED", "TIMED_OUT"}:
                            raise RunpodServerlessError(
                                f"Runpod verifier job ended with status {status}"
                            )
                        if status not in {"IN_QUEUE", "IN_PROGRESS"}:
                            raise RunpodServerlessError(
                                f"Runpod verifier returned unknown status {status}"
                            )
        except RunpodServerlessError:
            raise
        except (TimeoutError, httpx.HTTPError, ValidationError, ValueError) as error:
            raise RunpodServerlessError("Runpod verifier request failed") from error


__all__ = ["RunpodServerlessClient", "RunpodServerlessError"]
