"""Verified HTTPS access shared by the HTML job-board connectors.

The public ATS transport already verifies the server certificate against the
CA bundle shipped by ``certifi`` when it is available.  The HTML boards must
do the same.  Without it, a Python installation whose default CA bundle is
missing or stale cannot read a single published page: the connector reports an
opaque network error and the material published by the source never reaches
the common contract.

The context keeps the default verification: certificates are required and
hostnames are checked.  Nothing here relaxes a security check.
"""

from __future__ import annotations

from functools import lru_cache
import ssl


@lru_cache(maxsize=1)
def ssl_context() -> ssl.SSLContext:
    """Return the verifying TLS context used to read a public board."""
    try:
        import certifi  # noqa: PLC0415 - optional dependency, like the ATS transport
    except ImportError:
        return ssl.create_default_context()
    return ssl.create_default_context(cafile=certifi.where())


__all__ = ["ssl_context"]
