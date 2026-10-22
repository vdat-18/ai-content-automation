"""Local image files, technical checks and immutable binary artifacts."""

import hashlib
import io
import json
from dataclasses import asdict, replace
from decimal import Decimal
from pathlib import Path
from typing import TypedDict

from PIL import Image, UnidentifiedImageError
from pydantic import TypeAdapter

from ai_content.platform.artifacts.store import ArtifactStore

from ..domain.entities import QACheckResult, QASession
from ..ports.contracts import StaticCreativeInput
from ..ports.images import (
    GeneratedImage,
    ImageGenerationError,
    ImageGenerationRequest,
    ProductCutout,
    StoredImage,
)

INPUT_ADAPTER = TypeAdapter(StaticCreativeInput)
TECHNICAL_ONLY = "technical_only: product fidelity, text, claims and brand fit require human review"


def inspect_image(content: bytes) -> tuple[int, int, str]:
    try:
        with Image.open(io.BytesIO(content)) as image:
            image.verify()
        with Image.open(io.BytesIO(content)) as image:
            image.load()
            if image.format not in {"PNG", "JPEG", "WEBP"}:
                raise ImageGenerationError("Only PNG, JPEG and WebP images are supported")
            return image.width, image.height, image.format.lower()
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError) as exc:
        raise ImageGenerationError("Image is corrupt, unsupported or too large") from exc


def read_local_image(reference: str, max_bytes: int = 30_000_000) -> bytes:
    # Pilot only reads explicitly supplied local assets, never arbitrary URLs.
    if "://" in reference:
        raise ImageGenerationError("Image pilot requires local asset paths")
    try:
        with Path(reference).open("rb") as source:
            content = source.read(max_bytes + 1)
    except OSError as exc:
        raise ImageGenerationError("Cannot read local image asset") from exc
    if len(content) > max_bytes:
        raise ImageGenerationError("Image exceeds configured byte limit")
    return content


class InputAssetSnapshot(TypedDict):
    role: str
    index: int
    snapshot: str
    sha256: str


def snapshot_input_assets(
    input_contract: StaticCreativeInput,
    store: ArtifactStore,
    *parts: str,
    max_image_bytes: int,
) -> tuple[StaticCreativeInput, list[InputAssetSnapshot]]:
    input_snapshot = INPUT_ADAPTER.dump_python(input_contract, mode="json")
    asset_checksums = []
    for group in ("product_assets", "reference_assets"):
        for index, asset in enumerate(input_snapshot[group]):
            content = read_local_image(asset["url"], max_image_bytes)
            _, _, asset_format = inspect_image(content)
            relative = f"inputs/{group}-{index}.{asset_format}"
            snapshot = store.write_bytes(content, *parts, relative)
            asset_checksums.append(
                InputAssetSnapshot(
                    role=group,
                    index=index,
                    snapshot=relative,
                    sha256=hashlib.sha256(content).hexdigest(),
                )
            )
            asset["url"] = str(snapshot.resolve())
    logo = input_snapshot.get("logo_asset")
    if logo is not None:
        content = read_local_image(logo["url"], max_image_bytes)
        _, _, asset_format = inspect_image(content)
        relative = f"inputs/logo_asset.{asset_format}"
        snapshot = store.write_bytes(content, *parts, relative)
        asset_checksums.append(
            InputAssetSnapshot(
                role="logo_asset",
                index=0,
                snapshot=relative,
                sha256=hashlib.sha256(content).hexdigest(),
            )
        )
        logo["url"] = str(snapshot.resolve())
    return INPUT_ADAPTER.validate_python(input_snapshot), asset_checksums


class FileGeneratedImageStore:
    def __init__(self, store: ArtifactStore, max_image_bytes: int = 30_000_000) -> None:
        self._store = store
        self._max_image_bytes = max_image_bytes

    def prepare(self, version_ref: str, request: ImageGenerationRequest) -> ImageGenerationRequest:
        # Reserve each version before writing, preserving every previous attempt.
        directory = self._store.path("images", version_ref)
        directory.mkdir(parents=True, exist_ok=False)
        frozen_input, asset_checksums = snapshot_input_assets(
            request.input,
            self._store,
            "images",
            version_ref,
            max_image_bytes=self._max_image_bytes,
        )
        revision_image_ref = None
        if request.revision is not None:
            revision_content, revision_format = self._revision_source(
                request.revision.previous_version_ref
            )
            relative = f"inputs/revision_source.{revision_format}"
            revision_snapshot = self._store.write_bytes(
                revision_content, "images", version_ref, relative
            )
            revision_image_ref = str(revision_snapshot.resolve())
            asset_checksums.append(
                InputAssetSnapshot(
                    role="revision_source",
                    index=0,
                    snapshot=relative,
                    sha256=hashlib.sha256(revision_content).hexdigest(),
                )
            )
        self._store.write_text(
            json.dumps(
                {
                    "input": INPUT_ADAPTER.dump_python(frozen_input, mode="json"),
                    "input_assets": asset_checksums,
                    "seed": request.seed,
                    "input_hash": request.input_hash,
                    "revision": asdict(request.revision) if request.revision else None,
                    "revision_image_ref": revision_image_ref,
                    "generation_target": request.generation_target,
                },
                ensure_ascii=False,
                indent=2,
            ),
            "images",
            version_ref,
            "request.json",
        )
        self._store.write_text(
            json.dumps(
                {
                    "brand": frozen_input.brand,
                    "sku": frozen_input.sku,
                    "objective": frozen_input.objective,
                    "idea_id": frozen_input.idea_id,
                    "heading": frozen_input.heading,
                    "subtext": frozen_input.subtext,
                    "visual_direction": frozen_input.visual_direction,
                    "variation_key": frozen_input.variation_key,
                    "evidence_refs": frozen_input.variation_evidence_refs,
                    "awareness_stage": frozen_input.awareness_stage,
                    "angle": frozen_input.angle,
                    "offer": frozen_input.offer,
                    "production_level": frozen_input.production_level,
                    "output_spec": asdict(frozen_input.output_spec),
                    "output_stage": "rendered_static"
                    if frozen_input.composition is not None
                    else "visual_only",
                    "assets": [
                        {
                            "role": asset["role"],
                            "index": asset["index"],
                            "sha256": asset["sha256"],
                            "web_url": f"/artifacts/images/{version_ref}/{asset['snapshot']}",
                        }
                        for asset in asset_checksums
                        if asset["role"] != "revision_source"
                    ],
                },
                ensure_ascii=False,
                indent=2,
            ),
            "images",
            version_ref,
            "review.json",
        )
        if frozen_input.composition is not None:
            self._store.write_text(
                json.dumps(asdict(frozen_input.composition), ensure_ascii=False, indent=2),
                "images",
                version_ref,
                "composition.json",
            )
        return replace(
            request,
            input=frozen_input,
            revision_image_ref=revision_image_ref,
        )

    def _revision_source(self, previous_version_ref: str) -> tuple[bytes, str]:
        try:
            directory = self._store.path("images", previous_version_ref)
        except ValueError as exc:
            raise ImageGenerationError(
                "Previous image version reference is invalid", "revision_source_invalid"
            ) from exc
        raw = [path for path in (directory / "raw").glob("image.*") if path.is_file()]
        final = [path for path in directory.glob("image.*") if path.is_file()]
        candidates = raw or final
        if len(candidates) != 1:
            raise ImageGenerationError(
                "Previous image version is missing or ambiguous", "revision_source_missing"
            )
        content = read_local_image(str(candidates[0]), self._max_image_bytes)
        _, _, file_format = inspect_image(content)
        return content, file_format

    def save_product_cutout(self, version_ref: str, cutout: ProductCutout) -> None:
        directory = self._store.path("images", version_ref, "product")
        directory.mkdir(parents=True, exist_ok=False)
        mask_width, mask_height, mask_format = inspect_image(cutout.mask_png)
        cutout_width, cutout_height, cutout_format = inspect_image(cutout.rgba_png)
        if (
            mask_format != "png"
            or cutout_format != "png"
            or (mask_width, mask_height) != (cutout.source_width, cutout.source_height)
            or (cutout_width, cutout_height) != (cutout.source_width, cutout.source_height)
        ):
            raise ImageGenerationError(
                "Product cutout artifacts do not match the source",
                "invalid_segmentation_response",
            )
        mask_path = self._store.write_bytes(
            cutout.mask_png, "images", version_ref, "product", "mask.png"
        )
        cutout_path = self._store.write_bytes(
            cutout.rgba_png, "images", version_ref, "product", "cutout.png"
        )
        metadata = {
            "schema_version": 1,
            "source_checksum": cutout.source_checksum,
            "mask_checksum": hashlib.sha256(cutout.mask_png).hexdigest(),
            "cutout_checksum": hashlib.sha256(cutout.rgba_png).hexdigest(),
            "model": cutout.model,
            "model_version": cutout.model_version,
            "prompt": cutout.prompt,
            "bounding_box": list(cutout.bounding_box),
            "source_dimensions": [cutout.source_width, cutout.source_height],
            "mask_path": str(mask_path.resolve()),
            "cutout_path": str(cutout_path.resolve()),
        }
        self._store.write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2),
            "images",
            version_ref,
            "product",
            "metadata.json",
        )
        review_path = self._store.path("images", version_ref, "review.json")
        review = json.loads(review_path.read_text(encoding="utf-8"))
        review["product_preservation"] = {
            "source_checksum": cutout.source_checksum,
            "mask_web_url": f"/artifacts/images/{version_ref}/product/mask.png",
            "cutout_web_url": f"/artifacts/images/{version_ref}/product/cutout.png",
            "model": cutout.model,
            "model_version": cutout.model_version,
            "bounding_box": list(cutout.bounding_box),
        }
        review_path.write_text(json.dumps(review, ensure_ascii=False, indent=2), encoding="utf-8")

    def save(self, version_ref: str, image: GeneratedImage) -> StoredImage:
        width, height, file_format = inspect_image(image.content)
        directory = self._store.path("images", version_ref)
        snapshot = json.loads((directory / "request.json").read_text(encoding="utf-8"))
        if (directory / "metadata.json").exists():
            raise FileExistsError("Image version already completed")
        checksum = hashlib.sha256(image.content).hexdigest()
        image_path = self._store.write_bytes(
            image.content, "images", version_ref, f"image.{file_format}"
        )
        metadata = asdict(image)
        metadata.pop("content")
        metadata.update(
            {
                "schema_version": 1,
                "version_ref": version_ref,
                "sha256": checksum,
                "width": width,
                "height": height,
                "file_format": file_format,
                "byte_size": len(image.content),
                "input": snapshot["input"],
                "input_assets": snapshot["input_assets"],
                "input_hash": snapshot["input_hash"],
                "cost": None,
                "cost_note": "Local compute cost not measured",
                "qa_scope": "technical_only",
                "artifact_role": "final",
                "raw_artifact_path": next(
                    (
                        str(path.resolve())
                        for path in (directory / "raw").glob("image.*")
                        if path.is_file()
                    ),
                    None,
                ),
                "product_metadata_path": (
                    str((directory / "product" / "metadata.json").resolve())
                    if (directory / "product" / "metadata.json").is_file()
                    else None
                ),
                "composition_path": (
                    str((directory / "composition.json").resolve())
                    if (directory / "composition.json").is_file()
                    else None
                ),
            }
        )
        metadata_path = self._store.write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2),
            "images",
            version_ref,
            "metadata.json",
        )
        return StoredImage(str(image_path.resolve()), checksum, str(metadata_path.resolve()))

    def save_raw(self, version_ref: str, image: GeneratedImage) -> StoredImage:
        width, height, file_format = inspect_image(image.content)
        directory = self._store.path("images", version_ref, "raw")
        directory.mkdir(parents=True, exist_ok=False)
        checksum = hashlib.sha256(image.content).hexdigest()
        image_path = self._store.write_bytes(
            image.content, "images", version_ref, "raw", f"image.{file_format}"
        )
        metadata = asdict(image)
        metadata.pop("content")
        metadata.update(
            {
                "schema_version": 1,
                "version_ref": version_ref,
                "sha256": checksum,
                "width": width,
                "height": height,
                "file_format": file_format,
                "byte_size": len(image.content),
                "artifact_role": "raw_visual",
            }
        )
        metadata_path = self._store.write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2),
            "images",
            version_ref,
            "raw",
            "metadata.json",
        )
        review_path = self._store.path("images", version_ref, "review.json")
        review = json.loads(review_path.read_text(encoding="utf-8"))
        review["raw_background"] = {
            "sha256": checksum,
            "web_url": f"/artifacts/images/{version_ref}/raw/image.{file_format}",
            "width": width,
            "height": height,
            "file_format": file_format,
        }
        review_path.write_text(json.dumps(review, ensure_ascii=False, indent=2), encoding="utf-8")
        return StoredImage(str(image_path.resolve()), checksum, str(metadata_path.resolve()))


class TechnicalImageChecker:
    """File checks only; a pass is not semantic or business approval."""

    def __init__(self, max_image_bytes: int = 30_000_000) -> None:
        self._max_image_bytes = max_image_bytes

    async def check(self, session: QASession) -> QACheckResult:
        if session.asset.artifact_path is None:
            raise ImageGenerationError("Generated image has no local artifact")
        content = read_local_image(session.asset.artifact_path, self._max_image_bytes)
        width, height, file_format = inspect_image(content)
        spec = session.input_contract.output_spec
        issues = []
        if (width, height) != (spec.width, spec.height):
            issues.append("output_dimensions_mismatch")
        expected_format = "jpeg" if spec.file_format.lower() == "jpg" else spec.file_format.lower()
        if file_format != expected_format:
            issues.append("output_format_mismatch")
        composition = session.input_contract.composition
        if composition is not None and composition.product_preservation is not None:
            directory = Path(session.asset.artifact_path).parent
            product_metadata_path = directory / "product" / "metadata.json"
            final_metadata_path = directory / "metadata.json"
            raw_metadata_path = directory / "raw" / "metadata.json"
            try:
                product_metadata = json.loads(product_metadata_path.read_text(encoding="utf-8"))
                final_metadata = json.loads(final_metadata_path.read_text(encoding="utf-8"))
                raw_metadata = json.loads(raw_metadata_path.read_text(encoding="utf-8"))
                execution = json.loads(final_metadata["execution_graph"])
                placement = execution["product_placement"]
                selected = composition.product_preservation.source_index
                source_assets = [
                    item
                    for item in final_metadata["input_assets"]
                    if item["role"] == "product_assets" and item["index"] == selected
                ]
                if len(source_assets) != 1 or (
                    source_assets[0]["sha256"] != product_metadata["source_checksum"]
                ):
                    issues.append("product_source_checksum_mismatch")
                if not placement or not placement.get("aspect_ratio_preserved"):
                    issues.append("product_placement_invalid")
                expected_box = [
                    round(composition.product_region.x * width / 1000),
                    round(composition.product_region.y * height / 1000),
                    round(
                        (composition.product_region.x + composition.product_region.width)
                        * width
                        / 1000
                    ),
                    round(
                        (composition.product_region.y + composition.product_region.height)
                        * height
                        / 1000
                    ),
                ]
                if placement.get("placement_box") != expected_box:
                    issues.append("product_placement_region_mismatch")
                if not raw_metadata.get("sha256"):
                    issues.append("raw_background_missing")
            except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError):
                issues.append("product_provenance_missing")
        return QACheckResult(
            passed=not issues,
            score=Decimal("0") if issues else Decimal("100"),
            issues=tuple(issues),
            warnings=(TECHNICAL_ONLY,),
            feedback="Technical checks only; creative quality has not been scored",
        )
