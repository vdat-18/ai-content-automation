"""Read-only crosswalk for historical Static cases and local calibration images."""

from __future__ import annotations

import csv
from pathlib import Path

from pydantic import BaseModel, Field

from .config.images import load_image_dataset
from .config.rubrics import ReviewRubric
from .image_pilot import assess_golden_dataset


class _ManifestSource(BaseModel):
    source_of_truth_confirmed: bool


class _AdsJoin(BaseModel):
    status: str


class _ManifestCase(BaseModel):
    case_id: str = Field(min_length=1)
    brand: str = Field(min_length=1)
    sku: str = Field(min_length=1)
    tracker_sheet: str = Field(min_length=1)
    tracker_row: int = Field(ge=1)
    ad_name_exact: str = Field(min_length=1)
    local_calibration_case_id: str | None
    known_issues: list[str]
    ads_join: _AdsJoin


class _Manifest(BaseModel):
    source: _ManifestSource
    cases: list[_ManifestCase] = Field(min_length=1)


class StaticLineageRow(BaseModel):
    case_id: str
    brand: str
    sku: str
    tracker_sheet: str
    tracker_row: int
    tracker_ad_name: str
    calibration_case_id: str
    historical_candidate_id: str
    historical_image_path: str
    observed_stage: str
    calibration_status: str
    case_ads_status: str
    creative_version_id: str = ""
    ad_id: str = ""
    adset_id: str = ""
    metric_window: str = ""
    attribution: str = ""
    unresolved: str


def build_static_lineage_crosswalk(
    manifest_path: Path, dataset_path: Path, rubric: ReviewRubric
) -> list[StaticLineageRow]:
    """List observed images without attributing case-level Ads data to any image."""
    manifest = _Manifest.model_validate_json(manifest_path.read_text(encoding="utf-8"))
    dataset = load_image_dataset(dataset_path)
    readiness = assess_golden_dataset(dataset_path, rubric)
    if readiness.status == "invalid":
        raise ValueError("Calibration dataset has invalid assets")

    cases_by_id = {case.case_id: case for case in dataset.cases}
    readiness_by_id = {case.case_id: case for case in readiness.cases}
    if len(cases_by_id) != len(dataset.cases):
        raise ValueError("Calibration case IDs must be unique")
    case_ids = [case.case_id for case in manifest.cases]
    tracker_rows = [(case.tracker_sheet, case.tracker_row) for case in manifest.cases]
    ad_names = [case.ad_name_exact for case in manifest.cases]
    if (
        len(set(case_ids)) != len(case_ids)
        or len(set(tracker_rows)) != len(tracker_rows)
        or len(set(ad_names)) != len(ad_names)
    ):
        raise ValueError("Historical case, tracker row and ad name must be unique")

    rows: list[StaticLineageRow] = []
    dataset_root = dataset_path.resolve().parent
    for source_case in manifest.cases:
        issues = list(source_case.known_issues)
        if not manifest.source.source_of_truth_confirmed:
            issues.append("tracker_source_of_truth_unconfirmed")
        issues.append("per_image_ads_mapping_missing")
        calibration_id = source_case.local_calibration_case_id
        if calibration_id is None:
            issues.append("local_calibration_case_missing")
            candidates = [("", "", "")]
            calibration_status = "not_packaged"
        else:
            calibration_case = cases_by_id.get(calibration_id)
            if calibration_case is None:
                raise ValueError(f"Calibration case missing: {calibration_id}")
            if (calibration_case.input.brand, calibration_case.input.sku) != (
                source_case.brand,
                source_case.sku,
            ):
                raise ValueError(f"Brand/SKU mismatch for historical case: {source_case.case_id}")
            case_readiness = readiness_by_id[calibration_id]
            calibration_status = case_readiness.status
            issues.extend(case_readiness.warnings)
            candidates = []
            if calibration_case.golden is not None:
                for candidate in calibration_case.golden.historical_candidates:
                    for image_path in candidate.candidate_paths:
                        try:
                            relative_path = image_path.relative_to(dataset_root)
                        except ValueError as error:
                            raise ValueError("Historical image must be inside dataset") from error
                        candidates.append(
                            (candidate.candidate_id, relative_path.as_posix(), candidate.stage)
                        )
            if not candidates:
                issues.append("historical_candidate_missing")
                candidates = [("", "", "")]

        unresolved = ";".join(sorted(set(issues)))
        for candidate_id, image_path, stage in candidates:
            rows.append(
                StaticLineageRow(
                    case_id=source_case.case_id,
                    brand=source_case.brand,
                    sku=source_case.sku,
                    tracker_sheet=source_case.tracker_sheet,
                    tracker_row=source_case.tracker_row,
                    tracker_ad_name=source_case.ad_name_exact,
                    calibration_case_id=calibration_id or "",
                    historical_candidate_id=candidate_id,
                    historical_image_path=image_path,
                    observed_stage=stage,
                    calibration_status=calibration_status,
                    case_ads_status=source_case.ads_join.status,
                    unresolved=unresolved,
                )
            )
    return rows


def write_static_lineage_crosswalk(rows: list[StaticLineageRow], output_path: Path) -> None:
    """Write a reviewable CSV without filling unverified version or Ads identifiers."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8-sig", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=list(StaticLineageRow.model_fields))
        writer.writeheader()
        writer.writerows(row.model_dump() for row in rows)
