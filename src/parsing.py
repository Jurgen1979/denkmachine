"""helper voor het parsen van documenten naar markdown."""

from pathlib import Path


class ParsingFailure(Exception):
    """parsing van een document is mislukt."""


_SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".txt", ".md"}


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

    # pdf of docx via unstructured
    try:
        from unstructured.partition.auto import partition  # type: ignore[import-untyped]

        elements = partition(filename=str(file_path))
        text = "\n\n".join(str(el) for el in elements if str(el).strip())
    except Exception as e:
        raise ParsingFailure(f"parsing mislukt voor {file_path.name}: {e}") from e

    return header + text
