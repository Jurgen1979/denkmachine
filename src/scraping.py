"""helper voor url-scraping via firecrawl."""

import os

try:
    from firecrawl import V1FirecrawlApp  # type: ignore[import-untyped]
except ImportError:
    V1FirecrawlApp = None  # type: ignore[assignment,misc]


class ScrapingFailure(Exception):
    """scraping van een url is mislukt."""


def scrape_url(url: str, source_id: str) -> str:
    """Scrape een url via firecrawl en geef markdown terug."""
    if V1FirecrawlApp is None:
        raise ScrapingFailure("firecrawl-py is niet geïnstalleerd")

    api_key = os.environ["FIRECRAWL_API_KEY"]
    app = V1FirecrawlApp(api_key=api_key)

    try:
        response = app.scrape_url(url, formats=["markdown"])
    except Exception as e:
        raise ScrapingFailure(f"firecrawl-call mislukt voor {url}: {e}") from e

    # firecrawl-py v4 geeft een V1ScrapeResponse-object terug met een markdown-attribuut
    markdown = getattr(response, "markdown", None)
    if not markdown:
        raise ScrapingFailure(f"lege of ontbrekende markdown voor {url}")

    return f"# {url}\n\n{markdown}"
