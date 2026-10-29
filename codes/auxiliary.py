"""Run PaperCoder's configuration refinement, debugging, and evaluation stages."""
from __future__ import annotations

import json
import logging
from pathlib import Path
import re
from typing import TYPE_CHECKING, Any

import yaml

from cli_runner import StageError
from pipeline import atomic_json, atomic_text, fenced_text, json_content, safe_path, validate_config
from prompts import debugging_messages, refinement_messages

if TYPE_CHECKING:
    from pipeline import Pipeline

LOGGER = logging.getLogger(__name__)
SOURCE_EXTENSIONS = {'.py', '.yaml', '.yml', '.md', '.sh', '.bash'}  # Upstream evaluation's explicit source-file contract.


def repository_text(root: Path, selected: list[str] | None = None) -> str:
    """Read textual repository files without following symlinks or control directories."""
    if not root.is_dir():
        raise StageError(f'repository directory is missing: {root}')
    chunks: list[str] = []
    if selected is not None and (not selected or len(set(selected)) != len(selected)):
        raise StageError('selected reference filenames must be nonempty and unique')
    paths = [safe_path(root, name) for name in selected] if selected is not None else sorted(root.rglob('*'))
    for path in paths:
        if selected is not None and not path.is_file():
            raise StageError(f'selected reference file does not exist: {path.name}')
        relative = path.relative_to(root)
        if any(part.startswith('.') or part == '__pycache__' for part in relative.parts):
            continue
        if path.is_symlink() or any(parent.is_symlink() for parent in path.parents if parent != root.parent):
            raise StageError(f'repository contains a symlink: {relative}')
        if path.is_file():
            if path.suffix.lower() not in SOURCE_EXTENSIONS:
                if selected is not None:
                    raise StageError(f'selected reference file is not a supported source file: {relative}')
                continue
            try:
                text = path.read_text(encoding='utf-8')
            except UnicodeDecodeError as error:
                raise StageError(f'repository file is not UTF-8 text: {relative}') from error
            chunks.append(f'Filename: {relative.as_posix()}\n```\n{text}\n```')
    if not chunks:
        raise StageError(f'repository contains no textual files: {root}')
    return '\n\n'.join(chunks)


def name_kinds(value: Any, name: str, ancestry: tuple[str, ...] = ()) -> set[str]:
    """Identify model or dataset names using their complete YAML key ancestry."""
    if isinstance(value, dict):
        return set().union(*(name_kinds(item, name, (*ancestry, str(key))) for key, item in value.items()))
    if isinstance(value, list):
        return set().union(*(name_kinds(item, name, ancestry) for item in value))
    if value == name:
        return {'dataset' if any('dataset' in key.lower() or key.lower() == 'data' for key in ancestry) else 'model'}
    return set()


def replace_config_values(value: Any, replacements: dict[str, str]) -> Any:
    """Replace complete YAML string values without rewriting substrings or keys."""
    if isinstance(value, dict):
        return {key: replace_config_values(item, replacements) for key, item in value.items()}
    if isinstance(value, list):
        return [replace_config_values(item, replacements) for item in value]
    return replacements.get(value, value) if isinstance(value, str) else value


def lookup_name(name: str, config_text: str) -> str:
    """Resolve one model or dataset name through optional Hugging Face search."""
    try:
        from huggingface_hub import HfApi
    except ImportError as error:
        raise StageError('name refinement requires --lookup_file or pip install -r requirements-lookup.txt') from error
    api = HfApi()
    kinds = name_kinds(yaml.safe_load(config_text), name)
    if len(kinds) > 1:
        raise StageError(f'name occurs as both a model and dataset; provide --lookup_file: {name!r}')
    search = api.list_datasets if kinds == {'dataset'} else api.list_models
    try:
        candidates = iter(search(search=name, sort='downloads', direction=-1, limit=1))
        candidate = next(candidates, None)
    except (OSError, ValueError, RuntimeError) as error:
        raise StageError(f'Hugging Face lookup failed for {name!r}: {error}') from error
    if candidate is None:
        LOGGER.warning('No Hugging Face match for %s; retaining original name', name)
        return name
    return candidate.id


def refinement(pipeline: Pipeline) -> None:
    """Replace detected model and dataset names using an explicit lookup source."""
    pipeline.current_stage = 'refinement'
    source = safe_path(pipeline.config.output_dir, 'planning_config.yaml')
    original = validate_config(source.read_text(encoding='utf-8'))
    answer = pipeline.text_stage('refinement', refinement_messages(original))
    try:
        detected = json.loads(fenced_text(answer))
    except json.JSONDecodeError as error:
        raise StageError('refinement must return a JSON list of names') from error
    if not isinstance(detected, list) or any(not isinstance(name, str) or not name for name in detected):
        raise StageError('refinement names must be nonempty strings')
    controlled = pipeline.arguments.lookup_file
    mapping = json.loads(controlled.read_text(encoding='utf-8')) if controlled else None
    if mapping is not None and (not isinstance(mapping, dict) or any(not isinstance(value, str) or not value for value in mapping.values())):
        raise StageError('lookup file must map names to nonempty model or dataset IDs')
    replacements: dict[str, str] = {}
    for name in dict.fromkeys(detected):
        if not name_kinds(yaml.safe_load(original), name):
            raise StageError(f'detected name does not occur in configuration: {name!r}')
        if mapping is not None:
            if name not in mapping:
                raise StageError(f'lookup file has no entry for {name!r}')
            replacements[name] = mapping[name]
        else:
            replacements[name] = lookup_name(name, original)
    result = yaml.safe_dump(replace_config_values(yaml.safe_load(original), replacements), sort_keys=False, allow_unicode=True)
    validate_config(result)
    backup = safe_path(pipeline.config.output_dir, 'planning_config.yaml.bak')
    if backup.exists():
        raise StageError('refusing to overwrite existing planning_config.yaml.bak')
    atomic_text(backup, original)
    atomic_text(source, result)
    atomic_json(safe_path(pipeline.config.output_dir, 'refinement.json'), {'replacements': replacements})


def debugging(pipeline: Pipeline) -> None:
    """Validate every exact SEARCH patch before changing generated files."""
    pipeline.current_stage = 'debugging'
    arguments = pipeline.arguments
    if arguments.error_file_name is None:
        raise StageError('debugging requires --error_file_name')
    if arguments.save_num < 1:
        raise StageError('--save_num must be positive')
    root = pipeline.config.project_dir
    answer = pipeline.text_stage('debugging', debugging_messages(repository_text(root), arguments.error_file_name.read_text(encoding='utf-8')))
    content = fenced_text(answer)
    sections = re.split(r'(?m)^Filename:[ \t]*([^\n]+)\n', content)
    if sections[0].strip() or len(sections) < 3 or len(sections) % 2 != 1:
        raise StageError('debugging response must contain Filename and SEARCH/REPLACE sections')
    originals: dict[Path, str] = {}
    candidates: dict[Path, str] = {}
    backups: dict[Path, Path] = {}
    patch_pattern = re.compile(r'<<<<<<< SEARCH\n(.*?)\n=======\n(.*?)\n>>>>>>> REPLACE(?:\n|$)', re.DOTALL)
    for index in range(1, len(sections), 2):
        filename, blocks = sections[index].strip(), sections[index + 1]
        path = safe_path(root, filename)
        if not path.is_file():
            raise StageError(f'debugging target does not exist: {filename}')
        if path not in originals:
            originals[path] = path.read_text(encoding='utf-8')
            candidates[path] = originals[path]
            backups[path] = safe_path(root, f'{filename}.{arguments.save_num:03d}.bak')
            if backups[path].exists():
                raise StageError(f'refusing to overwrite debugging backup: {backups[path].name}')
        patches = list(patch_pattern.finditer(blocks))
        if not patches or patch_pattern.sub('', blocks).strip():
            raise StageError(f'malformed SEARCH/REPLACE blocks: {filename}')
        for patch in patches:
            search, replacement = patch.group(1), patch.group(2)
            if not search or candidates[path].count(search) != 1:
                raise StageError(f'SEARCH must match exactly once: {filename}')
            candidates[path] = candidates[path].replace(search, replacement, 1)
    for path, original in originals.items():
        atomic_text(backups[path], original)
    written: list[Path] = []
    try:
        for path, changed in candidates.items():
            atomic_text(path, changed)
            written.append(path)
    except OSError:
        for path in written:
            atomic_text(path, originals[path])
        raise
    atomic_json(safe_path(pipeline.config.output_dir, 'debugging.json'), {'changed_files': [str(path.relative_to(root)) for path in written], 'backups': [str(path.relative_to(root)) for path in backups.values()]})


def evaluation(pipeline: Pipeline) -> None:
    """Evaluate independent CLI samples and preserve invalid-sample failures."""
    arguments = pipeline.arguments
    mode = arguments.eval_type
    pipeline.current_stage = 'evaluation:' + mode
    if arguments.generated_n < 1:
        raise StageError('--generated_n must be positive')
    data = arguments.data_dir or Path(__file__).resolve().parents[1] / 'data'
    prompt = (data / 'prompts' / f'{mode}.txt').read_text(encoding='utf-8')
    if arguments.papercoder:
        task_file = pipeline.artifact('task_list.json')
        tasks = json.loads(task_file.read_text(encoding='utf-8')) if task_file.exists() else json_content(pipeline.context()[2])
        names = tasks.get('Task list') if isinstance(tasks, dict) else None
        if not isinstance(names, list) or not names or any(not isinstance(name, str) for name in names) or len(set(names)) != len(names):
            raise StageError('PaperCoder evaluation requires a nonempty unique Task list')
        for name in names:
            safe_path(pipeline.config.project_dir, name)
        selected_sources = [name for name in names if Path(name).suffix.lower() in SOURCE_EXTENSIONS - {'.yaml', '.yml'}]
        target_text = repository_text(pipeline.config.project_dir, selected_sources)
        planning_config = validate_config(pipeline.artifact('planning_config.yaml').read_text(encoding='utf-8'))
        target_text += f'\n\nFilename: config.yaml\n```yaml\n{planning_config}\n```'
    else:
        target_text = repository_text(pipeline.config.project_dir)
    prompt = prompt.replace('{{Paper}}', pipeline.config.paper_content).replace('{{Code}}', target_text)
    if mode == 'ref_based':
        if arguments.gold_repo_dir is None:
            raise StageError('reference-based evaluation requires --gold_repo_dir')
        selected_file = getattr(arguments, 'selected_file_path', None)
        selected = [line.strip() for line in selected_file.read_text(encoding='utf-8').splitlines() if line.strip()] if selected_file else None
        prompt = prompt.replace('{{GoldCode}}', repository_text(arguments.gold_repo_dir.resolve(), selected))
    samples: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    for index in range(arguments.generated_n):
        try:
            answer = pipeline.text_stage(f'evaluation:{mode}:{index}', [{'role': 'system', 'content': prompt}])
            result = json_content(answer)
            score = result.get('score')
            critiques = result.get('critique_list')
            fields = ('file_name', 'func_name', 'severity_level', 'critique') if mode == 'ref_free' else ('gold_file_name', 'gold_func_name', 'target_file_name', 'target_func_name', 'severity_level', 'critique')
            if type(score) is not int or not 1 <= score <= 5 or not isinstance(critiques, list) or any(not isinstance(critique, dict) or any(not isinstance(critique.get(field), str) for field in fields) or critique.get('severity_level') not in ('low', 'medium', 'high') for critique in critiques):
                raise StageError('evaluation requires an integer score from 1 to 5 and complete severity-labelled critiques')
            samples.append({'sample': index, 'score': score, 'critique_list': critiques})
        except (StageError, OSError, ValueError) as error:
            failures.append({'sample': index, 'error': str(error)})
    summary = {'paper_name': pipeline.config.paper_name, 'eval_type': mode, 'backend': pipeline.config.backend, 'model': pipeline.config.model, 'generated_n': arguments.generated_n, 'samples': samples, 'failures': failures, 'eval_result': {'score': sum(sample['score'] for sample in samples) / len(samples) if samples else None, 'valid_n': len(samples), 'failed_n': len(failures)}}
    output = arguments.eval_result_dir or pipeline.config.output_dir
    atomic_json(safe_path(output.resolve(), f'evaluation_{mode}.json'), summary)
    if failures:
        raise StageError(f'evaluation has {len(failures)} failed samples; inspect evaluation_{mode}.json')


def run_auxiliary(pipeline: Pipeline, stage: str) -> None:
    """Dispatch one retained auxiliary stage through the shared controller."""
    operations = {'refinement': refinement, 'debugging': debugging, 'evaluation': evaluation}
    if stage not in operations:
        raise StageError(f'unknown auxiliary stage: {stage}')
    operations[stage](pipeline)
