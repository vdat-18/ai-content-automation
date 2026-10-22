"""Opt-in, server-configured chat playground outside Marketing workflows."""

import os
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

router = APIRouter(prefix="/api/v1/model-lab", tags=["model-lab"])


class LabModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, pattern=r"^[a-zA-Z0-9._-]+$")
    label: str = Field(min_length=1)
    model: str = Field(min_length=1)
    base_url: str
    api_key_env: str | None = None
    timeout_seconds: float = Field(default=120, gt=0, le=600)

    @model_validator(mode="after")
    def valid_endpoint(self) -> "LabModel":
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
        if self.api_key_env is not None and not self.api_key_env.isidentifier():
            raise ValueError("api_key_env must be an environment variable name")
        return self


class LabConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    models: list[LabModel]

    @model_validator(mode="after")
    def unique_models(self) -> "LabConfig":
        if len({model.id for model in self.models}) != len(self.models):
            raise ValueError("Model Lab IDs must be unique")
        return self


class LabMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: str = Field(pattern=r"^(user|assistant)$")
    content: str = Field(min_length=1, max_length=16_000)


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model_id: str
    messages: list[LabMessage] = Field(min_length=1, max_length=30)


class ModelInfo(BaseModel):
    id: str
    label: str
    model: str


class ModelList(BaseModel):
    items: list[ModelInfo]


class ChatResponse(BaseModel):
    text: str
    model: str


class _ProviderMessage(BaseModel):
    content: str


class _ProviderChoice(BaseModel):
    message: _ProviderMessage


class _ProviderResponse(BaseModel):
    choices: list[_ProviderChoice] = Field(min_length=1)


def load_lab_config() -> LabConfig:
    config_path = os.getenv("AIC_AI_MODEL_LAB_CONFIG")
    if not config_path:
        return LabConfig(models=[])
    return LabConfig.model_validate_json(Path(config_path).read_text(encoding="utf-8"))


async def complete_chat(
    model: LabModel,
    messages: list[LabMessage],
    transport: httpx.AsyncBaseTransport | None = None,
) -> ChatResponse:
    api_key = os.getenv(model.api_key_env) if model.api_key_env else None
    if model.api_key_env and not api_key:
        raise HTTPException(status_code=503, detail="Model credential is not configured")
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    try:
        async with (
            httpx.AsyncClient(
                base_url=f"{model.base_url.rstrip('/')}/",
                headers=headers,
                timeout=httpx.Timeout(model.timeout_seconds, connect=10),
                transport=transport,
                follow_redirects=False,
                trust_env=False,
            ) as client,
            client.stream(
                "POST",
                "chat/completions",
                json={
                    "model": model.model,
                    "messages": [message.model_dump() for message in messages],
                    "stream": False,
                },
            ) as response,
        ):
            response.raise_for_status()
            body = bytearray()
            async for chunk in response.aiter_bytes():
                body.extend(chunk)
                if len(body) > 1_000_000:
                    raise ValueError("Provider response is too large")
        parsed = _ProviderResponse.model_validate_json(body)
        if not parsed.choices[0].message.content:
            raise ValueError("Provider returned empty content")
    except httpx.TimeoutException as exc:
        raise HTTPException(status_code=504, detail="Model request timed out") from exc
    except (httpx.HTTPError, ValidationError, ValueError) as exc:
        raise HTTPException(status_code=502, detail="Model request failed") from exc
    return ChatResponse(text=parsed.choices[0].message.content, model=model.model)


@router.get("/models", response_model=ModelList)
async def list_models() -> ModelList:
    return ModelList(
        items=[ModelInfo(id=m.id, label=m.label, model=m.model) for m in load_lab_config().models]
    )


@router.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest) -> ChatResponse:
    model = next((item for item in load_lab_config().models if item.id == request.model_id), None)
    if model is None:
        raise HTTPException(status_code=404, detail="Model is not configured")
    return await complete_chat(model, request.messages)
