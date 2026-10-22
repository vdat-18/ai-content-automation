"""Offline bitmap smoke test. This backend performs no AI generation."""

import io
from time import monotonic

from PIL import Image, ImageDraw

from ..ports.images import GeneratedImage, ImageGenerationRequest
from .image_files import read_local_image


class SyntheticImageBackend:
    async def generate(self, request: ImageGenerationRequest) -> GeneratedImage:
        start = monotonic()
        spec = request.input.output_spec
        if request.generation_target == "background":
            image = Image.new("RGB", (spec.width, spec.height), (232, 228, 220))
        else:
            source_ref = request.revision_image_ref or request.input.product_assets[0].url
            content = read_local_image(source_ref)
            with Image.open(io.BytesIO(content)) as source:
                image = source.convert("RGB").resize((spec.width, spec.height))
        ImageDraw.Draw(image).text((10, 10), "SYNTHETIC - NOT AI OUTPUT", fill="red")
        output = io.BytesIO()
        image.save(output, format="JPEG" if spec.file_format.lower() in {"jpg", "jpeg"} else "PNG")
        return GeneratedImage(
            content=output.getvalue(),
            model="synthetic-bitmap",
            model_revision="1",
            runtime_version="pillow",
            workflow_hash="synthetic-v1",
            prompt="Synthetic fixture only",
            seed=request.seed,
            elapsed_seconds=monotonic() - start,
        )
