"""Binary generation boundary; service-specific graphs stay in adapters."""

from dataclasses import dataclass
from typing import Literal, Protocol

from .contracts import RevisionRequest, StaticCreativeInput


@dataclass(frozen=True)
class ImageGenerationRequest:
    input: StaticCreativeInput
    seed: int
    input_hash: str | None = None
    revision: RevisionRequest | None = None
    revision_image_ref: str | None = None
    generation_target: Literal["full_visual", "background"] = "full_visual"


@dataclass(frozen=True)
class GeneratedImage:
    content: bytes
    model: str
    model_revision: str
    runtime_version: str
    workflow_hash: str
    prompt: str
    seed: int
    elapsed_seconds: float
    seed_applied: bool = True
    service_job_id: str | None = None
    # Serialized execution graph, including actual model parameters.
    execution_graph: str | None = None


@dataclass(frozen=True)
class StoredImage:
    path: str
    checksum: str
    metadata_path: str


@dataclass(frozen=True)
class ProductCutout:
    rgba_png: bytes
    mask_png: bytes
    source_checksum: str
    model: str
    model_version: str
    prompt: str
    bounding_box: tuple[int, int, int, int]
    source_width: int
    source_height: int


class IImageBackend(Protocol):
    async def generate(self, request: ImageGenerationRequest) -> GeneratedImage: ...


class IGeneratedImageStore(Protocol):
    def prepare(
        self, version_ref: str, request: ImageGenerationRequest
    ) -> ImageGenerationRequest: ...

    def save(self, version_ref: str, image: GeneratedImage) -> StoredImage: ...

    def save_raw(self, version_ref: str, image: GeneratedImage) -> StoredImage: ...

    def save_product_cutout(self, version_ref: str, cutout: ProductCutout) -> None: ...


class IProductSegmenter(Protocol):
    async def extract(self, source_ref: str, prompt: str) -> ProductCutout: ...


class IStaticRenderer(Protocol):
    def render(
        self,
        image: GeneratedImage,
        input_data: StaticCreativeInput,
        product_cutout: ProductCutout | None = None,
    ) -> GeneratedImage: ...


class ImageGenerationError(Exception):
    """Expected input, service or image failure safe to include in run reports."""

    def __init__(self, message: str, code: str = "image_generation_error") -> None:
        super().__init__(message)
        self.code = code
