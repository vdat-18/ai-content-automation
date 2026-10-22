"""Image backend factory for the fixture pilot."""

from .adapters.comfyui import ComfyUIBackend
from .adapters.invokeai import InvokeAIBackend
from .adapters.openai_compatible_images import OpenAICompatibleImageBackend
from .adapters.synthetic_images import SyntheticImageBackend
from .config.images import (
    ImageBackendConfig,
)
from .ports.images import IImageBackend


def build_image_backend(config: ImageBackendConfig, api_key: str | None = None) -> IImageBackend:
    if config.backend == "synthetic":
        return SyntheticImageBackend()
    if config.backend == "invokeai":
        return InvokeAIBackend(config, api_key=api_key)
    if config.backend == "comfyui":
        return ComfyUIBackend(config)
    return OpenAICompatibleImageBackend(config, api_key=api_key)
