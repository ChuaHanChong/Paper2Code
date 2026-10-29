"""Run inference stages through authenticated coding-agent CLIs."""
from __future__ import annotations

import json
import math
import os
from pathlib import Path
import signal
import subprocess
import tempfile
from typing import Any


class StageError(RuntimeError):
    """Report a failed or invalid CLI stage."""


def validate_schema(value: Any, schema: dict[str, Any], location: str = 'result') -> None:
    """Validate the JSON-schema subset used by Paper2Code artifacts."""
    kind = schema.get('type')
    types = {'object': dict, 'array': list, 'string': str, 'integer': int, 'number': (int, float), 'boolean': bool, 'null': type(None)}
    if kind not in types or not isinstance(value, types[kind]) or (kind in ('integer', 'number') and isinstance(value, bool)):
        raise StageError(f'{location}: expected {kind}')
    if kind == 'number' and not math.isfinite(value):
        raise StageError(f'{location}: expected finite number')
    if 'enum' in schema and value not in schema['enum']:
        raise StageError(f'{location}: unsupported value')
    if isinstance(value, dict):
        properties = schema.get('properties', {})
        if not set(schema.get('required', [])) <= value.keys():
            raise StageError(f'{location}: missing required fields')
        if schema.get('additionalProperties') is False and value.keys() - properties.keys():
            raise StageError(f'{location}: unexpected fields')
        for key, child in value.items():
            if key in properties:
                validate_schema(child, properties[key], f'{location}.{key}')
    if isinstance(value, list):
        if len(value) < schema.get('minItems', 0):
            raise StageError(f'{location}: too few items')
        for index, child in enumerate(value):
            validate_schema(child, schema['items'], f'{location}[{index}]')
    if isinstance(value, str) and len(value) < schema.get('minLength', 0):
        raise StageError(f'{location}: empty content')


def stop_process(process: subprocess.Popen[str]) -> None:
    """Terminate a stage process group and reap its launcher."""
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    process.communicate()


def run_stage(backend: str, messages: list[dict[str, str]], schema: dict[str, Any], workdir: Path, timeout: float, model: str | None = None) -> dict[str, Any]:
    """Return a validated artifact from one fresh CLI inference session."""
    if backend not in ('codex', 'claude'):
        raise ValueError('backend must be codex or claude')
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError('timeout must be a positive finite number')
    if not messages or any(message.get('role') not in ('system', 'user', 'assistant') or not isinstance(message.get('content'), str) for message in messages):
        raise ValueError('messages must contain role-labelled text')
    workdir = Path(workdir).resolve(strict=True)
    prompt = 'Complete the final request in this explicit conversation. Return only the requested JSON object. Do not call tools, edit files, execute code, or omit context.\n' + json.dumps(messages, ensure_ascii=False)
    environment = {key: value for key, value in os.environ.items() if key not in ('OPENAI_API_KEY', 'ANTHROPIC_API_KEY', 'ANTHROPIC_AUTH_TOKEN', 'CLAUDE_CODE_OAUTH_TOKEN')}
    with tempfile.TemporaryDirectory(prefix='paper2code-stage-') as temporary:
        scratch = Path(temporary)
        schema_path = scratch / 'schema.json'
        output_path = scratch / 'result.json'
        schema_path.write_text(json.dumps(schema), encoding='utf-8')
        if backend == 'codex':
            state_path = scratch / 'state'
            state_path.mkdir()
            environment['CODEX_SQLITE_HOME'] = str(state_path)
            # https://learn.chatgpt.com/docs/non-interactive-mode: -o is the final artifact, not JSONL events.
            command = ['codex', 'exec', '--ignore-user-config', '--ephemeral', '--skip-git-repo-check', '--sandbox', 'read-only', '-c', 'approval_policy="never"', '-c', 'features.shell_tool=false', '-c', 'features.apps=false', '-c', 'features.hooks=false', '-c', 'features.multi_agent=false', '-c', 'features.remote_plugin=false', '--disable', 'view_image', '-c', 'web_search="disabled"', '--output-schema', str(schema_path), '--output-last-message', str(output_path)]
            if model:
                command += ['--model', model]
            command += ['-']
        else:
            # https://code.claude.com/docs/en/headless: safe-mode preserves login; bare mode does not.
            command = ['claude', '--safe-mode', '--restricted', '--tools', '', '--strict-mcp-config', '--permission-mode', 'dontAsk', '--permission-prompts', 'none', '--no-session-persistence', '-p', '--output-format', 'json', '--json-schema', json.dumps(schema)]
            if model:
                command += ['--model', model]
        process = None
        def terminated(signum: int, frame: Any) -> None:
            """Convert termination into cleanup through the stage supervisor."""
            raise StageError(f'{backend} interrupted by signal {signum}')
        previous_handler = signal.getsignal(signal.SIGTERM)
        signal.signal(signal.SIGTERM, terminated)
        try:
            process = subprocess.Popen(command, cwd=scratch, env=environment, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, start_new_session=True)
            stdout, stderr = process.communicate(prompt, timeout=timeout)
        except FileNotFoundError as error:
            raise StageError(f'{backend} executable unavailable') from error
        except subprocess.TimeoutExpired as error:
            if process:
                stop_process(process)
            raise StageError(f'{backend} stage timed out after {timeout:g}s') from error
        except BaseException:
            if process and process.poll() is None:
                stop_process(process)
            raise
        finally:
            signal.signal(signal.SIGTERM, previous_handler)
        if process.returncode:
            raise StageError(f'{backend} exited {process.returncode}: {stderr[-2000:] or stdout[-2000:]}')
        try:
            if backend == 'codex':
                artifact = json.loads(output_path.read_text(encoding='utf-8'))
            else:
                envelope = json.loads(stdout)
                if not isinstance(envelope, dict) or envelope.get('is_error') or 'structured_output' not in envelope:
                    raise StageError('claude returned no successful structured_output')
                artifact = envelope['structured_output']
        except (OSError, json.JSONDecodeError) as error:
            raise StageError(f'{backend} returned missing or malformed JSON output') from error
        validate_schema(artifact, schema)
        return artifact
