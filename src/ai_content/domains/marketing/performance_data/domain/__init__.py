"""Domain exports for Performance data ingestion."""

from .models import (
    CatalogProduct,
    GmcIngestionRun,
    GmcIngestionSpec,
    GmcRunStatus,
    NormalizedProductRow,
    ProcessedProductRow,
    ProductFieldStatus,
    RunIssue,
    RunIssueSeverity,
    SourceDescriptor,
)

__all__ = [
    "CatalogProduct",
    "GmcIngestionRun",
    "GmcIngestionSpec",
    "GmcRunStatus",
    "NormalizedProductRow",
    "ProcessedProductRow",
    "ProductFieldStatus",
    "RunIssue",
    "RunIssueSeverity",
    "SourceDescriptor",
]
