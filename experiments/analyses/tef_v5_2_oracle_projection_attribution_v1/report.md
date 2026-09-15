# TEF-RAG v5.2 Oracle Projection Attribution

> DIAGNOSTIC ONLY — NOT AVAILABLE AT RETRIEVAL TIME. This is a seen diagnostic set. The analysis is for failure attribution and model development only. It must not be reported as a new unbiased holdout result.

## Setup

Offline 2×2×2 counterfactual attribution on the 12 seen set-mode queries. Candidate pools, bitemporal visibility, semantic scores, Top-k=5, character budget, frozen v5 weights, `_score_set`, exact search, gold definition, and evaluation are unchanged. Latest-control is excluded. No LLM was called. Oracle metadata exists only in this analyzer and is not a realizable retrieval graph.

Oracle roles use the explicit author-role prefix with probability 1. Oracle relations retain only explicit authoring edges whose endpoints are inside the unchanged visible candidate pool. Oracle profile demands the unique authored roles of required evidence and explicit relation types connecting required nodes; where no such relation exists, that field stays current and is flagged in the outputs.

## All set-mode

| Profile | Roles | Relations | Recall@5 | nDCG@5 | Complete@5 | repaired failures |
|---|---|---|---:|---:|---:|---:|
| current | current | current | 0.7208 | 0.7291 | 0.1667 | 0 |
| current | current | oracle | 0.7042 | 0.7145 | 0.1667 | 0 |
| current | oracle | current | 0.7000 | 0.7000 | 0.1667 | 1 |
| current | oracle | oracle | 0.7000 | 0.7041 | 0.1667 | 1 |
| oracle | current | current | 0.7750 | 0.7878 | 0.2500 | 1 |
| oracle | current | oracle | 0.7917 | 0.8035 | 0.3333 | 2 |
| oracle | oracle | current | 0.8417 | 0.8566 | 0.4167 | 3 |
| oracle | oracle | oracle | 0.8625 | 0.8752 | 0.5000 | 4 |

## Complex chain

| Profile | Roles | Relations | Recall@5 | nDCG@5 | Complete@5 | repaired failures |
|---|---|---|---:|---:|---:|---:|
| current | current | current | 0.6750 | 0.7074 | 0.1250 | 0 |
| current | current | oracle | 0.6500 | 0.6889 | 0.1250 | 0 |
| current | oracle | current | 0.6438 | 0.6604 | 0.1250 | 1 |
| current | oracle | oracle | 0.6438 | 0.6623 | 0.1250 | 1 |
| oracle | current | current | 0.7250 | 0.7689 | 0.1250 | 0 |
| oracle | current | oracle | 0.7500 | 0.7959 | 0.2500 | 1 |
| oracle | oracle | current | 0.8250 | 0.8485 | 0.3750 | 2 |
| oracle | oracle | oracle | 0.8250 | 0.8555 | 0.3750 | 2 |

## Attribution answers

- Oracle Profile alone repairs 1 CCC failures.
- Oracle Roles alone repairs 1 CCC failures.
- Oracle Relations alone repairs 0 CCC failures.
- Single-factor repairs: Profile 1, Roles 1, Relations 0. Compare the paired and OOO rows above for interactions.
- OOO leaves 6 of 10 original incomplete queries incomplete: tefv5h-q-01-01, tefv5h-q-02-00, tefv5h-q-02-01, tefv5h-q-03-01, tefv5h-q-04-00, tefv5h-q-04-02.

OOO residuals are direct evidence that a gold-complete Top-5 remains feasible while the frozen exact objective prefers an incomplete set under the strongest defensible authoring-derived representation. Thus residual failure is objective-misalignment evidence on this seen diagnostic set; it is not an independent validation result.

## Decision

Interpretation follows the frozen rule: large oracle-representation repair favors graph/projection work; substantial OOO residual failure favors objective/flow-completion work; both together imply both must be addressed. Detailed per-query selections and components are in `per_query.csv` and `results.json`.
