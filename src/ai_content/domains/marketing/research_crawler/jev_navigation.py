"""TypeSafe Jev decisions for safe, read-only browser navigation."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

import httpx
from pydantic import BaseModel, ConfigDict, Field

_MAX_CONTROLS = 40
_MAX_REQUEST_BYTES = 64 * 1024

_DISCOVER_CONTROLS_SCRIPT = r"""() => {
  const clean = (value) => (value || '').replace(/\s+/g, ' ').trim();
  const unsafe = /\b(buy|checkout|purchase|order|sign in|log in|subscribe|delete|remove)\b/i;
  const useful = /\b(load|show)\s+more\b|\bmore\s+results\b|^next$|pagination/i;
  const nodes = [...document.querySelectorAll('button, a[href], [role="button"]')];
  const controls = [];
  for (const node of nodes) {
    const rect = node.getBoundingClientRect();
    const text = clean(node.innerText || node.getAttribute('aria-label') || node.title);
    if (!text || rect.width < 1 || rect.height < 1 || unsafe.test(text)) continue;
    const href = node.href || '';
    const rel = clean(node.getAttribute('rel'));
    const inPagination = Boolean(node.closest('[aria-label*="pagination" i], [class*="pagination" i]'));
    if (!useful.test(`${text} ${rel}`) && !inPagination) continue;
    const id = `control_${controls.length}`;
    node.setAttribute('data-aic-jev-control', id);
    controls.push({id, tag: node.tagName.toLowerCase(), text: text.slice(0, 180), href});
    if (controls.length >= 40) break;
  }
  return {
    title: document.title || '',
    url: location.href,
    visible_text: clean(document.body?.innerText).slice(0, 6000),
    controls
  };
}"""


class _ChoiceAnswer(BaseModel):
    model_config = ConfigDict(extra="ignore")

    choice: str
    probabilities: dict[str, float] = Field(default_factory=dict)
    confidence: float = 0


class _JevResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    model: str | None = None
    answers: dict[str, _ChoiceAnswer]


@dataclass(frozen=True)
class BrowserDecision:
    action: str
    confidence: float
    model: str


class JevBrowserNavigator:
    """Ask Jev which safe discovery action should run on the current page."""

    def __init__(
        self,
        api_key: str,
        *,
        model: str = "jev-latest",
        endpoint: str,
        timeout_seconds: float = 30,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._endpoint = endpoint
        self._timeout = timeout_seconds
        self._client = client

    async def step(
        self,
        page: Any,
        *,
        goal: str,
        discovered_records: int,
        stable_rounds: int,
        may_finish: bool,
    ) -> BrowserDecision:
        page_state = await page.evaluate(_DISCOVER_CONTROLS_SCRIPT)
        controls = list(page_state.get("controls") or [])[:_MAX_CONTROLS]
        criteria = {
            "scroll_down": (
                "Scroll down to reveal more results or lazy-loaded data. Prefer this when "
                "the page can still contain unseen records."
            ),
        }
        for control in controls:
            criteria[f"click_{control['id']}"] = (
                f"Click the safe discovery control labelled {control['text']!r}"
            )
        if may_finish:
            criteria["done"] = (
                "Finish only because repeated discovery actions produced no new records and "
                "there is no useful load-more or next-page control."
            )
        payload = {
            "model": self._model,
            "state": {
                "goal": goal,
                "safety_policy": (
                    "Read-only research. Never buy, submit, sign in, or leave the current site."
                ),
                "page": {
                    "url": str(page_state.get("url") or page.url),
                    "title": str(page_state.get("title") or "")[:300],
                    "visible_text": str(page_state.get("visible_text") or "")[:6000],
                },
                "discovered_records": discovered_records,
                "consecutive_rounds_without_new_records": stable_rounds,
            },
            "questions": {
                "next_action": {
                    "type": "choice",
                    "instructions": (
                        "Choose the next safe action that most likely exposes every remaining "
                        "public result. Use only an action listed in the criteria."
                    ),
                    "criteria": criteria,
                }
            },
        }
        result = await self._call(payload)
        answer = result.answers.get("next_action")
        if answer is None or answer.choice not in criteria:
            raise ValueError("Jev returned an unsupported browser action")
        if answer.choice.startswith("click_"):
            await self._click(page, answer.choice.removeprefix("click_"), controls)
        elif answer.choice == "scroll_down":
            await page.mouse.wheel(0, 1_600)
        return BrowserDecision(
            action=answer.choice,
            confidence=answer.confidence,
            model=result.model or self._model,
        )

    async def _click(self, page: Any, control_id: str, controls: list[dict[str, Any]]) -> None:
        control = next((item for item in controls if item.get("id") == control_id), None)
        if control is None:
            raise ValueError("Jev selected a browser control that no longer exists")
        href = str(control.get("href") or "")
        if href and urlsplit(href).hostname != urlsplit(str(page.url)).hostname:
            raise ValueError("Jev attempted to leave the current public source")
        locator = page.locator(f'[data-aic-jev-control="{control_id}"]')
        await locator.first.click(timeout=5_000)

    async def _call(self, payload: dict[str, Any]) -> _JevResponse:
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
        if len(body) > _MAX_REQUEST_BYTES:
            raise ValueError("Jev browser state exceeds the 64 KiB API limit")
        owns_client = self._client is None
        client = self._client or httpx.AsyncClient(timeout=self._timeout)
        try:
            response = await client.post(
                self._endpoint,
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
                content=body,
            )
            response.raise_for_status()
            return _JevResponse.model_validate(response.json())
        finally:
            if owns_client:
                await client.aclose()


__all__ = ["BrowserDecision", "JevBrowserNavigator"]
