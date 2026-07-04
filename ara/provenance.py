"""Provenance tracking for ARA entries.

Every entry in an artifact is tagged with a provenance value that distinguishes
human-confirmed facts from AI inferences. This is a core structural principle of
the protocol: it lets a reviewer (human or agent) tell which statements are
grounded in human-verified reality and which are AI-suggested inferences awaiting
confirmation.
"""

from __future__ import annotations

from enum import Enum


class Provenance(str, Enum):
    """Who originally produced an entry.

    The values are the canonical short tags stored on disk.
    """

    USER = "user"
    """A human researcher asserted or confirmed this entry."""

    AI_SUGGESTED = "ai-suggested"
    """An AI agent proposed this entry; it has not yet been human-confirmed."""

    AI_EXECUTED = "ai-executed"
    """An AI agent produced this entry by executing code / running an experiment."""

    USER_REVISED = "user-revised"
    """An AI proposed the entry and a human has since revised it."""

    @classmethod
    def parse(cls, value: "str | Provenance | None") -> "Provenance":
        """Parse a provenance tag, defaulting to ``ai-suggested`` when missing.

        Unknown values are normalised to ``ai-suggested`` rather than rejected so
        that loading a slightly non-conformant artifact never throws; the
        validator reports the discrepancy instead.
        """
        if value is None:
            return cls.AI_SUGGESTED
        if isinstance(value, cls):
            return value
        lowered = str(value).strip().lower()
        for member in cls:
            if member.value == lowered:
                return member
        return cls.AI_SUGGESTED

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.value
