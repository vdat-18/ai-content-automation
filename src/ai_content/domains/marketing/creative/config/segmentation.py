"""Typed configuration for the product segmentation service."""

from pathlib import Path
from typing import Self
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ProductSegmenterConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    base_url: str
    model: str = Field(default="SAM 3.1", min_length=1)
    model_version: str = Field(min_length=1)
    request_timeout_seconds: float = Field(default=120, gt=0)
    max_image_bytes: int = Field(default=100_000_000, gt=0)
    max_response_bytes: int = Field(default=200_000_000, gt=0)

    @model_validator(mode="after")
    def validate_url(self) -> Self:
        url = urlsplit(self.base_url)
        if (
            url.scheme not in {"http", "https"}
            or not url.hostname
            or url.username
            or url.password
            or url.query
            or url.fragment
        ):
            raise ValueError("base_url must be an HTTP endpoint without credentials or query")
        return self


def load_product_segmenter_config(path: Path) -> ProductSegmenterConfig:
    return ProductSegmenterConfig.model_validate_json(path.read_text(encoding="utf-8"))


__all__ = ["ProductSegmenterConfig", "load_product_segmenter_config"]
