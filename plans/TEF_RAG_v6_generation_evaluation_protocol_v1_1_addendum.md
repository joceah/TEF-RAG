# TEF-RAG v6 Generation Evaluation Protocol v1.1 Canonicalization Addendum

Status: frozen deterministic post-annotation canonicalization addendum.

This addendum does not add model calls, alter the annotation prompt, or change any
diagnosis, action, dependency, or claim-level citation meaning. It only repairs
mechanical derived fields and normalizes procedure status from deployment-visible
procedure metadata. The same canonicalizer is applied to development, validation,
and the private test generation gold.

## 1. Top-level citation union

`work_order.supporting_evidence_ids` is a derived field. It is never trusted from
the annotator/model output. The canonicalizer computes it as the sorted,
deduplicated union of:

- `diagnosis.supporting_evidence_ids`;
- `applicable_procedure.supporting_evidence_ids`;
- `verification_or_uncertainty.supporting_evidence_ids`; and
- every `action_plan[*].supporting_evidence_ids`.

Object-level citation IDs are deduplicated for serialization only. Their semantic
assignment is preserved. IDs are not added, removed, or reassigned except when
procedure canonicalization below determines the procedure object itself.

## 2. Procedure canonicalization

The only allowed final procedure statuses are:

`applicable | superseded | uncertain | not_applicable`.

`not_available` is never emitted for a procedure object. For each intent, the
canonicalizer considers only visible evidence with procedure metadata, and applies
the query cutoff, `valid_from`, `valid_to`, `withdrawn_at`, and model-scope checks.

- Exactly one remaining valid canonical `(procedure identity, procedure_version)`
  group: emit `applicable`, copy its explicit `procedure_version`, and cite all
  records merged into that group.
- Multiple simultaneously valid records whose applicable version cannot be
  uniquely selected: emit `uncertain`, set `procedure_version=null`, and retain
  only the directly supporting procedure-record citations.
- A visible record explicitly superseded by another visible procedure record, with
  no current applicable record: emit `superseded`; preserve only direct
  supersession/version evidence.
- No current applicable procedure: emit `not_applicable`, set
  `procedure_version=null`, and retain citations only when a visible procedure
  record directly supports the conclusion that no procedure applies; otherwise
  use an empty citation list.

Candidate uniqueness is evaluated by canonical `(procedure identity, procedure_version)`,
not by evidence-record count. The identity is the deterministic metadata tuple
formed from model scope, source-basis IDs, and procedure source type; multiple
records with the same identity and version are merged and all directly supporting
record IDs are retained. Within each identity, visible valid records are first
reduced by the explicit `supersedes` links: any version whose evidence is replaced
by a current visible replacement is removed before counting remaining versions.
Only multiple remaining different versions with no metadata-determined winner are
`uncertain`.

The canonicalizer never infers a procedure version, parameter, or applicability
from free-text similarity or common sense.

## 3. Acceptance and unresolved handling

After canonicalization, the frozen deterministic QA is rerun for schema,
temporal visibility, procedure validity, citation provenance/union, DAG validity,
and paraphrase consistency. A chain is accepted only if all three intent objects
pass. A chain that still has a semantic disagreement between independent passes,
or a non-mechanical schema/provenance error, remains `REVIEW_UNRESOLVED`.

No additional LLM call, semantic rewrite, or threshold adjustment is permitted.

## 4. Provenance

The v1.1 canonicalization hash and the pre-canonicalization raw A/B/adjudication
artifacts are recorded in the generation manifest. Private test item-level gold
remains outside the repository.
