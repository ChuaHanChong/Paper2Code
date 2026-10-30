"""Test paper-to-project behavior with deterministic fake inference."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

KIT = Path(__file__).resolve().parents[1]

class PipelineTests(unittest.TestCase):
    """Observe generated artifacts through the public command."""

    def test_copied_runtime_never_reports_its_parent_repository_revision(self) -> None:
        """Keep unrelated host Git history out of copied runtime provenance."""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            parent = root / 'unrelated-host'
            subprocess.run(['git', 'clone', '--quiet', '--shared', str(KIT), str(parent)], check=True)
            copied = parent / 'copied-runtime'
            shutil.copytree(KIT / 'codes', copied / 'codes', ignore=shutil.ignore_patterns('__pycache__'))
            fake = root / 'codex'
            shutil.copy2(KIT / 'tests/fixtures/fake_agent.py', fake)
            fake.chmod(0o755)
            paper = root / 'paper.json'
            paper.write_text('{"title":"Affine"}')
            environment = {**os.environ, 'PATH': str(root) + os.pathsep + os.environ['PATH']}
            result = subprocess.run([sys.executable, str(copied / 'codes/pipeline.py'), '--backend', 'codex', '--timeout', '10', '--input', str(paper), '--output_dir', str(root / 'artifacts'), '--output_repo_dir', str(root / 'project')], env=environment, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIsNone(json.loads(result.stdout)['paper2code_revision'])

    def test_full_pipeline_for_both_backends_and_formats(self) -> None:
        """Carry planning and analysis context through generated project artifacts."""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fake = root / 'fake'
            fake.write_text((KIT / 'tests/fixtures/fake_agent.py').read_text())
            fake.chmod(0o755)
            for backend in ('codex', 'claude'):
                (root / backend).symlink_to(fake)
                for fmt in ('JSON','LaTeX'):
                    run = root / f'{backend}-{fmt}'
                    run.mkdir()
                    paper = run / 'paper'
                    paper.write_text(json.dumps({'title':'Affine','abstract':'y=2*x+1'}) if fmt == 'JSON' else 'y=2*x+1')
                    result = subprocess.run([sys.executable,str(KIT/'codes/pipeline.py'),'--backend',backend,'--timeout','10','--paper_name','Affine','--paper_format',fmt,'--input',str(paper),'--output_dir',str(run/'artifacts'),'--output_repo_dir',str(run/'project')],capture_output=True,text=True,env={**os.environ,'PATH':str(root)+os.pathsep+os.environ['PATH']})
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual(json.loads(result.stdout)['status'], 'completed')
                    self.assertEqual((run/'project/model.py').read_text(), 'def transform(x):\n    return 2*x+1\n')
                    self.assertTrue((run/'project/reproduce.sh').is_file())
                    self.assertTrue((run/'artifacts/planning_config.yaml').is_file())

    def test_unsafe_tasks_fail_before_project_writes(self) -> None:
        """Reject model-controlled traversal, reserved paths, and canonical duplicates."""
        for filename in ('../escape.py','/escape.py','.git/config','AGENTS.md','nested/../../escape.py','a/./b.py','config.yaml'):
            with self.subTest(filename=filename), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                fake = root/'codex'
                fake.write_text((KIT/'tests/fixtures/fake_agent.py').read_text())
                fake.chmod(0o755)
                paper = root/'paper.json'
                paper.write_text('{"title":"Affine"}')
                tasks = {'Task list':['config.yaml',filename],'Logic Analysis':[[filename,'Return 2*x+1']]}
                env = {**os.environ,'PATH':str(root)+os.pathsep+os.environ['PATH'],'PAPER2CODE_FAKE_OUTPUTS':json.dumps({'planning.tasks':json.dumps(tasks)})}
                result = subprocess.run([sys.executable,str(KIT/'codes/pipeline.py'),'--backend','codex','--timeout','10','--input',str(paper),'--output_dir',str(root/'artifacts'),'--output_repo_dir',str(root/'project')],capture_output=True,text=True,env=env)
                self.assertNotEqual(result.returncode,0,result.stdout)
                self.assertFalse((root/'project').exists())
                self.assertEqual(json.loads((root/'artifacts/run.json').read_text())['status'],'failed')

    def test_controller_owned_task_filenames_require_canonical_case(self) -> None:
        """Reject auto-owned filename aliases before coding while preserving canonical tasks."""
        for filename in ('CONFIG.YAML', 'Config.yaml', 'REPRODUCE.SH', 'Reproduce.sh', 'config.yaml', 'reproduce.sh'):
            with self.subTest(filename=filename), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                fake = root / 'codex'
                shutil.copy2(KIT / 'tests/fixtures/fake_agent.py', fake)
                fake.chmod(0o755)
                paper = root / 'paper.json'
                paper.write_text('{"title":"Affine"}')
                tasks = {'Task list': [filename, 'model.py'], 'Logic Analysis': [[filename, 'Return 2*x+1'], ['model.py', 'Return 2*x+1']]}
                outputs = {'planning.tasks': json.dumps(tasks), 'analysis:' + filename: 'x=3 yields 7, Return 2*x+1', 'coding:' + filename: '```yaml\nwrong: overwritten\n```'}
                environment = {**os.environ, 'PATH': str(root) + os.pathsep + os.environ['PATH'], 'PAPER2CODE_FAKE_OUTPUTS': json.dumps(outputs)}
                result = subprocess.run([sys.executable, str(KIT / 'codes/pipeline.py'), '--backend', 'codex', '--timeout', '10', '--input', str(paper), '--output_dir', str(root / 'artifacts'), '--output_repo_dir', str(root / 'project')], env=environment, capture_output=True, text=True)
                manifest = json.loads((root / 'artifacts/run.json').read_text())
                if filename in ('config.yaml', 'reproduce.sh'):
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual(manifest['status'], 'completed')
                    self.assertEqual((root / 'project/config.yaml').read_text(), 'scale: 2\nbias: 1\n')
                    self.assertEqual((root / 'project/reproduce.sh').read_text(), '#!/bin/sh\npython3 -c "from model import transform; assert transform(3)==7"\n')
                else:
                    self.assertNotEqual(result.returncode, 0, result.stdout)
                    self.assertEqual(manifest['status'], 'failed')
                    self.assertEqual(manifest['stage'], 'planning.tasks')
                    self.assertIn('controller-owned', manifest['error'])
                    self.assertFalse((root / 'project').exists())
                    self.assertFalse((root / 'artifacts/analyzing_artifacts').exists())
                    self.assertFalse((root / 'artifacts/coding_artifacts').exists())

    def test_failed_generation_and_existing_files_are_preserved(self) -> None:
        """Keep existing project files and refuse success on a failed inference stage."""
        for failure in ('coding:model.py','existing'):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                fake = root/'codex'
                fake.write_text((KIT/'tests/fixtures/fake_agent.py').read_text())
                fake.chmod(0o755)
                paper = root/'paper.json'
                paper.write_text('{"title":"Affine"}')
                project = root/'project'
                if failure == 'existing':
                    project.mkdir()
                    (project/'model.py').write_text('user content')
                env = {**os.environ,'PATH':str(root)+os.pathsep+os.environ['PATH'],'PAPER2CODE_FAIL_STAGE':failure}
                result = subprocess.run([sys.executable,str(KIT/'codes/pipeline.py'),'--backend','codex','--timeout','10','--input',str(paper),'--output_dir',str(root/'artifacts'),'--output_repo_dir',str(project)],capture_output=True,text=True,env=env)
                self.assertNotEqual(result.returncode,0)
                self.assertFalse((project/'config.yaml').exists())
                if failure == 'existing':
                    self.assertEqual((project/'model.py').read_text(),'user content')
                else:
                    self.assertFalse(project.exists())

    def test_original_code_headings_and_paper_reproduction_constraints(self) -> None:
        """Accept upstream response examples and pass paper-specific reproduction requirements."""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fake = root/'codex'
            fake.write_text((KIT/'tests/fixtures/fake_agent.py').read_text())
            fake.chmod(0o755)
            paper = root/'paper.json'
            paper.write_text('{"title":"Affine","reproduction":"UNIQUE_REPRODUCTION_CONSTRAINT: print only JSON, no install"}')
            outputs = {'planning.config':'## Code: config.yaml\n```yaml\nscale: 2\nbias: 1\n```', 'coding:model.py':'## Code: model.py\n```python\ndef transform(x):\n    return 2*x+1\n```', 'reproduction':'## Code: reproduce.sh\n```bash\n#!/bin/sh\npython3 -c "from model import transform; assert transform(3)==7"\n```'}
            env = {**os.environ,'PATH':str(root)+os.pathsep+os.environ['PATH'],'PAPER2CODE_FAKE_OUTPUTS':json.dumps(outputs),'PAPER2CODE_REPRODUCTION_CONTEXT':'UNIQUE_REPRODUCTION_CONSTRAINT'}
            result = subprocess.run([sys.executable,str(KIT/'codes/pipeline.py'),'--backend','codex','--timeout','10','--input',str(paper),'--output_dir',str(root/'artifacts'),'--output_repo_dir',str(root/'project')],capture_output=True,text=True,env=env)
            self.assertEqual(result.returncode,0,result.stderr+result.stdout)
            self.assertEqual((root/'project/model.py').read_text(),'def transform(x):\n    return 2*x+1\n')

    def test_artifact_symlink_never_writes_outside_output_directory(self) -> None:
        """Reject preexisting artifact-file and directory symlinks without external writes."""
        for name in ('planning_artifacts','planning_config.yaml','planning_trajectories.json','task_list.json','run.json','stages'):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                fake = root/'codex'
                fake.write_text((KIT/'tests/fixtures/fake_agent.py').read_text())
                fake.chmod(0o755)
                paper = root/'paper.json'
                paper.write_text('{"title":"Affine"}')
                artifacts = root/'artifacts'
                artifacts.mkdir()
                outside = root/'outside'
                outside.mkdir()
                if name in ('planning_artifacts','stages'):
                    (artifacts/name).symlink_to(outside,target_is_directory=True)
                else:
                    (outside/'sentinel').write_text('original')
                    (artifacts/name).symlink_to(outside/'sentinel')
                env = {**os.environ,'PATH':str(root)+os.pathsep+os.environ['PATH']}
                result = subprocess.run([sys.executable,str(KIT/'codes/pipeline.py'),'--backend','codex','--timeout','10','--stage','planning','--input',str(paper),'--output_dir',str(artifacts),'--output_repo_dir',str(root/'project')],capture_output=True,text=True,env=env)
                self.assertNotEqual(result.returncode,0,result.stdout)
                if name in ('planning_artifacts','stages'):
                    self.assertEqual(list(outside.iterdir()),[])
                else:
                    self.assertEqual(list(outside.iterdir()),[outside/'sentinel'])
                    self.assertEqual((outside/'sentinel').read_text(),'original')

    def test_mismatched_or_ambiguous_artifact_formats_fail(self) -> None:
        """Reject incorrect filenames, mixed prose, multiple fences, and truncated artifacts."""
        formats = [
            '## Code: other.yaml\n```yaml\nscale: 2\n```',
            '## Code: config.yaml\n```yaml\nscale: 2\n```\n```yaml\nbias: 1\n```',
            '## Code: config.yaml\nscale: 2',
            'An introduction\n```yaml\nscale: 2\n```',
            '```yaml\nscale: 2',
        ]
        for content in formats:
            with self.subTest(content=content), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                fake = root/'codex'
                fake.write_text((KIT/'tests/fixtures/fake_agent.py').read_text())
                fake.chmod(0o755)
                paper = root/'paper.json'
                paper.write_text('{"title":"Affine"}')
                env = {**os.environ,'PATH':str(root)+os.pathsep+os.environ['PATH'],'PAPER2CODE_FAKE_OUTPUTS':json.dumps({'planning.config':content})}
                result = subprocess.run([sys.executable,str(KIT/'codes/pipeline.py'),'--backend','codex','--timeout','10','--input',str(paper),'--output_dir',str(root/'artifacts'),'--output_repo_dir',str(root/'project')],capture_output=True,text=True,env=env)
                self.assertNotEqual(result.returncode,0,result.stdout)
                self.assertFalse((root/'project').exists())

    def test_markdown_artifacts_preserve_inner_code_fences(self) -> None:
        """Generate README content with valid nested fences or explicit raw Markdown context."""
        markdown = '# Affine guide\n\nRun this code:\n\n```python\nfrom model import transform\nprint(transform(3))\n```\n\n```bash\npython3 model.py\n```\n'
        responses = ['## Code: README.md\n```markdown\n'+markdown+'```', '## Code: README.md\n```python\n'+markdown+'```', '## Code: README.md\n````markdown\n'+markdown+'````', '## Code: README.md\n'+markdown, markdown]
        raw_cases = ['```'+language+'\nexample command\n```\n\n'+markdown for language in ('sh','python')]
        responses.extend(raw_cases)
        for response in responses:
            with self.subTest(response=response[:40]), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                fake = root/'codex'
                fake.write_text((KIT/'tests/fixtures/fake_agent.py').read_text())
                fake.chmod(0o755)
                paper = root/'paper.json'
                paper.write_text('{"title":"Affine"}')
                tasks = {'Task list':['config.yaml','model.py','README.md'],'Logic Analysis':[['model.py','Return 2*x+1'],['README.md','Return 2*x+1 documentation']]}
                overrides = {'planning.tasks':json.dumps(tasks),'analysis:README.md':'Document x=3 yields 7.','coding:README.md':response}
                env = {**os.environ,'PATH':str(root)+os.pathsep+os.environ['PATH'],'PAPER2CODE_FAKE_OUTPUTS':json.dumps(overrides)}
                result = subprocess.run([sys.executable,str(KIT/'codes/pipeline.py'),'--backend','codex','--timeout','10','--input',str(paper),'--output_dir',str(root/'artifacts'),'--output_repo_dir',str(root/'project')],capture_output=True,text=True,env=env)
                self.assertEqual(result.returncode,0,result.stderr+result.stdout)
                self.assertEqual((root/'project/README.md').read_text(),response if response in raw_cases else markdown)

    def test_full_rerun_preserves_completed_outputs_before_any_cli_call(self) -> None:
        """Reject occupied full-run destinations before changing evidence or invoking inference."""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fake = root/'codex'
            fixture = KIT/'tests/fixtures/fake_agent.py'
            fake.write_text('#!/usr/bin/env python3\nimport os,pathlib,runpy,sys\np=pathlib.Path(os.environ["CLI_CALL_LOG"])\nwith p.open("a") as f: f.write(repr(sys.argv[1:])+"\\n")\nrunpy.run_path('+repr(str(fixture))+',run_name="__main__")\n')
            fake.chmod(0o755)
            paper = root/'paper.json'; paper.write_text('{"title":"Affine"}')
            output, project = root/'artifacts', root/'project'
            calls = root/'calls.log'
            env = {**os.environ,'PATH':str(root)+os.pathsep+os.environ['PATH'],'CLI_CALL_LOG':str(calls)}
            base = [sys.executable,str(KIT/'codes/pipeline.py'),'--backend','codex','--timeout','10','--input',str(paper)]
            result = subprocess.run([*base,'--output_dir',str(output),'--output_repo_dir',str(project)],capture_output=True,text=True,env=env)
            self.assertEqual(result.returncode,0,result.stderr+result.stdout)
            original = {str(path.relative_to(root)):path.read_bytes() for directory in (output,project) for path in directory.rglob('*') if path.is_file()}
            directories = sorted(str(path.relative_to(root)) for directory in (output,project) for path in directory.rglob('*') if path.is_dir())
            original_calls = calls.read_bytes()
            for artifact_target,project_target in ((output,project),(root/'fresh-artifacts',project),(output,root/'fresh-project')):
                with self.subTest(artifacts=artifact_target.name,project=project_target.name):
                    result = subprocess.run([*base,'--output_dir',str(artifact_target),'--output_repo_dir',str(project_target)],capture_output=True,text=True,env=env)
                    self.assertNotEqual(result.returncode,0,result.stdout)
                    self.assertIn('occupied',json.loads(result.stdout)['error'])
                    current = {str(path.relative_to(root)):path.read_bytes() for directory in (output,project) for path in directory.rglob('*') if path.is_file()}
                    self.assertEqual(current,original)
                    self.assertEqual(sorted(str(path.relative_to(root)) for directory in (output,project) for path in directory.rglob('*') if path.is_dir()),directories)
                    self.assertEqual(calls.read_bytes(),original_calls)
                    self.assertFalse((root/'fresh-artifacts').exists())
                    self.assertFalse((root/'fresh-project').exists())
            result = subprocess.run([*base,'--output_dir',str(output),'--output_repo_dir',str(project),'--stage','extract'],capture_output=True,text=True,env=env)
            self.assertEqual(result.returncode,0,result.stderr+result.stdout)
            self.assertEqual(json.loads(result.stdout)['stage'],'extract')
            self.assertEqual(calls.read_bytes(),original_calls)

    def test_inference_input_validation_precedes_cli_calls_and_writes(self) -> None:
        """Reject invalid budgets and missing actual-stage requirements before external work."""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fake = root/'codex'
            fixture = KIT/'tests/fixtures/fake_agent.py'
            fake.write_text('#!/usr/bin/env python3\nimport os,pathlib,runpy,sys\np=pathlib.Path(os.environ["CLI_CALL_LOG"])\nwith p.open("a") as f: f.write(repr(sys.argv[1:])+"\\n")\nrunpy.run_path('+repr(str(fixture))+',run_name="__main__")\n')
            fake.chmod(0o755)
            paper = root/'paper.json'; paper.write_text('{"title":"Affine"}')
            calls = root/'calls.log'
            env = {**os.environ,'PATH':str(root)+os.pathsep+os.environ['PATH'],'CLI_CALL_LOG':str(calls)}
            cases = [(KIT/'codes/pipeline.py',['--backend','codex','--timeout='+budget]) for budget in ('0','-1','nan','inf','-inf')]
            cases.extend((KIT/'codes/pipeline.py',['--backend','codex','--timeout','10','--model',model]) for model in ('',' ','\t'))
            cases.extend((KIT/'codes/1.1_extract_config.py',['--stage','planning',*options]) for options in ([],['--backend','codex'],['--timeout','10']))
            for index,(entrypoint,options) in enumerate(cases):
                with self.subTest(options=options):
                    output = root/f'artifacts-{index}'
                    project = root/f'project-{index}'
                    result = subprocess.run([sys.executable,str(entrypoint),*options,'--input',str(paper),'--output_dir',str(output),'--output_repo_dir',str(project)],capture_output=True,text=True,env=env,timeout=10)
                    self.assertNotEqual(result.returncode,0,result.stdout)
                    self.assertFalse(calls.exists(),result.stderr+result.stdout)
                    self.assertFalse(output.exists())
                    self.assertFalse(project.exists())

    def test_actual_extraction_stage_needs_no_backend_or_budget(self) -> None:
        """Permit generic and legacy extraction entry points to reuse records without CLI access."""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fake = root/'codex'
            fixture = KIT/'tests/fixtures/fake_agent.py'
            fake.write_text('#!/usr/bin/env python3\nimport os,pathlib,runpy,sys\np=pathlib.Path(os.environ["CLI_CALL_LOG"])\nwith p.open("a") as f: f.write(repr(sys.argv[1:])+"\\n")\nrunpy.run_path('+repr(str(fixture))+',run_name="__main__")\n')
            fake.chmod(0o755)
            paper = root/'paper.json'; paper.write_text('{"title":"Affine"}')
            calls = root/'calls.log'
            env = {**os.environ,'PATH':str(root)+os.pathsep+os.environ['PATH'],'CLI_CALL_LOG':str(calls)}
            output,project = root/'artifacts',root/'project'
            result = subprocess.run([sys.executable,str(KIT/'codes/pipeline.py'),'--backend','codex','--timeout','10','--input',str(paper),'--output_dir',str(output),'--output_repo_dir',str(project)],capture_output=True,text=True,env=env)
            self.assertEqual(result.returncode,0,result.stderr+result.stdout)
            original_calls = calls.read_bytes()
            for entrypoint,options in ((KIT/'codes/pipeline.py',['--stage','extract']),(KIT/'codes/1.1_extract_config.py',[])):
                with self.subTest(entrypoint=entrypoint.name):
                    result = subprocess.run([sys.executable,str(entrypoint),*options,'--output_dir',str(output),'--output_repo_dir',str(project)],capture_output=True,text=True,env=env)
                    self.assertEqual(result.returncode,0,result.stderr+result.stdout)
                    self.assertEqual(json.loads(result.stdout)['stage'],'extract')
                    self.assertEqual(calls.read_bytes(),original_calls)

if __name__ == '__main__':
    unittest.main()
