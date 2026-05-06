"""tests voor src/parsing.py."""

import os

import pytest

os.environ.setdefault("DM_USER", "testuser")
os.environ.setdefault("DM_SECRET_KEY", "test-secret-key")
os.environ.setdefault("DM_PASSWORD_HASH", "")
os.environ.setdefault("OPENROUTER_API_KEY", "test-key")


def test_parse_txt_returns_markdown(tmp_path):
    """parse_document geeft een string terug met de inhoud en een h1-header."""
    from src.parsing import parse_document

    txt_file = tmp_path / "testbestand.txt"
    txt_file.write_text("dit is testinhoud", encoding="utf-8")

    result = parse_document(txt_file, "src_001")

    assert isinstance(result, str)
    assert "# testbestand.txt" in result
    assert "dit is testinhoud" in result


def test_parse_md_returns_markdown(tmp_path):
    """parse_document werkt ook voor .md-bestanden."""
    from src.parsing import parse_document

    md_file = tmp_path / "notitie.md"
    md_file.write_text("## sectie\n\ntekst hier", encoding="utf-8")

    result = parse_document(md_file, "src_002")

    assert "# notitie.md" in result
    assert "## sectie" in result


def test_parse_unsupported_extension_raises(tmp_path):
    """parse_document raises ValueError voor een niet-ondersteunde extensie."""
    from src.parsing import parse_document

    exe_file = tmp_path / "programma.exe"
    exe_file.write_bytes(b"\x00\x01\x02")

    with pytest.raises(ValueError, match="niet-ondersteunde"):
        parse_document(exe_file, "src_003")
