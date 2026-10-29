#!/usr/bin/env python3
"""Verify a generated attention project against independently worked examples."""
from __future__ import annotations

import argparse
import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
from typing import Any
import unittest

ABSOLUTE_TOLERANCE = 1e-9  # Specified in the synthetic paper's numerical acceptance rule.
EXPECTED_FIRST_ROW = [[1.3395230986533139, 1.3209538026933723]]
EXPECTED_MULTIPLE_ROWS = [
    [1.3395230986533139, 1.3209538026933723],
    [0.6604769013466861, 2.6790461973066277],
]
REPRODUCE_TIMEOUT_SECONDS = 10  # The fixture runs one stdlib-only numerical function, with no I/O beyond JSON.


def load_attention(project: Path) -> Any:
    """Load the generated attention module without altering sys.path."""
    spec = importlib.util.spec_from_file_location("generated_attention", project / "attention.py")
    if spec is None or spec.loader is None:
        raise ValueError("attention.py could not be loaded")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def build_suite(project: Path) -> unittest.TestSuite:
    """Build public-interface checks for one generated attention project."""
    module = load_attention(project)

    class GeneratedAttentionTests(unittest.TestCase):
        """Exercise the required function and reproduction command."""

        def assert_matrix_close(self, actual: Any, expected: list[list[float]]) -> None:
            """Check matrix shape and values against the paper's literal answers."""
            self.assertIsInstance(actual, list)
            self.assertEqual(len(actual), len(expected))
            for actual_row, expected_row in zip(actual, expected):
                self.assertIsInstance(actual_row, list)
                self.assertEqual(len(actual_row), len(expected_row))
                for actual_value, expected_value in zip(actual_row, expected_row):
                    self.assertIsInstance(actual_value, float)
                    self.assertAlmostEqual(actual_value, expected_value, delta=ABSOLUTE_TOLERANCE)

        def test_first_worked_answer(self) -> None:
            """Check the nonuniform attention weights from the worked example."""
            actual = module.scaled_dot_product_attention([[1, 0]], [[1, 0], [0, 1]], [[2, 0], [0, 4]])
            self.assert_matrix_close(actual, EXPECTED_FIRST_ROW)

        def test_zero_query_averages_values(self) -> None:
            """Check the uniform-weight case independently of score scaling."""
            actual = module.scaled_dot_product_attention([[0, 0]], [[1, 0], [0, 1]], [[2, 0], [0, 4]])
            self.assert_matrix_close(actual, [[1.0, 2.0]])

        def test_multiple_rows(self) -> None:
            """Check that separate query rows have separate normalized weights."""
            actual = module.scaled_dot_product_attention([[1, 0], [0, 1]], [[1, 0], [0, 1]], [[2, 0], [0, 4]])
            self.assert_matrix_close(actual, EXPECTED_MULTIPLE_ROWS)

        def test_value_feature_count_is_independent(self) -> None:
            """Check that value width need not match key width."""
            actual = module.scaled_dot_product_attention([[0, 0]], [[1, 0], [0, 1]], [[2, 4, 6], [4, 8, 10]])
            self.assert_matrix_close(actual, [[3.0, 6.0, 8.0]])

        def test_inputs_are_unchanged(self) -> None:
            """Check that inference does not mutate the caller's matrices."""
            inputs = [[[1, 0]], [[1, 0], [0, 1]], [[2, 0], [0, 4]]]
            before = copy.deepcopy(inputs)
            module.scaled_dot_product_attention(*inputs)
            self.assertEqual(inputs, before)

        def test_large_scores_are_stable(self) -> None:
            """Check the paper's overflow-sensitive worked example."""
            actual = module.scaled_dot_product_attention([[1000, 0]], [[1, 0], [0, 1]], [[2, 0], [0, 4]])
            self.assert_matrix_close(actual, [[2.0, 0.0]])

        def test_invalid_shapes_raise(self) -> None:
            """Check every invalid shape explicitly rejected by the paper."""
            valid_query, valid_key, valid_value = [[1, 0]], [[1, 0], [0, 1]], [[2, 0], [0, 4]]
            cases = [
                ([], valid_key, valid_value),
                (valid_query, [], valid_value),
                (valid_query, valid_key, []),
                ([[]], valid_key, valid_value),
                (valid_query, [[], []], valid_value),
                (valid_query, valid_key, [[], []]),
                ([[1, 0], [1]], valid_key, valid_value),
                (valid_query, [[1, 0], [1]], valid_value),
                (valid_query, valid_key, [[2, 0], [4]]),
                ([[1]], valid_key, valid_value),
                (valid_query, valid_key, [[2, 0]]),
            ]
            for query, key, value in cases:
                with self.subTest(query=query, key=key, value=value):
                    with self.assertRaises(ValueError):
                        module.scaled_dot_product_attention(query, key, value)

        def test_nonfinite_inputs_raise(self) -> None:
            """Check that invalid numeric values never become successful output."""
            for invalid in (float("nan"), float("inf"), float("-inf")):
                for position in range(3):
                    args = [[[1, 0]], [[1, 0], [0, 1]], [[2, 0], [0, 4]]]
                    args[position][0][0] = invalid
                    with self.subTest(position=position, invalid=invalid):
                        with self.assertRaises(ValueError):
                            module.scaled_dot_product_attention(*args)

        def test_required_artifacts_exist(self) -> None:
            """Check the exact runnable project surface requested in the paper."""
            paths = {path.name for path in project.iterdir() if path.is_file()}
            self.assertEqual(paths, {"attention.py", "config.yaml", "reproduce.sh"})
            for name in paths:
                self.assertTrue((project / name).read_text().strip(), name)
            config = (project / "config.yaml").read_text()
            self.assertIn("scaled_dot_product_attention", config)
            self.assertIn("float64", config)

        def test_reproduction_command(self) -> None:
            """Check that the reproduction script executes the known example."""
            result = subprocess.run(["bash", str(project / "reproduce.sh")], cwd=project, text=True,
                                    capture_output=True, timeout=REPRODUCE_TIMEOUT_SECONDS, check=False)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assert_matrix_close(json.loads(result.stdout), EXPECTED_FIRST_ROW)

    return unittest.defaultTestLoader.loadTestsFromTestCase(GeneratedAttentionTests)


def main() -> int:
    """Run the independent verifier against a supplied project directory."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True, type=Path)
    args = parser.parse_args()
    result = unittest.TextTestRunner(verbosity=2).run(build_suite(args.repo.resolve()))
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
