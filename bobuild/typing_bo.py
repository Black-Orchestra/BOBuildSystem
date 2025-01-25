try:
    from typing import overload
    from typing import override
except ImportError:
    from typing_extensions import overload
    from typing_extensions import override

__all__ = [
    "overload",
    "override",
]
