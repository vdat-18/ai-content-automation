"""Test configuration."""

from pathlib import Path

import pytest


@pytest.fixture
def project_root() -> Path:
    """Get project root directory."""
    return Path(__file__).parent.parent


@pytest.fixture
def src_root(project_root: Path) -> Path:
    """Get src directory."""
    return project_root / "src" / "ai_content"
