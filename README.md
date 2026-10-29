# 📄 Paper2Code: Automating Code Generation from Scientific Papers in Machine Learning

**Minju Seo, Jinheon Baek†, Seongyun Lee, and Sung Ju Hwang†** († denotes equal advising)
International Conference on Learning Representations (ICLR), 2026
📄 [Read the paper](https://arxiv.org/abs/2504.17192)

![PaperCoder Overview](./assets/papercoder_overview.png)

PaperCoder is the system introduced in Paper2Code for generating code repositories from papers.

This fork runs PaperCoder's full paper-to-project workflow through authenticated Codex or Claude Code command-line sessions.
The four planning substeps, per-file analysis, sequential coding, reproduction script generation, name refinement, debugging, and reference-free/reference-based evaluation remain available.
Direct model SDKs, provider key configuration, model-specific price estimates, and the duplicate GPU inference implementation have been removed.
Inference still uses network access and your CLI account's usage allowance.

## Install

Python 3.10 or later and a current authenticated `codex` or `claude` executable are required.

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
codex login
# Or authenticate Claude Code with: claude auth login
```

Generation uses a fresh session per stage with the complete role-labelled conversation supplied explicitly.
Codex runs in a read-only scratch directory with command tools disabled; Claude uses safe mode with built-in tools and MCP disabled while retaining subscription login.
PaperCoder writes only validated artifacts and generated files itself; it does not execute generated scripts or create commits, PRs, or merges.
Do not use Claude bare mode: it does not use subscription authentication.
An inherited nested-session guard is preserved; a rejected nested launch is a failed stage requiring a supported external launcher.

## Run the full workflow

Use a JSON paper (the bundled cleaned GROBID-compatible example) or LaTeX source.
Raw PDF conversion remains an external preprocessing step using [s2orc-doc2json](https://github.com/allenai/s2orc-doc2json); `codes/0_pdf_process.py` can clean its JSON.
Inference stages require an explicit `--backend` and a positive finite `--timeout`, validated before CLI calls or output writes.
Choose that per-stage timeout from measured fixture runtimes on your host; zero, negative, NaN, and infinite budgets are rejected.
An explicitly supplied `--model` must contain non-whitespace text; model availability is checked by the selected CLI.

```bash
.venv/bin/python codes/pipeline.py \
  --backend codex \
  --timeout "$MEASURED_STAGE_TIMEOUT" \
  --paper_name Transformer \
  --paper_format JSON \
  --input examples/Transformer_cleaned.json \
  --output_dir outputs/Transformer \
  --output_repo_dir outputs/Transformer_repo
```

Use `--backend claude` for Claude Code, `--model MODEL` to select an available model, or `--paper_format LaTeX --input examples/Transformer_cleaned.tex` for LaTeX.
An unavailable backend or model fails explicitly; providers never switch silently.
Model-provider key/token environment variables are omitted from child inference processes so saved CLI authentication is used.
User policy and managed settings remain authoritative.

`bash scripts/run.sh codex "$MEASURED_STAGE_TIMEOUT"` and `run_latex.sh` run the bundled examples.
Set `PYTHON` to the virtual environment interpreter when using those shell entry points.
The old GPU inference scripts and `--gpt_version` option are removed; migrate to `--backend` and optional `--model`.

The command emits one JSON result on stdout; stage progress goes to stderr.
`run.json` records completion/failure, the current stage, completed stages, backend/model selection, CLI version, source revision, input hash, and artifact paths.
Inspect the manifest and exit status; generated files are not evidence that the run completed.
Full runs (`--stage all`, the default) require both artifact and project destinations to be absent or empty.
An occupied destination is rejected before directory creation, CLI version checks, inference, or artifact writes, preserving the earlier `run.json` and generated project.
Use fresh destinations for another full run; explicit single-stage commands can reuse the required preceding artifacts and retain their existing per-stage validation.

## Artifacts and stage entry points

- `stages/`: provider-neutral records containing stage, backend/model, CLI version, input hash, and validated output.
- `planning_trajectories.json`: explicit planning history; named stage records replace fixed conversation positions as the authoritative interface.
- `planning_config.yaml`, `planning_artifacts/`, `task_list.json`: validated planning outputs.
- `analyzing_artifacts/` and `coding_artifacts/`: per-file evidence, retaining nested filenames.
- Output project: `config.yaml`, generated implementation files, and `reproduce.sh`.

`--stage planning|extract|analyzing|coding|reproduction|refinement|debugging|evaluation` runs an individual stage.
The original numbered Python entry points select their matching stage and accept the same backend, timeout, input, and output arguments.
Extraction requires existing planning records, invokes no CLI, and may omit backend and timeout options through either entry point.
Validation follows the selected `--stage`, so overriding an extraction entry point to an inference stage requires explicit backend and timeout options.
Later stages require their preceding artifacts.

Optional name refinement requires `--stage refinement` plus `--lookup_file` containing a JSON name-to-ID mapping, or install `requirements-lookup.txt` to search Hugging Face.
Debugging requires `--stage debugging --error_file_name ERROR_LOG --output_repo_dir PROJECT`; missing/ambiguous patch targets fail before mutation, and backups preserve originals.
Evaluation uses `--stage evaluation --eval_type ref_free|ref_based --generated_n COUNT --target_repo_dir PROJECT`; reference-based evaluation also requires `--gold_repo_dir REFERENCE`.
Evaluation defaults to eight samples, as upstream; pass `--generated_n 1` for a smoke test.
For evaluation, an explicit `--target_repo_dir` takes precedence over `--output_repo_dir`.
`--papercoder` restricts target code to the planned task files and uses `planning_config.yaml` from the artifact directory; without it, all supported source files in the target are evaluated.
Each evaluation sample is a separate CLI call; failures are counted separately from valid scores.
Evaluation is model critique, not a substitute for executable acceptance tests or proof of published scientific results.

## Verify

```bash
.venv/bin/python -m unittest discover -s tests -v
```

Offline tests exercise the public command using local fake CLI executables.
For opt-in live checks, see [the standalone acceptance instructions](tests/acceptance/README.md).
Verify the backend, input format, generated behavior, and nested-launch path you intend to use separately from the offline tests.

## Paper2Code benchmark datasets

The upstream benchmark is available on [Hugging Face](https://huggingface.co/datasets/iaminju/paper2code), with its [dataset description](https://github.com/going-doer/Paper2Code/tree/main/data/paper2code) and methodology in Section 4.1 of the paper.
Published benchmark results describe the original PaperCoder experiments, not verified results for this CLI fork.

## License and provenance

Apache-2.0; retain [LICENSE](LICENSE) and upstream notices.
Original prompts and workflow semantics are retained in `codes/prompts.py`.
