"""Conversion des résultats du moteur en structures JSON-safe.

Les autres agents de Côme IA échangent des dictionnaires sérialisables. DuckDB
et Pandas produisent des types riches (``Timestamp``, ``date``, ``Decimal``,
entiers NumPy, ``NaN``/``NaT``) qu'il faut normaliser avant de les exposer.
"""

from __future__ import annotations

import math
from datetime import date, datetime
from decimal import Decimal
from typing import Any


def to_jsonable(value: Any) -> Any:
    """Convertit récursivement ``value`` en types JSON standards."""
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (str, int)):
        return value
    if isinstance(value, float):
        return None if math.isnan(value) or math.isinf(value) else value
    # Types Pandas / NumPy sans dépendance d'import explicite.
    module = type(value).__module__ or ""
    if module.startswith("numpy"):
        item = value.item() if hasattr(value, "item") else value
        return to_jsonable(item)
    if _is_pandas_na(value) is True:
        return None
    if isinstance(value, dict):
        return {str(key): to_jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [to_jsonable(item) for item in value]
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except Exception:  # noqa: BLE001
            pass
    return str(value)


def _is_pandas_na(value: Any) -> bool | None:
    """Renvoie True/False si la valeur est une sentinelle Pandas, sinon None."""
    try:
        import pandas as pd  # noqa: PLC0415
    except ImportError:
        return None
    try:
        if value is pd.NaT:
            return True
        result = pd.isna(value)
    except (TypeError, ValueError):
        return None
    if isinstance(result, bool):
        return result
    return None
