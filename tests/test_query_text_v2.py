import unittest

from baseline_adapters.query_text_v2 import semantic_question


class QueryTextV2Tests(unittest.TestCase):
    def test_removes_wrapper_and_current_cutoff(self):
        text = "设备A，资料截止2026-01-02T00:00:00Z；截至当前，问题进展如何？"
        self.assertEqual(semantic_question(text), "问题进展如何？")

    def test_removes_repeated_calendar_cutoff(self):
        text = "设备A，资料截止2026-06-09T23:00:00Z；截至2026年6月9日，哪些事实成立？"
        self.assertEqual(semantic_question(text), "哪些事实成立？")

    def test_preserves_internal_temporal_comparison(self):
        text = "设备A，资料截止2026-06-13T00:00:00Z；规程换版前后有什么变化？"
        self.assertEqual(semantic_question(text), "规程换版前后有什么变化？")


if __name__ == "__main__":
    unittest.main()
