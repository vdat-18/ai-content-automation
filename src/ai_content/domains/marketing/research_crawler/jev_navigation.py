"""TypeSafe Jev decides what the crawler does next on the current page."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

_PAGE_STATUS = {
    "content": (
        "The page shows results or media that can be collected, even if it also offers a "
        "sign-in button."
    ),
    "modal": "A popup, cookie banner or dialog covers the content.",
    "login_required": "The page shows no results and asks the visitor to sign in first.",
    "blocked": "The page shows a captcha, an access-denied message or an error.",
}
_SAFETY_POLICY = (
    "Read-only research. Never buy, submit forms, sign in, sign up or leave the current site."
)


@dataclass(frozen=True)
class NavigationDecision:
    page_status: str
    action: str
    confidence: float


class JevBrowserNavigator:
    def __init__(
        self,
        api_key: str,
        *,
        endpoint: str,
        model: str = "jev-latest",
        timeout_seconds: float = 30,
    ) -> None:
        self._api_key = api_key
        self._endpoint = endpoint
        self._model = model
        self._timeout = timeout_seconds

    async def decide(
        self,
        snapshot: dict[str, Any],
        *,
        goal: str,
        collected_media: int,
        rounds_without_new_media: int,
    ) -> NavigationDecision:
        actions = {
            "scroll_down": "Scroll down to reveal more results or lazy-loaded media.",
            "done": "Stop because the page shows no more results to collect.",
        }
        for control in snapshot["controls"]:
            actions[f"click_{control['id']}"] = f"Click the control labelled {control['text']!r}."
        payload = {
            "model": self._model,
            "state": {
                "goal": goal,
                "safety_policy": _SAFETY_POLICY,
                "page": {
                    "url": snapshot["url"],
                    "title": snapshot["title"],
                    "visible_text": snapshot["text"],
                },
                "collected_media": collected_media,
                "rounds_without_new_media": rounds_without_new_media,
            },
            "questions": {
                "page_status": {
                    "type": "choice",
                    "instructions": "Classify what the page currently shows.",
                    "criteria": _PAGE_STATUS,
                },
                "next_action": {
                    "type": "choice",
                    "instructions": "Choose the next action that best serves the goal.",
                    "criteria": actions,
                },
            },
        }
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response = await client.post(
                self._endpoint,
                headers={"Authorization": f"Bearer {self._api_key}"},
                json=payload,
            )
        response.raise_for_status()
        answers = response.json()["answers"]
        return NavigationDecision(
            page_status=answers["page_status"]["choice"],
            action=answers["next_action"]["choice"],
            confidence=float(answers["next_action"].get("confidence", 0)),
        )


__all__ = ["JevBrowserNavigator", "NavigationDecision"]
