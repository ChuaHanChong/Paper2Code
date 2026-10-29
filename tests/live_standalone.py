#!/usr/bin/env python3
"""Generate an attention project through a real CLI without executing generated code."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
PROVIDER_CREDENTIALS = ('OPENAI_API_KEY', 'ANTHROPIC_API_KEY', 'ANTHROPIC_AUTH_TOKEN', 'CLAUDE_CODE_OAUTH_TOKEN')


def main() -> int:
    """Run opt-in generation and preserve its outcome and raw diagnostic logs."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--backend', required=True, choices=['codex', 'claude'])
    parser.add_argument('--paper-format', required=True, choices=['JSON', 'LaTeX'])
    parser.add_argument('--output-dir', required=True, type=Path)
    parser.add_argument('--timeout', required=True, type=float, help='Per-stage seconds, chosen from measured host runtimes.')
    parser.add_argument('--model')
    args = parser.parse_args()
    if not math.isfinite(args.timeout) or args.timeout <= 0:
        parser.error('--timeout must be a positive finite number')
    output = args.output_dir.resolve()
    if output.exists() and (not output.is_dir() or any(output.iterdir())):
        parser.error('--output-dir must be absent or empty; existing evidence is never overwritten')
    output.mkdir(parents=True, exist_ok=True)
    fixture = ROOT / 'tests/acceptance' / ('attention.json' if args.paper_format == 'JSON' else 'attention.tex')
    command = [sys.executable, str(ROOT / 'codes/pipeline.py'), '--backend', args.backend,
               '--paper_format', args.paper_format, '--paper_name', 'Tiny Scaled Dot Product Attention',
               '--input', str(fixture), '--timeout', str(args.timeout), '--output_dir', str(output / 'artifacts'),
               '--output_repo_dir', str(output / 'project')]
    if args.model:
        command += ['--model', args.model]
    environment = {key: value for key, value in os.environ.items() if key not in PROVIDER_CREDENTIALS}
    started = datetime.now(timezone.utc).isoformat()
    result = subprocess.run(command, cwd=ROOT, env=environment, capture_output=True, text=True, check=False)
    (output / 'generation.stdout.log').write_text(result.stdout, encoding='utf-8')
    (output / 'generation.stderr.log').write_text(result.stderr, encoding='utf-8')
    error = None
    try:
        pipeline_result = json.loads(result.stdout)
        if not isinstance(pipeline_result, dict):
            raise ValueError('pipeline result must be an object')
    except (ValueError, json.JSONDecodeError) as failure:
        pipeline_result = None
        error = f'pipeline returned no valid result object: {failure}'
    generated = result.returncode == 0 and pipeline_result is not None and pipeline_result.get('status') == 'completed'
    summary = {'status': 'generated' if generated else 'failed', 'backend': args.backend,
               'paper_format': args.paper_format, 'model': args.model, 'command': command,
               'started_at': started, 'finished_at': datetime.now(timezone.utc).isoformat(),
               'fixture_sha256': hashlib.sha256(fixture.read_bytes()).hexdigest(),
               'pipeline_returncode': result.returncode, 'pipeline_result': pipeline_result,
               'generated_code_executed': False, 'error': error}
    (output / 'generation.json').write_text(json.dumps(summary, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(summary))
    return 0 if generated else 1


if __name__ == '__main__':
    raise SystemExit(main())
