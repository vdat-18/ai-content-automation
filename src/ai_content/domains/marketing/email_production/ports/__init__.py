"""Ports used by Email production."""

from .interfaces import (
    EmailProductionInputDriftError,
    IEmailPackageGenerator,
    IEmailPreflightGateway,
    IEmailProductionRepository,
    IEmailSemanticReviewer,
    PreflightOutcome,
)

__all__ = [
    "EmailProductionInputDriftError",
    "IEmailPackageGenerator",
    "IEmailPreflightGateway",
    "IEmailProductionRepository",
    "IEmailSemanticReviewer",
    "PreflightOutcome",
]
