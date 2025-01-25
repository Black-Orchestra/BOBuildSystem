try:
    from typing import overload  # type: ignore[attr-defined]
except ImportError:
    from typing_extensions import overload
try:
    from typing import override  # type: ignore[attr-defined]
except ImportError:
    from typing_extensions import override

__all__ = [
    "overload",
    "override",
]
