"""BAML boundary for evidence-grounded Performance Learning analysis."""

import asyncio
import json
from dataclasses import asdict
from datetime import UTC, datetime
from typing import Protocol
from uuid import NAMESPACE_URL, uuid5

from baml_py.baml_py import BamlError
from baml_py.logging import set_log_level

from ..config.learning import PerformanceLearningConfig
from ..domain.models import (
    AdsDiagnosis,
    AdsEvidencePack,
    LearningProposal,
    PerformanceLearningAnalysis,
    RecommendationAction,
)
from ..ports.interfaces import PerformanceLearningAnalysisError
from .baml_client import types as baml_types
from .baml_client.async_client import b

_PROMPT_VERSION = "performance-learning@3-baml"


class _BamlLearningClient(Protocol):
    async def DiagnoseAdsOutcome(
        self,
        evidence_json: str,
        baml_options: dict[str, object],
    ) -> baml_types.AdsDiagnosisResult: ...

    async def SynthesizeCreativeLesson(
        self,
        evidence_json: str,
        diagnosis_json: str,
        baml_options: dict[str, object],
    ) -> baml_types.CreativeLessonResult: ...


class BamlPerformanceLearningAnalyzer:
    def __init__(
        self,
        config: PerformanceLearningConfig,
        *,
        api_key: str | None = None,
        client: _BamlLearningClient | None = None,
    ) -> None:
        self._config = config
        resolved_key = api_key or config.api_key
        if not resolved_key:
            raise PerformanceLearningAnalysisError("Performance Learning credential is missing")
        set_log_level("OFF")
        self._client = client or b.with_options(
            env={
                "MARKETING_LLM_BASE_URL": config.base_url,
                "MARKETING_LLM_MODEL": config.model,
                "MARKETING_LLM_API_KEY": resolved_key,
            }
        )

    async def analyze(self, evidence: AdsEvidencePack) -> PerformanceLearningAnalysis:
        evidence_json = json.dumps(asdict(evidence), default=str, sort_keys=True)
        try:
            async with asyncio.timeout(self._config.timeout_seconds):
                diagnosis_result = await self._client.DiagnoseAdsOutcome(
                    evidence_json=evidence_json,
                    baml_options={},
                )
                diagnosis_json = diagnosis_result.model_dump_json()
                lesson_result = await self._client.SynthesizeCreativeLesson(
                    evidence_json=evidence_json,
                    diagnosis_json=diagnosis_json,
                    baml_options={},
                )
        except (TimeoutError, BamlError, ValueError) as exc:
            raise PerformanceLearningAnalysisError("Performance Learning analysis failed") from exc

        try:
            diagnosis = AdsDiagnosis(
                observations=tuple(diagnosis_result.observations),
                hypotheses=tuple(diagnosis_result.hypotheses),
                confounders=tuple(diagnosis_result.confounders),
                uncertainty=diagnosis_result.uncertainty,
                evidence_refs=tuple(diagnosis_result.evidence_refs),
            )
            analysis_id = str(
                uuid5(
                    NAMESPACE_URL,
                    f"performance-learning:{evidence.pack_id}:{_PROMPT_VERSION}:"
                    f"{self._config.model}",
                )
            )
            proposal = None
            if lesson_result.proposal is not None:
                output = lesson_result.proposal
                proposal = LearningProposal(
                    proposal_id=str(uuid5(NAMESPACE_URL, f"learning-proposal:{analysis_id}")),
                    version_number=1,
                    creative_version_id=evidence.creative_version_id,
                    sku_id=evidence.sku_id,
                    priority=output.priority,
                    recommended_action=RecommendationAction(
                        output.recommended_action.value.lower()
                    ),
                    hypothesis=output.hypothesis,
                    experiment=output.experiment,
                    success_signal=output.success_signal,
                    evidence_refs=tuple(output.evidence_refs),
                    uncertainty=output.uncertainty,
                )
            return PerformanceLearningAnalysis(
                analysis_id=analysis_id,
                evidence_pack_id=evidence.pack_id,
                creative_version_id=evidence.creative_version_id,
                sku_id=evidence.sku_id,
                diagnosis=diagnosis,
                proposal=proposal,
                prompt_version=_PROMPT_VERSION,
                model=self._config.model,
                rubric_version=self._config.rubric_version,
                created_at=datetime.now(UTC),
            )
        except ValueError as exc:
            raise PerformanceLearningAnalysisError(
                "Performance Learning model returned invalid output"
            ) from exc


__all__ = ["BamlPerformanceLearningAnalyzer"]
