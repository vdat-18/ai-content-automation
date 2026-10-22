"""Deterministic copy and logo rendering for planned static compositions."""

from __future__ import annotations

import hashlib
import io
import json
from dataclasses import asdict, replace

from PIL import Image, ImageColor, ImageDraw, ImageFont

from ..ports.contracts import NormalizedRegion, StaticCreativeInput, TextPlacement
from ..ports.images import GeneratedImage, ImageGenerationError, ProductCutout
from .image_files import inspect_image, read_local_image

RENDERER_VERSION = "pillow-static@4"


def _pixel_box(region: NormalizedRegion, width: int, height: int) -> tuple[int, int, int, int]:
    left = round(region.x * width / 1000)
    top = round(region.y * height / 1000)
    right = round((region.x + region.width) * width / 1000)
    bottom = round((region.y + region.height) * height / 1000)
    return left, top, right, bottom


def _wrap(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont, width: int) -> str:
    lines: list[str] = []
    for paragraph in text.splitlines() or [text]:
        current = ""
        for word in paragraph.split():
            candidate = f"{current} {word}".strip()
            if not current or draw.textbbox((0, 0), candidate, font=font)[2] <= width:
                current = candidate
            else:
                lines.append(current)
                current = word
        lines.append(current)
    return "\n".join(lines)


def _fit_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    box: tuple[int, int, int, int],
) -> tuple[ImageFont.ImageFont, str]:
    width = box[2] - box[0]
    height = box[3] - box[1]
    for size in range(max(12, height // 3), 11, -2):
        font = ImageFont.load_default(size=size)
        wrapped = _wrap(draw, text, font, width)
        bounds = draw.multiline_textbbox((0, 0), wrapped, font=font, spacing=max(2, size // 5))
        if bounds[2] <= width and bounds[3] <= height:
            return font, wrapped
    raise ImageGenerationError(
        "Approved copy does not fit the planned text region", "copy_overflow"
    )


def _draw_text(
    image: Image.Image,
    text: str,
    placement: TextPlacement,
) -> None:
    draw = ImageDraw.Draw(image)
    box = _pixel_box(placement.region, image.width, image.height)
    try:
        foreground = ImageColor.getcolor(placement.text_color, "RGBA")
        background = (
            ImageColor.getcolor(placement.background_color, "RGBA")
            if placement.background_color
            else None
        )
    except ValueError as error:
        raise ImageGenerationError(
            "Composition contains an invalid color", "invalid_composition"
        ) from error
    if background is not None:
        draw.rounded_rectangle(box, radius=max(4, image.width // 100), fill=background)
    padding = max(4, image.width // 100)
    content_box = (box[0] + padding, box[1] + padding, box[2] - padding, box[3] - padding)
    font, wrapped = _fit_text(draw, text, content_box)
    spacing = max(2, getattr(font, "size", 12) // 5)
    bounds = draw.multiline_textbbox((0, 0), wrapped, font=font, spacing=spacing)
    text_width = bounds[2] - bounds[0]
    text_height = bounds[3] - bounds[1]
    if placement.alignment == "center":
        x = content_box[0] + (content_box[2] - content_box[0] - text_width) // 2
    elif placement.alignment == "right":
        x = content_box[2] - text_width
    elif placement.alignment == "left":
        x = content_box[0]
    else:
        raise ImageGenerationError(
            "Composition contains an invalid alignment", "invalid_composition"
        )
    y = content_box[1] + (content_box[3] - content_box[1] - text_height) // 2
    draw.multiline_text((x, y), wrapped, font=font, fill=foreground, spacing=spacing)


class PillowStaticRenderer:
    """Finish a visual to the requested format, then render optional copy and logo."""

    def render(
        self,
        image: GeneratedImage,
        input_data: StaticCreativeInput,
        product_cutout: ProductCutout | None = None,
    ) -> GeneratedImage:
        composition = input_data.composition
        spec = input_data.output_spec
        raw_width, raw_height, raw_format = inspect_image(image.content)
        file_format = spec.file_format.lower()
        if file_format not in {"jpg", "jpeg", "png", "webp"}:
            raise ImageGenerationError(
                "Renderer supports only PNG, JPEG and WebP", "unsupported_output_format"
            )
        output_format = "jpeg" if file_format in {"jpg", "jpeg"} else file_format
        if (
            composition is None
            and product_cutout is None
            and (raw_width, raw_height) == (spec.width, spec.height)
            and raw_format == output_format
        ):
            return image
        if raw_width * spec.height != raw_height * spec.width:
            raise ImageGenerationError(
                "Generated visual aspect ratio does not match output spec",
                "output_aspect_ratio_mismatch",
            )
        if raw_width < spec.width or raw_height < spec.height:
            raise ImageGenerationError(
                "Generated visual is smaller than output spec", "output_upscale_required"
            )
        with Image.open(io.BytesIO(image.content)) as source:
            rendered = source.convert("RGBA")
            if (raw_width, raw_height) != (spec.width, spec.height):
                rendered = rendered.resize(
                    (spec.width, spec.height),
                    Image.Resampling.LANCZOS,
                )
        width, height = rendered.size
        product_placement: dict[str, object] | None = None
        if product_cutout is not None:
            if composition is None or composition.product_preservation is None:
                raise ImageGenerationError(
                    "Product cutout requires a preservation composition",
                    "invalid_composition",
                )
            with Image.open(io.BytesIO(product_cutout.rgba_png)) as cutout_source:
                cutout = cutout_source.convert("RGBA")
            left, top, right, bottom = product_cutout.bounding_box
            cutout = cutout.crop((left, top, right, bottom))
            if cutout.width <= 0 or cutout.height <= 0:
                raise ImageGenerationError(
                    "Product cutout bounding box is empty", "empty_segmentation_mask"
                )
            box = _pixel_box(composition.product_region, width, height)
            box_width = box[2] - box[0]
            box_height = box[3] - box[1]
            scale = min(box_width / cutout.width, box_height / cutout.height)
            target_size = (
                max(1, round(cutout.width * scale)),
                max(1, round(cutout.height * scale)),
            )
            cutout = cutout.resize(target_size, Image.Resampling.LANCZOS)
            position = (
                box[0] + (box_width - cutout.width) // 2,
                box[3] - cutout.height,
            )
            rendered.alpha_composite(cutout, position)
            product_placement = {
                "source_checksum": product_cutout.source_checksum,
                "mask_checksum": hashlib.sha256(product_cutout.mask_png).hexdigest(),
                "cutout_checksum": hashlib.sha256(product_cutout.rgba_png).hexdigest(),
                "source_dimensions": [
                    product_cutout.source_width,
                    product_cutout.source_height,
                ],
                "source_bounding_box": list(product_cutout.bounding_box),
                "placement_box": list(box),
                "placed_position": list(position),
                "placed_dimensions": list(target_size),
                "scale": scale,
                "aspect_ratio_preserved": True,
                "model": product_cutout.model,
                "model_version": product_cutout.model_version,
            }
        if composition is not None:
            _draw_text(rendered, input_data.heading, composition.heading)
            if input_data.subtext and composition.subtext:
                _draw_text(rendered, input_data.subtext, composition.subtext)
            if input_data.logo_asset and composition.logo_region:
                logo_content = read_local_image(input_data.logo_asset.url)
                with Image.open(io.BytesIO(logo_content)) as logo_source:
                    logo = logo_source.convert("RGBA")
                box = _pixel_box(composition.logo_region, width, height)
                logo.thumbnail((box[2] - box[0], box[3] - box[1]), Image.Resampling.LANCZOS)
                position = (
                    box[0] + (box[2] - box[0] - logo.width) // 2,
                    box[1] + (box[3] - box[1] - logo.height) // 2,
                )
                rendered.alpha_composite(logo, position)
        output = io.BytesIO()
        if file_format in {"jpg", "jpeg"}:
            rendered.convert("RGB").save(output, format="JPEG", quality=95)
        elif file_format == "webp":
            rendered.save(output, format="WEBP", quality=95, method=6)
        else:
            rendered.save(output, format="PNG")
        finish_spec = {
            "composition": asdict(composition) if composition is not None else None,
            "width": spec.width,
            "height": spec.height,
            "format": output_format,
        }
        finish_payload = json.dumps(finish_spec, sort_keys=True, separators=(",", ":"))
        workflow_hash = hashlib.sha256(
            f"{image.workflow_hash}:{RENDERER_VERSION}:{finish_payload}".encode()
        ).hexdigest()
        execution = {
            "image_backend": image.execution_graph,
            "renderer": RENDERER_VERSION,
            "composition_id": composition.composition_id if composition is not None else None,
            "raw_sha256": hashlib.sha256(image.content).hexdigest(),
            "raw_dimensions": [raw_width, raw_height],
            "raw_format": raw_format,
            "output_dimensions": [width, height],
            "output_format": output_format,
            "resized": (raw_width, raw_height) != (width, height),
            "product_placement": product_placement,
        }
        return replace(
            image,
            content=output.getvalue(),
            runtime_version=f"{image.runtime_version}+{RENDERER_VERSION}",
            workflow_hash=workflow_hash,
            execution_graph=json.dumps(execution, sort_keys=True),
        )


__all__ = ["PillowStaticRenderer", "RENDERER_VERSION"]
