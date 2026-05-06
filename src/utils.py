"""hulpfuncties voor denkmachine."""

import yaml


def load_yaml(path: str) -> dict:
    """Laad een yaml-bestand en geef de inhoud terug als dict."""
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}
