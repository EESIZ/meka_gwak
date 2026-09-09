"""Local form/content checks. Page appearance and legal meaning are reviewed by AI."""
import argparse
import re
import sys
import zipfile
from collections import Counter
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import url2pathname
from xml.etree import ElementTree as ET

from _shared import changes, configure_console, emit, error_result, normalized, read_json, read_text

NUM_LIST = r'\d+(?:\s*(?:,|·|및|내지|~|∼)\s*\d+)*'
EVIDENCE_CORE = r'제?\s*(?P<numbers>'+NUM_LIST+r')\s*호\s*증(?:\s*의\s*(?P<parts>'+NUM_LIST+r'))?'
EVIDENCE = re.compile(r'(?P<party>갑|을)\s*'+EVIDENCE_CORE)
FOLLOWING = re.compile(r'\s*(?P<link>,|및|내지)\s*'+EVIDENCE_CORE)
PLACEHOLDERS = re.compile(r'\{\{[^{}]+\}\}|\[\s*(?:TODO|입력|작성|미정|확인\s*필요)[^\]]*\]', re.I)


def evidence(text):
    def numbers(value):
        pieces = re.split(r'\s*(,|·|및|내지|~|∼)\s*', value)
        result = [int(pieces[0])]
        for separator, raw in zip(pieces[1::2], pieces[2::2]):
            end = int(raw)
            if separator in {'내지','~','∼'}:
                if end < result[-1] or end-result[-1] > 1000:
                    raise ValueError('증거번호의 범위를 개별 번호로 확인하세요.')
                result.extend(range(result[-1]+1,end+1))
            else:
                result.append(end)
        return result
    result = set()
    def add(party, match):
        bases = numbers(match['numbers'])
        parts = numbers(match['parts']) if match['parts'] else [None]
        for base in bases:
            for part in parts:
                result.add(party+':'+str(base)+(':'+str(part) if part is not None else ''))
        return bases
    for match in EVIDENCE.finditer(text):
        party = match['party']
        bases = add(party,match)
        end = match.end()
        while (following := FOLLOWING.match(text,end)):
            next_bases = add(party,following)
            if following['link'] == '내지' and len(bases) == len(next_bases) == 1:
                for value in numbers(str(bases[0])+'내지'+str(next_bases[0])):
                    result.add(party+':'+str(value))
            bases, end = next_bases, following.end()
    return result


def local_source(source, form_file):
    if re.match(r'^[a-zA-Z]:[/\\]', source):
        return Path(source)
    parts = urlsplit(source)
    if parts.scheme in {'http','https'}:
        return None
    if parts.scheme == 'file':
        return Path(url2pathname(('//'+parts.netloc if parts.netloc else '')+parts.path))
    path = Path(source)
    return path if path.is_absolute() else Path(form_file).resolve().parent/path


def evidence_notation_review(text):
    starts = {m.start() for m in EVIDENCE.finditer(text)}
    return [text[m.start():m.start()+60] for m in re.finditer(r'(?:갑|을)\s*제?\s*\d+',text)
            if m.start() not in starts]


def xml_root(raw):
    if b'<!DOCTYPE' in raw.upper() or b'<!ENTITY' in raw.upper():
        raise ValueError('문서 XML의 외부 선언을 확인하세요.')
    return ET.fromstring(raw)


def localname(element):
    return element.tag.rsplit('}', 1)[-1]


def extract_xml_paragraphs(raw):
    root = xml_root(raw)
    rows = []
    for p in root.iter():
        if localname(p) == 'p':
            parts = []
            for element in p.iter():
                if localname(element) == 't' and element.text:
                    parts.append(element.text)
                elif localname(element) in {'tab', 'br', 'lineBreak'}:
                    parts.append(' ')
            rows.append(''.join(parts))
    return '\n'.join(rows)


def extract_file(path):
    path = Path(path)
    kind = path.suffix.lower()
    if kind in {'.txt', '.md'}:
        return {'text': read_text(path), 'kind': kind, 'pages': [], 'page_review': 'final_document_required'}
    if kind in {'.docx', '.hwpx'}:
        with zipfile.ZipFile(path) as archive:
            if sum(i.file_size for i in archive.infolist()) > 100_000_000:
                raise ValueError('문서 압축 해제 크기를 확인하세요.')
            if kind == '.docx':
                text = extract_xml_paragraphs(archive.read('word/document.xml'))
            else:
                sections = [n for n in archive.namelist() if re.fullmatch(r'Contents/section\d+\.xml', n)]
                sections.sort(key=lambda n: int(re.search(r'section(\d+)', n).group(1)))
                if not sections:
                    raise ValueError('HWPX 본문 section 파일을 확인하세요.')
                text = '\n'.join(extract_xml_paragraphs(archive.read(n)) for n in sections)
        return {'text': text, 'kind': kind, 'pages': [], 'page_review': 'render_and_review_required'}
    if kind == '.pdf':
        try:
            from pypdf import PdfReader
            from pypdf.errors import PyPdfError
        except ImportError as exc:
            raise ImportError('PDF 확인을 위해 requirements.txt를 설치하세요.') from exc
        try:
            reader = PdfReader(path)
            if reader.is_encrypted and reader.decrypt('') == 0:
                raise ValueError('열람 가능한 PDF 또는 암호 해제된 확인본을 제공하세요.')
            pages = [page.extract_text() or '' for page in reader.pages]
        except PyPdfError as exc:
            raise ValueError('PDF 확인본의 구조와 열람 가능 상태를 확인하세요: ' + str(exc)) from exc
        return {'text': '\n'.join(pages), 'kind': kind,
                'pages': [{'page': i+1, 'text_empty': not text.strip()} for i, text in enumerate(pages)],
                'page_review': 'visual_review_required'}
    raise ImportError('이 형식은 문서 도구에서 DOCX·HWPX·PDF 확인본을 생성한 뒤 다시 확인하세요: ' + kind)


def validate_form(form):
    if not isinstance(form, dict) or not isinstance(form.get('fields'), list) or not form['fields']:
        raise ValueError('form.json에 서식별 fields 배열을 제공하세요.')
    if not isinstance(form.get('document_type'), str) or not form['document_type'].strip():
        raise ValueError('form.json에 document_type을 제공하세요.')
    if not isinstance(form.get('context', {}), dict):
        raise ValueError('context는 조건 이름과 값의 객체로 제공하세요.')
    names = []
    for field in form['fields']:
        if not isinstance(field, dict) or not isinstance(field.get('name'), str) or not field['name'].strip():
            raise ValueError('각 서식 항목에 name을 제공하세요.')
        if type(field.get('required', True)) is not bool:
            raise ValueError('required는 true 또는 false로 제공하세요.')
        if 'value' in field and not isinstance(field['value'], str):
            raise ValueError('항목 value는 문자열로 제공하세요.')
        condition = field.get('required_if')
        if condition is not None and (not isinstance(condition, dict) or not condition):
            raise ValueError('required_if는 조건 이름과 값의 객체로 제공하세요.')
        names.append(field['name'])
    if len(set(names)) != len(names):
        raise ValueError('서식 항목 이름을 고유하게 제공하세요.')


def required_field(field, context):
    condition = field.get('required_if')
    if condition:
        missing = [k for k in condition if k not in context]
        if missing:
            return None, missing
        return all(type(context[k]) is type(v) and context[k] == v for k, v in condition.items()), []
    return field.get('required', True), []


def compare_body(expected, actual):
    # Ordered paragraph containment permits surrounding form fields and page numbers.
    compact = normalized(actual)
    paragraphs = [p for p in re.split(r'\n\s*\n', expected) if p.strip()]
    cursor, missing, between = 0, [], []
    for index, paragraph in enumerate(paragraphs, 1):
        part = normalized(paragraph)
        location = compact.find(part, cursor)
        if location < 0:
            missing.append({'paragraph': index, 'text': paragraph})
        else:
            if cursor and compact[cursor:location]:
                between.append(compact[cursor:location])
            cursor = location + len(part)
    return {'status': 'matched' if not missing and not between else 'review_required', 'missing_or_changed': missing,
            'inserted_between_paragraphs': between,
            'next': '판독 순서·내용 추가·누락·수정 여부를 실제 페이지와 대조하세요.' if missing or between else '배치 전 본문이 순서대로 확인되었습니다.'}


def inspect(final_path, body, form, attachment_file=None):
    validate_form(form)
    if not body.strip():
        raise ValueError('대조할 퇴고 본문을 제공하세요.')
    document = extract_file(final_path)
    text = document['text']
    issues = []
    if not text.strip():
        issues.append({'kind': 'text_extraction', 'message': '텍스트 확인본 또는 OCR 결과를 확보하세요.'})
    if not isinstance(form.get('source'), str) or not form['source'].strip():
        issues.append({'kind': 'form_source', 'message': '확인한 원본 서식 위치 또는 제출 요구사항 출처를 제공하세요.'})
    context, compact = form.get('context', {}), normalized(text)
    for field in form['fields']:
        needed, unknown = required_field(field, context)
        if needed is None:
            issues.append({'kind': 'condition_required', 'field': field['name'], 'conditions': unknown})
        elif needed:
            value = field.get('value', '').strip()
            if not value:
                issues.append({'kind': 'value_required', 'field': field['name']})
            elif normalized(value) not in compact:
                issues.append({'kind': 'value_missing_in_file', 'field': field['name'], 'value': value})
    markers = PLACEHOLDERS.findall(text)
    if markers:
        issues.append({'kind': 'placeholders', 'values': markers})
    body_check = compare_body(body, text)
    if body_check['status'] != 'matched':
        issues.append({'kind': 'body_review', 'message': '퇴고본과 최종 파일의 본문을 대조하세요.'})
    body_refs = evidence(body)
    final_refs = evidence(text)
    unknown_notation = evidence_notation_review(body) + evidence_notation_review(text)
    if unknown_notation:
        issues.append({'kind': 'evidence_notation_review', 'passages': list(dict.fromkeys(unknown_notation))})
    attachment_rows = read_json(attachment_file) if attachment_file else []
    if not isinstance(attachment_rows, list):
        raise ValueError('첨부 목록은 배열 JSON으로 제공하세요.')
    manifest_refs, all_refs = set(), []
    if (body_refs or final_refs) and not attachment_file:
        issues.append({'kind': 'attachment_manifest_required', 'references': sorted(body_refs | final_refs)})
    for item in attachment_rows:
        if not isinstance(item, dict) or not isinstance(item.get('label'), str) or not isinstance(item.get('path'), str):
            raise ValueError('첨부 항목에 label과 path 문자열을 제공하세요.')
        label, raw_path = item['label'].strip(), item['path'].strip()
        if not label or not raw_path:
            raise ValueError('첨부 항목의 label과 path를 채우세요.')
        refs = evidence(label)
        manifest_refs.update(refs); all_refs.extend(refs)
        file_path = Path(raw_path)
        if not file_path.is_absolute():
            file_path = Path(attachment_file).resolve().parent / file_path
        if not file_path.is_file():
            issues.append({'kind': 'attachment_file_missing', 'label': label})
        elif file_path.stat().st_size == 0:
            issues.append({'kind': 'attachment_empty', 'label': label})
        if refs:
            if not refs.issubset(evidence(text)):
                issues.append({'kind': 'attachment_label_missing', 'label': label})
        elif normalized(label) not in compact:
            issues.append({'kind': 'attachment_label_missing', 'label': label})
    if (body_refs | final_refs) - manifest_refs:
        issues.append({'kind': 'unmapped_evidence', 'references': sorted((body_refs | final_refs)-manifest_refs)})
    added_refs = final_refs - body_refs
    if added_refs:
        issues.append({'kind': 'final_evidence_review', 'references': sorted(added_refs),
                       'message': '배치 후 추가된 증거 참조 또는 첨부 목록을 확인하세요.'})
    duplicates = [ref for ref, count in Counter(all_refs).items() if count > 1]
    if duplicates:
        issues.append({'kind': 'duplicate_evidence', 'references': duplicates})
    empty_pages = [p['page'] for p in document['pages'] if p['text_empty']]
    if empty_pages:
        issues.append({'kind': 'page_text_review', 'pages': empty_pages})
    return {'status': 'needs_review' if issues else 'mechanical_checks_complete',
            'issues': issues, 'body': body_check, 'page_review': document['page_review'],
            'next': 'AI가 항목의 의미·첨부 내용·최종 페이지를 확인하고 사용자에게 제출 결정을 받으세요.'}


def main(argv=None):
    configure_console()
    p = argparse.ArgumentParser(description='서식별 항목·첨부·최종 본문 대조')
    p.add_argument('final')
    p.add_argument('--body', required=True)
    p.add_argument('--form', required=True)
    p.add_argument('--attachments')
    p.add_argument('--output', required=True)
    args = p.parse_args(argv)
    try:
        form = read_json(args.form)
        result = inspect(args.final, read_text(args.body), form, args.attachments)
        summary = {k: result[k] for k in ('status', 'issues', 'page_review', 'next')}
        summary['issues'] = result['issues'][:10]
        summary['more_issues_in_detail'] = len(result['issues']) > 10
        summary['detail_file'] = args.output
        protected = [args.final, args.body, args.form, args.attachments]
        if isinstance(form.get('source'),str) and form['source'].strip():
            protected.append(local_source(form['source'],args.form))
        if args.attachments:
            for item in read_json(args.attachments):
                path = Path(item['path'])
                protected.append(path if path.is_absolute() else Path(args.attachments).resolve().parent / path)
        emit(result, args.output, protected, summary)
        return 0
    except (OSError, ValueError, ImportError, TypeError, KeyError, ET.ParseError, zipfile.BadZipFile) as exc:
        emit(error_result(exc))
        return 2


if __name__ == '__main__':
    sys.exit(main())
