"""helper voor url-scraping via firecrawl."""

import os

try:
    from firecrawl import FirecrawlApp  # type: ignore[import-untyped]
except ImportError:
    FirecrawlApp = None  # type: ignore[assignment,misc]


class ScrapingFailure(Exception):
    """scraping van een url is mislukt."""


def scrape_url(url: str, source_id: str) -> str:
    """Scrape een url via firecrawl en geef markdown terug."""
    if FirecrawlApp is None:
        raise ScrapingFailure("firecrawl-py is niet geïnstalleerd")

    api_key = os.environ["FIRECRAWL_API_KEY"]
    app = FirecrawlApp(api_key=api_key)

    try:
        response = app.scrape_url(url, params={"formats": ["markdown"]})
    except Exception as e:
        raise ScrapingFailure(f"firecrawl-call mislukt voor {url}: {e}") from e

    # firecrawl-py v1 geeft response['data'] al terug als dict, met "markdown"-key
    if not isinstance(response, dict):
        raise ScrapingFailure(
            f"onverwachte response-vorm voor {url}: {type(response).__name__}"
        )

    markdown = response.get("markdown")
    if not markdown:
        raise ScrapingFailure(f"lege of ontbrekende markdown voor {url}")

    return f"# {url}\n\n{markdown}"
