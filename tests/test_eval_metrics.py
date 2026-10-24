"""Standard-library tests for the evaluation math and frozen-real-data contract."""
import unittest

from eval_gold import LABELS, load_real, metric_for_check, evaluate
from llm import get_backend


class EvalMetricsTest(unittest.TestCase):
    def test_confusion_precision_recall_and_abstention(self):
        m = metric_for_check(["A", "A", "B", "B"], ["A", "B", "B", "UNCLEAR"],
                             ["A", "B", "UNCLEAR"])
        self.assertEqual(m["confusion_matrix"]["A"]["B"], 1)
        self.assertEqual(m["labels"]["B"]["precision"], 0.5)
        self.assertEqual(m["labels"]["B"]["recall"], 0.5)
        self.assertEqual(m["abstention_rate"], 0.25)
        self.assertEqual(m["coverage"], 0.75)
        self.assertEqual(m["accuracy_on_non_abstained"], 2 / 3)
        self.assertIsNone(m["labels"]["UNCLEAR"]["recall"])
        zero = metric_for_check(["A", "B"], ["B", "A"], ["A", "B"])
        self.assertEqual(zero["labels"]["A"]["f1"], 0.0)

    def test_real_reference_has_frozen_snapshots_and_required_cases(self):
        rows = load_real("data/gold_set.json")
        self.assertEqual(len(rows), 25)
        self.assertEqual(sum(g["sex_stratified"] == "STRATIFIED_FOUND" for g, _, _ in rows), 2)
        self.assertEqual(sum(not has_results for _, _, has_results in rows), 5)
        self.assertEqual(next(g for g, _, _ in rows if g["nct_id"] == "NCT00074724")["enrollment_by_sex"],
                         "NOT_REPORTED_IN_RECORD")

    def test_mock_integration_keeps_reference_provenance(self):
        result = evaluate(load_real("data/gold_set.json"), get_backend("mock"))
        self.assertEqual(len(result["reference_digest"]), 64)
        self.assertEqual(len(result["decisions"]), 25)
        self.assertEqual(set(result["metrics"]), set(LABELS))


if __name__ == "__main__":
    unittest.main()
