# CLI conversion evidence

Scope: standalone PaperCoder conversion, implementation phases T0-T2.
Live CLI inference and Super Board integration are separate gates and are not claimed by offline tests.

## Source and contract characterization

Baseline: ba9169978043d5799c8d4f4a0963e6b66a24c2e1.
`CONTRACTS.md` maps all retained entry points and their artifact consumers.
The planning/analysis/coding/reproduction/debug/refinement prompts were extracted into pure functions and compared against AST evaluation of the original expressions before replacing the scripts.
All four planning groups matched the original output byte-for-byte.
The temporary checkout's GitNexus analysis wrote index metadata, but its MCP query still reported the repo unavailable; direct source inspection filled that gap.

## Red and green slices

- `python3 -m unittest discover -s tests -v`: first runner slice failed with `ModuleNotFoundError: cli_runner` before implementation.
- `python3 -m unittest discover -s tests -p test_cli_runner.py -v`: five tests passed after implementation, covering both real subprocess transports, missing/invalid output, credential stripping, timeout, and SIGTERM descendant cleanup.
- `python3 -m unittest discover -s tests -p test_pipeline.py -v`: full workflow fixture failed because `codes/pipeline.py` did not exist before implementing the controller.
- Core/auxiliary tests require the declared PyYAML dependency; their final results are recorded after clean environment installation.

The fake inference outputs are fixed literals for an affine transformation; the tests check generated project artifacts rather than inspecting private pipeline state.
The independent live acceptance fixture is owned separately and is not supplied to the model with its reference implementation.

## Final offline verification

`PYTHONPATH=/Users/chuahanchong/.cache/uv/archive-v0/FY23Kj3KDi1xyAJSd7pUt/lib/python3.13/site-packages .venv/bin/python -m unittest discover -s tests -v`: 14 tests pass.
The existing cached PyYAML package was reused read-only because the parent clean-install process had not completed; a clean dependency install remains a separate environment check.
The suite covers the full core pipeline for both fake backends and both input formats, auxiliary capabilities for both fake backends, path traversal and control-file rejection, failed-stage and existing-file preservation, patch atomicity, exact YAML-value replacement, reference selection, independent evaluation failure accounting, and transport/process failures.
`git diff --check` and Python compilation pass.
The scan for model SDK imports, Chat Completions calls, provider response parsing, old GPT-version flags in runnable sources, and accumulated-cost helpers returns no matches.
The only provider credential names in runnable code explicitly remove those variables from child environments.
No live generation, clean installation, commit, push, submodule addition, or Super Board integration is claimed by these results.

## Independent review corrections

Public regressions reproduced the original `## Code: filename` plus fenced-output format rejection, an artifact-directory symlink escaping the output root, and binary repository files breaking evaluation before inference.
The format parser now accepts only a matching known Code heading and one complete fence, while rejecting mismatched names, mixed prose, multiple fences, and truncation.
Reproduction receives the original paper and approved planning context, with explicit paper constraints taking precedence over generic environment setup suggestions.
All artifact reads and writes validate containment, including planning outputs and the run manifest; symlink regressions cover files and directories.
Repository evaluation restores the upstream source-extension filter and ignores binary assets.
The unsupported `tools.view_image` CLI option was removed after a real Codex probe reported it ignored.
After these fixes, `.venv/bin/python -m unittest discover -s tests -v` passes all 17 tests using the clean environment's installed PyYAML 6.0.3, with no cached-package `PYTHONPATH` needed.
Compilation, whitespace checks, and the runnable-provider-code scan remain clean.
Live backend and Board gates are still separate and not implied by these results.

## Transport permission assertions

A public subprocess fake now asserts the actual Codex read-only/isolated-session configuration and all command/app/hook/plugin/multi-agent/web disables, and the Claude safe-mode/no-tools/strict-MCP/no-prompts contract.
The added test failed because the supported `--disable view_image` flag was absent, then passed after adding that exact installed-feature option.
`.venv/bin/python -m unittest discover -s tests -v`: all 18 tests pass after this delta; compilation and whitespace checks pass.
No other controller, prompt, or auxiliary source changed during this transport correction.

## Retained evaluation semantics

Two public subprocess regressions failed before correcting evaluation behavior: `--papercoder` included unplanned supported source files and the target's stale configuration; an explicit `--target_repo_dir` silently lost to `--output_repo_dir`.
PaperCoder evaluation now validates the planned Task list, selects only its supported non-YAML source files, and appends the authoritative artifact `planning_config.yaml`.
Unrestricted evaluation still includes all supported target sources, while binary assets remain excluded.
For evaluation only, an explicit target directory now takes precedence over the generation output directory.
The full offline suite, including the separately added acceptance-harness tests, passes all 22 tests after these fixes; compilation and whitespace checks pass.
Changed implementation files: `codes/auxiliary.py`, the evaluation-target choice in `codes/pipeline.py`, `tests/test_auxiliary.py`, and README documentation.
No inference runner, prompt builder, or core generation method changed in this correction.


## Durable rerun protection

The durable checkout is `data/.repositories/Paper2Code` in ResearchBrain; the running Transformer experiment uses the separate frozen temporary checkout.
A public regression first reproduced full reruns overwriting completed evidence before failing on existing project files.
The initial durable rerun-protection delta from the frozen Transformer snapshot was four added preflight lines in `Pipeline.run`, before directory creation, CLI version checks, inference, and failed-manifest handling.
The later selected-stage input-validation correction is recorded below.
Full runs reject either occupied artifact or occupied project destinations without changing the earlier manifest or generated files; explicit single-stage reuse remains available.
The regression compares every completed artifact and project file byte-for-byte, directory sets, and CLI-call logs across three occupied-destination combinations, then proves explicit extraction reuse still works.
Artifact-symlink checks use an explicit planning stage so they continue to exercise path containment beyond the new full-run guard.

From the durable checkout, `/private/tmp/researchbrain-paper2code-dev/.venv/bin/python -m unittest discover -s tests -v` passed all 24 offline tests in 14.502 seconds.
An independent core rerun using `-p test_pipeline.py` passed all eight tests in 6.842 seconds.
Compilation and whitespace checks passed.
These checks do not complete the two-backend live standalone matrix or Super Board integration gate.
The additional real Codex JSON run against durable source was still in progress when this entry was written and is not counted here as a pass.


## Selected stage input validation

Public CLI regressions first reproduced explicit zero being replaced by a guessed one-second inference budget, invalid negative or nonfinite budgets reaching output/CLI setup, and extraction entry points overridden to inference without explicit backend/budget choices.
A generic command selecting extraction also incorrectly required inference options.
Validation now follows the actual selected stage before any CLI call or output write; inference requires an explicit backend and positive finite timeout, and explicitly blank or whitespace-only model selectors are rejected.
The nonempty model ID is passed unchanged for CLI availability validation.
Generic and legacy extraction entry points may omit backend and timeout and remain CLI-free while reusing existing planning records.
Absent extraction-only options use deliberately invalid `none`/zero sentinels inside the existing configuration record; these are never inference defaults.
The public tests verify no CLI calls, including version checks, and no output creation for zero, negative, NaN, infinite, missing backend/budget, and blank-model inputs.
The full durable offline suite passes all 26 tests after these changes; compilation and whitespace checks pass.
Only the durable argument-validation/configuration code, its public command tests, and documentation changed; the frozen live checkout, inference runner, prompts, and generation methods remain untouched.

## Final Markdown decoder correction and live recovery

The captured real Transformer README response was complete but used an outer triple Markdown fence containing ordinary inner triple-language fences.
A failing public CLI regression established premature wrapper closure before changing the decoder.
Matching Code headings now identify the requested wrapper, Markdown closes at its final matching fence, and unheaded raw Markdown with ordinary language blocks remains intact.
Strict mismatched-name, sibling-file, mixed-output, and truncated-output rejection remains covered.
Offline public CLI replay of the exact 33,141-character response preserved the full 33,107-byte body, all 30 fence tokens, and SHA-256 `bae5958d71417815681095952000bfe5a6ee17acbcd65f7cb47ece60f612aa87`.
The latest durable suite has 26 passing tests; root independently reran all 10 core pipeline tests.

Real Codex recovery then used 55 hash-verified successful planning/analysis prerequisites from the failed Transformer attempt, followed by 22 fresh coding calls and one fresh reproduction call on the repaired durable source.
The 49 combined real records comprise a staged workflow, not an uninterrupted new `--stage all` pass.
Static checks and 12 independent CPU behavior groups passed; root independently reran all 12 groups.
All 13 production source hashes and 24 candidate source-file hashes remained unchanged during generation and verification.
Preserved evidence is in ResearchBrain `data/.paper2code-verification/2026-10-29/transformer/attempt3-staged/`, including the report, provenance, phase manifests, independent verifier, and results.
The failed uninterrupted attempt remains preserved separately in `transformer/attempt2-failed/`.
No generated setup, training, complete generated pytest suite, dataset/scorer run, or published metrics were verified.
Claude live tests remain pending at the user's instruction until quota resets; submodule addition and Super Board integration remain gated.

## Installed source provenance

Super Board integration exposed copied runtimes inheriting an unrelated parent repository's Git HEAD.
A public subprocess regression reproduced the false revision in a runtime copied beneath a different Git checkout.
The controller now reports a Git revision only when `git rev-parse --show-toplevel` resolves exactly to its own source root; installed copies otherwise report null and their caller supplies installation provenance.
No Board-specific metadata contract was added to the standalone controller.
The new regression passed after the change, and the complete standalone suite passed all 27 tests in 17.306 seconds.
The user subsequently removed Claude verification as an integration gate; actual Claude execution remains unverified.

## Controller-owned filename aliases

A public subprocess regression reproduced uppercase and mixed-case `config.yaml` aliases overwriting the controller's lowercase configuration on case-insensitive macOS while returning completed, and reproduction aliases failing only after candidate writes.
The common task-list boundary now rejects noncanonical case variants of `config.yaml` and `reproduce.sh` before analysis or coding.
The same regression preserves exact canonical configuration and reproduction bytes.
Its focused six-subcase check passes, and the complete standalone suite passes all 28 tests in 19.146 seconds.
Compilation and whitespace checks pass in the durable and nested checkouts; prompts, inference permissions, and generation methods remain unchanged.
Evidence is preserved in ResearchBrain `data/.paper2code-verification/2026-10-29/integration/offline/source-alias-fix/`.
