"""Image pilot composition, fixed dataset execution and human evaluation."""

import hashlib
import html
import json
import random
from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from statistics import mean, median
from time import monotonic
from typing import Literal
from uuid import uuid4

from PIL import Image, ImageDraw, ImageOps
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, model_validator

from ai_content.platform.artifacts.store import ArtifactStore

from .adapters.comfyui import ComfyUIBackend
from .adapters.image_files import (
    INPUT_ADAPTER,
    FileGeneratedImageStore,
    TechnicalImageChecker,
    inspect_image,
    read_local_image,
    snapshot_input_assets,
)
from .adapters.invokeai import InvokeAIBackend
from .adapters.openai_compatible_images import OpenAICompatibleImageBackend
from .adapters.pillow_renderer import PillowStaticRenderer
from .adapters.synthetic_images import SyntheticImageBackend
from .application.image_generation import StoredImageGenerator
from .application.use_cases import compute_input_hash
from .config.images import (
    HistoricalHumanReview,
    HumanCriterionReview,
    ImageBackendConfig,
    ImageDataset,
    load_image_config,
    load_image_dataset,
)
from .domain.entities import CreativeJobId, QASession, VersionId
from .domain.reviews import (
    CriterionReview,
    ReviewOutcome,
    ReviewRubric,
    RubricAssessment,
    assess_rubric_review,
)
from .ports.images import IImageBackend, ImageGenerationError


def build_image_backend(config: ImageBackendConfig, api_key: str | None = None) -> IImageBackend:
    if config.backend == "synthetic":
        return SyntheticImageBackend()
    if config.backend == "invokeai":
        return InvokeAIBackend(config, api_key=api_key)
    if config.backend == "comfyui":
        return ComfyUIBackend(config)
    return OpenAICompatibleImageBackend(config, api_key=api_key)


class HumanImageReview(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sample_id: str
    decision: Literal["accept", "revise", "reject"]
    reviewer: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    critical_product_error: bool
    rubric_version: str | None = None
    criteria: list[HumanCriterionReview] = Field(default_factory=list)
    reviewed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @model_validator(mode="after")
    def require_versioned_structured_review(self) -> "HumanImageReview":
        if bool(self.criteria) != bool(self.rubric_version):
            raise ValueError("criteria and rubric_version must be provided together")
        if len({item.criterion_id for item in self.criteria}) != len(self.criteria):
            raise ValueError("criterion_id values must be unique within a review")
        return self


def load_human_criterion_reviews(path: Path) -> list[HumanCriterionReview]:
    return TypeAdapter(list[HumanCriterionReview]).validate_json(path.read_text(encoding="utf-8"))


class GoldenCaseReadiness(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str
    status: Literal["ready", "incomplete", "invalid"]
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class GoldenDatasetReadiness(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dataset_id: str
    version: str
    status: Literal["ready", "incomplete", "invalid"]
    cases: list[GoldenCaseReadiness]


class HistoricalReviewMapping(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sample_id: str = Field(pattern=r"^historical-[a-f0-9]{12}$")
    case_id: str
    candidate_id: str
    input_hash: str
    source_checksums: list[str]
    candidate_checksums: list[str]


def assess_golden_dataset(
    dataset_path: Path, rubric: ReviewRubric | None = None
) -> GoldenDatasetReadiness:
    """Validate local assets and metadata required for calibrated evaluation."""
    dataset = load_image_dataset(dataset_path)
    reports = []
    for case in dataset.cases:
        errors: list[str] = []
        warnings: list[str] = []
        assets = (*case.input.product_assets, *case.input.reference_assets)
        for asset in assets:
            try:
                inspect_image(read_local_image(asset.url))
            except ImageGenerationError:
                errors.append(f"unreadable_asset:{Path(asset.url).name}")
        for reference in case.input.reference_assets:
            if not reference.license_info:
                warnings.append("reference_license_not_recorded")

        if case.golden is None:
            warnings.append("golden_metadata_missing")
        else:
            if not case.golden.usage_permission_confirmed:
                warnings.append("usage_permission_not_confirmed")
            if not case.golden.source_truth_resolved:
                warnings.append("source_truth_not_resolved")
            if not case.golden.historical_candidates:
                warnings.append("historical_candidate_missing")
            if rubric is None:
                warnings.append("rubric_definition_not_supplied")
            for candidate in case.golden.historical_candidates:
                for candidate_path in candidate.candidate_paths:
                    try:
                        inspect_image(read_local_image(str(candidate_path)))
                    except ImageGenerationError:
                        errors.append(f"unreadable_historical_candidate:{candidate_path.name}")
                if not candidate.reviews:
                    warnings.append(f"historical_review_missing:{candidate.candidate_id}")
                    continue
                review = max(candidate.reviews, key=lambda item: item.reviewed_at)
                if review.rubric_version != str(case.input.rubric_version):
                    warnings.append(f"historical_review_rubric_mismatch:{candidate.candidate_id}")
                if rubric is not None:
                    _assess_historical_review(
                        review, rubric, candidate.candidate_id, errors, warnings
                    )

        status: Literal["ready", "incomplete", "invalid"]
        if errors:
            status = "invalid"
        elif warnings:
            status = "incomplete"
        else:
            status = "ready"
        reports.append(
            GoldenCaseReadiness(
                case_id=case.case_id,
                status=status,
                errors=sorted(set(errors)),
                warnings=sorted(set(warnings)),
            )
        )

    dataset_status: Literal["ready", "incomplete", "invalid"] = "ready"
    if any(report.status == "invalid" for report in reports):
        dataset_status = "invalid"
    elif any(report.status == "incomplete" for report in reports):
        dataset_status = "incomplete"
    return GoldenDatasetReadiness(
        dataset_id=dataset.dataset_id,
        version=dataset.version,
        status=dataset_status,
        cases=reports,
    )


def _domain_criteria(criteria: list[HumanCriterionReview]) -> tuple[CriterionReview, ...]:
    return tuple(
        CriterionReview(
            criterion_id=item.criterion_id,
            status=item.status,
            reason=item.reason,
            score=Decimal(item.score) if item.score is not None else None,
        )
        for item in criteria
    )


def _assess_historical_review(
    review: HistoricalHumanReview,
    rubric: ReviewRubric,
    candidate_id: str,
    errors: list[str],
    warnings: list[str],
) -> RubricAssessment | None:
    if review.rubric_version != rubric.ref:
        warnings.append(f"rubric_definition_mismatch:{candidate_id}")
        return None
    if not review.criteria:
        warnings.append(f"structured_review_missing:{candidate_id}")
        return None
    try:
        assessment = assess_rubric_review(rubric, _domain_criteria(review.criteria))
    except ValueError:
        errors.append(f"invalid_structured_review:{candidate_id}")
        return None
    if assessment.missing_criteria or assessment.outcome == ReviewOutcome.UNKNOWN:
        warnings.append(f"structured_review_incomplete:{candidate_id}")
    if review.decision == "accept" and assessment.hard_gates_passed is not True:
        errors.append(f"accepted_hard_gate_failure:{candidate_id}")
    expected_decision = {
        ReviewOutcome.PASS: "accept",
        ReviewOutcome.REVISE: "revise",
        ReviewOutcome.REJECT: "reject",
    }.get(assessment.outcome)
    if expected_decision is not None and review.decision != expected_decision:
        warnings.append(f"human_decision_differs_from_rubric:{candidate_id}")
    return assessment


class EvaluationSample(BaseModel):
    """On-disk results boundary used by report/review commands."""

    model_config = ConfigDict(extra="forbid")
    sample_id: str = Field(pattern=r"^sample-[a-f0-9]{12}$")
    case_id: str
    generator: str
    backend: Literal["synthetic", "invokeai", "openai_compatible", "comfyui"]
    seed: int
    status: Literal["running", "completed", "failed"]
    technical_passed: bool | None = None
    artifact: str | None = None
    error: str | None = None
    issues: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    elapsed_seconds: float | None = None


def read_evaluation_results(run_dir: Path) -> list[EvaluationSample]:
    return TypeAdapter(list[EvaluationSample]).validate_json(
        (run_dir / "results.json").read_text(encoding="utf-8")
    )


async def benchmark_images(
    dataset_path: Path,
    config_paths: list[Path],
    output_root: Path,
    seeds: list[int],
    case_id: str | None = None,
    credential_resolver: Callable[[str | None], str | None] | None = None,
) -> Path:
    dataset = load_image_dataset(dataset_path)
    configs = [load_image_config(path) for path in config_paths]
    if not configs:
        raise ValueError("At least one generator config is required")
    if len({config.name for config in configs}) != len(configs):
        raise ValueError("Generator names must be unique within a benchmark")
    if (
        not seeds
        or any(seed < 0 or seed >= 2**32 for seed in seeds)
        or len(set(seeds)) != len(seeds)
    ):
        raise ValueError("Seeds must be distinct unsigned 32-bit integers")
    cases = [case for case in dataset.cases if case_id is None or case.case_id == case_id]
    if not cases:
        raise ValueError("Selected case_id does not exist")
    # Fail configuration errors before creating an incomplete benchmark directory.
    backends = []
    for config in configs:
        backend = (
            build_image_backend(
                config,
                credential_resolver(config.api_key_env or config.token_env),
            )
            if credential_resolver is not None
            else build_image_backend(config)
        )
        backends.append((config, backend))
    run_dir = output_root.resolve() / f"image-eval-{uuid4().hex}"
    run_dir.mkdir(parents=True, exist_ok=False)
    store = ArtifactStore(run_dir)
    store.write_text(dataset.model_dump_json(indent=2), "source_dataset.json")
    store.write_text(
        json.dumps([config.model_dump(mode="json") for config in configs], indent=2), "configs.json"
    )
    # Source-contract identity must not include this experiment's snapshot directory UUID.
    source_input_hashes = {case.case_id: compute_input_hash(case.input) for case in cases}
    # Freeze every selected case before model calls; smaller per-config limits still apply later.
    for index, case in enumerate(cases):
        case.input, assets = snapshot_input_assets(
            case.input,
            store,
            "dataset_assets",
            f"case-{index}",
            max_image_bytes=max(config.max_image_bytes for config in configs),
        )
        store.write_text(
            json.dumps(assets, indent=2), "dataset_assets", f"case-{index}", "assets.json"
        )
    dataset = dataset.model_copy(update={"cases": cases})
    frozen_dataset = dataset.model_dump(mode="json")
    for frozen_case in frozen_dataset["cases"]:
        for group in ("product_assets", "reference_assets"):
            for asset in frozen_case["input"][group]:
                asset["url"] = Path(asset["url"]).relative_to(run_dir).as_posix()
    store.write_text(json.dumps(frozen_dataset, ensure_ascii=False, indent=2), "dataset.json")
    samples = []
    jobs = [
        (case, config, backend, seed)
        for case in cases
        for config, backend in backends
        for seed in seeds
    ]
    random.Random(0).shuffle(jobs)
    # Serial submission bounds GPU concurrency to one, including queue wait/download.
    for case, config, backend, seed in jobs:
        sample_id = f"sample-{uuid4().hex[:12]}"
        sample = {
            "sample_id": sample_id,
            "case_id": case.case_id,
            "generator": config.name,
            "backend": config.backend,
            "seed": seed,
            "status": "running",
            "technical_passed": None,
            "artifact": None,
            "error": None,
        }
        samples.append(sample)
        store.write_text(json.dumps(samples, indent=2), "results.json")
        start = monotonic()
        try:
            image_store = FileGeneratedImageStore(store, config.max_image_bytes)
            generator = StoredImageGenerator(
                backend,
                image_store,
                seed,
                source_input_hash=source_input_hashes[case.case_id],
                renderer=PillowStaticRenderer(),
            )
            version = await generator.generate(
                case.input, VersionId(CreativeJobId.from_string(sample_id), 1)
            )
            qa = await TechnicalImageChecker(config.max_image_bytes).check(
                QASession(
                    asset=version,
                    input_contract=case.input,
                    rubric_version=str(case.input.rubric_version),
                    policy_version=str(case.input.policy_version),
                )
            )
            sample.update(
                {
                    "status": "completed",
                    "technical_passed": qa.passed,
                    "issues": list(qa.issues),
                    "warnings": list(qa.warnings),
                    "artifact": str(Path(version.artifact_path).relative_to(run_dir)),
                }
            )
            _write_blind_preview(
                Path(version.artifact_path), store.path("review", f"{sample_id}.png")
            )
        except (ImageGenerationError, OSError) as exc:
            sample.update({"status": "failed", "error": type(exc).__name__})
            if isinstance(exc, ImageGenerationError):
                sample["error"] = str(exc)
        sample["elapsed_seconds"] = monotonic() - start
        store.write_text(json.dumps(samples, indent=2), "results.json")
        if sample["error"] and "unknown_check_service" in sample["error"]:
            # A timed-out GPU job may still be running; don't enqueue another candidate.
            break
    _write_review_pack(store, dataset, samples)
    summarize_image_evaluation(run_dir)
    return run_dir


def _write_blind_preview(source: Path, destination: Path) -> None:
    # Normalize display orientation/color mode before dropping private generation metadata.
    with Image.open(source) as original:
        oriented = ImageOps.exif_transpose(original)
        mode = "RGBA" if "A" in oriented.getbands() or "transparency" in oriented.info else "RGB"
        clean = oriented.convert(mode)
        clean.info.clear()
        destination.parent.mkdir(parents=True, exist_ok=True)
        clean.save(destination, "PNG")


def prepare_historical_review_pack(
    dataset_path: Path,
    rubric: ReviewRubric,
    output_dir: Path,
) -> Path:
    """Create a blind pack for labeling historical candidates without model metadata."""
    dataset = load_image_dataset(dataset_path)
    if output_dir.exists():
        raise FileExistsError(f"Review pack already exists: {output_dir}")
    store = ArtifactStore(output_dir)
    mappings: list[HistoricalReviewMapping] = []
    templates: list[dict[str, object]] = []
    sections: list[str] = []
    for case in dataset.cases:
        if case.golden is None:
            continue
        if str(case.input.rubric_version) != rubric.ref:
            raise ValueError(f"Case {case.case_id} does not pin the supplied rubric")
        for candidate in case.golden.historical_candidates:
            identity = f"{dataset.dataset_id}:{case.case_id}:{candidate.candidate_id}"
            sample_id = f"historical-{hashlib.sha256(identity.encode()).hexdigest()[:12]}"
            source_paths = [
                Path(asset.url)
                for asset in (*case.input.product_assets, *case.input.reference_assets)
            ]
            mappings.append(
                HistoricalReviewMapping(
                    sample_id=sample_id,
                    case_id=case.case_id,
                    candidate_id=candidate.candidate_id,
                    input_hash=compute_input_hash(case.input),
                    source_checksums=[_file_checksum(path) for path in source_paths],
                    candidate_checksums=[
                        _file_checksum(path) for path in candidate.candidate_paths
                    ],
                )
            )
            sources = []
            product_count = len(case.input.product_assets)
            for index, asset in enumerate(
                (*case.input.product_assets, *case.input.reference_assets)
            ):
                name = f"{sample_id}-source-{index}.png"
                _write_blind_preview(Path(asset.url), store.path("review", name))
                is_product = index < product_count
                role = "Product asset" if is_product else "Reference asset"
                role_index = index + 1 if is_product else index - product_count + 1
                sources.append(
                    f"<figure><figcaption>{role} {role_index}</figcaption>"
                    f"<img src='{name}' alt='{role}'></figure>"
                )
            candidates = []
            for index, candidate_path in enumerate(candidate.candidate_paths):
                name = f"{sample_id}-candidate-{index}.png"
                _write_blind_preview(candidate_path, store.path("review", name))
                candidates.append(
                    f"<figure><figcaption>Candidate {index + 1}</figcaption>"
                    f"<img src='{name}' alt='Candidate'></figure>"
                )
            checklist = "".join(f"<li>{html.escape(item)}</li>" for item in case.checklist)
            brief = case.input
            sections.append(
                f"<article><h2>{sample_id}</h2>"
                f"<p>Brand: {html.escape(brief.brand)}</p>"
                f"<p>SKU: {html.escape(brief.sku)}</p>"
                f"<p>Objective: {html.escape(brief.objective)}</p>"
                f"<p>Heading: {html.escape(brief.heading)}</p>"
                f"<p>Visual direction: {html.escape(brief.visual_direction)}</p>"
                f"<p>Checklist:</p><ul>{checklist}</ul>"
                f"<h3>Source and reference</h3>{''.join(sources)}"
                f"<h3>Candidate</h3>{''.join(candidates)}</article>"
            )
            templates.append(
                {
                    "sample_id": sample_id,
                    "decision": "revise",
                    "reason": "",
                    "critical_product_error": False,
                    "rubric_version": rubric.ref,
                    "criteria": [
                        {
                            "criterion_id": item.criterion_id,
                            "status": "unknown",
                            "reason": "",
                            "score": None,
                        }
                        for item in (*rubric.hard_gates, *rubric.scored_criteria)
                    ],
                }
            )
    if not mappings:
        raise ValueError("Dataset has no historical candidates to review")
    store.write_text(
        TypeAdapter(list[HistoricalReviewMapping]).dump_json(mappings, indent=2).decode(),
        "mapping.json",
    )
    store.write_text(json.dumps(templates, indent=2), "review-template.json")
    store.write_text(
        "<!doctype html><html lang='en'><meta charset='utf-8'>"
        "<title>Historical Static Creative review</title>"
        "<style>body{font:16px system-ui;max-width:1100px;margin:32px auto;padding:16px}"
        "article{border-top:1px solid #ccc;margin-top:32px}figure{display:inline-block;"
        "vertical-align:top;max-width:45%}img{max-width:100%;height:auto}</style>"
        "<h1>Historical Static Creative blind review</h1>"
        "<p>Review only the supplied source, brief, checklist, and candidate. "
        "Prior stage, feedback, and decision are intentionally hidden.</p>"
        + "".join(sections)
        + "</html>",
        "review",
        "index.html",
    )
    return output_dir


def record_historical_review(
    dataset_path: Path,
    review_pack: Path,
    sample_id: str,
    review: HistoricalHumanReview,
    rubric: ReviewRubric,
) -> Path:
    """Append one versioned review to a historical candidate in a local dataset."""
    if review.rubric_version != rubric.ref:
        raise ValueError("Review rubric version does not match the supplied rubric")
    assessment = assess_rubric_review(rubric, _domain_criteria(review.criteria))
    if assessment.missing_criteria:
        raise ValueError("Historical review must include every candidate-level rubric criterion")
    if review.decision == "accept" and (
        review.critical_product_error or assessment.outcome != ReviewOutcome.PASS
    ):
        raise ValueError("Cannot accept a critical error or a review that is not rubric-ready")
    mapping = TypeAdapter(list[HistoricalReviewMapping]).validate_json(
        (review_pack / "mapping.json").read_text(encoding="utf-8")
    )
    selected = next((item for item in mapping if item.sample_id == sample_id), None)
    if selected is None:
        raise ValueError("Historical sample does not exist in the review pack")

    resolved_dataset = load_image_dataset(dataset_path)
    resolved_case = next(
        (item for item in resolved_dataset.cases if item.case_id == selected.case_id), None
    )
    if resolved_case is None or resolved_case.golden is None:
        raise ValueError("Historical sample case does not exist in the dataset")
    resolved_candidate = next(
        (
            item
            for item in resolved_case.golden.historical_candidates
            if item.candidate_id == selected.candidate_id
        ),
        None,
    )
    if resolved_candidate is None:
        raise ValueError("Historical candidate does not exist in the dataset")
    current_sources = [
        Path(asset.url)
        for asset in (*resolved_case.input.product_assets, *resolved_case.input.reference_assets)
    ]
    if (
        compute_input_hash(resolved_case.input) != selected.input_hash
        or [_file_checksum(path) for path in current_sources] != selected.source_checksums
        or [_file_checksum(path) for path in resolved_candidate.candidate_paths]
        != selected.candidate_checksums
    ):
        raise ValueError(
            "Dataset input or candidate changed after the blind review pack was created"
        )

    dataset = ImageDataset.model_validate_json(dataset_path.read_text(encoding="utf-8"))
    case = next((item for item in dataset.cases if item.case_id == selected.case_id), None)
    if case is None or case.golden is None:
        raise ValueError("Historical sample case does not exist in the dataset")
    candidate = next(
        (
            item
            for item in case.golden.historical_candidates
            if item.candidate_id == selected.candidate_id
        ),
        None,
    )
    if candidate is None:
        raise ValueError("Historical candidate does not exist in the dataset")
    candidate.reviews.append(review)
    return ArtifactStore(dataset_path.parent).write_text(
        dataset.model_dump_json(indent=2), dataset_path.name
    )


def _file_checksum(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_review_pack(store: ArtifactStore, dataset: ImageDataset, samples: list[dict]) -> None:
    cases = {case.case_id: case for case in dataset.cases}
    sections = []
    for sample in samples:
        if sample["status"] != "completed":
            continue
        case = cases[sample["case_id"]]
        # Source snapshots, rather than mutable originals, support fidelity review.
        image_dir = store.path(sample["artifact"]).parent
        metadata = json.loads((image_dir / "metadata.json").read_text(encoding="utf-8"))
        sources = []
        for index, asset in enumerate(metadata["input_assets"]):
            source_name = f"{sample['sample_id']}-source-{index}.png"
            _write_blind_preview(image_dir / asset["snapshot"], store.path("review", source_name))
            role = "Product asset" if asset["role"] == "product_assets" else "Reference asset"
            label = f"{role} {asset['index'] + 1}"
            sources.append(
                f"<figure><figcaption>{label}</figcaption>"
                f"<img style='max-width:220px' src='{source_name}' alt='{label}'></figure>"
            )
        checklist = "".join(f"<li>{html.escape(item)}</li>" for item in case.checklist)
        brief = case.input
        fields = {
            "Brand": brief.brand,
            "SKU": brief.sku,
            "Objective": brief.objective,
            "Visual direction": brief.visual_direction,
            "Heading": brief.heading,
            "Subtext": brief.subtext or "Not specified",
            "Brand guideline reference": brief.brand_guideline_ref or "Not specified",
            "Output": (
                f"{brief.output_spec.width} × {brief.output_spec.height} {brief.output_spec.file_format}"
                + (f" ({brief.output_spec.aspect_ratio})" if brief.output_spec.aspect_ratio else "")
            ),
        }
        brief_html = "".join(
            f"<dt>{label}</dt><dd>{html.escape(value)}</dd>" for label, value in fields.items()
        )
        banned_claims = "".join(f"<li>{html.escape(claim)}</li>" for claim in brief.banned_claims)
        proofs = "".join(
            f"<li>{html.escape(proof.proof_type.value)}: {html.escape(proof.text)} — "
            f"{'Verified' if proof.verified else 'Unverified'}"
            + (f"; source: {html.escape(proof.source_url)}" if proof.source_url else "")
            + "</li>"
            for proof in brief.proof_references
        )
        sections.append(
            f"<article><h2>{html.escape(sample['sample_id'])}</h2>"
            f"<p>Case: {html.escape(case.case_id)}</p>"
            f"<dl>{brief_html}</dl>"
            f"<p>Banned claims:</p><ul>{banned_claims or '<li>None specified</li>'}</ul>"
            f"<p>Proof references:</p><ul>{proofs or '<li>None supplied</li>'}</ul>"
            f"<p>Checklist:</p><ul>{checklist}</ul><p>Source/reference:</p>{''.join(sources)}"
            f"<p>Candidate:</p><img src='{sample['sample_id']}.png' alt='Candidate'></article>"
        )
    store.write_text(
        "<!doctype html><html lang='vi'><meta charset='utf-8'><title>Image review</title>"
        "<style>body{font:16px system-ui;max-width:1000px;margin:32px auto;padding:16px}"
        "article{border-top:1px solid #ccc;margin-top:32px}img{max-width:100%;height:auto}</style>"
        "<h1>Static Creative — human review</h1>"
        "<p>Đánh giá đúng sản phẩm, brief, text và brand. Technical PASS chỉ là kiểm tra file. "
        "Tên model được ẩn trong thư mục review; results.json chỉ dành cho engineer.</p>"
        + "".join(sections)
        + "</html>",
        "review",
        "index.html",
    )


def record_image_review(
    run_dir: Path,
    review: HumanImageReview,
    rubric: ReviewRubric | None = None,
) -> Path:
    samples = [sample.model_dump() for sample in read_evaluation_results(run_dir)]
    sample = next((item for item in samples if item["sample_id"] == review.sample_id), None)
    if sample is None or sample["status"] != "completed":
        raise ValueError("Review must refer to a completed sample")
    assessment = _assess_image_review(review, rubric)
    if rubric is not None:
        dataset = load_image_dataset(run_dir / "dataset.json")
        case = next((item for item in dataset.cases if item.case_id == sample["case_id"]), None)
        if case is None or str(case.input.rubric_version) != rubric.ref:
            raise ValueError("Candidate input does not pin the supplied rubric")
    if review.decision == "accept" and (
        not sample["technical_passed"]
        or review.critical_product_error
        or (assessment is not None and assessment.outcome != ReviewOutcome.PASS)
    ):
        raise ValueError("Cannot accept a technical failure or critical product error")
    store = ArtifactStore(run_dir)
    path = store.write_text(review.model_dump_json(indent=2), "reviews", f"{uuid4().hex}.json")
    summarize_image_evaluation(run_dir, rubric)
    return path


def _assess_image_review(
    review: HumanImageReview, rubric: ReviewRubric | None
) -> RubricAssessment | None:
    if not review.criteria:
        return None
    if rubric is None:
        raise ValueError("A rubric definition is required for a structured review")
    if review.rubric_version != rubric.ref:
        raise ValueError("Review rubric version does not match the supplied rubric")
    assessment = assess_rubric_review(rubric, _domain_criteria(review.criteria))
    if assessment.missing_criteria:
        raise ValueError("Structured review must include every candidate-level rubric criterion")
    return assessment


def summarize_image_evaluation(run_dir: Path, rubric: ReviewRubric | None = None) -> dict:
    samples = [sample.model_dump() for sample in read_evaluation_results(run_dir)]
    reviews: dict[str, HumanImageReview] = {}
    for path in (run_dir / "reviews").glob("*.json"):
        review = HumanImageReview.model_validate_json(path.read_text(encoding="utf-8"))
        old = reviews.get(review.sample_id)
        if old is None or old.reviewed_at < review.reviewed_at:
            reviews[review.sample_id] = review
    groups = {}
    for name in sorted({sample["generator"] for sample in samples}):
        rows = [sample for sample in samples if sample["generator"] == name]
        reviewed = [reviews[row["sample_id"]] for row in rows if row["sample_id"] in reviews]
        assessments = [
            assessment
            for review in reviewed
            if (assessment := _assess_image_review(review, rubric)) is not None
        ]
        latencies = [row["elapsed_seconds"] for row in rows if row["status"] == "completed"]
        criterion_rows: dict[str, list[HumanCriterionReview]] = {}
        for review in reviewed:
            for criterion in review.criteria:
                criterion_rows.setdefault(criterion.criterion_id, []).append(criterion)
        groups[name] = {
            "attempted": len(rows),
            "completed": sum(row["status"] == "completed" for row in rows),
            "technical_passed": sum(row["technical_passed"] is True for row in rows),
            "reviewed": len(reviewed),
            "accepted": sum(review.decision == "accept" for review in reviewed),
            "revision_requested": sum(review.decision == "revise" for review in reviewed),
            "rejected": sum(review.decision == "reject" for review in reviewed),
            "acceptance_rate_reviewed": (
                sum(review.decision == "accept" for review in reviewed) / len(reviewed)
                if reviewed
                else None
            ),
            "critical_product_error_rate_reviewed": (
                sum(review.critical_product_error for review in reviewed) / len(reviewed)
                if reviewed
                else None
            ),
            "human_criterion_failure_rate_reviewed": {
                criterion_id: sum(item.status == "fail" for item in items) / len(items)
                for criterion_id, items in sorted(criterion_rows.items())
            },
            "mean_weighted_score_reviewed": (
                mean(
                    float(item.weighted_score)
                    for item in assessments
                    if item.weighted_score is not None
                )
                if any(item.weighted_score is not None for item in assessments)
                else None
            ),
            "rubric_outcomes_reviewed": {
                outcome.value: sum(item.outcome == outcome for item in assessments)
                for outcome in ReviewOutcome
            },
            "mean_seconds_completed": mean(latencies) if latencies else None,
            "median_seconds_completed": median(latencies) if latencies else None,
            "cost_per_accepted": None,
            "peak_gpu_memory": None,
            "note": "Latency includes upload/queue/download; GPU and cost are unmeasured",
        }
    ArtifactStore(run_dir).write_text(json.dumps(groups, indent=2), "summary.json")
    return groups


def initialize_image_example(directory: Path) -> None:
    """Create an explicitly synthetic, runnable local dataset without real business data."""
    directory.mkdir(parents=True, exist_ok=False)
    image = Image.new("RGB", (256, 256), "#eee8df")
    draw = ImageDraw.Draw(image)
    draw.rectangle((48, 75, 208, 130), fill="#795548")
    draw.rectangle((60, 130, 75, 215), fill="#795548")
    draw.rectangle((180, 130, 195, 215), fill="#795548")
    image.save(directory / "product.png")
    raw_input = {
        "brand": "SyntheticBrand",
        "sku": "SYN-TABLE-001",
        "objective": "test",
        "idea_id": "team-provided-synthetic-idea",
        "heading": "Complete your room",
        "visual_direction": "A wooden table in a bright room. Preserve the product shape.",
        "product_assets": [
            {"url": "product.png", "asset_type": "product", "provenance": "team_provided"}
        ],
        "output_spec": {"width": 256, "height": 256, "file_format": "png"},
        "prompt_version": {
            "prompt_id": "prompt-static-creative-generation",
            "version": "1.0-draft",
        },
        "rubric_version": {"rubric_id": "rubric-static-creative-qa", "version": "1.0-draft"},
        "policy_version": {"policy_id": "policy-static-creative", "version": "1.0-draft"},
        "banned_claims": ["guaranteed results"],
    }
    INPUT_ADAPTER.validate_python(raw_input)
    store = ArtifactStore(directory)
    store.write_text(
        json.dumps(
            {
                "dataset_id": "synthetic-smoke",
                "version": "1",
                "cases": [
                    {
                        "case_id": "table",
                        "input": raw_input,
                        "checklist": ["Product shape preserved", "Brief followed", "Text correct"],
                    }
                ],
            },
            indent=2,
        ),
        "dataset.json",
    )
    store.write_text(
        ImageBackendConfig(
            name="synthetic",
            backend="synthetic",
            model="synthetic-bitmap",
            model_revision="1",
            runtime_version="pillow",
        ).model_dump_json(indent=2),
        "synthetic.json",
    )
    versions = {
        "prompt_version": {"id": raw_input["prompt_version"]["prompt_id"], "version": "1.0-draft"},
        "rubric_version": {"id": raw_input["rubric_version"]["rubric_id"], "version": "1.0-draft"},
        "policy_version": {"id": raw_input["policy_version"]["policy_id"], "version": "1.0-draft"},
        "rule_version": {"id": "rule-static-creative", "version": "1.0-draft"},
        "workflow_version": {"id": "workflow-static-creative-generation", "version": "1.0-draft"},
    }
    store.write_text(
        json.dumps(
            {
                "source_run_id": "synthetic-image-pilot-001",
                "marketing_scope": {"brand": raw_input["brand"], "market": "US"},
                "objective": "test",
                "channel": "meta",
                "time_window": "synthetic",
                **versions,
                "target_sku_set": [
                    {
                        "sku_id": raw_input["sku"],
                        "sku_name": "Synthetic Table",
                        "product_metadata": {
                            "image_refs": [str((directory / "product.png").resolve())]
                        },
                        "creative_constraints": {"format_constraints": raw_input["output_spec"]},
                    }
                ],
            },
            indent=2,
        ),
        "work-item.json",
    )
