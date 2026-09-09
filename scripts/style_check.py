"""Descriptive Korean style measurements; writing decisions stay with the reader."""
import argparse
import importlib.metadata
import re
import statistics
import sys
from collections import Counter

from _shared import ROOT, changes, configure_console, digest, emit, error_result, read_json, read_text

VERSION = '1.0.0'
EXTRACTOR = 'kiwi-0.22.2-style-v1'
CONTENT = {'NNG', 'NNP', 'VV', 'VA', 'MAG', 'XR'}
PUNCT = {'SF', 'SP', 'SS', 'SSO', 'SSC', 'SE', 'SO', 'SW', 'SB'}
APPELLATE_TOKENS = {'상고/NNG', '원심/NNG', '주문/NNG', '관여/NNG', '법관/NNG', '일치/NNG', '의견/NNG',
                    '오해/NNG', '심리/NNG', '영향/NNG', '미치/VV', '패소/NNG'}  # 상고심 절차·결어 관용구 전용
PARTY_TOKENS = {'원고/NNG', '피고/NNG', '피고인/NNG', '피의자/NNG', '검사/NNG', '민원인/NNG', '신청인/NNG',
                '청구인/NNG', '피청구인/NNG', '채권자/NNG', '채무자/NNG', '참가인/NNG', '상대방/NNG', '소외/NNG',
                '망인/NNG', '기관/NNG', '행정청/NNG', '법원/NNG', '국가/NNG', '공무원/NNG'}  # 당사자·기관 지칭
EXCLUDED_LEXICAL = APPELLATE_TOKENS | PARTY_TOKENS
REFERENCE_ONLY = {'sentence_chars'}  # 측정·참고 위치는 유지하되 우선 퇴고 신호로는 선정하지 않는 지표
LABELS = {
    'sentence_chars': '문장당 글자 수',
    'ec_per_sentence': '문장당 연결어미',
    'comma_per_sentence': '문장당 쉼표',
    'etn_per1000': '형태소 기준 명사형 어미 빈도',
    'etm_per1000': '형태소 기준 관형형 어미 빈도',
    'repetition_pct': '내용 형태소 반복 비율',
}


def analyzer():
    try:
        from kiwipiepy import Kiwi
    except ImportError as exc:
        raise ImportError('동일 Python 환경에 requirements.txt를 설치하세요.') from exc
    actual = importlib.metadata.version('kiwipiepy')
    if actual != '0.22.2':
        raise ImportError('문체 참고값과 같은 kiwipiepy==0.22.2를 사용하세요. 현재: ' + actual)
    if importlib.metadata.version('kiwipiepy_model') != '0.22.1':
        raise ImportError('문체 참고값과 같은 kiwipiepy_model==0.22.1을 사용하세요.')
    return Kiwi(num_workers=1)


def paragraphs(text):
    result, buffer, start, quote = [], [], 1, False
    def flush():
        if buffer:
            result.append({'line': start, 'quoted': quote, 'text': '\n'.join(buffer)})
    for line_no, line in enumerate(text.splitlines(), 1):
        if not line.strip() or re.match(r'^\s*#{1,6}\s', line):
            flush(); buffer = []
            continue
        is_quote = line.lstrip().startswith('>')
        if buffer and is_quote != quote:
            flush(); buffer = []
        if not buffer:
            start, quote = line_no, is_quote
        buffer.append(re.sub(r'^\s*>\s?', '', line) if is_quote else line)
    flush()
    return result


def extract(text, kiwi):
    sentences = kiwi.split_into_sents(text)
    tokens = [t for t in kiwi.tokenize(text) if t.tag not in PUNCT]
    tags = Counter(t.tag for t in tokens)
    words = Counter(t.form + '/' + t.tag for t in tokens if t.tag in CONTENT)
    n, count, content_n = len(tokens), len(sentences), sum(words.values())
    def ratio(a, b, scale=1):
        return scale*a/b if b else None
    values = {
        'sentence_chars': statistics.mean(len(s.text) for s in sentences) if sentences else None,
        'ec_per_sentence': ratio(tags['EC'], count),
        'comma_per_sentence': ratio(text.count(','), count),
        'etn_per1000': ratio(tags['ETN'], n, 1000),
        'etm_per1000': ratio(tags['ETM'], n, 1000),
        'repetition_pct': ratio(content_n-len(words), content_n, 100),
    }
    rates = {word: 1000*freq/content_n for word, freq in words.items()} if content_n else {}
    return {'metrics': values, 'lexical': rates, 'counts': {'morphs': n, 'sentences': count, 'content_morphs': content_n}}


def quantile(values, q):
    values = sorted(values)
    k = (len(values)-1)*q
    a, b = int(k), min(int(k)+1, len(values)-1)
    return values[a] + (values[b]-values[a])*(k-a)


def locate(value, values):
    return {'value': round(value, 4), 'reference_middle': round(quantile(values, .5), 4),
            'reference_middle_half': [round(quantile(values, .25), 4), round(quantile(values, .75), 4)],
            'percentile': round(100*(sum(v < value for v in values)+.5*sum(v == value for v in values))/len(values), 1)}


def get_examples(domain, document_type, query='', pattern=None, limit=3):
    # 예문은 같은 문서 종류를 우선하고, 없으면 같은 분야의 법률문서 예문을 사용한다.
    data = read_json(ROOT / 'data' / 'examples.json')
    pool = [x for x in data if x['domain'] == domain and (not pattern or pattern in x['patterns'])]
    rows = [x for x in pool if x['document_type'] == document_type] or pool
    terms = set(re.findall(r'[가-힣A-Za-z]{2,}', query))
    if terms:
        rows.sort(key=lambda r: (-sum(t in r['text'] for t in terms), r['key']))
    return [{'key': r['key'], 'document_type': r['document_type'], 'text': r['text']} for r in rows[:limit]]


def reference_group(groups, domain):
    # 참고 분포는 분야별 법률문서 공통 분포다. 분야 분포가 없으면 모든 분야를 합산한 분포를 사용한다.
    if domain in groups:
        return domain, groups[domain], 'matched'
    keys = sorted(groups)
    if not keys:
        raise ValueError('문체 참고 분포가 비어 있습니다.')
    metrics = {m: [v for k in keys for v in groups[k]['metrics'][m]] for m in groups[keys[0]]['metrics']}
    shared = set.intersection(*(set(groups[k]['lexical']) for k in keys))
    lexical = {t: [v for k in keys for v in groups[k]['lexical'][t]] for t in sorted(shared)}
    return 'combined:' + '+'.join(keys), {'metrics': metrics, 'lexical': lexical}, 'matched'


def inspect(text, domain, document_type, kiwi, profiles=None):
    if not text.strip():
        raise ValueError('측정할 본문을 제공하세요.')
    blocks = paragraphs(text)
    body = '\n\n'.join(p['text'] for p in blocks if not p['quoted'])
    quoted = '\n\n'.join(p['text'] for p in blocks if p['quoted'])
    if not body.strip():
        raise ValueError('문체 측정에 사용할 작성자 본문을 제공하세요.')
    features = extract(body, kiwi)
    data = profiles if profiles is not None else read_json(ROOT / 'data' / 'style_profiles.json')
    if data['extractor'] != EXTRACTOR:
        raise ValueError('현재 분석기와 일치하는 문체 참고값을 사용하세요.')
    group_key, group, reference = reference_group(data['groups'], domain)
    measurements, lexical = {}, []
    if group:
        for key, values in group['metrics'].items():
            value = features['metrics'][key]
            if value is not None and values:
                measurements[key] = dict(label=LABELS[key], **locate(value, values))
        for token, values in group['lexical'].items():
            if token in EXCLUDED_LEXICAL:
                continue
            item = dict(token=token, **locate(features['lexical'].get(token, 0), values))
            lexical.append(item)
        lexical.sort(key=lambda r: -abs(r['percentile']-50))
    per_paragraph = []
    for index, p in enumerate(blocks, 1):
        if not p['quoted']:
            per_paragraph.append({'paragraph': index, 'line': p['line'],
                                  'metrics': extract(p['text'], kiwi)['metrics']})
    signals = sorted((r for key, r in measurements.items() if key not in REFERENCE_ONLY),
                     key=lambda r: -abs(r['percentile']-50))[:3]
    return {
        'status': 'measured', 'reference': reference, 'reference_group': group_key,
        'metrics': features['metrics'], 'reference_positions': measurements,
        'review_signals': signals, 'lexical_positions': lexical[:5],
        'paragraphs': per_paragraph, 'quoted_metrics': extract(quoted, kiwi)['metrics'] if quoted else None,
        'examples': get_examples(domain, document_type, body),
        'next': '참고 위치와 예문을 읽고 문맥에 따라 수정하거나 유지하세요.',
        'text_sha256': digest(text),
    }


def main(argv=None):
    configure_console()
    p = argparse.ArgumentParser(description='문체 측정·예문 검색·수정 전후 대조')
    sub = p.add_subparsers(dest='command', required=True)
    check = sub.add_parser('check')
    check.add_argument('text')
    check.add_argument('--domain', choices=['civil', 'criminal', 'administrative'], required=True)
    check.add_argument('--document-type', default='judgment')
    check.add_argument('--before')
    check.add_argument('--anchors', help='보존할 이름·수치 등의 문자열 배열 JSON')
    check.add_argument('--output', required=True)
    find = sub.add_parser('examples')
    find.add_argument('--domain', choices=['civil', 'criminal', 'administrative'], required=True)
    find.add_argument('--document-type', default='judgment')
    find.add_argument('--query', default='')
    find.add_argument('--pattern')
    find.add_argument('--limit', type=int, choices=range(1, 6), default=3)
    args = p.parse_args(argv)
    try:
        if args.command == 'examples':
            emit({'examples': get_examples(args.domain, args.document_type, args.query, args.pattern, args.limit)})
        else:
            text = read_text(args.text)
            result = inspect(text, args.domain, args.document_type, analyzer())
            if args.before:
                result['revision'] = changes(read_text(args.before), text, read_json(args.anchors) if args.anchors else [])
            summary = {k: result[k] for k in ('status', 'reference', 'reference_group', 'review_signals', 'lexical_positions', 'next')}
            summary['paragraph_locations'] = [{'paragraph': r['paragraph'], 'line': r['line']} for r in result['paragraphs'][:5]]
            summary['examples'] = [{'text': x['text'][:1200], 'excerpt': len(x['text']) > 1200} for x in result['examples'][:2]]
            summary['detail_file'] = str(args.output)
            if 'revision' in result:
                revision = result['revision']
                values = {k: {direction: items[:10] for direction, items in v.items()}
                          for k, v in revision['changed_values'].items()}
                summary['revision'] = {'changed': revision['changed'], 'changed_values_preview': values,
                                       'anchor_changes_preview': revision['anchor_changes'][:10], 'next': revision['next']}
            emit(result, args.output, [args.text, args.before, args.anchors], summary)
        return 0
    except (ValueError, OSError, ImportError, KeyError, TypeError) as exc:
        emit(error_result(exc))
        return 2


if __name__ == '__main__':
    sys.exit(main())
