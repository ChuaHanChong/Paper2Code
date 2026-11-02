"""Pick the OpenAI API or an authenticated Codex or Claude Code CLI as the chat client."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace

API_KEYS = ('OPENAI_API_KEY', 'ANTHROPIC_API_KEY', 'ANTHROPIC_AUTH_TOKEN', 'CLAUDE_CODE_OAUTH_TOKEN')  # Use the saved CLI login, never bill a key.
INSTRUCTION = 'Complete the final request in this conversation. Reply with only the requested content. Do not call tools, edit files, or execute code.\n'


def make_client():
    """Return the client selected by PAPER2CODE_BACKEND: openai (default), codex or claude."""
    backend = os.environ.get('PAPER2CODE_BACKEND', 'openai')
    if backend == 'openai':
        from openai import OpenAI
        return OpenAI(api_key=os.environ['OPENAI_API_KEY'])
    if backend not in ('codex', 'claude'):
        raise ValueError(f'PAPER2CODE_BACKEND must be openai, codex or claude, not {backend!r}')
    return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=lambda **request: create(backend, **request))))


def create(backend: str, messages: list, n: int = 1, **_ignored) -> SimpleNamespace:
    """Return n CLI replies shaped like an OpenAI completion, without usage data; the model comes from PAPER2CODE_MODEL."""
    texts = [run_cli(backend, messages) for _ in range(n)]
    choices = [{'message': {'role': 'assistant', 'content': text}} for text in texts]
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(**choice['message'])) for choice in choices],
        model_dump_json=lambda: json.dumps({'choices': choices}),
    )


def run_cli(backend: str, messages: list) -> str:
    """Run one fresh read-only CLI session and return its text reply."""
    environment = {key: value for key, value in os.environ.items() if key not in API_KEYS}
    model = os.environ.get('PAPER2CODE_MODEL')
    prompt = INSTRUCTION + json.dumps(messages, ensure_ascii=False)
    with tempfile.TemporaryDirectory(prefix='paper2code-') as scratch:
        output = Path(scratch) / 'reply.txt'
        if backend == 'codex':
            environment['CODEX_SQLITE_HOME'] = scratch  # A lane sandbox cannot write the global state database.
            # https://learn.chatgpt.com/docs/non-interactive-mode: -o is the final message, not JSONL events.
            command = ['codex', 'exec', '--ignore-user-config', '--ephemeral', '--skip-git-repo-check', '--sandbox', 'read-only', '-c', 'approval_policy="never"', '-c', 'features.shell_tool=false', '-c', 'features.apps=false', '-c', 'features.hooks=false', '-c', 'features.multi_agent=false', '-c', 'features.remote_plugin=false', '--disable', 'view_image', '-c', 'web_search="disabled"', '--output-last-message', str(output)]
        else:
            # https://code.claude.com/docs/en/headless: safe mode keeps the saved login; bare mode does not.
            command = ['claude', '--safe-mode', '--restricted', '--tools', '', '--strict-mcp-config', '--permission-mode', 'dontAsk', '--permission-prompts', 'none', '--no-session-persistence', '-p', '--output-format', 'json']
        if model:
            command += ['--model', model]
        if backend == 'codex':
            command.append('-')
        result = subprocess.run(command, input=prompt, cwd=scratch, env=environment, capture_output=True, text=True)
        if result.returncode:
            raise RuntimeError(f'{backend} exited {result.returncode}: {result.stderr[-2000:] or result.stdout[-2000:]}')
        if backend == 'codex':
            return output.read_text(encoding='utf-8')
        reply = json.loads(result.stdout)
        if reply.get('is_error') or not isinstance(reply.get('result'), str):
            raise RuntimeError(f'claude returned no reply: {result.stdout[-2000:]}')
        return reply['result']
