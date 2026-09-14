import unittest

from tef_rag_v5 import QueryConditionedSetEvidenceRetrieverV5


def record(identifier, day, text=None, available_day=None):
    event_time = f"2026-03-{day:02d}T00:00:00Z"
    available_at = f"2026-03-{(available_day or day):02d}T00:00:00Z"
    return {
        "id": identifier,
        "asset_id": "A",
        "event_time": event_time,
        "available_at": available_at,
        "kind": "maintenance_record",
        "text": text or identifier,
        "work_order_ids": [],
    }


def query(text="概括当前证据集合"):
    return {
        "asset_id": "A",
        "query_time": "2026-03-20T00:00:00Z",
        "text": text,
    }


def engine(records, relations=(), roles=None, top_k=2, budget=16000, beam_width=64):
    return QueryConditionedSetEvidenceRetrieverV5(
        records,
        [{"asset_id": "A", "model_scope": "M"}],
        relations,
        roles=roles or {},
        top_k=top_k,
        budget=budget,
        beam_width=beam_width,
    )


def profile(roles=None, relations=None, mode="set"):
    return {
        "selection_mode": mode,
        "role_demands": roles or {},
        "relation_demands": relations or {},
    }


class QueryConditionedSetEvidenceV5Tests(unittest.TestCase):
    def test_exact_search_finds_hand_checked_optimum(self):
        records = [record(letter, index + 1) for index, letter in enumerate("abcde")]
        retriever = engine(records, top_k=3)
        result = retriever.retrieve(
            query(),
            {"a": 1.0, "b": 0.8, "c": 0.6, "d": 0.2, "e": 0.0},
            query_profile=profile(),
            search_strategy="exact",
        )

        self.assertEqual(set(result["evidence_ids"]), {"a", "b", "c"})
        self.assertEqual(result["search_diagnostics"]["evaluated_sets"], 10)

    def test_beam_and_exact_share_identical_score_semantics(self):
        records = [record("a", 1), record("b", 2), record("c", 3), record("d", 4)]
        retriever = engine(records, top_k=3, beam_width=64)
        kwargs = {
            "query_profile": profile(roles={"observation": 1.0}),
            "relevance": {item["id"]: 0.5 for item in records},
        }

        beam = retriever.retrieve(query(), search_strategy="beam", **kwargs)
        exact = retriever.retrieve(query(), search_strategy="exact", **kwargs)

        self.assertEqual(set(beam["evidence_ids"]), set(exact["evidence_ids"]))
        self.assertEqual(beam["score_components"], exact["score_components"])
        self.assertEqual(beam["raw_score_components"], exact["raw_score_components"])

    def test_exact_search_is_deterministic(self):
        records = [record("c", 3), record("a", 1), record("b", 2), record("d", 4)]
        retriever = engine(records, top_k=2)
        kwargs = {
            "query_profile": profile(),
            "search_strategy": "exact",
        }
        first = retriever.retrieve(query(), {item["id"]: 0.5 for item in records}, **kwargs)
        second = retriever.retrieve(query(), {item["id"]: 0.5 for item in records}, **kwargs)

        self.assertEqual(first, second)
        self.assertEqual(first["evidence_ids"], ["a", "b"])

    def test_exact_preserves_visibility_budget_pool_and_top_k(self):
        records = [
            record("large", 1, "x" * 20),
            record("a", 2, "aa"),
            record("b", 3, "bb"),
            record("future", 4, "ff", available_day=21),
        ]
        result = engine(records, top_k=2, budget=4).retrieve(
            query(),
            {"large": 100.0, "a": 0.5, "b": 0.4, "future": 200.0},
            query_profile=profile(),
            search_strategy="exact",
        )

        self.assertEqual(set(result["evidence_ids"]), {"a", "b"})
        self.assertEqual(len(result["evidence_ids"]), 2)
        self.assertEqual(result["candidate_count"], 3)
        self.assertEqual(result["characters"], 4)

    def test_complementarity_chain_exact_recovers_global_set(self):
        records = [
            record("a", 1),
            record("b", 2),
            record("c", 3),
            record("d", 4),
            record("e", 5),
        ]
        roles = {
            "a": {"role": "observation"},
            "b": {"role": "diagnosis"},
            "c": {"role": "verification"},
            "d": {"role": "observation"},
            "e": {"role": "observation"},
        }
        relations = [
            {"prior_id": "a", "update_id": "b", "update_relation": "follows", "confidence": 1.0},
            {"prior_id": "b", "update_id": "c", "update_relation": "follows", "confidence": 1.0},
        ]
        retriever = engine(records, relations, roles=roles, top_k=3, beam_width=1)
        kwargs = {
            "relevance": {"a": 0.6, "b": 0.0, "c": 0.6, "d": 0.7, "e": 0.65},
            "query_profile": profile(
                roles={"observation": 1.0, "diagnosis": 1.0, "verification": 1.0},
                relations={"follows": 1.0},
            ),
        }

        exact = retriever.retrieve(query(), search_strategy="exact", **kwargs)
        beam = retriever.retrieve(query(), search_strategy="beam", **kwargs)

        self.assertEqual(set(exact["evidence_ids"]), {"a", "b", "c"})
        self.assertGreater(exact["score_components"]["total"], beam["score_components"]["total"])
        self.assertNotEqual(set(beam["evidence_ids"]), {"a", "b", "c"})

    def test_query_profile_changes_selection_without_changing_candidates_or_relevance(self):
        records = [record("diagnosis", 1), record("verification", 2)]
        roles = {
            "diagnosis": {"role": "diagnosis"},
            "verification": {"role": "verification"},
        }
        retriever = engine(records, roles=roles, top_k=1)
        relevance = {item["id"]: 0.5 for item in records}

        diagnosis_result = retriever.retrieve(
            query(), relevance, query_profile=profile(roles={"diagnosis": 1.0})
        )
        verification_result = retriever.retrieve(
            query(), relevance, query_profile=profile(roles={"verification": 1.0})
        )

        self.assertEqual(diagnosis_result["evidence_ids"], ["diagnosis"])
        self.assertEqual(verification_result["evidence_ids"], ["verification"])
        self.assertEqual(diagnosis_result["candidate_count"], verification_result["candidate_count"])

    def test_new_role_beats_redundant_duplicate_at_set_level(self):
        records = [
            record("a_observation", 1, "same repeated observation"),
            record("b_observation_copy", 2, "same repeated observation"),
            record("z_diagnosis", 3, "independent diagnostic finding"),
        ]
        roles = {
            "a_observation": {"role": "observation"},
            "b_observation_copy": {"role": "observation"},
            "z_diagnosis": {"role": "diagnosis"},
        }
        result = engine(records, roles=roles).retrieve(
            query(),
            {item["id"]: 0.5 for item in records},
            query_profile=profile(roles={"observation": 1.0, "diagnosis": 1.0}),
            redundancy_scores={("a_observation", "b_observation_copy"): 1.0},
        )

        self.assertEqual(set(result["evidence_ids"]), {"a_observation", "z_diagnosis"})
        self.assertGreater(result["score_components"]["role"], 0.0)
        self.assertEqual(result["score_components"]["redundancy"], 0.0)

    def test_chain_gain_activates_only_after_both_selected_endpoints(self):
        records = [
            record("a_action", 1),
            record("b_verification", 2),
            record("c_keyword_distractor", 3),
            record("d_low", 4),
        ]
        roles = {
            "a_action": {"role": "action"},
            "b_verification": {"role": "verification"},
        }
        relations = [
            {
                "prior_id": "a_action",
                "update_id": "b_verification",
                "update_relation": "verifies",
                "confidence": 1.0,
            }
        ]
        result = engine(records, relations, roles=roles).retrieve(
            query(),
            {"a_action": 0.9, "b_verification": 0.95, "c_keyword_distractor": 1.0, "d_low": 0.4},
            query_profile=profile(
                roles={"action": 1.0, "verification": 1.0},
                relations={"verifies": 1.0},
            ),
        )

        self.assertEqual(set(result["evidence_ids"]), {"a_action", "b_verification"})
        self.assertEqual(result["trace"][0]["marginal_components"]["chain"], 0.0)
        self.assertGreater(result["trace"][1]["marginal_components"]["chain"], 0.0)
        self.assertEqual(len(result["selected_edges"]), 1)

    def test_backward_process_edge_is_rejected_and_never_scores(self):
        records = [record("later", 8), record("earlier", 2)]
        relations = [
            {
                "prior_id": "later",
                "update_id": "earlier",
                "update_relation": "follows",
                "confidence": 1.0,
            }
        ]
        result = engine(records, relations).retrieve(
            query(),
            {"later": 1.0, "earlier": 0.9},
            query_profile=profile(relations={"follows": 1.0}),
        )

        self.assertEqual(result["score_components"]["chain"], 0.0)
        self.assertEqual(result["selected_edges"], [])
        self.assertEqual(result["rejected_edges"][0]["reason"], "backward_event_time")

    def test_last_slot_compares_nodes_instead_of_truncating_a_path_prefix(self):
        records = [
            record("a_semantic_anchor", 1),
            record("b_path_start", 2),
            record("c_nonessential_middle", 3),
            record("z_key_update", 4),
        ]
        roles = {
            "a_semantic_anchor": {"role": "context"},
            "b_path_start": {"role": "action"},
            "c_nonessential_middle": {"role": "administrative"},
            "z_key_update": {"role": "verification"},
        }
        relations = [
            {"prior_id": "b_path_start", "update_id": "c_nonessential_middle", "update_relation": "follows", "confidence": 1.0},
            {"prior_id": "c_nonessential_middle", "update_id": "z_key_update", "update_relation": "verifies", "confidence": 1.0},
        ]
        result = engine(records, relations, roles=roles, top_k=2).retrieve(
            query(),
            {
                "a_semantic_anchor": 1.0,
                "b_path_start": 0.2,
                "c_nonessential_middle": 0.1,
                "z_key_update": 0.95,
            },
            query_profile=profile(
                roles={"context": 1.0, "verification": 1.0},
                relations={"verifies": 1.0},
            ),
        )

        self.assertEqual(result["evidence_ids"], ["a_semantic_anchor", "z_key_update"])
        self.assertNotIn("c_nonessential_middle", result["evidence_ids"])

    def test_trace_is_exactly_the_actual_selection_history(self):
        records = [record("a", 1), record("b", 2), record("c", 3)]
        result = engine(records, top_k=2).retrieve(
            query(),
            {"a": 1.0, "b": 0.5, "c": 0.0},
            query_profile=profile(),
        )

        self.assertEqual(len(result["trace"]), len(result["evidence_ids"]))
        for index, step in enumerate(result["trace"]):
            self.assertEqual(step["selected_id"], result["evidence_ids"][index])
            self.assertEqual(step["set_after"], result["evidence_ids"][: index + 1])
            for edge in step["activated_relations"]:
                self.assertIn(edge["prior_id"], step["set_after"])
                self.assertIn(edge["update_id"], step["set_after"])

    def test_visibility_budget_and_top_k_are_hard_constraints(self):
        records = [
            record("a_large", 1, "x" * 20),
            record("b_small", 2, "bb"),
            record("c_small", 3, "cc"),
            record("future", 4, "ff", available_day=21),
        ]
        result = engine(records, top_k=2, budget=4).retrieve(
            query(),
            {"a_large": 1.0, "b_small": 0.5, "c_small": 0.4, "future": 100.0},
            query_profile=profile(),
        )

        self.assertEqual(result["evidence_ids"], ["b_small", "c_small"])
        self.assertEqual(result["characters"], 4)
        self.assertEqual(result["candidate_count"], 3)

    def test_selection_is_deterministic(self):
        records = [record("a", 1), record("b", 2), record("c", 3)]
        retriever = engine(records, top_k=2)
        kwargs = dict(query_profile=profile(roles={"observation": 1.0}))
        first = retriever.retrieve(query(), {item["id"]: 0.5 for item in records}, **kwargs)
        second = retriever.retrieve(query(), {item["id"]: 0.5 for item in records}, **kwargs)
        self.assertEqual(first, second)

    def test_latest_mode_is_profile_driven_not_keyword_routed(self):
        records = [record("old", 1), record("new", 5)]
        retriever = engine(records, top_k=1)
        result = retriever.retrieve(
            query("请提供记录"),
            {"old": 100.0, "new": 0.0},
            query_profile=profile(mode="latest"),
        )
        self.assertEqual(result["evidence_ids"], ["new"])
        self.assertEqual(result["selector"], "query_profile_recency_control_v5")

        set_result = retriever.retrieve(
            query("最新业务记录是什么"),
            {"old": 100.0, "new": 0.0},
            query_profile=profile(mode="set"),
        )
        self.assertEqual(set_result["evidence_ids"], ["old"])
        self.assertEqual(set_result["selector"], "query_conditioned_set_beam_v5")


if __name__ == "__main__":
    unittest.main()
