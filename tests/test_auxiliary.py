"""Exercise auxiliary capabilities through the public standalone command."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class AuxiliaryTests(unittest.TestCase):
    """Check files and result manifests produced by each public stage."""

    def test_refinement_debugging_and_evaluation_work_for_both_hosts(self) -> None:
        """Retain all auxiliary behavior without SDK response assumptions."""
        for backend in ('codex', 'claude'):
            with self.subTest(backend=backend), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                binaries = root / 'bin'
                binaries.mkdir()
                executable = binaries / backend
                executable.write_text((ROOT / 'tests/fixtures/fake_agent.py').read_text())
                executable.chmod(0o755)
                env = dict(os.environ, PATH=str(binaries) + os.pathsep + os.environ['PATH'])
                output = root / 'output'
                output.mkdir()
                project = root / 'project'
                project.mkdir()
                (output / 'planning_config.yaml').write_text('model: example-model\n')
                lookup = root / 'lookup.json'
                lookup.write_text(json.dumps({'example-model': 'owner/model'}))
                paper = root / 'paper.json'
                paper.write_text('{"title":"Affine transform","body":"f(x)=2*x+1"}')
                error = root / 'error.txt'
                error.write_text('transform(3) returned 0 instead of 7')
                (project / 'model.py').write_text('def transform(x):\n    return 0\n')
                base = [sys.executable, str(ROOT / 'codes/pipeline.py'), '--backend', backend, '--timeout', '10', '--output_dir', str(output), '--output_repo_dir', str(project)]
                result = subprocess.run([*base, '--stage', 'refinement', '--lookup_file', str(lookup)], env=env, capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
                self.assertEqual((output / 'planning_config.yaml').read_text(), 'model: owner/model\n')
                self.assertEqual((output / 'planning_config.yaml.bak').read_text(), 'model: example-model\n')
                result = subprocess.run([*base, '--stage', 'debugging', '--error_file_name', str(error)], env=env, capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
                self.assertIn('return 2*x+1', (project / 'model.py').read_text())
                self.assertIn('return 0', (project / 'model.py.001.bak').read_text())
                (project / 'plot.png').write_bytes(bytes([137, 80, 78, 71, 255]))
                for mode in ('ref_free', 'ref_based'):
                    result = subprocess.run([*base, '--stage', 'evaluation', '--input', str(paper), '--generated_n', '1', '--eval_type', mode, '--gold_repo_dir', str(project)], env=env, capture_output=True, text=True)
                    self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
                    record = json.loads((output / f'evaluation_{mode}.json').read_text())
                    self.assertEqual(record['eval_result']['score'], 5)
                    self.assertEqual(record['eval_result']['valid_n'], 1)
                    self.assertEqual(record['eval_result']['failed_n'], 0)


    def test_malformed_debugging_never_partially_changes_files(self) -> None:
        """Reject a bad second patch before applying an otherwise valid first patch."""
        patch_text = 'Filename: model.py\n<<<<<<< SEARCH\n    return 0\n=======\n    return 7\n>>>>>>> REPLACE\nFilename: missing.py\n<<<<<<< SEARCH\nx\n=======\ny\n>>>>>>> REPLACE'
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            binaries = root / 'bin'
            binaries.mkdir()
            executable = binaries / 'codex'
            executable.write_text((ROOT / 'tests/fixtures/fake_agent.py').read_text())
            executable.chmod(0o755)
            project = root / 'project'
            project.mkdir()
            original = 'def transform(x):\n    return 0\n'
            (project / 'model.py').write_text(original)
            error = root / 'error.txt'
            error.write_text('bad result')
            result = subprocess.run([sys.executable, str(ROOT / 'codes/pipeline.py'), '--backend', 'codex', '--timeout', '10', '--output_dir', str(root / 'output'), '--output_repo_dir', str(project), '--stage', 'debugging', '--error_file_name', str(error)], env=dict(os.environ, PATH=str(binaries) + os.pathsep + os.environ['PATH'], PAPER2CODE_FAKE_OUTPUTS=json.dumps({'debugging': patch_text})), capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual((project / 'model.py').read_text(), original)
            self.assertFalse((project / 'model.py.001.bak').exists())

    def test_evaluation_records_failed_samples_without_fabricating_scores(self) -> None:
        """Keep one valid score and one failed independent inference call distinct."""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            binaries = root / 'bin'
            binaries.mkdir()
            executable = binaries / 'codex'
            executable.write_text((ROOT / 'tests/fixtures/fake_agent.py').read_text())
            executable.chmod(0o755)
            project = root / 'project'
            project.mkdir()
            (project / 'model.py').write_text('def transform(x):\n    return 2*x+1\n')
            paper = root / 'paper.json'
            paper.write_text('{"title":"Affine transform"}')
            output = root / 'output'
            result = subprocess.run([sys.executable, str(ROOT / 'codes/pipeline.py'), '--backend', 'codex', '--timeout', '10', '--output_dir', str(output), '--output_repo_dir', str(project), '--stage', 'evaluation', '--input', str(paper), '--generated_n', '2'], env=dict(os.environ, PATH=str(binaries) + os.pathsep + os.environ['PATH']), capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            record = json.loads((output / 'evaluation_ref_free.json').read_text())
            self.assertEqual(record['eval_result'], {'score': 5.0, 'valid_n': 1, 'failed_n': 1})
            self.assertEqual([sample['sample'] for sample in record['samples']], [0])
            self.assertEqual([sample['sample'] for sample in record['failures']], [1])


    def test_refinement_replaces_only_whole_yaml_values(self) -> None:
        """Preserve embedded model-name substrings and nested model or dataset fields."""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            binaries = root / 'bin'
            binaries.mkdir()
            executable = binaries / 'codex'
            executable.write_text((ROOT / 'tests/fixtures/fake_agent.py').read_text())
            executable.chmod(0o755)
            output = root / 'output'
            output.mkdir()
            (output / 'planning_config.yaml').write_text('model:\n  name: example-model\ndataset:\n  name: example-data\ntokenizer: custom-example-model\n')
            # Only the optional external lookup interface is replaced, not Paper2Code internals.
            (root / 'huggingface_hub.py').write_text('class HfApi:\n def list_models(self, **kwargs):\n  assert kwargs["search"] == "example-model"\n  return [type("Result", (), {"id": "owner/model"})()]\n def list_datasets(self, **kwargs):\n  assert kwargs["search"] == "example-data"\n  return [type("Result", (), {"id": "owner/dataset"})()]\n')
            result = subprocess.run([sys.executable, str(ROOT / 'codes/pipeline.py'), '--backend', 'codex', '--timeout', '10', '--output_dir', str(output), '--stage', 'refinement'], env=dict(os.environ, PATH=str(binaries) + os.pathsep + os.environ['PATH'], PYTHONPATH=str(root) + os.pathsep + os.environ.get('PYTHONPATH', ''), PAPER2CODE_FAKE_OUTPUTS=json.dumps({'refinement': '[\"example-model\",\"example-data\"]'})), capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            import yaml
            refined = yaml.safe_load((output / 'planning_config.yaml').read_text())
            self.assertEqual(refined, {'model': {'name': 'owner/model'}, 'dataset': {'name': 'owner/dataset'}, 'tokenizer': 'custom-example-model'})

    def test_reference_selection_excludes_unselected_gold_files(self) -> None:
        """Keep all target code while limiting reference context to selected safe filenames."""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            binaries = root / 'bin'
            binaries.mkdir()
            executable = binaries / 'codex'
            fixture = ROOT / 'tests/fixtures/fake_agent.py'
            executable.write_text('#!/usr/bin/env python3\nimport io,runpy,sys\nif sys.argv[1:] != ["--version"]:\n raw=sys.stdin.read()\n assert "SELECTED_REFERENCE" in raw and "EXCLUDED_REFERENCE" not in raw and "ALL_TARGET_CODE" in raw\n sys.stdin=io.StringIO(raw)\nrunpy.run_path(' + repr(str(fixture)) + ',run_name="__main__")\n')
            executable.chmod(0o755)
            project = root / 'project'; project.mkdir()
            (project / 'model.py').write_text('# ALL_TARGET_CODE\n')
            reference = root / 'gold'; reference.mkdir()
            (reference / 'selected.py').write_text('# SELECTED_REFERENCE\n')
            (reference / 'excluded.py').write_text('# EXCLUDED_REFERENCE\n')
            selected = root / 'selected.txt'; selected.write_text('selected.py\n')
            paper = root / 'paper.json'; paper.write_text('{"title":"Affine"}')
            result = subprocess.run([sys.executable, str(ROOT / 'codes/pipeline.py'), '--backend', 'codex', '--timeout', '10', '--output_dir', str(root / 'output'), '--output_repo_dir', str(project), '--stage', 'evaluation', '--input', str(paper), '--generated_n', '1', '--eval_type', 'ref_based', '--gold_repo_dir', str(reference), '--selected_file_path', str(selected)], env=dict(os.environ, PATH=str(binaries) + os.pathsep + os.environ['PATH']), capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)


    def test_papercoder_evaluation_selects_planned_sources_and_planning_config(self) -> None:
        """Use only declared project sources and the authoritative planning configuration."""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            binaries = root/'bin'; binaries.mkdir()
            executable = binaries/'codex'
            fixture = ROOT/'tests/fixtures/fake_agent.py'
            executable.write_text('#!/usr/bin/env python3\nimport io,os,runpy,sys\nif sys.argv[1:] != ["--version"]:\n raw=sys.stdin.read()\n assert "PLANNED_SOURCE_MARKER" in raw\n if os.environ["EXPECT_PAPER_SELECTION"]=="yes":\n  assert "UNPLANNED_SOURCE_MARKER" not in raw and "PAPER_CONFIG_MARKER" in raw and "TARGET_CONFIG_MARKER" not in raw\n else:\n  assert "UNPLANNED_SOURCE_MARKER" in raw and "TARGET_CONFIG_MARKER" in raw\n sys.stdin=io.StringIO(raw)\nrunpy.run_path('+repr(str(fixture))+',run_name="__main__")\n')
            executable.chmod(0o755)
            project = root/'project'; project.mkdir()
            (project/'model.py').write_text('# PLANNED_SOURCE_MARKER\n')
            (project/'unplanned.py').write_text('# UNPLANNED_SOURCE_MARKER\n')
            (project/'config.yaml').write_text('value: TARGET_CONFIG_MARKER\n')
            (project/'plot.png').write_bytes(bytes([137,80,78,71,255]))
            output = root/'output'; output.mkdir()
            (output/'planning_config.yaml').write_text('value: PAPER_CONFIG_MARKER\n')
            (output/'task_list.json').write_text(json.dumps({'Task list':['model.py','config.yaml']}))
            paper = root/'paper.json'; paper.write_text('{"title":"Affine"}')
            base = [sys.executable,str(ROOT/'codes/pipeline.py'),'--backend','codex','--timeout','10','--output_dir',str(output),'--target_repo_dir',str(project),'--stage','evaluation','--input',str(paper),'--generated_n','1']
            for selected in (False,True):
                with self.subTest(papercoder=selected):
                    result = subprocess.run([*base,*(['--papercoder'] if selected else [])],env=dict(os.environ,PATH=str(binaries)+os.pathsep+os.environ['PATH'],EXPECT_PAPER_SELECTION='yes' if selected else 'no'),capture_output=True,text=True)
                    self.assertEqual(result.returncode,0,result.stderr+result.stdout)

    def test_explicit_evaluation_target_has_priority_over_generation_directory(self) -> None:
        """Evaluate the explicitly requested repository when both directory flags are supplied."""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            binaries = root/'bin'; binaries.mkdir()
            executable = binaries/'codex'
            fixture = ROOT/'tests/fixtures/fake_agent.py'
            executable.write_text('#!/usr/bin/env python3\nimport io,runpy,sys\nif sys.argv[1:] != ["--version"]:\n raw=sys.stdin.read()\n assert "EXPLICIT_EVALUATION_TARGET" in raw and "UNRELATED_GENERATION_DIRECTORY" not in raw\n sys.stdin=io.StringIO(raw)\nrunpy.run_path('+repr(str(fixture))+',run_name="__main__")\n')
            executable.chmod(0o755)
            project = root/'project'; project.mkdir()
            (project/'model.py').write_text('# EXPLICIT_EVALUATION_TARGET\n')
            generated = root/'generated'; generated.mkdir()
            (generated/'model.py').write_text('# UNRELATED_GENERATION_DIRECTORY\n')
            paper = root/'paper.json'; paper.write_text('{"title":"Affine"}')
            result = subprocess.run([sys.executable,str(ROOT/'codes/pipeline.py'),'--backend','codex','--timeout','10','--output_dir',str(root/'output'),'--output_repo_dir',str(generated),'--target_repo_dir',str(project),'--stage','evaluation','--input',str(paper),'--generated_n','1'],env=dict(os.environ,PATH=str(binaries)+os.pathsep+os.environ['PATH']),capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr+result.stdout)
            self.assertEqual(json.loads(result.stdout)['project_dir'],str(project.resolve()))

if __name__ == '__main__':
    unittest.main()
