"""Thin, timeout-guarded Tavily web-search client."""

import httpx
from pydantic import BaseModel

from app.config import Settings

_TAVILY_SEARCH_URL = "https://api.tavily.com/search"


class WebSearchUnavailableError(Exception):
    """Raised when Tavily cannot be reached, times out, or rejects the request."""


class WebResult(BaseModel):
    title: str
    url: str
    snippet: str


class WebSearchClient:
    """Queries Tavily for program information the knowledge base doesn't cover."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def search(self, query: str) -> list[WebResult]:
        if not self._settings.tavily_api_key:
            raise WebSearchUnavailableError("TAVILY_API_KEY is not configured")

        try:
            async with httpx.AsyncClient(
                timeout=self._settings.web_search_timeout_seconds
            ) as client:
                response = await client.post(
                    _TAVILY_SEARCH_URL,
                    json={
                        "api_key": self._settings.tavily_api_key,
                        "query": query,
                        "max_results": self._settings.retrieval_top_k,
                    },
                )
                response.raise_for_status()
                body = response.json()
        except httpx.HTTPError as exc:
            raise WebSearchUnavailableError("Tavily search failed") from exc
        except ValueError as exc:
            raise WebSearchUnavailableError("Tavily response was not valid JSON") from exc

        try:
            return [
                WebResult(
                    title=result.get("title", ""),
                    url=result.get("url", ""),
                    snippet=result.get("content", ""),
                )
                for result in body.get("results", [])
            ]
        except AttributeError as exc:
            raise WebSearchUnavailableError("Tavily response had an unexpected shape") from exc
