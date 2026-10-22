"""BAML boundary for read-only Creative Opportunity shadow analysis."""

import asyncio
import hashlib
import json
from dataclasses import asdict
from datetime import UTC, datetime
from typing import Protocol
from uuid import NAMESPACE_URL, uuid5

from baml_py.baml_py import BamlError
from baml_py.logging import set_log_level

from ..config.opportunity import OpportunityConfig
from ..domain.models import (
    CreativeOpportunityAnalysis,
    ExperimentProposal,
    OpportunityCategory,
    PerformanceEvidencePack,
)
from ..ports.interfaces import OpportunityAnalysisError
from .baml_client import types as baml_types
from .baml_client.async_client import b
from .baml_client.inlinedbaml import get_baml_files


class _BamlOpportunityClient(Protocol):
    async def AnalyzeCreativeOpportunity(
        self,
        instructions: str,
        evidence_json: str,
        baml_options: dict[str, object],
    ) -> baml_types.CreativeOpportunityResult: ...


class BamlCreativeOpportunityAnalyzer:
    def __init__(
        self,
        config: OpportunityConfig,
        *,
        api_key: str | None = None,
        client: _BamlOpportunityClient | None = None,
    ) -> None:
        self._config = config
        if config.api_key_env and not api_key:
            raise OpportunityAnalysisError("Opportunity model credential is missing")
        set_log_level("OFF")
        self._client = client or b.with_options(
            env={
                "LOCAL_LLM_BASE_URL": config.base_url,
                "LOCAL_LLM_MODEL": config.model,
                "LOCAL_LLM_API_KEY": api_key or "local-no-auth",
            }
        )
        self._template_fingerprint = _template_fingerprint(
            get_baml_files()["performance_opportunity.baml"],
            "AnalyzeCreativeOpportunity",
            config.prompt.text,
        )

    async def analyze(
        self,
        evidence: PerformanceEvidencePack,
    ) -> CreativeOpportunityAnalysis:
        payload = json.dumps(asdict(evidence), default=str, sort_keys=True)
        try:
            async with asyncio.timeout(self._config.timeout_seconds):
                result = await self._client.AnalyzeCreativeOpportunity(
                    instructions=self._config.prompt.text,
                    evidence_json=payload,
                    baml_options={},
                )
        except (TimeoutError, BamlError, ValueError) as exc:
            raise OpportunityAnalysisError("Opportunity shadow analysis failed") from exc

        try:
            category = OpportunityCategory(result.category.value.lower())
            prompt_version = f"{self._config.prompt.version}+baml:{self._template_fingerprint[:12]}"
            analysis_id = str(
                uuid5(
                    NAMESPACE_URL,
                    f"opportunity-analysis:{evidence.pack_id}:{prompt_version}:"
                    f"{self._config.model}",
                )
            )
            proposal_id = str(uuid5(NAMESPACE_URL, f"experiment-proposal:{analysis_id}"))
            proposal = ExperimentProposal(
                proposal_id=proposal_id,
                version_number=1,
                sku_id=evidence.sku_id,
                priority=result.priority,
                category=category,
                hypothesis=result.hypothesis,
                experiment=result.experiment,
                success_signal=result.success_signal,
                evidence_refs=tuple(result.evidence_refs),
                uncertainty=result.uncertainty,
            )
            return CreativeOpportunityAnalysis(
                analysis_id=analysis_id,
                evidence_pack_id=evidence.pack_id,
                category=category,
                priority=result.priority,
                rationale=result.rationale,
                evidence_refs=tuple(result.evidence_refs),
                uncertainty=result.uncertainty,
                counterargument=result.counterargument,
                proposal=proposal,
                prompt_version=prompt_version,
                model=self._config.model,
                rubric_version=self._config.rubric_version,
                created_at=datetime.now(UTC),
            )
        except ValueError as exc:
            raise OpportunityAnalysisError("Opportunity model returned invalid output") from exc


def _template_fingerprint(source: str, function: str, instructions: str) -> str:
    payload = json.dumps(
        {"baml": source, "function": function, "instructions": instructions},
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode()).hexdigest()


__all__ = ["BamlCreativeOpportunityAnalyzer"]
