#!/usr/bin/env python3
"""Emit independently fixed stage outputs using the real subprocess contract."""
import json
import os
from pathlib import Path
import re
import sys

args = sys.argv[1:]
if args == ['--version']:
    print('fixture-agent 1.0')
    raise SystemExit(0)
messages = json.loads(sys.stdin.read().split('\n', 1)[1])
stage = re.search(r'Paper2Code stage: ([^\n]+)', messages[-1]['content']).group(1)
outputs = {
    'planning.overview': 'Implement the affine transform from the paper.',
    'planning.architecture': json.dumps({'Implementation approach':'scalar transform','File list':['model.py','config.yaml'],'Data structures and interfaces':'transform(x)','Program call flow':'transform'}),
    'planning.tasks': json.dumps({'Required packages':[],'Required other language third-party packages':[],'Logic Analysis':[['model.py','Return 2*x+1']],'Task list':['config.yaml','model.py']}),
    'planning.config': '```yaml\nscale: 2\nbias: 1\n```',
    'analysis:model.py': 'Return scale*x+bias; x=3 yields 7.',
    'coding:model.py': '```python\ndef transform(x):\n    return 2*x+1\n```',
    'reproduction': '```bash\n#!/bin/sh\npython3 -c "from model import transform; assert transform(3)==7"\n```',
    'refinement': '["example-model"]',
    'debugging': 'Filename: model.py\n<<<<<<< SEARCH\n    return 0\n=======\n    return 2*x+1\n>>>>>>> REPLACE',
    'evaluation:ref_free:0': '{"score":5,"critique_list":[]}',
    'evaluation:ref_based:0': '{"score":5,"critique_list":[]}',
}
if stage.startswith(('analysis:', 'coding:')):
    assert 'Return 2*x+1' in str(messages), 'task context missing'
if stage.startswith('coding:'):
    assert 'x=3 yields 7' in str(messages), 'analysis context missing'
overrides = json.loads(os.environ.get('PAPER2CODE_FAKE_OUTPUTS','{}'))
if stage == os.environ.get('PAPER2CODE_FAIL_STAGE'):
    raise SystemExit(7)
if stage == 'reproduction' and os.environ.get('PAPER2CODE_REPRODUCTION_CONTEXT'):
    assert os.environ['PAPER2CODE_REPRODUCTION_CONTEXT'] in str(messages), 'paper reproduction context missing'
artifact = {'text': overrides[stage] if stage in overrides else outputs[stage]}
if '--output-last-message' in args:
    Path(args[args.index('--output-last-message')+1]).write_text(json.dumps(artifact))
    print('progress event')
else:
    print(json.dumps({'is_error':False,'structured_output':artifact}))
