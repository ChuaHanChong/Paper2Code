# PaperCoder stage contracts

| Entry point | Inputs | Outputs and consumers |
| --- | --- | --- |
| `0_pdf_process.py` | GROBID JSON | Cleaned JSON for planning, analysis, coding, evaluation. |
| `1_planning.py` | Paper JSON or LaTeX, explicit history | Four named records: overview, architecture, task list, YAML config. |
| `1.1_extract_config.py` | Named planning records | Config, architecture/task artifacts, validated task list for analysis/coding. |
| `2_analyzing.py` | Paper, three planning outputs, YAML config, file description | Per-file analysis consumed by coding. |
| `3_coding.py` | Paper, plan/design/tasks, config, analysis, previous code | Validated candidate files, written after all generation succeeds. |
| `3.1_coding_sh.py` | Config and generated sources | Reproduction script artifact; not automatically executed. |
| `1.2_rag_config.py` | Config, CLI name detection, optional lookup | Backed-up and refined config. |
| `4_debugging.py` | Error log, generated sources | Validated exact SEARCH/REPLACE changes and backups. |
| `eval.py` | Paper, target sources, optional reference, critique prompt | Separate valid/failed samples and aggregate critique results. |

All inference entry points share `run_stage`; no provider response object crosses that interface.
OpenAI-shaped response dumps, price/token logging, and vLLM entry points are removed rather than emulated.
Fixed conversation indexes are replaced by named stage records; consumers migrate together.
The explicit full-run interface is `codes/pipeline.py`; stage wrappers preserve individual entry-point functionality.

Test seams agreed in the implementation plan: public CLI stage runner and complete paper-to-project command, followed by separate live backend and Board integration gates.
