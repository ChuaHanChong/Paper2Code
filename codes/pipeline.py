"""Execute PaperCoder's staged paper-to-project workflow with coding CLIs."""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
import logging
import math
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys
import tempfile
from typing import Any

import yaml

from cli_runner import StageError, run_stage
from prompts import analysis_messages, coding_messages, planning_messages, reproduction_messages

LOGGER = logging.getLogger(__name__)
TEXT_SCHEMA = {'type':'object','properties':{'text':{'type':'string','minLength':1}},'required':['text'],'additionalProperties':False}
CONTROL_NAMES = {'.git', '.gitmodules', '.agents', '.claude', '.codex', '.github', 'agents.md', 'claude.md'}


def atomic_text(path: Path, content: str) -> None:
    """Replace one artifact atomically after its content is validated."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent, delete=False) as stream:
        temporary = Path(stream.name)
        try:
            stream.write(content)
            stream.flush()
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise
    try:
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def atomic_json(path: Path, value: Any) -> None:
    """Write a JSON artifact atomically."""
    atomic_text(path, json.dumps(value, ensure_ascii=False, indent=2) + '\n')


def safe_path(root: Path, filename: str) -> Path:
    """Resolve a generated filename strictly inside its allowed output root."""
    name = PurePosixPath(filename)
    if not filename or filename != name.as_posix() or '\\' in filename or name.is_absolute() or any(part in ('..', '.', '') or part.casefold() in CONTROL_NAMES or part.casefold().startswith('.env') for part in name.parts):
        raise StageError(f'unsafe generated filename: {filename!r}')
    target = root.joinpath(*name.parts)
    resolved_root = root.resolve()
    resolved_target = target.resolve()
    if resolved_target == resolved_root or not resolved_target.is_relative_to(resolved_root) or any(parent.is_symlink() for parent in [target, *target.parents] if parent != root.parent):
        raise StageError(f'generated path escapes output root: {filename!r}')
    return target


def fenced_text(text: str, language: str = '', filename: str | None = None) -> str:
    """Extract one matching outer fence or preserve explicitly identified raw Markdown."""
    heading = re.match(r'\s*## Code:[ \t]*([^\n]+)\n', text)
    if heading:
        if filename is None or heading.group(1).strip() != filename:
            raise StageError('generated Code heading does not match the requested filename')
        text = text[heading.end():]
    markdown = filename is not None and Path(filename).suffix.lower() in ('.md', '.markdown')
    # CommonMark fences use three or more backticks; a longer outer fence preserves shorter inner fences.
    opening = re.match(r'\s*(`{3,})([^`\n]*)\n', text)
    if opening and (not markdown or heading is not None or len(opening.group(1)) > 3 or opening.group(2).strip().lower() in ('markdown', 'md', '')):
        delimiter = opening.group(1)
        closing_pattern = r'(?m)^' + re.escape(delimiter) + (r'[ \t]*\s*\Z' if markdown else r'[ \t]*$')
        closing = re.search(closing_pattern, text[opening.end():])
        if closing is None:
            raise StageError(f'incomplete {language or "content"} artifact fence')
        end = opening.end() + closing.start()
        remainder = text[opening.end() + closing.end():]
        if '```' in remainder:  # claude may append fence-free notes after the one artifact fence
            raise StageError('multiple artifact fences are ambiguous')
        content = text[opening.end():end]
        return content if content.endswith('\n') else content + '\n'
    if markdown:
        return text if text.endswith('\n') else text + '\n'
    if heading:
        raise StageError('generated Code heading requires one complete artifact fence')
    if '```' in text:
        raise StageError(f'ambiguous or incomplete {language or "content"} fence')
    return text if text.endswith('\n') else text + '\n'


def json_content(text: str) -> dict[str, Any]:
    """Parse a stage's JSON object without heuristic repairs."""
    stripped = re.sub(r'^\s*\[CONTENT\]|\[/CONTENT\]\s*$', '', text).strip()
    try:
        value = json.loads(fenced_text(stripped), strict=False)  # prompt format examples show raw newlines inside strings
    except json.JSONDecodeError as error:
        raise StageError('stage content is not valid JSON') from error
    if not isinstance(value, dict):
        raise StageError('stage content must be a JSON object')
    return value


def validate_config(text: str) -> str:
    """Validate a generated YAML mapping and return its source text."""
    content = fenced_text(text, 'yaml', 'config.yaml')
    try:
        parsed = yaml.safe_load(content)
    except yaml.YAMLError as error:
        raise StageError('configuration is not valid YAML') from error
    if not isinstance(parsed, dict) or not parsed:
        raise StageError('configuration must be a nonempty YAML mapping')
    return content


@dataclass(frozen=True)
class RunConfig:
    """Hold explicit inference and output configuration."""
    backend: str
    timeout: float
    model: str | None
    output_dir: Path
    project_dir: Path
    paper_name: str
    paper_format: str
    paper_content: str


class Pipeline:
    """Run the original planning, per-file analysis, coding, and reproduction stages."""

    def __init__(self, config: RunConfig) -> None:
        """Initialize one isolated run without invoking inference."""
        self.config = config
        self.current_stage = 'initialization'
        self.records: list[dict[str, Any]] = []
        self.cli_version: str | None = None
        self.revision: str | None = None
        self.arguments: argparse.Namespace

    def text_stage(self, stage: str, messages: list[dict[str, str]]) -> str:
        """Generate text and persist its provider-neutral stage record."""
        self.current_stage = stage
        LOGGER.info('Running %s using %s', stage, self.config.backend)
        request = [*messages, {'role':'user','content':f'Paper2Code stage: {stage}\nReturn a JSON object with exactly one field, text, containing the complete requested answer. Preserve all content and follow the original instructions above.'}]
        result = run_stage(self.config.backend, request, TEXT_SCHEMA, self.config.output_dir, self.config.timeout, self.config.model)
        record = {'stage':stage,'backend':self.config.backend,'model':self.config.model,'cli_version':self.cli_version,'input_sha256':hashlib.sha256(json.dumps(request,ensure_ascii=False).encode()).hexdigest(),'output':result}
        self.records.append(record)
        artifact_name = stage.replace(':','/') + '.json'
        atomic_json(safe_path(self.config.output_dir / 'stages', artifact_name), record)
        return result['text']

    def artifact(self, filename: str) -> Path:
        """Validate one controller-owned artifact path inside the configured root."""
        return safe_path(self.config.output_dir, filename)

    def context(self) -> list[str]:
        """Read the three named planning outputs required by later stages."""
        outputs = []
        for name in ('overview', 'architecture', 'tasks'):
            record = json.loads(self.artifact(f'stages/planning.{name}.json').read_text())
            outputs.append(record['output']['text'])
        return outputs

    def task_list(self) -> tuple[list[str], dict[str, str]]:
        """Validate declared tasks and return their file paths and descriptions."""
        tasks = json_content(self.context()[2])
        names = tasks.get('Task list')
        logic = tasks.get('Logic Analysis')
        if not isinstance(names, list) or not names or any(not isinstance(name,str) for name in names):
            raise StageError('Task list must be a nonempty list of filenames')
        if any(name.casefold() in ('config.yaml', 'reproduce.sh') and name != name.casefold() for name in names):
            raise StageError('Task list must use canonical controller-owned filenames config.yaml and reproduce.sh')
        if len({name.casefold() for name in names}) != len(names):
            raise StageError('Task list contains duplicate filenames')
        if not isinstance(logic, list) or any(not isinstance(item,list) or len(item)!=2 or not all(isinstance(value,str) for value in item) for item in logic):
            raise StageError('Logic Analysis must contain filename/description pairs')
        targets = [safe_path(self.config.project_dir, name) for name in names]
        for target in targets:
            if any(parent in targets for parent in target.parents):
                raise StageError('Task list contains conflicting file and directory paths')
            if any(parent.is_file() for parent in target.parents):
                raise StageError('generated file has an existing file as a parent directory')
        return names, dict(logic)

    def planning(self) -> None:
        """Generate the original four planning outputs with explicit conversation history."""
        history: list[dict[str,str]] = []
        for name, group in zip(('overview','architecture','tasks','config'), planning_messages(self.config.paper_content,self.config.paper_format)):
            history.extend(group)
            answer = self.text_stage('planning.'+name,history)
            if name == 'architecture':
                architecture = json_content(answer)
                fields = ('Implementation approach','File list','Data structures and interfaces','Program call flow')
                if any(field not in architecture for field in fields):
                    raise StageError('architecture is missing required design fields')
            if name == 'tasks':
                self.task_list()
            if name == 'config':
                validate_config(answer)
            history.append({'role':'assistant','content':answer})
        atomic_json(self.artifact('planning_trajectories.json'),history)
        self.extract()

    def extract(self) -> None:
        """Extract named planning outputs without relying on conversation positions."""
        self.current_stage = 'extract'
        context = self.context()
        self.task_list()
        record = json.loads(self.artifact('stages/planning.config.json').read_text())
        config_text = validate_config(record['output']['text'])
        atomic_text(self.artifact('planning_config.yaml'),config_text)
        for name, content in zip(('1.1_overall_plan.txt','1.2_arch_design.txt','1.3_logic_design.txt'),context):
            atomic_text(self.artifact('planning_artifacts/'+name),content)
        atomic_text(self.artifact('planning_artifacts/1.4_config.yaml'),config_text)
        atomic_json(self.artifact('task_list.json'),json_content(context[2]))

    def analyzing(self) -> None:
        """Analyze each declared file using the full paper and planning context."""
        self.current_stage = 'analysis'
        names, descriptions = self.task_list()
        config_text = self.artifact('planning_config.yaml').read_text()
        for name in names:
            if name in ('config.yaml','reproduce.sh'):
                continue
            messages = analysis_messages(self.config.paper_content,self.config.paper_format,self.context(),config_text,name,descriptions.get(name,''))
            answer = self.text_stage('analysis:'+name,messages)
            atomic_text(safe_path(self.config.output_dir/'analyzing_artifacts',name+'.txt'),answer)

    def coding(self) -> None:
        """Generate declared files sequentially using prior code and per-file analysis."""
        self.current_stage = 'coding'
        names, _ = self.task_list()
        config_text = self.artifact('planning_config.yaml').read_text()
        done: dict[str,str] = {'config.yaml':config_text}
        candidates: dict[str,str] = {'config.yaml':config_text}
        for name in names:
            if name in ('config.yaml','reproduce.sh'):
                continue
            analysis = safe_path(self.config.output_dir/'analyzing_artifacts',name+'.txt').read_text()
            messages = coding_messages(self.config.paper_content,self.config.paper_format,self.context(),config_text,name,analysis,done)
            answer = self.text_stage('coding:'+name,messages)
            code = fenced_text(answer, filename=name)
            if not code.strip():
                raise StageError(f'empty generated file: {name}')
            candidates[name] = code
            done[name] = code
            atomic_text(safe_path(self.config.output_dir/'coding_artifacts',name+'.txt'),answer)
        for name in candidates:
            target = safe_path(self.config.project_dir,name)
            if target.exists():
                raise StageError(f'refusing to overwrite existing generated file: {name}')
        for name, content in candidates.items():
            atomic_text(safe_path(self.config.project_dir,name),content)

    def reproduction(self) -> None:
        """Generate a reproduction script without executing it."""
        self.current_stage = 'reproduction'
        names, _ = self.task_list()
        done = {name:safe_path(self.config.project_dir,name).read_text() for name in names if name != 'reproduce.sh'}
        config_text = safe_path(self.config.project_dir,'config.yaml').read_text()
        messages = reproduction_messages(config_text,done)
        messages.append({'role':'user','content':f'## Original paper ({self.config.paper_format})\n{self.config.paper_content}\n\n## Approved planning context\n'+ '\n\n'.join(self.context()) + '\n\nPreserve the paper-specific reproduction requirements exactly, including stdout, commands, dependencies, and environment restrictions. These explicit requirements take precedence over generic setup suggestions. Return only the requested reproduce.sh artifact.'})
        answer = self.text_stage('reproduction',messages)
        target = safe_path(self.config.project_dir,'reproduce.sh')
        if target.exists():
            raise StageError('refusing to overwrite existing reproduce.sh')
        atomic_text(target,fenced_text(answer,'bash','reproduce.sh'))

    def run(self, stage: str = 'all') -> dict[str, Any]:
        """Run a selected entry point and write an explicit completion or failure manifest."""
        if stage == 'all':
            for destination in (self.config.output_dir, self.config.project_dir):
                if (destination.exists() or destination.is_symlink()) and (not destination.is_dir() or any(destination.iterdir())):
                    raise StageError(f'full runs require empty artifact and project destinations; occupied path: {destination}')
        self.config.output_dir.mkdir(parents=True,exist_ok=True)
        status = 'failed'
        error = None
        try:
            if stage != 'extract':
                version = subprocess.run([self.config.backend,'--version'],capture_output=True,text=True,timeout=self.config.timeout,check=True)
                self.cli_version = version.stdout.strip()
            source_root = Path(__file__).resolve().parents[1]
            repository = subprocess.run(['git','-C',str(source_root),'rev-parse','--show-toplevel'],capture_output=True,text=True,check=False)
            if repository.returncode == 0 and Path(repository.stdout.strip()).resolve() == source_root:
                revision = subprocess.run(['git','-C',str(source_root),'rev-parse','HEAD'],capture_output=True,text=True,check=False)
                self.revision = revision.stdout.strip() or None
            if stage == 'all':
                for operation in (self.planning,self.analyzing,self.coding,self.reproduction):
                    operation()
            elif stage in ('planning','extract','analyzing','coding','reproduction'):
                getattr(self,stage)()
            else:
                from auxiliary import run_auxiliary
                run_auxiliary(self,stage)
            status = 'completed'
        except (StageError, ValueError, OSError, json.JSONDecodeError, subprocess.SubprocessError) as failure:
            error = str(failure)
        result = {'status':status,'stage':self.current_stage,'backend':self.config.backend,'model':self.config.model,'cli_version':self.cli_version,'paper2code_revision':self.revision,'input_sha256':hashlib.sha256(self.config.paper_content.encode()).hexdigest(),'output_dir':str(self.config.output_dir),'project_dir':str(self.config.project_dir),'completed_stages':[record['stage'] for record in self.records if status == 'completed' or record['stage'] != self.current_stage],'error':error}
        atomic_json(self.artifact('run.json'),result)
        return result


def parse_args(default_stage: str = 'all') -> argparse.Namespace:
    """Parse one provider-neutral command for standalone and legacy entry points."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--backend',choices=['codex','claude'])
    parser.add_argument('--model')
    parser.add_argument('--timeout',type=float,help='Per-stage seconds; choose from measured fixture runtime.')
    parser.add_argument('--paper_name',default='paper')
    parser.add_argument('--paper_format',choices=['JSON','LaTeX'],default='JSON')
    parser.add_argument('--input',type=Path)
    parser.add_argument('--pdf_json_path',type=Path)
    parser.add_argument('--pdf_latex_path',type=Path)
    parser.add_argument('--output_dir',type=Path,required=True)
    parser.add_argument('--output_repo_dir',type=Path)
    parser.add_argument('--stage',default=default_stage,choices=['all','planning','extract','analyzing','coding','reproduction','refinement','debugging','evaluation'])
    parser.add_argument('--error_file_name',type=Path)
    parser.add_argument('--save_num',type=int,default=1)
    parser.add_argument('--eval_type',choices=['ref_free','ref_based'],default='ref_free')
    parser.add_argument('--generated_n',type=int,default=8)
    parser.add_argument('--gold_repo_dir',type=Path)
    parser.add_argument('--selected_file_path',type=Path,help='Optional newline-separated reference filenames for evaluation.')
    parser.add_argument('--target_repo_dir',type=Path)
    parser.add_argument('--eval_result_dir',type=Path)
    parser.add_argument('--data_dir',type=Path)
    parser.add_argument('--papercoder',action='store_true')
    parser.add_argument('--lookup_file',type=Path,help='Controlled model/dataset ID lookup JSON; otherwise query Hugging Face.')
    arguments = parser.parse_args()
    if arguments.stage != 'extract' and arguments.backend is None:
        parser.error('--backend is required for inference stages')
    if arguments.stage != 'extract' and arguments.timeout is None:
        parser.error('--timeout is required for inference stages')
    if arguments.timeout is not None and (not math.isfinite(arguments.timeout) or arguments.timeout <= 0):
        parser.error('--timeout must be a positive finite number')
    if arguments.model is not None and not arguments.model.strip():
        parser.error('--model must be nonempty when supplied')
    return arguments


def main(default_stage: str = 'all') -> int:
    """Run the requested workflow and emit one machine-readable result."""
    logging.basicConfig(level=logging.INFO,stream=sys.stderr)
    args = parse_args(default_stage)
    source = args.input or (args.pdf_json_path if args.paper_format=='JSON' else args.pdf_latex_path)
    try:
        content = source.read_text(encoding='utf-8') if source else ''
        if args.stage in ('all','planning','analyzing','coding','evaluation') and not content.strip():
            raise StageError('provide --input or the matching --pdf_json_path/--pdf_latex_path')
        if source and args.paper_format=='JSON':
            parsed = json.loads(content)
            if not isinstance(parsed,dict):
                raise StageError('JSON paper must be an object')
        project = args.target_repo_dir if args.stage == 'evaluation' and args.target_repo_dir else args.output_repo_dir or args.target_repo_dir or args.output_dir/'project'
        config = RunConfig(args.backend or 'none',args.timeout if args.timeout is not None else 0,args.model,args.output_dir.resolve(),project.resolve(),args.paper_name,args.paper_format,content)  # Extraction-only sentinels cannot invoke inference.
        pipeline = Pipeline(config)
        pipeline.arguments = args
        result = pipeline.run(args.stage)
        print(json.dumps(result))
        return 0 if result['status']=='completed' else 1
    except (StageError,ValueError,OSError) as error:
        print(json.dumps({'status':'failed','stage':'input','error':str(error)}))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
