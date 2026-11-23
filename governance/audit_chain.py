"""Hash-chained, append-only audit log (Pattern B).

Every material decision or record produced by this control plane (quality
flags, claim-verification verdicts, GAR calculations, etc.) can be appended to
an :class:`AuditChain`. Each entry stores a SHA-256 hash of its own payload
*and* the hash of the previous entry, so any retroactive edit or deletion
breaks the hash chain. :func:`verify_chain` walks the chain and reports the
first broken link, if any -- the same tamper-evidence pattern used across the
sibling repos in this account (``graphrag-selective-forgetting``,
``enterprise-llm-gateway-router``, ``telemetry-rca-agentic-runtime``).

This is deliberately *not* a blockchain or a distributed ledger: it is a
single-writer, in-process (or file-backed) append-only log whose integrity
can be checked locally. It gives auditors a cheap, offline way to prove that
a report, verdict, or metric was not quietly edited after the fact.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field

GENESIS_HASH = "0" * 64


def _canonical_json(payload: Any) -> str:
    """Serialize payload deterministically so hashing is reproducible."""
    return json.dumps(payload, sort_keys=True, default=str, separators=(",", ":"))


def _compute_hash(index: int, timestamp: str, payload: Any, prev_hash: str) -> str:
    digest_input = _canonical_json(
        {"index": index, "timestamp": timestamp, "payload": payload, "prev_hash": prev_hash}
    )
    return hashlib.sha256(digest_input.encode("utf-8")).hexdigest()


class AuditEntry(BaseModel):
    """A single tamper-evident record in the audit chain."""

    index: int
    timestamp: str
    entry_type: str
    payload: dict[str, Any]
    prev_hash: str
    hash: str


class ChainVerificationResult(BaseModel):
    """Result of walking an :class:`AuditChain` to check integrity."""

    ok: bool
    length: int
    broken_at_index: int | None = None
    reason: str | None = None


class AuditChain(BaseModel):
    """An in-memory, append-only, hash-chained log of audit entries."""

    entries: list[AuditEntry] = Field(default_factory=list)

    def append(self, entry_type: str, payload: dict[str, Any]) -> AuditEntry:
        """Append a new entry whose hash commits to the full prior chain."""
        index = len(self.entries)
        prev_hash = self.entries[-1].hash if self.entries else GENESIS_HASH
        timestamp = datetime.now(timezone.utc).isoformat()
        entry_hash = _compute_hash(index, timestamp, payload, prev_hash)
        entry = AuditEntry(
            index=index,
            timestamp=timestamp,
            entry_type=entry_type,
            payload=payload,
            prev_hash=prev_hash,
            hash=entry_hash,
        )
        self.entries.append(entry)
        return entry

    def verify_chain(self) -> ChainVerificationResult:
        """Walk the chain, recomputing hashes, and report the first break."""
        expected_prev = GENESIS_HASH
        for entry in self.entries:
            if entry.prev_hash != expected_prev:
                return ChainVerificationResult(
                    ok=False,
                    length=len(self.entries),
                    broken_at_index=entry.index,
                    reason=f"prev_hash mismatch at index {entry.index}: "
                    f"expected {expected_prev}, found {entry.prev_hash}",
                )
            recomputed = _compute_hash(entry.index, entry.timestamp, entry.payload, entry.prev_hash)
            if recomputed != entry.hash:
                return ChainVerificationResult(
                    ok=False,
                    length=len(self.entries),
                    broken_at_index=entry.index,
                    reason=f"hash mismatch at index {entry.index}: tampered payload or metadata",
                )
            expected_prev = entry.hash
        return ChainVerificationResult(ok=True, length=len(self.entries))

    def tamper_with(self, index: int, new_payload: dict[str, Any]) -> None:
        """Test/demo-only helper: mutate an entry's payload without rehashing.

        This simulates an attacker editing history after the fact, so that
        :meth:`verify_chain` can be exercised against a genuinely broken
        chain. Never used by production code paths.
        """
        self.entries[index].payload = new_payload
