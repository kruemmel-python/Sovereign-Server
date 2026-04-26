from __future__ import annotations

import html, re
from pathlib import Path
from typing import Any, Mapping

from .responses import Response


class SafeString(str):
    pass


def safe(value: Any) -> SafeString:
    return SafeString(str(value))


class Template:
    _expr = re.compile(r"{{\s*([a-zA-Z_][a-zA-Z0-9_.]*)(?:\s*\|\s*(safe))?\s*}}")

    def __init__(self, source: str) -> None:
        self.source = source

    def render(self, context: Mapping[str, Any] | None = None, **kwargs: Any) -> str:
        data = dict(context or {})
        data.update(kwargs)

        def lookup(name: str) -> Any:
            cur: Any = data
            for part in name.split("."):
                if isinstance(cur, Mapping):
                    cur = cur[part]
                else:
                    cur = getattr(cur, part)
            return cur

        def repl(match: re.Match[str]) -> str:
            value = lookup(match.group(1))
            if match.group(2) == "safe" or isinstance(value, SafeString):
                return str(value)
            return html.escape(str(value), quote=True)

        return self._expr.sub(repl, self.source)


class TemplateEnvironment:
    def __init__(self, template_dir: str | Path = "templates") -> None:
        self.template_dir = Path(template_dir).resolve()

    def get_template(self, name: str) -> Template:
        candidate = (self.template_dir / name).resolve()
        if self.template_dir not in candidate.parents and candidate != self.template_dir:
            raise ValueError("template path escapes template_dir")
        return Template(candidate.read_text(encoding="utf-8"))

    def render(self, name: str, context: Mapping[str, Any] | None = None, **kwargs: Any) -> str:
        return self.get_template(name).render(context, **kwargs)


class TemplateResponse(Response):
    def __init__(self, template_name: str, context: Mapping[str, Any] | None = None, *,
                 template_dir: str | Path = "templates", status: int = 200,
                 headers: Mapping[str, str] | None = None) -> None:
        env = TemplateEnvironment(template_dir)
        super().__init__(env.render(template_name, context or {}), status=status, headers=headers,
                         content_type="text/html; charset=utf-8")
