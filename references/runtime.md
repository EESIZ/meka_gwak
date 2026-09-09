# 실행 방법

스킬 폴더를 기준으로 경로를 지정한다. 작업 파일은 사용자 작업 폴더에 둔다. 본문은 UTF-8 텍스트로 저장하고 실제 문단 사이에 빈 줄을 둔다. Markdown 제목은 구분하여 집계하고, `>` 인용 블록은 별도로 측정한다. 본문 안의 직접 인용도 문체 분리 측정이 필요하면 인용 블록으로 표시한다.

## 실행 환경

Python 3.10 이상을 사용한다. 처음 실행할 때 사용자 작업 폴더에 가상환경을 준비하고 의존성을 설치한다.

```sh
python -m venv "<work>/.legal-writing-venv"
```

Windows에서는 `<work>/.legal-writing-venv/Scripts/python.exe`, macOS·Linux에서는 `<work>/.legal-writing-venv/bin/python`을 아래 `PYTHON` 위치에 사용한다. 설치는 초기 한 번 수행한다.

```sh
PYTHON -m pip install --no-cache-dir -r "<skill>/requirements.txt"
```

## 예문 검색

```sh
PYTHON "<skill>/scripts/style_check.py" examples --domain administrative --document-type judgment --query "요건 사실 판단" --limit 2
```

필요하면 `--pattern P01`처럼 [전개 방식](logic.md)의 키를 지정한다. 예문의 법리를 현재 사건에 사용하려면 3번 판례 원문 확인을 거친다.

## 문체 측정

```sh
PYTHON "<skill>/scripts/style_check.py" check "draft.txt" --domain administrative --document-type judgment --output "style-before.json"
PYTHON "<skill>/scripts/style_check.py" check "revised.txt" --domain administrative --document-type judgment --before "draft.txt" --output "style-after.json"
```

- 분야: `civil`, `criminal`, `administrative`.
- 문서 종류: `judgment`, `complaint`, `brief`, `opinion` 등 실제 역할에 맞는 이름.
- `reference: matched`는 같은 문서 종류·분야의 참고 집단을 사용했다는 뜻이다. `domain_reference`는 같은 문서 종류의 분포가 없어 같은 분야 법률문서의 공통 분포(`reference_group`에 표시)를 참고한 상태다. `examples_or_user_reference_required`는 분야에도 분포가 없어 문맥 예문 중심으로 검토할 상태다.
- 예문 검색도 같은 문서 종류의 예문이 없으면 같은 분야의 법률문서 예문을 제공하고, 각 예문에 `document_type`을 표시한다.
- `--anchors values.json`에는 보존할 당사자 이름·문구 등의 문자열 배열을 제공할 수 있다.
- 화면에는 짧은 측정 결과를 표시한다. 전체 변경 구간과 예문 문맥은 `--output` 파일에서 확인한다.

통계는 전체 문서의 참고 위치로 읽는다. 형태소 기준 빈도는 1,000개당, 연결어미·쉼표는 문장당, 반복은 내용 형태소 기준 비율이다. 문단별 값은 위치를 찾아 읽는 보조 정보다.

## 상태와 복구

`measured`와 `mechanical_checks_complete`는 각각 측정과 기계적 대조의 완료다. AI는 의미와 페이지 확인을 이어간다. `needs_review`는 보완할 항목을 읽고 처리하는 상태다. `tool_required`와 `input_error`는 본문을 보존하고 환경·입력을 확인하는 상태다.

프로그램 종료 코드 0은 결과 생성 완료, 2는 도구·입력 확인 요청이다. 작성 중단·재개는 실제 결과와 작성 지침에 따라 판단한다.
