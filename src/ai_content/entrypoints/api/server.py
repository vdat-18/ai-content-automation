"""Uvicorn entrypoint for dashboard API."""

from __future__ import annotations

import uvicorn


def main() -> None:
    """Run the dashboard API server."""
    uvicorn.run("ai_content.entrypoints.api.app:app", host="0.0.0.0", port=8000, reload=True)


if __name__ == "__main__":
    main()
