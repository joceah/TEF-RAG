# TEF-RAG v6 Stage 3B: learned set scorer

## 1. Motivation

Stage 3A's corrected selector diagnostic attributed 125 of 129 validation typed-feasible failures to objective misalignment. Stage 3B therefore freezes retrieval, Top-32 learned pair proposal, relation prompt/judgments, and `final_k=5`, changing only full-set scoring.

## 2. Frozen Stage 3A graph

Every run uses the frozen Stage 3A proposer/model hash and relation cache. HTTP transport is fail-closed. Development and validation achieved 100% relation-cache hits and zero new requests.

## 3. Candidate set bank

Each query shares one deterministic bank across all objectives: every 5-combination of the top 15 node-scored evidence, the Stage 3A greedy set, raw beam when available, and every single-swap neighbor using the top-30 pool. Gold never generates candidates. Mean bank sizes were 2,414.22 development and 1,714.97 validation.

## 4. Bank oracle

The official FlowComplete bank oracle was 75.42% on development and 79.17% on validation. The large gap above achieved scores shows that candidate generation contains substantial headroom and is not the immediate limiting factor.

## 5. Set features

Deployment-visible features cover node-score aggregates, individual handcrafted components, event composition, query role coverage, generic directed-edge statistics, temporal span, connectivity/path structure, and lexical/source diversity. The type-aware variant additionally uses count, confidence sum, and maximum confidence for every observed frozen relation type. Gold, chain/query IDs, split, difficulty, and evidence-ID patterns are excluded.

## 6. Type-agnostic vs type-aware scorer

Both are balanced logistic regressions with fixed `C=1`, `liblinear`, and seed `20260916`. Type-aware exceeded agnostic FlowComplete by 3.54 points on all development and 1.46 points on validation, showing small positive relation-type utility, but both were substantially worse than the existing objectives.

## 7. Development training

The Stage 3A grouped split was reused: 188 train and 52 tune chains. The final development refit used 11,544 positive and 92,372 negative sampled sets. Positives were official FlowComplete sets; negatives combined high-handcrafted-score and deterministic diverse failures.

## 8. Validation results

Validation FlowComplete was 31.25% for Stage 3A greedy, 26.88% for bank + handcrafted, 16.88% for learned type-agnostic, and 18.33% for learned type-aware. The learned objective did not solve the selector problem.

## 9. Same-bank objective ablation

The 79.17% bank oracle leaves a 60.83-point gap above type-aware. Type-aware improved 1.46 points over agnostic but trailed the same-bank handcrafted scorer by 8.54 points. More exhaustive search of the old objective also failed to beat the original greedy path.

## 10. Stage 3A Top-24 cost sensitivity

This post-hoc diagnostic was not used for model selection. Validation Rule/Top-24/Top-32 used 21.10/21.40/27.15 pairs per query and achieved 28.96%/31.46%/31.25% FlowComplete. Top-24 therefore matched the rule cost and slightly exceeded frozen Top-32, with zero new calls.

## 11. Cache integrity

Development reused 43,746 judgments and validation reused 13,030. Cache hit rate was 1.0; new HTTP requests were zero, including Top-24 sensitivity.

## 12. Limitations

The synthetic benchmark remains under `BENCHMARK_ISSUE_FOUND`. Linear pointwise classification is poorly aligned with choosing one winner from thousands of sets, and sampled negatives do not cover every high-model-score failure. No nonlinear model or large hyperparameter search was introduced.

## 13. Next-stage decision

Candidate-set generation has a high oracle, while the learned pointwise objective fails badly. Relation-type features add only limited value. The next priority is a directly ranking-oriented flow-utility objective with query-level hard-negative mining, not relation-classifier optimization or a larger search bank.
