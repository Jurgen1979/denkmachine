"""hulpfuncties voor het laden en renderen van prompt-templates."""

import re
from pathlib import Path

_BASE_DIR = Path(__file__).parent.parent
_PROMPTS_DIR = _BASE_DIR / "config" / "prompts"


def load_prompt(name: str) -> str:
    """Laad een prompt-template uit config/prompts/{name}.md."""
    path = _PROMPTS_DIR / f"{name}.md"
    if not path.exists():
        raise FileNotFoundError(f"prompt niet gevonden: {path}")
    return path.read_text(encoding="utf-8")


def render_prompt(template: str, variables: dict) -> str:
    """Vervang {{var}}-placeholders in de template door de opgegeven waarden."""
    result = template
    for key, value in variables.items():
        placeholder = f"{{{{{key}}}}}"
        result = result.replace(placeholder, str(value))
    remaining = re.findall(r"\{\{(\w+)\}\}", result)
    if remaining:
        raise KeyError(f"ontbrekende variabelen in prompt: {remaining}")
    return result
