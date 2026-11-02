# PaperCoder stage contracts

| Stage | Inputs | Outputs and consumers |
| --- | --- | --- |
| `codes/0_pdf_process.py` (separate script) | GROBID JSON | Cleaned JSON for the stages below. |
| `planning` | Paper JSON or LaTeX, explicit history | Four named records: overview, architecture, task list, YAML config. |
| `extract` | Named planning records | Config, architecture/task artifacts, validated task list for analysis/coding. |
| `analyzing` | Paper, three planning outputs, YAML config, file description | Per-file analysis consumed by coding. |
| `coding` | Paper, plan/design/tasks, config, analysis, previous code | Validated candidate files, written after all generation succeeds. |
| `reproduction` | Config and generated sources | Reproduction script artifact; not automatically executed. |

All inference stages share `run_stage`; no provider response object crosses that interface.
OpenAI-shaped response dumps, price/token logging, and vLLM entry points are removed rather than emulated.
Fixed conversation indexes are replaced by named stage records; consumers migrate together.
The interface is `codes/pipeline.py --stage`.
