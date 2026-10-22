"""Configuration loader for YAML config files."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


class ConfigError(Exception):
    """Error loading configuration."""

    pass


@dataclass(frozen=True)
class PromptConfig:
    prompt_id: str
    version: str
    status: str
    is_draft: bool


@dataclass(frozen=True)
class RubricConfig:
    rubric_id: str
    version: str
    status: str
    is_draft: bool


@dataclass(frozen=True)
class WorkflowConfig:
    workflow_id: str
    version: str
    status: str


@dataclass(frozen=True)
class PolicyConfig:
    policy_id: str
    version: str
    status: str


@dataclass(frozen=True)
class RuleConfig:
    rule_id: str
    version: str
    status: str


class ConfigLoader:
    """Load and validate YAML configuration files."""

    def __init__(self, config_dir: Path) -> None:
        self._config_dir = config_dir

    def load_prompt(self, prompt_id: str, version: str) -> PromptConfig:
        data = self._load_versioned("prompts/creative", prompt_id, version)

        return PromptConfig(
            prompt_id=data["id"],
            version=data["version"],
            status=data["status"],
            is_draft=data.get("status") == "draft",
        )

    def load_rubric(self, rubric_id: str, version: str) -> RubricConfig:
        data = self._load_versioned("rubrics/creative", rubric_id, version)

        return RubricConfig(
            rubric_id=data["id"],
            version=data["version"],
            status=data["status"],
            is_draft=data.get("status") == "draft",
        )

    def load_workflow(
        self,
        workflow_id: str,
        version: str,
    ) -> WorkflowConfig:
        data = self._load_versioned("workflows", workflow_id, version)

        return WorkflowConfig(
            workflow_id=data["id"],
            version=data["version"],
            status=data["status"],
        )

    def load_policy(self, policy_id: str, version: str) -> PolicyConfig:
        data = self._load_versioned("policies/creative", policy_id, version)
        return PolicyConfig(
            policy_id=data["id"],
            version=data["version"],
            status=data["status"],
        )

    def load_rule(self, rule_id: str, version: str) -> RuleConfig:
        data = self._load_versioned("rules/creative", rule_id, version)
        return RuleConfig(
            rule_id=data["id"],
            version=data["version"],
            status=data["status"],
        )

    def validate_work_item_versions(
        self,
        *,
        prompt_id: str,
        prompt_version: str,
        rubric_id: str,
        rubric_version: str,
        policy_id: str,
        policy_version: str,
        rule_id: str,
        rule_version: str,
        workflow_id: str,
        workflow_version: str,
    ) -> None:
        """Resolve every version reference before a workflow run starts."""
        self.load_prompt(prompt_id, prompt_version)
        self.load_rubric(rubric_id, rubric_version)
        self.load_policy(policy_id, policy_version)
        self.load_rule(rule_id, rule_version)
        self.load_workflow(workflow_id, workflow_version)

    def _load_versioned(
        self,
        relative_dir: str,
        expected_id: str,
        expected_version: str,
    ) -> dict[str, Any]:
        directory = self._config_dir / relative_dir
        if not directory.is_dir():
            raise ConfigError(f"Config directory not found: {directory}")

        configs: list[dict[str, Any]] = []
        for config_file in sorted(directory.glob("*.yaml")):
            try:
                data = self._load_yaml(config_file)
            except yaml.YAMLError as e:
                raise ConfigError(f"Invalid YAML in {config_file}: {e}") from e
            self._validate_required_fields(data, config_file)
            configs.append(data)

        matches = [
            data
            for data in configs
            if data["id"] == expected_id and data["version"] == expected_version
        ]

        if not matches:
            same_version = [data for data in configs if data["version"] == expected_version]
            if same_version:
                actual_ids = ", ".join(sorted(str(data["id"]) for data in same_version))
                raise ConfigError(f"ID mismatch: expected {expected_id}, found {actual_ids}")
            same_id = [data for data in configs if data["id"] == expected_id]
            if same_id:
                actual_versions = ", ".join(sorted(str(data["version"]) for data in same_id))
                raise ConfigError(
                    f"Version mismatch: expected {expected_version}, found {actual_versions}"
                )
            raise ConfigError(
                f"Config not found for {expected_id}@{expected_version} in {directory}"
            )
        if len(matches) > 1:
            raise ConfigError(
                f"Multiple configs found for {expected_id}@{expected_version} in {directory}"
            )
        return matches[0]

    @staticmethod
    def _validate_required_fields(data: dict[str, Any], file_path: Path) -> None:
        for field in ("id", "version", "status"):
            if field not in data:
                raise ConfigError(f"Missing required field '{field}' in {file_path}")

    def _load_yaml(self, file_path: Path) -> dict[str, Any]:
        with file_path.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

        if not isinstance(data, dict):
            raise ConfigError(f"Config must be a YAML mapping: {file_path}")

        return data


__all__ = [
    "ConfigError",
    "PromptConfig",
    "RubricConfig",
    "WorkflowConfig",
    "PolicyConfig",
    "RuleConfig",
    "ConfigLoader",
]
