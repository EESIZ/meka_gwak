"""Local text I/O and change inspection shared by the two entrypoints."""
import difflib
import hashlib
import json
import re
import sys
import unicodedata
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CASE = re.compile(r'(?<!\d)\d{2,4}\s*(?:구합|구단|헌마|헌바|헌가|두|누|다|도|나|노|추|부)\s*\d+')
NUMBERS = re.compile(r'\d[\d,]*(?:\.\d+)?(?:\s*(?:억|만|천))?(?:\s*(?:원|달러|%|년|월|일))?')


def read_text(path):
    return Path(path).read_text(encoding='utf-8-sig')


def read_json(path):
    return json.loads(read_text(path))


def configure_console():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8')


def emit(value, output=None, protected=(), summary=None):
    text = json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n'
    if output:
        target = Path(output).resolve()
        if target.is_relative_to(ROOT):
            raise ValueError('결과 파일은 스킬 밖의 사용자 작업 폴더에 저장하세요.')
        if target in {Path(p).resolve() for p in protected if p}:
            raise ValueError('출력 경로를 입력 파일과 구분하세요.')
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding='utf-8')
    print(json.dumps(summary, ensure_ascii=False, indent=2, allow_nan=False) if summary is not None else text, end='\n')


def normalized(text):
    return re.sub(r'\s+', '', unicodedata.normalize('NFC', text))


def digest(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def changes(before, after, anchors=()):
    # Keep all changed blocks for semantic review, including purely verbal changes.
    if not isinstance(anchors, (list, tuple)):
        raise ValueError('보존할 값은 문자열 배열로 제공하세요.')
    old, new = before.splitlines(), after.splitlines()
    blocks = []
    for tag, a, b, c, d in difflib.SequenceMatcher(None, old, new, autojunk=False).get_opcodes():
        if tag != 'equal':
            blocks.append({'before_lines': [a + 1, b], 'after_lines': [c + 1, d],
                           'before': '\n'.join(old[a:b]), 'after': '\n'.join(new[c:d])})
    changed_values = {}
    for name, pattern in [('numbers', NUMBERS), ('case_references', CASE)]:
        first = Counter(normalized(m.group()) for m in pattern.finditer(before))
        second = Counter(normalized(m.group()) for m in pattern.finditer(after))
        if first != second:
            changed_values[name] = {'removed': list((first-second).elements()),
                                    'added': list((second-first).elements())}
    for anchor in anchors:
        if not isinstance(anchor, str) or not anchor.strip():
            raise ValueError('보존할 값은 비어 있지 않은 문자열로 제공하세요.')
    anchor_changes = [a for a in anchors if normalized(before).count(normalized(a)) != normalized(after).count(normalized(a))]
    return {'changed': bool(blocks), 'blocks': blocks, 'changed_values': changed_values,
            'anchor_changes': anchor_changes, 'next': '변경 문맥에서 의미·조건·예외·판단 강도를 확인하세요.' if blocks else '변경 없음'}


def error_result(exc):
    return {'status': 'tool_required' if isinstance(exc, ImportError) else 'input_error',
            'message': str(exc), 'next': '본문을 보존하고 도구 또는 입력을 확인한 뒤 다시 실행하세요.'}
