"""Check the CLI backends against fake codex and claude executables."""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'codes'))
from cli_client import make_client

FAKE = '''#!/usr/bin/env python3
import json, os, sys
assert not os.environ.get('ANTHROPIC_API_KEY') and not os.environ.get('OPENAI_API_KEY')
assert 'hello' in sys.stdin.read()
if os.environ.get('FAKE_FAIL'):
    sys.exit(3)
if sys.argv[0].endswith('opencode'):
    assert json.loads(os.environ['OPENCODE_CONFIG_CONTENT']) == {'permission': 'deny'}
    print(os.environ.get('FAKE_OPENCODE', json.dumps({'type': 'text', 'part': {'type': 'text', 'text': 'reply'}})))
elif '--output-last-message' in sys.argv:
    open(sys.argv[sys.argv.index('--output-last-message') + 1], 'w').write('reply')
else:
    print(json.dumps({'is_error': False, 'result': 'reply'}))
'''


class CLIClient(unittest.TestCase):
    """Return the OpenAI shape the scripts read, and fail loudly."""

    def setUp(self) -> None:
        """Put fake CLIs first on PATH with API keys set."""
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        for name in ('codex', 'claude', 'opencode'):
            path = Path(directory.name) / name
            path.write_text(FAKE)
            path.chmod(0o755)
        patcher = mock.patch.dict(os.environ, {'PATH': directory.name + os.pathsep + os.environ['PATH'], 'OPENAI_API_KEY': 'x', 'ANTHROPIC_API_KEY': 'x'})
        patcher.start()
        self.addCleanup(patcher.stop)

    def request(self, backend: str, **options):
        """Send one request through the selected backend."""
        with mock.patch.dict(os.environ, {'PAPER2CODE_BACKEND': backend}):
            return make_client().chat.completions.create(model='ignored', reasoning_effort='high', messages=[{'role': 'user', 'content': 'hello'}], **options)

    def test_cli_backends_return_the_openai_shape(self) -> None:
        """Expose choices, n replies and model_dump_json like the API."""
        for backend in ('codex', 'claude', 'opencode'):
            completion = self.request(backend, n=2)
            self.assertEqual(completion.choices[1].message.content, 'reply')
            self.assertEqual(completion.choices[0].message.role, 'assistant')
            self.assertEqual(json.loads(completion.model_dump_json())['choices'][1]['message']['content'], 'reply')

    def test_failure_and_unknown_backend_raise(self) -> None:
        """Never turn a failed CLI or a typo into an empty reply."""
        with mock.patch.dict(os.environ, {'FAKE_FAIL': '1'}), self.assertRaises(RuntimeError):
            self.request('claude')
        with mock.patch.dict(os.environ, {'FAKE_OPENCODE': '{"type":"text","part":{"type":"text","text":"partial"}}\n{"type":"error"}'}), self.assertRaises(RuntimeError):
            self.request('opencode')
        with self.assertRaises(ValueError):
            self.request('gemini')


if __name__ == '__main__':
    unittest.main()
