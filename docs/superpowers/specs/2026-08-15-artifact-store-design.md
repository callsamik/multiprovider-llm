# `artifact_store` standalone design (cancelled)

**Date:** 2026-08-15  
**Status:** **Cancelled** (2026-08-15) — will not implement; retained as historical design only  
**Package:** `artifact-store` (not shipped)  
**Import:** `artifact_store`  
**Precursor:** [docs/proposals/2026-08-15-artifact-store-extraction-survey-and-design.md](../../proposals/2026-08-15-artifact-store-extraction-survey-and-design.md)

### Cancellation reason

Not required for `multiprovider-llm` (LLM call execution only). AIN already owns
an append-only Research Knowledge Base (`ain.knowledge_base`). No second consumer
or OV/contract gap justifies a standalone extraction. Do **not** schedule a new
repo, AIN adapter cutover, or library packaging work from this doc.

---

This document froze survey decisions into an implementable contract. It did
**not** authorize changes to `multiprovider-llm` package code or to AIN.
Implementation was targeted at a separate repository so this project remains a
single-package distribution — that path is cancelled.

## 1. Locked decisions

| Topic | Decision |
| --- | --- |
| Package home | New repository later; design docs stay in multiprovider-llm |
| `confidence` | Optional (`float \| None`). When set, validate `[0, 1]`. AIN may require/validate in its adapter |
| Ingest outcomes | Non-fatal `IngestResult` buckets only; conflicts never overwrite |
| Current pointer key | `(entity_id, namespace, artifact_type)` only |
| Async | Sync-only for v1 |
| Content hashes | Opaque `metadata` only; not used for equality |

## 2. Boundary and layout

### In scope

* Immutable, versioned artifact records.
* Entity-level current pointers keyed by `(entity_id, namespace, artifact_type)`.
* Duplicate and same-ID conflict classification.
* Append-only SQLite and equivalent in-memory backends.
* Provider/source metadata as opaque structured metadata.
* Injectable validity/TTL policy hooks.
* Deterministic JSON serialization/deserialization.
* Synchronous API as the only v1 interface.

### Out of scope

Symbols and investment namespaces; `CompanyKnowledge`; market/news semantics;
portfolio decisions; namespace **allowlists**; provider fetching; ranking,
confidence aggregation, or domain-specific conflict resolution; native async
APIs; first-class content-hash fields or hash-based duplicate detection; AIN
adapters and import rewrites.

### Target repository layout

```text
src/artifact_store/
  __init__.py
  models.py          # Artifact
  results.py         # IngestResult
  protocol.py        # ArtifactStore, ValidityPolicy
  classify.py        # ingest classification helpers
  serialization.py   # canonical dict/JSON
  memory.py
  sqlite.py
  validity.py        # default is_valid helper (optional module)
tests/
  ...                # parity suite over memory + SQLite
```

**Dependencies:** Python standard library only (`dataclasses`, `sqlite3`,
`json`, `datetime`). No AIN imports. No HTTP client.

## 3. Model and API

### 3.1 `Artifact`

```python
@dataclass(frozen=True)
class Artifact:
    artifact_id: str
    lineage_id: str
    entity_id: str
    namespace: str          # required opaque string; no allowlist / semantics
    artifact_type: str
    provider_id: str
    observed_at: datetime
    version: int           # >= 1
    payload: Mapping[str, Any]
    confidence: float | None = None
    valid_until: datetime | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)
```

Structural validation only:

* Non-empty strings for identity fields (`artifact_id`, `lineage_id`,
  `entity_id`, `namespace`, `artifact_type`, `provider_id`).
* `version >= 1`.
* `payload` and `metadata` are mappings; values must be JSON-compatible for
  canonical serialization.
* If `confidence` is not `None`, it must be a float in `[0, 1]`.

`namespace` is **required** and treated as an opaque string. The store performs
no allowlist or semantic validation. Callers that need domain constraints (for
example AIN’s `KNOWN_NAMESPACES`) enforce them outside this package.

### 3.2 `IngestResult`

```python
@dataclass(frozen=True)
class IngestResult:
    accepted: tuple[str, ...] = ()
    duplicates: tuple[str, ...] = ()
    conflicts: tuple[tuple[str, str], ...] = ()  # (artifact_id, reason)
    rejected: tuple[tuple[str, str], ...] = ()   # (id_or_placeholder, reason)
```

Duplicate and conflict outcomes are non-fatal classification results. They do
not raise. Conflicts never mutate an existing artifact row.

### 3.3 `ArtifactStore` protocol

```python
class ArtifactStore(Protocol):
    def ingest(self, artifacts: Iterable[Artifact]) -> IngestResult: ...
    def get(self, artifact_id: str) -> Artifact | None: ...
    def current(
        self,
        entity_id: str,
        *,
        namespace: str,
        artifact_type: str,
    ) -> Artifact | None: ...
    def list(
        self,
        *,
        entity_id: str | None = None,
        namespace: str | None = None,
        artifact_type: str | None = None,
        limit: int = 50,
    ) -> tuple[Artifact, ...]: ...
    def is_valid(
        self,
        artifact: Artifact,
        *,
        as_of: datetime,
        policy: ValidityPolicy | None = None,
    ) -> bool: ...
```

`ValidityPolicy` is a small protocol, for example
`is_valid(artifact: Artifact, as_of: datetime) -> bool`.

### 3.4 Typed ingest vs runtime rejection

The public type of `ingest` is `Iterable[Artifact]`. Implementations may still
encounter malformed runtime values (for example dicts or broken objects when
callers bypass the type checker). Those inputs are classified as `rejected`
with a stable reason, not raised as exceptions. Unexpected backend failures
(for example SQLite operational errors) still raise and, for SQLite, roll back
the batch transaction.

## 4. Ingest classification and pointers

For each item in a batch:

1. Coerce/validate structurally → on failure: `rejected`.
2. If `artifact_id` already exists and canonical JSON equals stored
   `artifact_json` → `duplicate`.
3. If `artifact_id` already exists and canonical JSON differs → `conflict`
   (existing row unchanged).
4. Otherwise → `accepted`: insert immutable row; maybe advance current pointer.

Pointer rules:

* Key: `(entity_id, namespace, artifact_type)`.
* On accept, advance the pointer only when the new artifact’s `version` is
  **strictly greater** than the pointed artifact’s version.
* Equal or lower versions remain addressable via `get` / `list` but do not roll
  the pointer back.

Callers that need multiple currents for one logical type should use distinct
`artifact_type` or `namespace` values rather than a variant key.

## 5. Serialization and equality

Canonical serialization is the **only** equality boundary for duplicate vs
conflict.

Requirements:

* Deterministic datetime encoding (RFC 3339-compatible ISO-8601 strings).
* Sorted mapping keys in JSON.
* Stable separators, for example `json.dumps(..., sort_keys=True, separators=(",", ":"))`.
* `Artifact.to_dict()` / `from_dict()` validate required fields; `to_json()` /
  `from_json()` round-trip through the canonical form.

In SQLite, `artifact_json` stores that canonical form and is used for equality
checks. Scalar columns are projections for indexing and filtering and **must
never independently define equality**.

Provider/source details belong in `provider_id` and opaque `metadata` (for
example source URL, fetch timestamp, content hash, response ID). The package
does not interpret credibility or hashes. Secrets must not be serialized by
providers into stored metadata.

## 6. Storage backends

### SQLite

* Table `artifacts`: primary key `artifact_id`; scalar index columns plus
  canonical `artifact_json`; public API never updates or deletes rows.
* Table `current_pointers`: primary key `(entity_id, namespace, artifact_type)`;
  stores `artifact_id` and selected `version`.
* Each `ingest` batch runs in one transaction. Pointer updates occur in the
  same transaction as accepted inserts. Unexpected backend errors roll back the
  entire batch.

### In-memory

* Same two logical maps as the tables above.
* Behavioral reference implementation for tests.
* Must not expose mutable internal mappings.

## 7. Validity

`is_valid(artifact, as_of=..., policy=...)`:

* If `policy` is provided, return `policy.is_valid(artifact, as_of)`.
* If `policy` is `None`, validity is `valid_until is None or as_of <= valid_until`.

The store ships no built-in domain freshness rules.

## 8. Acceptance criteria (new repository) — cancelled

Had this path proceeded, before any AIN integration the standalone package would
have needed parity tests for memory and SQLite covering:

* Identical re-ingest → duplicate.
* Same ID, different canonical body → conflict; original unchanged.
* Append-only history.
* Higher version advances pointer; equal/lower does not; older versions remain
  gettable.
* SQLite unexpected error mid-batch → full rollback; memory matches observable
  classification and pointer behavior for successful batches.
* Arbitrary namespaces accepted (no allowlist).
* Optional `confidence` preserved and round-tripped; invalid confidence when
  present is rejected.
* Opaque provider metadata (including content hashes) round-tripped without
  interpretation.
* JSON round-trip preserves canonical equality.
* Injected `ValidityPolicy` honored; default `valid_until` rule when policy is
  absent.

AIN changes, adapters, and import rewrites are a separate follow-up after this
package exists.

## 9. Explicit non-goals for multiprovider-llm

This repository may hold cancelled survey/design documentation only for
`artifact_store`. It must not grow a second installable package under `src/`
for this work. No implementation plan under `docs/superpowers/plans/` should be
opened from this cancelled design.
