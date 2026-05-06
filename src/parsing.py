"""helper voor het parsen van documenten naar markdown."""

from pathlib import Path

try:
    from pypdf import PdfReader  # type: ignore[import-untyped]
except ImportError:
    PdfReader = None  # type: ignore[assignment,misc]

try:
    from docx import Document  # type: ignore[import-untyped]
except ImportError:
    Document = None  # type: ignore[assignment,misc]


class ParsingFailure(Exception):
    """parsing van een document is mislukt."""


_SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".txt", ".md"}


def _parse_pdf(file_path: Path) -> str:
    """Parseer een pdf-bestand naar platte tekst via pypdf."""
    if PdfReader is None:
        raise ParsingFailure("pypdf is niet geïnstalleerd")
    try:
        reader = PdfReader(str(file_path))
        pages = [page.extract_text() or "" for page in reader.pages]
        return "\n\n".join(p.strip() for p in pages if p.strip())
    except ParsingFailure:
        raise
    except Exception as e:
        raise ParsingFailure(f"pdf-parsing mislukt voor {file_path.name}: {e}") from e


def _parse_docx(file_path: Path) -> str:
    """Parseer een docx-bestand naar platte tekst via python-docx."""
    if Document is None:
        raise ParsingFailure("python-docx is niet geïnstalleerd")
    try:
        doc = Document(str(file_path))
        paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
        return "\n\n".join(paragraphs)
    except ParsingFailure:
        raise
    except Exception as e:
        raise ParsingFailure(f"docx-parsing mislukt voor {file_path.name}: {e}") from e


def parse_document(file_path: Path, source_id: str) -> str:
    """Parse pdf/docx/txt/md naar markdown. Geeft markdown-string terug."""
    file_path = Path(file_path)
    ext = file_path.suffix.lower()
    header = f"# {file_path.name}\n\n"

    if ext not in _SUPPORTED_EXTENSIONS:
        raise ValueError(
            f"niet-ondersteunde bestandsextensie: {ext!r} ({file_path.name})"
        )

    if ext in (".txt", ".md"):
        try:
            content = file_path.read_text(encoding="utf-8")
        except Exception as e:
            raise ParsingFailure(f"leesfout voor {file_path.name}: {e}") from e
        return header + content

    if ext == ".pdf":
        return header + _parse_pdf(file_path)

    return header + _parse_docx(file_path)
