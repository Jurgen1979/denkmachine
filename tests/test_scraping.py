"""tests voor src/scraping.py – firecrawl wordt altijd gemockt."""

import os
from unittest.mock import MagicMock, patch

import pytest

os.environ.setdefault("DM_USER", "testuser")
os.environ.setdefault("DM_SECRET_KEY", "test-secret-key")
os.environ.setdefault("DM_PASSWORD_HASH", "")
os.environ.setdefault("OPENROUTER_API_KEY", "test-key")
os.environ.setdefault("FIRECRAWL_API_KEY", "test-firecrawl-key")


def test_scrape_url_returns_markdown():
    """scrape_url geeft een string terug met h1-header en de gemockte content."""
    from src.scraping import scrape_url

    mock_response = MagicMock()
    mock_response.markdown = "## inhoud\n\ntekst van de pagina"

    with patch("src.scraping.FirecrawlApp") as mock_app_cls:
        mock_app_cls.return_value.scrape_url.return_value = mock_response
        result = scrape_url("https://www.example.com/pagina", "src_001")

    assert "# https://www.example.com/pagina" in result
    assert "tekst van de pagina" in result


def test_scrape_url_failure_raises():
    """scrape_url raises ScrapingFailure als firecrawl een uitzondering gooit."""
    from src.scraping import ScrapingFailure, scrape_url

    with patch("src.scraping.FirecrawlApp") as mock_app_cls:
        mock_app_cls.return_value.scrape_url.side_effect = RuntimeError("verbinding mislukt")
        with pytest.raises(ScrapingFailure):
            scrape_url("https://www.example.com", "src_002")


def test_scrape_url_empty_markdown_raises():
    """scrape_url raises ScrapingFailure als de response geen markdown bevat."""
    from src.scraping import ScrapingFailure, scrape_url

    mock_response = MagicMock()
    mock_response.markdown = None

    with patch("src.scraping.FirecrawlApp") as mock_app_cls:
        mock_app_cls.return_value.scrape_url.return_value = mock_response
        with pytest.raises(ScrapingFailure, match="lege"):
            scrape_url("https://www.example.com", "src_003")
