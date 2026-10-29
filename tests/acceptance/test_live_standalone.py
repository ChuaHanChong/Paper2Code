"""Check the live launcher with fake CLIs instead of making model calls."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]


class LiveStandaloneTests(unittest.TestCase):
    """Exercise the public generation-only command and its recorded outcomes."""

    def test_generation_records_results_without_executing_reproduction(self) -> None:
        """Record both transports while leaving a generated command unexecuted."""
        for backend, paper_format in (('codex', 'JSON'), ('claude', 'LaTeX')):
            with self.subTest(backend=backend), tempfile.TemporaryDirectory(prefix='live fixture ') as temporary:
                base = Path(temporary)
                binaries = base / 'bin'
                binaries.mkdir()
                fake = binaries / backend
                fake.write_text((ROOT / 'tests/fixtures/fake_agent.py').read_text())
                fake.chmod(0o755)
                output = base / 'run'
                marker = base / 'generated-command-was-executed'
                overrides = {'reproduction': f'```bash\n#!/bin/sh\ntouch "{marker}"\n```'}
                environment = dict(os.environ, PATH=str(binaries) + os.pathsep + os.environ['PATH'],
                                   PAPER2CODE_FAKE_OUTPUTS=json.dumps(overrides), OPENAI_API_KEY='not-a-real-key')
                command = [sys.executable, str(ROOT / 'tests/live_standalone.py'), '--backend', backend,
                           '--paper-format', paper_format, '--output-dir', str(output), '--timeout', '10']
                result = subprocess.run(command, env=environment, capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                summary = json.loads((output / 'generation.json').read_text())
                self.assertEqual(summary['status'], 'generated')
                self.assertEqual(summary['pipeline_result']['status'], 'completed')
                self.assertTrue((output / 'project/reproduce.sh').is_file())
                self.assertTrue((output / 'generation.stderr.log').is_file())
                self.assertFalse(marker.exists(), 'the generation launcher executed generated code')
                self.assertNotIn('not-a-real-key', (output / 'generation.json').read_text())
                repeated = subprocess.run(command, env=environment, capture_output=True, text=True)
                self.assertNotEqual(repeated.returncode, 0)
                self.assertEqual(json.loads((output / 'generation.json').read_text())['status'], 'generated')

    def test_generation_failure_is_recorded_as_failure(self) -> None:
        """Preserve a failed stage and its logs without reporting successful generation."""
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            fake = base / 'codex'
            fake.write_text((ROOT / 'tests/fixtures/fake_agent.py').read_text())
            fake.chmod(0o755)
            output = base / 'run'
            result = subprocess.run([sys.executable, str(ROOT / 'tests/live_standalone.py'), '--backend', 'codex',
                                     '--paper-format', 'JSON', '--output-dir', str(output), '--timeout', '10'],
                                    env=dict(os.environ, PATH=str(base) + os.pathsep + os.environ['PATH'],
                                             PAPER2CODE_FAIL_STAGE='planning.overview'), capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            summary = json.loads((output / 'generation.json').read_text())
            self.assertEqual(summary['status'], 'failed')
            self.assertEqual(summary['pipeline_result']['stage'], 'planning.overview')
            self.assertTrue((output / 'generation.stderr.log').read_text())
            self.assertFalse((output / 'project').exists())


if __name__ == '__main__':
    unittest.main()
