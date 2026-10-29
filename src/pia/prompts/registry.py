"""Versioned prompt templates.

Each template file has a system block and a user block separated by a line of '---'.
Placeholders are {{name}}. Rendering is a single pass, so values inserted into a
placeholder are never re-scanned for placeholders.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import cache
from pathlib import Path

TEMPLATE_DIR = Path(__file__).parent / "templates"
_SEPARATOR = "\n---\n"
_PLACEHOLDER = re.compile(r"\{\{(\w+)\}\}")


@dataclass(frozen=True)
class Prompt:
    name: str
    version: int
    system: str
    user_template: str

    def render(self, **values: str) -> str:
        needed = set(_PLACEHOLDER.findall(self.user_template))
        missing = needed - values.keys()
        if missing:
            raise ValueError(f"prompt {self.name} v{self.version} missing: {sorted(missing)}")
        return _PLACEHOLDER.sub(lambda m: str(values[m.group(1)]), self.user_template)


@cache
def load_prompt(name: str, version: int) -> Prompt:
    text = (TEMPLATE_DIR / f"{name}.v{version}.md").read_text()
    system, user = text.split(_SEPARATOR, 1)
    return Prompt(name=name, version=version, system=system.strip(), user_template=user.strip())


def wrap_untrusted(label: str, text: str) -> str:
    """Mark document or user text as data. Escape anything that could close the wrapper early."""
    safe = text.replace("<untrusted_content", "&lt;untrusted_content").replace(
        "</untrusted_content", "&lt;/untrusted_content"
    )
    return f'<untrusted_content label="{label}">\n{safe}\n</untrusted_content>'
