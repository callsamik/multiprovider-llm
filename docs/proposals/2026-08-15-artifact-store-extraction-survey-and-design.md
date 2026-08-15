# `artifact-store` extraction survey and standalone design

**Date:** 2026-08-15  
**Status:** Provisional design; no AIN integration performed  
**Package:** `artifact-store`  
**Import:** `artifact_store`

## 1. Executive summary

AIN already has a small, useful artifact repository in `ain.knowledge_base`:
immutable versioned records, current pointers, duplicate/conflict classification,
an in-memory implementation, an append-only SQLite implementation, provider
metadata, TTL projection hooks, and JSON round-tripping. The storage contract is
extractable, but the current models mix generic storage with AIN policy.

The proposed package extracts only the generic repository kernel. AIN remains the
owner of symbols, investment namespaces, `CompanyKnowledge`, market/news meaning,
portfolio decisions, and namespace allowlists. This document is a design target,
not an implementation plan for modifying AIN.

## 2. Short extraction survey

### 2.1 Primary source: `ain.knowledge_base`

Relevant files in the sibling AIN checkout (`../AutonomousInvestmentNavigator`):

| AIN component | Existing behavior | Extraction assessment |
| --- | --- | --- |
| `knowledge_base/models.py:KnowledgeArtifact` | Frozen record with `artifact_id`, `lineage_id`, domain subject (`symbol`), namespace/type, provider, observation time, confidence, payload, version, validity, metadata; JSON conversion | Extract after replacing `symbol` with a generic entity key and removing namespace policy |
| `knowledge_base/base.py:classify_for_ingest` | Accepted / duplicate / conflict / rejected classification by artifact ID and serialized equality | Extract as repository-independent ingest classification |
| `knowledge_base/base.py:next_company_knowledge` | Selects current artifact per namespace/type, preferring higher version | Extract as generic current-pointer policy; do not retain `CompanyKnowledge` |
| `knowledge_base/memory.py` | Append-only artifact map plus mutable current pointers | Extract as reference backend |
| `knowledge_base/sqlite_kb.py` | Transactional SQLite insert, immutable artifact rows, mutable current projection | Extract schema/transaction pattern; rename generic tables |
| `knowledge_base/provider.py` | Provider produces artifacts and does not receive storage handles | Extract as optional producer protocol or leave to callers |
| `knowledge_base/ttl.py` and `_state_mixin.py` | Policy-specific freshness and rebuildable state projection | Extract only a hook protocol; AIN supplies its policy |
| `knowledge_base/models.py:CompanyKnowledge` | Symbol-level rollup and current map | Keep in AIN; explicitly out of package |
| `knowledge_base/models.py:KNOWN_NAMESPACES` | Hard-coded investment/research namespace allowlist | Keep in AIN; package must accept arbitrary namespace strings |

### 2.2 Adjacent AIN libraries

* `ain.evidence.run_store` stores evidence-run operational records. It is an
  audit/run store, not a generic immutable artifact repository.
* `ain.news.source_snapshot`, news caches, and market-event providers carry
  source-specific fetch and market semantics. They should produce generic
  artifacts through an adapter, not become dependencies of the extracted package.
* `ain.proposals.store` has useful conflict and idempotency patterns, but its
  mutable proposal lifecycle and domain conflict rules do not belong in the
  artifact store.
* Raw source/failure sidecars in equity-monitor code implement content hashes and
  immutable files. They are useful provenance precedents, but are file-ingest
  products rather than repository primitives.

### 2.3 Existing libraries/dependencies

No standalone artifact or provenance library was found in either repository by
searching source, tests, and project metadata. The extracted package should use
the Python standard library initially (`dataclasses`, `sqlite3`, `json`,
`datetime`) and avoid importing AIN. SQLite is a backend, not a required external
dependency.

## 3. Scope and boundary

### In scope

* Immutable, versioned artifact records.
* Generic entity-level current pointers, keyed by `(entity_id, namespace,
  artifact_type)`.
* Duplicate detection and artifact-ID conflict detection.
* Append-only SQLite and equivalent in-memory backends.
* Provider/source metadata as opaque structured metadata.
* Injectable validity/TTL policy hooks.
* Deterministic JSON serialization/deserialization.
* Synchronous API as the first and default interface.

### Explicitly out of scope

Symbols and investment namespaces; `CompanyKnowledge`; market/news semantics;
portfolio decisions; namespace allowlists; provider fetching; ranking,
confidence aggregation, or domain-specific conflict resolution; async APIs unless
an identified consumer needs native async I/O.

## 4. Proposed model

```python
@dataclass(frozen=True)
class Artifact:
    artifact_id: str
    lineage_id: str
    entity_id: str
    namespace: str
    artifact_type: str
    provider_id: str
    observed_at: datetime
    version: int
    payload: Mapping[str, Any]
    confidence: float | None = None
    valid_until: datetime | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)
```

The store treats `namespace`, `artifact_type`, `provider_id`, and payload as
opaque values. It normalizes only structural identifiers (non-empty strings),
version (`>= 1`), timestamps, and JSON-compatible values. Immutability means an
existing `artifact_id` may be submitted again only if its canonical serialized
form is identical; otherwise the operation reports a conflict and never
overwrites the original.

Current pointers are a mutable projection, not replacements for artifact rows.
For an accepted artifact, the pointer advances when its version is greater than
the pointed artifact's version. Equal or lower versions remain addressable but do
not roll back the pointer.

## 5. API sketch

```python
class ArtifactStore(Protocol):
    def ingest(self, artifacts: Iterable[Artifact]) -> IngestResult: ...
    def get(self, artifact_id: str) -> Artifact | None: ...
    def current(self, entity_id: str, *, namespace: str,
                artifact_type: str) -> Artifact | None: ...
    def list(self, *, entity_id: str | None = None,
             namespace: str | None = None,
             artifact_type: str | None = None,
             limit: int = 50) -> tuple[Artifact, ...]: ...
    def is_valid(self, artifact: Artifact, *, as_of: datetime,
                 policy: ValidityPolicy | None = None) -> bool: ...
```

`IngestResult` should report accepted IDs, duplicate IDs, conflicts (ID plus a
stable reason), and rejected inputs. A batch is atomic for SQLite: malformed
items can be reported as rejected according to the contract, while unexpected
backend errors roll back the transaction. The in-memory backend must match the
observable classification and pointer behavior.

`ValidityPolicy` is intentionally small, for example
`is_valid(artifact, as_of) -> bool`. A policy may use namespace, type, metadata,
or provider, but the store must not provide built-in domain rules. A missing
policy means validity is determined only by explicit `valid_until` (or is
considered valid when no end is present, subject to the final API decision).

## 6. Storage design

SQLite tables:

* `artifacts`: primary key `artifact_id`; scalar index columns plus canonical
  `artifact_json`; never update or delete rows through the public API.
* `current_pointers`: primary key `(entity_id, namespace, artifact_type)`;
  stores `artifact_id` and the pointer's selected version.

The canonical JSON is the equality boundary and preserves opaque payload and
metadata. Scalar columns support filtering and indexes. Each ingest batch runs in
one transaction; pointer updates happen in the same transaction as artifact
inserts. SQLite connections are caller/backend-owned and should use the existing
project's normal timeout and journal settings only when the package has an
explicit configuration for them.

The in-memory backend stores the same two logical maps and is the behavioral
reference for tests. It should not expose mutable internal mappings.

## 7. Serialization and provenance

`Artifact.to_dict()` emits stable keys and RFC 3339-compatible timestamps;
`from_dict()` validates required fields. `to_json()` uses sorted keys and compact
or documented canonical separators. Provider/source information belongs in
`provider_id` and `metadata` (for example source URL, fetch timestamp, content
hash, response ID); the package does not assign credibility or interpret those
fields. Secrets must not be serialized accidentally by providers.

## 8. Open decisions before implementation

1. Whether `confidence` is optional (recommended) or required for compatibility
   with AIN's current model.
2. Whether duplicate/conflict items are non-fatal results (recommended) or raise
   typed exceptions.
3. Whether a pointer key should include an explicit `artifact_type` only, or also
   a caller-defined variant key for multiple projections of one type.
4. Whether native async is needed by a real consumer; do not add it merely to
   mirror a sync API.
5. Whether content hashes are first-class fields or remain provider metadata.

## 9. Extraction acceptance criteria

Before any AIN integration, a standalone package should have parity tests for
memory and SQLite covering: identical duplicate, same-ID conflict, append-only
history, higher/lower version pointer behavior, transaction rollback, arbitrary
namespaces, provider metadata round-trip, JSON round-trip, and injected validity
policy behavior. AIN changes, import rewrites, and namespace adapters are a
separate follow-up proposal.

