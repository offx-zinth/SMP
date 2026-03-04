from __future__ import annotations

import logging
import os
from urllib.parse import quote_plus

import httpx
from bs4 import BeautifulSoup

from vibecoder.agent.tools_async import tool

logger = logging.getLogger(__name__)


class KnowledgeEngine:
    """Web retrieval toolbelt for up-to-date docs and troubleshooting context."""

    def __init__(self, *, timeout_sec: float = 15.0, user_agent: str | None = None) -> None:
        self._timeout = httpx.Timeout(timeout_sec)
        self._user_agent = user_agent or "VibeCoderKnowledgeEngine/1.0 (+https://example.com)"
        self._tavily_api_key = os.getenv("TAVILY_API_KEY", "").strip()

    @tool
    async def search_web(self, query: str) -> str:
        query = query.strip()
        if not query:
            return "No query provided."

        if self._tavily_api_key:
            result = await self._search_tavily(query)
            if result:
                return result

        return await self._search_duckduckgo_html(query)

    @tool
    async def fetch_url(self, url: str) -> str:
        if not url.startswith(("http://", "https://")):
            return "Invalid URL."

        headers = {"User-Agent": self._user_agent}
        async with httpx.AsyncClient(timeout=self._timeout, follow_redirects=True, headers=headers) as client:
            response = await client.get(url)
            response.raise_for_status()
        return self._html_to_markdown(response.text, source_url=str(response.url))

    async def _search_tavily(self, query: str) -> str | None:
        headers = {"Authorization": f"Bearer {self._tavily_api_key}"}
        payload = {
            "query": query,
            "search_depth": "advanced",
            "include_answer": True,
            "max_results": 5,
        }
        try:
            async with httpx.AsyncClient(timeout=self._timeout, headers=headers) as client:
                response = await client.post("https://api.tavily.com/search", json=payload)
                response.raise_for_status()
            data = response.json()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Tavily search failed, falling back to DDG: %s", exc)
            return None

        lines = [f"# Web search results for: {query}"]
        answer = str(data.get("answer", "")).strip()
        if answer:
            lines.append(f"\n## Summary\n{answer}")

        for idx, item in enumerate(data.get("results", []), start=1):
            title = str(item.get("title", "Untitled"))
            url = str(item.get("url", ""))
            content = str(item.get("content", "")).strip()
            lines.append(f"\n## Result {idx}: {title}\n- URL: {url}\n- Snippet: {content}")
        return "\n".join(lines)

    async def _search_duckduckgo_html(self, query: str) -> str:
        url = f"https://duckduckgo.com/html/?q={quote_plus(query)}"
        headers = {"User-Agent": self._user_agent}
        async with httpx.AsyncClient(timeout=self._timeout, follow_redirects=True, headers=headers) as client:
            response = await client.get(url)
            response.raise_for_status()

        soup = BeautifulSoup(response.text, "html.parser")
        cards = soup.select(".result")
        if not cards:
            return f"No web results found for '{query}'."

        lines = [f"# DuckDuckGo results for: {query}"]
        for idx, card in enumerate(cards[:5], start=1):
            title_node = card.select_one(".result__title")
            link_node = card.select_one("a.result__a")
            snippet_node = card.select_one(".result__snippet")
            title = title_node.get_text(" ", strip=True) if title_node else "Untitled"
            link = link_node.get("href", "") if link_node else ""
            snippet = snippet_node.get_text(" ", strip=True) if snippet_node else ""
            lines.append(f"\n## {idx}. {title}\n- URL: {link}\n- Snippet: {snippet}")
        return "\n".join(lines)

    @staticmethod
    def _html_to_markdown(html: str, *, source_url: str) -> str:
        soup = BeautifulSoup(html, "html.parser")
        for bad in soup(["script", "style", "noscript", "svg"]):
            bad.decompose()

        title = soup.title.get_text(" ", strip=True) if soup.title else source_url
        body = soup.body or soup
        text = body.get_text("\n", strip=True)
        compact = "\n".join(line.strip() for line in text.splitlines() if line.strip())
        return f"# {title}\n\nSource: {source_url}\n\n{compact[:12000]}"


__all__ = ["KnowledgeEngine"]
