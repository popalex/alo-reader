"""Store layer: typed async data-access functions, one module per aggregate.

Every function touching user-scoped data takes ``user_id: int`` as a required
argument (structural tenant isolation).
"""

from typing import Any, cast

from sqlalchemy import CursorResult
from sqlalchemy.engine import Result


def rowcount(result: Result[Any]) -> int:
    """Rows affected by a DML statement (``CursorResult.rowcount``), typed for mypy."""
    return cast("CursorResult[Any]", result).rowcount
