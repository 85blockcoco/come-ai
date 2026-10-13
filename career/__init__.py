"""Local-first Career modules for Côme AI V3.

Career data is deliberately separate from the document workspace and from the
Gemini/Ollama tool allow-list. Local workflows work offline; public job boards
are contacted only after an explicit manual request.
"""

from .service import CareerService

__all__ = ["CareerService"]
