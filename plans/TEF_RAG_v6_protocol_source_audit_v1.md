# TEF-RAG v6 Benchmark Protocol Source Audit v1

**STATUS: COMPLETED — PASS WITH REQUIRED CORRECTIONS BEFORE FREEZE**

**Audit date:** 2026-09-15

**Scope:** `plans/TEF_RAG_v6_temporal_hard_benchmark_protocol_v1.md` 与 `configs/temporal_hard_benchmark_protocol_v1.json` 中的 source-backed physical envelope、sampling precedent、benchmark modeling choices、review/test-access 纪律，以及 scale/split/difficulty 算术一致性。

本 audit 只检查 protocol 是否可以安全进入 `FROZEN BEFORE DATA GENERATION`。没有生成 benchmark 数据，没有运行 v6，也没有根据目标算法表现改变 benchmark 规则。

## 1. 公开来源核验结果

### 1.1 HiTHIUM 280 Ah LFP reference system — VERIFIED

官方 HiTHIUM 280 Ah 储能电芯 datasheet 支持：

- prismatic LiFePO4 (LFP)；
- nominal capacity `280 Ah`；
- nominal voltage `3.2 V`；
- operating voltage：`2.50–3.65 V` at `T > 0°C`；
- operating voltage：`2.00–3.65 V` at `T <= 0°C`；
- charging temperature：`0–60°C`；
- discharging temperature：`-30–60°C`。

旧版 HiTHIUM V1.1 English datasheet 还明确给出 max continuous charge/discharge rate `1 P`，并在脚注中明确上述 temperature range 是 **ambient temperature**。当前公开的中文 20240918 V3.3 资料给出标准充/放电倍率 `0.5 P / 0.5 P`。

Source snapshots / public URLs:

1. HiTHIUM V1.1 EU English datasheet: `https://hithium.com/fileadmin/ns_theme_hithium/pdf/HiTHIUM_Data-Sheet_ESS-Cell280Ah_V1-1_EU_EN_230612.pdf`
2. HiTHIUM 20240918 V3.3 Chinese datasheet: `https://cn.hithium.com/bocupload/2024/11/14/17315688038239mc70h.pdf`
3. HiTHIUM current product page: `https://www.hithium.com/products/1.html`

**Audit judgment:** LFP / 280 Ah / 3.2 V / voltage envelope / ambient charge-discharge temperature claims are source-backed. `0.5P` and `1P` claims are version-specific datasheet specifications and must not be silently generalized to all LFP cells.

### 1.2 REPT 280 Ah cross-check — VERIFIED AS CORROBORATION

REPT BATTERO official 2025 energy-storage brochure independently lists its 280 Ah storage cell as `3.2 V` nominal with `2.50–3.65 V` voltage range.

Official source:

`https://www.reptbattero.com/wp-content/uploads/2025/10/REPT-BATTERO-ENERGY-STORAGE-PROMOTIONAL-2510.pdf`

**Audit judgment:** use REPT only as corroboration for the broad 280 Ah / 3.2 V / 2.50–3.65 V stationary-LFP reference choice; do not merge manufacturer-specific temperature/rate limits across vendors.

### 1.3 RWTH Aachen M5BAT one-second field data — VERIFIED WITH TECHNOLOGY CAVEAT

RWTH Aachen `M5BAT Large-Scale Battery Storage System: Dataset for Battery Unit Pb1 2017–2025`, DOI `10.18154/RWTH-2026-06637`, explicitly provides continuous **one-second-resolution** BMS/BSC operational field data.

Official source:

`https://publications.rwth-aachen.de/record/1038622`

The documented unit is a **flooded lead-acid** battery unit, not LFP.

**Audit judgment:** this source supports only the statement that one-second telemetry has a real large-scale-BESS field-data precedent. It does **not** support LFP-specific distributions, limits, or sampling requirements.

## 2. Modeling choices — VERIFIED AS PROTOCOL CHOICES, NOT INDUSTRY FACTS

The following values do not have to be source-backed as industry incidence/safety standards, provided the protocol consistently labels them as synthetic benchmark modeling choices:

- SOC generation window `10–90%`;
- cell-temperature generation bands `15–35 / 35–45 / 45–55°C`;
- gross data-quality outlier target `0.02%`, hard cap `0.05%`, chain cap `2%`;
- Realistic mixture `60/25/15`;
- Challenge difficulty composition;
- `400 chains / 1200 primary intents / 2400 query rows / 100 assets`;
- 60/20/20 split；
- Latest-5 / RECENCY_SOLVABLE gates。

**Audit judgment:** these are acceptable as preregistered experimental design choices. Paper/report wording must never present them as measured field incidence, universal BMS limits, or manufacturer safety thresholds.

## 3. Scale / split / difficulty arithmetic audit — PASS

Verified:

- `400 chains × 3 primary intents = 1200 primary intents`;
- `1200 intents × 2 phrasings = 2400 query rows`;
- each layer: `200 chains = 120 dev + 40 val + 40 test`;
- Challenge single-primary: `8 difficulties × 20 chains = 160 chains`;
- Challenge compositional: `40 chains`； total Challenge = `200`;
- each primary difficulty split `12/4/4` sums to `20`;
- each primary difficulty therefore has `60 intents` total and `12/12` validation/test intents;
- Realistic mixture `120 + 50 + 30 = 200` and its split subtotals are consistent;
- Challenge asset split `30/10/10 = 50`, exact asset-disjoint across splits； Realistic uses a separate 50-asset pool.

No arithmetic blocker found.

## 4. REQUIRED CORRECTION 1 — ambient temperature must not be treated as cell-temperature hard envelope

Current source-backed HiTHIUM temperature limits are explicitly annotated as **ambient temperature** in the datasheet. The benchmark, however, also generates `cell-temperature` telemetry.

Therefore the protocol must not infer:

`cell_temperature > 60°C => source-backed physical impossibility / automatic data-quality error`

from the ambient-temperature datasheet range alone.

Required correction before freeze:

- keep `ambient_charge_temperature_c` and `ambient_discharge_temperature_c` as source-backed contextual envelope;
- keep `normal/elevated/fault cell-temperature bands` as benchmark modeling choices;
- deterministic validation must not compare a cell-temperature sensor value directly against the manufacturer ambient envelope as if they were the same variable;
- values outside a modeling band are not automatically dirty data; classification must depend on authored physical/contextual evidence and source support.

This is a **freeze blocker** because otherwise source-backed and synthetic variables are semantically conflated.

## 5. REQUIRED CORRECTION 2 — P-rate is not current and must not be written as `|I| <= 0.5P`

HiTHIUM uses `P` notation in its datasheets. P-rate is a power/energy rate concept; it is not an ampere-valued current threshold.

Current Markdown wording such as:

`routine current: |I| <= 0.5P`

is dimensionally misleading.

Required correction before freeze:

- write `normalized charge/discharge P-rate <= 0.5P` instead of `current <= 0.5P`;
- write the high-load band as `0.5P < normalized P-rate <= 1.0P`;
- if synthetic current in amperes is needed, generate/derive it consistently from authored power/voltage (or separately define a C-rate/current model); do not equate P-rate numerically with amperes;
- record that HiTHIUM V3.3 uses `0.5P/0.5P` as standard charge/discharge rate, while V1.1 lists `1P` max continuous charge/discharge rate. These are manufacturer/version-specific specs.

This is a **freeze blocker** because the current wording conflates electrical quantities.

## 6. REQUIRED CORRECTION 3 — do not overclaim “independent AI review”

The project has no qualified field expert. If the same AI system / development workflow performs both review passes, calling the second pass `independent review` is stronger than the procedure supports.

Required correction before freeze:

- rename the requirement to **second blind source-grounded AI review pass**;
- the second pass must not receive the first pass verdict/reasoning before making its own judgment;
- if a genuinely separate model/agent is used, record that execution fact, but still do not call it expert review;
- paper wording remains `public-source-grounded, AI-assisted reviewed synthetic benchmark`;
- limitation remains explicit: no qualified field expert / real-station work-order validation.

This is a **freeze blocker in wording/protocol discipline**, not a reason to abandon AI-assisted review.

## 7. REQUIRED CORRECTION 4 — seal test-gold review from the algorithm-development workflow

The current policy correctly says test gold/canonical flow are evaluator-only before primary evaluation. Because AI-assisted review will inspect authored gold/flow, test review itself can leak test semantics back into later method development if performed in the same development context.

Required correction before freeze:

- test-chain semantic review must run in a **sealed evaluator/review workflow**;
- the main algorithm-development workflow receives only aggregate QC results, unresolved counts, source-audit status, and hashes — not per-test gold, canonical flow, or item-level reviewer reasoning;
- test gold/canonical flow remain off the public development branch before primary evaluation;
- validation remains visible for method development as currently specified;
- if test review finds an unresolved item, repair/regeneration occurs under preregistered rules and the final sealed test artifact is re-hashed before any target-method evaluation.

This is a **freeze blocker for test integrity**.

## 8. Source-version discipline — REQUIRED BEFORE FREEZE

Because manufacturer datasheets can change, the final protocol should pin source identity/version/access date where available.

Recommended source registry:

- HiTHIUM V1.1 EU English datasheet — archived manufacturer source for `1P max continuous` and ambient footnote;
- HiTHIUM 20240918 V3.3 Chinese datasheet — newer manufacturer source for 280Ah/3.2V/voltage/temp and `0.5P` standard rate;
- HiTHIUM current product page — product-level corroboration;
- REPT BATTERO 2025 storage brochure — cross-manufacturer corroboration for 280Ah/3.2V/2.50–3.65V only;
- RWTH M5BAT DOI dataset — one-second BESS telemetry precedent only, explicitly lead-acid.

The protocol must keep a per-source `supports` list so a source is never cited for a claim it does not support.

## 9. Final audit verdict

**PASS WITH 4 REQUIRED CORRECTIONS BEFORE FREEZE.**

No issue was found with the benchmark scale, split arithmetic, difficulty counts, FlowComplete global-assignment definition, Latest-5 gates, or the decision to use public-source-grounded AI-assisted review instead of falsely claiming expert review.

Before changing protocol status to `FROZEN BEFORE DATA GENERATION`, apply and regression-test these four corrections:

1. ambient-temperature vs cell-temperature separation;
2. P-rate vs current semantics;
3. second **blind** AI review pass wording/procedure;
4. sealed test-gold review workflow.

After these corrections pass the protocol validator/tests, the protocol is suitable for a final user freeze decision. This audit itself does **not** authorize data generation or v6 implementation.

## CORRECTION STATUS

以下 4 个 freeze blockers 已按本 audit 要求修复：

1. ambient temperature 与 cell temperature 已分离；
2. P-rate 与 current 语义已分离；
3. 第二轮审核已改为 blind AI review；
4. test gold/canonical flow 已纳入 sealed review workflow。

**RESOLVED — see branch history.** Protocol 仍为 `DRAFT_FOR_REVIEW`；本状态不构成 Freeze、数据生成或 v6 实现授权。
