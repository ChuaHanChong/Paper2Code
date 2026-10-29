"""Exercise the public CLI stage interface with local fake executables."""
import json
import signal
import time
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'codes'))
from cli_runner import run_stage, StageError

SCHEMA = {'type': 'object', 'properties': {'text': {'type': 'string'}}, 'required': ['text'], 'additionalProperties': False}

class CliRunnerTests(unittest.TestCase):
    """Check real subprocess I/O rather than mocking stage internals."""

    def test_both_backends_return_the_validated_artifact(self) -> None:
        """Accept the backend-specific result only through the common stage interface."""
        with tempfile.TemporaryDirectory(prefix='paper coder ') as temporary:
            root = Path(temporary)
            executable = root / 'fake'
            executable.write_text('#!/usr/bin/env python3\nimport json,pathlib,sys\na=sys.argv[1:]\np=sys.stdin.read()\nassert "user" in p and "hello" in p\nr={"text":"verified"}\nif "--output-last-message" in a:\n pathlib.Path(a[a.index("--output-last-message")+1]).write_text(json.dumps(r))\n print("event noise")\nelse:\n print(json.dumps({"is_error":False,"structured_output":r}))\n')
            executable.chmod(0o755)
            for backend in ('codex', 'claude'):
                (root / backend).symlink_to(executable)
            with patch.dict(os.environ, {'PATH': str(root) + os.pathsep + os.environ['PATH']}):
                for backend in ('codex', 'claude'):
                    with self.subTest(backend=backend):
                        self.assertEqual(run_stage(backend, [{'role':'user','content':'hello'}], SCHEMA, root, 10), {'text':'verified'})


    def run_fake(self, backend: str, code: str, timeout: float = 10) -> dict:
        """Run a supplied fake executable through the public stage interface."""
        with tempfile.TemporaryDirectory(prefix='paper coder ') as temporary:
            root = Path(temporary)
            executable = root / backend
            executable.write_text('#!/usr/bin/env python3\n' + code)
            executable.chmod(0o755)
            with patch.dict(os.environ, {'PATH': str(root) + os.pathsep + os.environ['PATH']}):
                return run_stage(backend, [{'role':'user','content':'hello'}], SCHEMA, root, timeout)

    def test_failures_never_return_a_successful_artifact(self) -> None:
        """Reject process, envelope, schema, and output failures for both transports."""
        cases = [
            ('codex', 'import sys; sys.exit(7)', 'exited 7'),
            ('codex', 'print("events only")', 'missing or malformed'),
            ('codex', 'import pathlib,sys; a=sys.argv; pathlib.Path(a[a.index("--output-last-message")+1]).write_text("not json")', 'malformed'),
            ('claude', "print('{\"result\":\"no schema\"}')", 'structured_output'),
            ('claude', "print('{\"is_error\":true,\"structured_output\":{\"text\":\"x\"}}')", 'structured_output'),
            ('claude', "print('{\"structured_output\":{\"text\":3}}')", 'expected string'),
            ('claude', "print('{\"structured_output\":{\"text\":\"x\",\"extra\":1}}')", 'unexpected fields'),
        ]
        for backend, code, message in cases:
            with self.subTest(backend=backend, message=message):
                with self.assertRaisesRegex(StageError, message):
                    self.run_fake(backend, code)

    def test_provider_credentials_are_not_forwarded(self) -> None:
        """Use saved CLI login instead of inherited provider key or token variables."""
        code = 'import json,os\nassert all(k not in os.environ for k in ("OPENAI_API_KEY","ANTHROPIC_API_KEY","ANTHROPIC_AUTH_TOKEN","CLAUDE_CODE_OAUTH_TOKEN"))\nprint(json.dumps({"structured_output":{"text":"saved login"}}))'
        keys = {key:'test-secret' for key in ('OPENAI_API_KEY','ANTHROPIC_API_KEY','ANTHROPIC_AUTH_TOKEN','CLAUDE_CODE_OAUTH_TOKEN')}
        with patch.dict(os.environ, keys):
            self.assertEqual(self.run_fake('claude', code), {'text':'saved login'})

    def test_generation_permissions_and_isolation_reach_each_executable(self) -> None:
        """Require the actual subprocess argv to enforce the generation-only contract."""
        codex = """import json,pathlib,sys,os
a=sys.argv[1:]
assert '--ignore-user-config' in a and '--ephemeral' in a and '--skip-git-repo-check' in a
assert a[a.index('--sandbox')+1]=='read-only'
assert '--ignore-rules' not in a
for setting in ('approval_policy=\"never\"','features.shell_tool=false','features.apps=false','features.hooks=false','features.multi_agent=false','features.remote_plugin=false','web_search=\"disabled\"'):
 assert any(a[i]=='-c' and a[i+1]==setting for i in range(len(a)-1)),setting
assert any(a[i]=='--disable' and a[i+1]=='view_image' for i in range(len(a)-1))
assert not any('dangerously' in value for value in a)
assert pathlib.Path.cwd().name.startswith('paper2code-stage-')
assert '--output-schema' in a and a[-1]=='-'
assert 'hello' in sys.stdin.read()
pathlib.Path(a[a.index('--output-last-message')+1]).write_text(json.dumps({'text':'safe'}))
"""
        claude = """import json,pathlib,sys
a=sys.argv[1:]
for flag in ('--safe-mode','--restricted','--strict-mcp-config','--no-session-persistence','-p','--json-schema'):
 assert flag in a,flag
assert a[a.index('--tools')+1]==''
assert a[a.index('--permission-mode')+1]=='dontAsk'
assert a[a.index('--permission-prompts')+1]=='none'
assert a[a.index('--output-format')+1]=='json'
assert '--bare' not in a and not any('dangerously' in value for value in a)
assert pathlib.Path.cwd().name.startswith('paper2code-stage-')
assert 'hello' in sys.stdin.read()
print(json.dumps({'structured_output':{'text':'safe'}}))
"""
        for backend, code in (('codex',codex),('claude',claude)):
            with self.subTest(backend=backend):
                self.assertEqual(self.run_fake(backend,code),{'text':'safe'})

    def test_missing_executable_is_actionable(self) -> None:
        """Fail immediately when the selected CLI is absent."""
        with tempfile.TemporaryDirectory() as temporary:
            with patch.dict(os.environ, {'PATH': temporary}):
                with self.assertRaisesRegex(StageError, 'executable unavailable'):
                    run_stage('codex', [{'role':'user','content':'hello'}], SCHEMA, Path(temporary), 10)

    def test_timeout_is_an_explicit_failure(self) -> None:
        """Stop an unresponsive stage using a caller-supplied test deadline."""
        with self.assertRaisesRegex(StageError, 'timed out'):
            self.run_fake('claude', 'import time; time.sleep(60)', timeout=0.05)

    def test_controller_sigterm_reaps_inference_descendants(self) -> None:
        """Reap a launched process group when the controller receives termination."""
        import subprocess
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fake = root / 'claude'
            pidfile = root / 'child.pid'
            fake.write_text('#!/usr/bin/env python3\nimport os,pathlib,subprocess,time\np=subprocess.Popen(["sleep","60"])\npathlib.Path(os.environ["CHILD_PID_FILE"]).write_text(str(p.pid))\ntime.sleep(60)\n')
            fake.chmod(0o755)
            source = 'from pathlib import Path; from cli_runner import run_stage; run_stage("claude",[{"role":"user","content":"x"}],'+repr(SCHEMA)+',Path('+repr(str(root))+'),60)'
            process = subprocess.Popen([sys.executable,'-c',source],env={**os.environ,'PYTHONPATH':str(Path(__file__).resolve().parents[1]/'codes'),'PATH':str(root)+os.pathsep+os.environ['PATH'],'CHILD_PID_FILE':str(pidfile)},stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
            # The ten-second readiness bound protects the test against a failed fake startup.
            deadline = time.monotonic()+10
            while not pidfile.exists() and process.poll() is None and time.monotonic()<deadline:
                time.sleep(0.01)
            self.assertTrue(pidfile.exists())
            descendant = int(pidfile.read_text())
            process.send_signal(signal.SIGTERM)
            process.communicate(timeout=10)
            with self.assertRaises(ProcessLookupError):
                os.kill(descendant,0)

if __name__ == '__main__':
    unittest.main()
