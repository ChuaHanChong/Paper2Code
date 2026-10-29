#!/usr/bin/env python3
"""Check that the independent verifier accepts correct code and rejects a regression."""
from __future__ import annotations

from pathlib import Path
import subprocess
import sys
import tempfile

REFERENCE_CODE = '''import json
import math

def scaled_dot_product_attention(query: list[list[float]], key: list[list[float]], value: list[list[float]]) -> list[list[float]]:
    """Compute attention from query [N,D], key [M,D], value [M,V]."""
    for matrix in (query, key, value):
        if not matrix or not matrix[0] or any(len(row) != len(matrix[0]) for row in matrix):
            raise ValueError("invalid matrix shape")
        if any(not math.isfinite(number) for row in matrix for number in row):
            raise ValueError("nonfinite input")
    if len(query[0]) != len(key[0]) or len(key) != len(value):
        raise ValueError("incompatible shapes")
    output = []
    for row in query:
        logits = [sum(a * b for a, b in zip(row, key_row)) / math.sqrt(len(row)) for key_row in key]
        peak = max(logits)
        numerators = [math.exp(logit - peak) for logit in logits]
        denominator = sum(numerators)
        output.append([float(sum(weight * vector[index] for weight, vector in zip(numerators, value)) / denominator)
                       for index in range(len(value[0]))])
    return output

if __name__ == "__main__":
    print(json.dumps(scaled_dot_product_attention([[1, 0]], [[1, 0], [0, 1]], [[2, 0], [0, 4]])))
'''


def main() -> int:
    """Exercise the verifier with an isolated reference and scaling mutation."""
    verifier = Path(__file__).with_name("verify_generated.py")
    with tempfile.TemporaryDirectory(prefix="paper2code acceptance ") as temporary:
        root = Path(temporary)
        source = root / "attention.py"
        source.write_text(REFERENCE_CODE)
        (root / "config.yaml").write_text("method: scaled_dot_product_attention\ndtype: float64\n")
        (root / "reproduce.sh").write_text('#!/usr/bin/env bash\nset -eu\ncd "$(dirname "$0")"\npython3 attention.py\n')
        correct = subprocess.run([sys.executable, str(verifier), "--repo", str(root)], capture_output=True, text=True)
        if correct.returncode:
            print(correct.stdout + correct.stderr, file=sys.stderr)
            return 1
        source.write_text(REFERENCE_CODE.replace("math.sqrt(len(row))", "len(row)"))
        incorrect = subprocess.run([sys.executable, str(verifier), "--repo", str(root)], capture_output=True, text=True)
        if incorrect.returncode == 0:
            print("Verifier accepted the incorrect score denominator", file=sys.stderr)
            return 1
        print("PASS: 10 checks accept the reference; the incorrect score denominator is rejected.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
