"""Readable errors for the Venture Capital revision coach."""

from __future__ import annotations


class VcError(Exception):
    """Base error with a message safe to show to the learner."""


class InputError(VcError):
    """The learner input is invalid."""


class ContentError(VcError):
    """A content pack is invalid or unsupported."""


class StorageError(VcError):
    """The local VC storage cannot be read or written."""
