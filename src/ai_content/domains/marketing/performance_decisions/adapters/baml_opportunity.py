"""BAML boundary for read-only Creative Opportunity shadow analysis."""

import asyncio
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

_PROMPT_VERSION = "performance-opportunity@3-baml"


class _BamlOpportunityClient(Protocol):
    async def AnalyzeCreativeOpportunity(
        self,
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
        set_log_level("OFF")
        self._client = client or b.with_options(
            env={
                "MARKETING_LLM_BASE_URL": config.base_url,
                "MARKETING_LLM_MODEL": config.model,
                "MARKETING_LLM_API_KEY": api_key or "local-no-auth",
            }
        )

    async def analyze(
        self,
        evidence: PerformanceEvidencePack,
    ) -> CreativeOpportunityAnalysis:
        payload = json.dumps(asdict(evidence), default=str, sort_keys=True)
        try:
            async with asyncio.timeout(self._config.timeout_seconds):
                result = await self._client.AnalyzeCreativeOpportunity(
                    evidence_json=payload,
                    baml_options={},
                )
        except (TimeoutError, BamlError, ValueError) as exc:
            raise OpportunityAnalysisError("Opportunity shadow analysis failed") from exc

        try:
            category = OpportunityCategory(result.category.value.lower())
            analysis_id = str(
                uuid5(
                    NAMESPACE_URL,
                    f"opportunity-analysis:{evidence.pack_id}:{_PROMPT_VERSION}:"
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
                prompt_version=_PROMPT_VERSION,
                model=self._config.model,
                rubric_version=self._config.rubric_version,
                created_at=datetime.now(UTC),
            )
        except ValueError as exc:
            raise OpportunityAnalysisError("Opportunity model returned invalid output") from exc


__all__ = ["BamlCreativeOpportunityAnalyzer"]
