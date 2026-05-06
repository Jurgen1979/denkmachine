"""hulpfuncties voor denkmachine."""

import os

import yaml


def load_yaml(path: str) -> dict:
    """Laad een yaml-bestand en geef de inhoud terug als dict."""
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def get_cost_caps() -> tuple[float, float]:
    """Geef de hard cap en alert-drempel terug uit omgevingsvariabelen.

    Geeft terug: (hard_cap_eur, alert_at_eur)
    """
    hard_cap = float(os.environ.get("DM_HARD_CAP_EUR", "30"))
    alert_at = float(os.environ.get("DM_ALERT_AT_EUR", "20"))
    return hard_cap, alert_at
