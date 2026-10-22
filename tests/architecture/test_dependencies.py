"""Architecture tests for dependency direction across the modular monolith."""

import ast
from pathlib import Path

import pytest


def _python_files(path: Path) -> list[Path]:
    files = list(path.rglob("*.py"))
    assert files, f"No Python files found in {path}"
    return files


def _imports(path: Path) -> list[tuple[int, str]]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imports: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend((node.lineno, alias.name) for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imports.append((node.lineno, f"{'.' * node.level}{node.module or ''}"))
    return imports


def _violations(files: list[Path], forbidden: set[str]) -> list[str]:
    violations: list[str] = []
    for path in files:
        for line, imported in _imports(path):
            blocked = sorted(set(imported.lstrip(".").split(".")) & forbidden)
            if blocked:
                violations.append(f"{path}:{line}: {imported} ({', '.join(blocked)})")
    return violations


@pytest.fixture
def marketing_root(project_root: Path) -> Path:
    return project_root / "src" / "ai_content" / "domains" / "marketing"


def test_all_marketing_domain_layers_are_framework_independent(marketing_root: Path) -> None:
    files = [
        path
        for bounded_context in marketing_root.iterdir()
        if bounded_context.is_dir() and (bounded_context / "domain").exists()
        for path in _python_files(bounded_context / "domain")
    ]
    violations = _violations(
        files,
        {"adapters", "application", "bootstrap", "config", "entrypoints", "platform", "ports"},
    )
    assert not violations, "Domain dependency violations:\n" + "\n".join(violations)


def test_all_marketing_application_layers_avoid_outward_dependencies(
    marketing_root: Path,
) -> None:
    files = [
        path
        for bounded_context in marketing_root.iterdir()
        if bounded_context.is_dir() and (bounded_context / "application").exists()
        for path in _python_files(bounded_context / "application")
    ]
    violations = _violations(files, {"adapters", "bootstrap", "config", "entrypoints"})
    assert not violations, "Application dependency violations:\n" + "\n".join(violations)


def test_shared_platform_does_not_import_business_domains(project_root: Path) -> None:
    files = _python_files(project_root / "src" / "ai_content" / "platform")
    violations = _violations(files, {"domains"})
    assert not violations, "Platform dependency violations:\n" + "\n".join(violations)


def test_creative_public_contracts_are_importable() -> None:
    from ai_content.domains.marketing.creative import domain, ports
    from ai_content.domains.marketing.creative.application import use_cases
    from ai_content.domains.marketing.creative.ports import contracts

    assert ports.IImageGenerator
    assert ports.IQAChecker
    assert ports.ICreativeRepository
    assert domain.CreativeJob
    assert domain.AssetVersion
    assert contracts.StaticCreativeInput
    assert use_cases.RunCreativeWorkflow
