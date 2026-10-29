# Standalone acceptance checks

These small fixtures check real CLI generation and generated behavior separately.
Live generation is opt-in and uses the selected CLI account's usage allowance; offline tests make no model calls.

## Generate without executing generated code

`attention.json` and `attention.tex` contain the same complete synthetic specification.
The JSON follows the bundled Transformer cleaned paper structure; the LaTeX carries the exact specification in a verbatim block and requires no TeX compiler.
The model must produce `attention.py`, `config.yaml`, and `reproduce.sh` using only the Python standard library in the generated project.

From the Paper2Code checkout, explicitly choose a backend, input format, fresh output path, and a per-stage timeout measured on the host:

```sh
.venv/bin/python tests/live_standalone.py --backend codex --paper-format JSON --timeout "$MEASURED_STAGE_TIMEOUT" --output-dir /tmp/paper2code-codex-json
.venv/bin/python tests/live_standalone.py --backend codex --paper-format LaTeX --timeout "$MEASURED_STAGE_TIMEOUT" --output-dir /tmp/paper2code-codex-latex
.venv/bin/python tests/live_standalone.py --backend claude --paper-format JSON --timeout "$MEASURED_STAGE_TIMEOUT" --output-dir /tmp/paper2code-claude-json
.venv/bin/python tests/live_standalone.py --backend claude --paper-format LaTeX --timeout "$MEASURED_STAGE_TIMEOUT" --output-dir /tmp/paper2code-claude-latex
```

`--model MODEL` is optional; the selected CLI must already be authenticated through its saved login.
The launcher removes provider key/token variables, uses the public pipeline command, and records `generation.json`, stdout/stderr logs, pipeline artifacts, and the candidate project.
It never executes generated files or `reproduce.sh`; `status: generated` proves generation only.
Existing nonempty output directories are refused to preserve evidence and prevent accidental reruns over earlier output.
Provider failure, invalid output, or nonzero pipeline exit produces a failed result and nonzero launcher exit.

## Verify generated behavior separately

Review the generated files, then run the verifier in the normal sandbox, without additional model/network permissions:

```sh
.venv/bin/python tests/acceptance/verify_generated.py --repo /tmp/paper2code-codex-json/project
```

Repeat that separate command for every successful backend/format output directory.
The verifier imports generated `attention.py` and executes `bash reproduce.sh`, so it belongs to the generated-code execution phase, not generation.
It checks fixed numerical answers, zero-query averaging, separate query rows, independent value width, input preservation, stable softmax, invalid shapes/nonfinite input, required project artifacts, and reproduction behavior.
The literals come from a 60-digit Decimal calculation of p = exp(1/sqrt(2)) / (exp(1/sqrt(2)) + 1), independent of generated code.
The paper states the absolute acceptance tolerance of 1e-9 before generation.

Check the verifier itself without any model calls:

```sh
.venv/bin/python tests/acceptance/self_check.py
.venv/bin/python tests/acceptance/test_live_standalone.py -v
```

The self-check accepts a hand-written reference in a path containing spaces, then replaces sqrt(d_key) with d_key and verifies rejection.
Do not supply `self_check.py` or its reference implementation as generation context.
Launcher tests use fake coding CLIs and prove result recording, failure recording, evidence preservation, and that generated reproduction commands remain unexecuted.

This small fixture does not establish Transformer training quality, published paper metrics, auxiliary-stage live compatibility, nested host compatibility, or Super Board integration.
Verify those separately when required by the calling project.
