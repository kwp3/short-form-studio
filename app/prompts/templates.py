"""Prompt template loader for script and terms generation.

Templates use Python str.format() syntax: {variable_name}
Literal curly braces in templates must be escaped as {{ and }}.
"""

from pathlib import Path

from loguru import logger

from app.config import config

_DEFAULTS_DIR = Path(__file__).parent / "defaults"
_USER_DIR = Path(config.root_dir) / "prompts"


def _resolve_template_path(category: str, style: str) -> Path:
    """Find template file: user overrides first, then built-in defaults."""
    filename = f"{category}_{style}.txt"

    user_path = _USER_DIR / filename
    if user_path.is_file():
        return user_path

    default_path = _DEFAULTS_DIR / filename
    if default_path.is_file():
        return default_path

    # Fallback to default style
    fallback = _DEFAULTS_DIR / f"{category}_default.txt"
    if fallback.is_file():
        logger.warning(f"Template '{filename}' not found, falling back to {category}_default.txt")
        return fallback

    raise FileNotFoundError(f"No template found for {category}_{style}")


def load_template(category: str, style: str) -> str:
    path = _resolve_template_path(category, style)
    return path.read_text(encoding="utf-8")


def render_script_prompt(
    video_subject: str,
    language: str = "",
    paragraph_number: int = 1,
    prompt_style: str = "default",
) -> str:
    template = load_template("script", prompt_style)
    language_line = f"- language: {language}" if language else ""
    return template.format(
        video_subject=video_subject,
        paragraph_number=paragraph_number,
        language_line=language_line,
    ).strip()


def render_terms_prompt(
    video_subject: str,
    video_script: str,
    amount: int = 5,
) -> str:
    template = load_template("terms", "default")
    return template.format(
        amount=amount,
        video_subject=video_subject,
        video_script=video_script,
    ).strip()


def list_available_styles() -> list[str]:
    """Return available script style names for UI dropdown."""
    styles = set()
    for d in [_DEFAULTS_DIR, _USER_DIR]:
        if d.is_dir():
            for f in d.glob("script_*.txt"):
                style = f.stem.removeprefix("script_")
                styles.add(style)
    return ["default"] + sorted(styles - {"default"})
