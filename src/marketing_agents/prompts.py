from __future__ import annotations

from dataclasses import dataclass
from typing import Any


class PromptRenderError(ValueError):
    """Raised when a versioned prompt is missing required context."""


@dataclass(frozen=True)
class PromptTemplate:
    name: str
    version: str
    system: str
    user_template: str

    @property
    def identifier(self) -> str:
        return f"{self.name}:{self.version}"

    def render_user(self, **context: Any) -> str:
        try:
            return self.user_template.format_map(context)
        except KeyError as exc:
            raise PromptRenderError(
                f"Prompt {self.identifier} is missing context value: {exc.args[0]}"
            ) from exc
