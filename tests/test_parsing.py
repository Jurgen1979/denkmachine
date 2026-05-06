"""tests voor src/parsing.py."""

import os
from unittest.mock import MagicMock, patch

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


def test_parse_pdf_returns_markdown(tmp_path):
    """parse_document verwerkt een pdf via pypdf en geeft header + tekst terug."""
    import src.parsing as parsing_mod
    from src.parsing import parse_document

    pdf_file = tmp_path / "rapport.pdf"
    pdf_file.write_bytes(b"%PDF-1.4 nep")

    mock_page = MagicMock()
    mock_page.extract_text.return_value = "tekst uit de pdf"
    mock_reader = MagicMock()
    mock_reader.pages = [mock_page]

    with patch.object(parsing_mod, "PdfReader", return_value=mock_reader):
        result = parse_document(pdf_file, "src_004")

    assert "# rapport.pdf" in result
    assert "tekst uit de pdf" in result


def test_parse_docx_returns_markdown(tmp_path):
    """parse_document verwerkt een docx via python-docx en geeft header + tekst terug."""
    import src.parsing as parsing_mod
    from src.parsing import parse_document

    docx_file = tmp_path / "brief.docx"
    docx_file.write_bytes(b"PK nep-docx")

    mock_para = MagicMock()
    mock_para.text = "alinea uit het docx-bestand"
    mock_doc = MagicMock()
    mock_doc.paragraphs = [mock_para]

    with patch.object(parsing_mod, "Document", return_value=mock_doc):
        result = parse_document(docx_file, "src_005")

    assert "# brief.docx" in result
    assert "alinea uit het docx-bestand" in result


def test_parse_pdf_failure_raises(tmp_path):
    """parse_document raises ParsingFailure als pypdf een uitzondering gooit."""
    import src.parsing as parsing_mod
    from src.parsing import ParsingFailure, parse_document

    pdf_file = tmp_path / "kapot.pdf"
    pdf_file.write_bytes(b"%PDF-1.4 nep")

    with patch.object(parsing_mod, "PdfReader", side_effect=RuntimeError("corrupt")):
        with pytest.raises(ParsingFailure, match="pdf-parsing mislukt"):
            parse_document(pdf_file, "src_006")
