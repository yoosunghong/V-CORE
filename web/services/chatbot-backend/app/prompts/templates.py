from __future__ import annotations

from pathlib import Path
from string import Template
from typing import Any


class PromptTemplateStore:
    def __init__(self, template_dir: Path | None = None) -> None:
        self._template_dir = template_dir or Path(__file__).with_name("templates")

    def render(self, template_name: str, **values: Any) -> str:
        path = self._template_dir / f"{template_name}.txt"
        template = Template(path.read_text(encoding="utf-8"))
        safe_values = {key: self._stringify(value) for key, value in values.items()}
        return template.safe_substitute(safe_values)

    def _stringify(self, value: Any) -> str:
        if value is None:
            return "none"
        return str(value)
