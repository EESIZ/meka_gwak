# 서식 확인

선택한 원본 서식과 제출 요구사항을 확인하고 필요한 항목만 `form.json`으로 정리한다. 작성문 전체는 본문 파일로 전달한다.

```json
{
  "document_type": "complaint",
  "source": "확인한 원본 서식 경로 또는 제출 요구사항 주소",
  "context": {"case_assigned": false},
  "fields": [
    {"name": "문서 표제", "value": "소장", "required": true},
    {"name": "제출처", "value": "사용자가 확인한 제출처", "required": true},
    {"name": "사건번호", "value": "", "required_if": {"case_assigned": true}}
  ]
}
```

예시 항목은 구조 설명용이다. 실제 필수·조건부 항목은 선택한 서식에서 구성한다. `value`는 실제 값으로 채운다. 조건의 값이 필요한 경우 사용자에게 확인한다. 항목에 값이 기재된 위치와 의미는 AI가 최종 파일에서 읽는다.

원본 서식의 상대 경로는 `form.json` 폴더를 기준으로 해석한다. 결과 파일은 원본 서식·본문·첨부와 구분하여 사용자 작업 폴더에 저장한다.

첨부가 있으면 `attachments.json`에 목록을 제공한다. 상대 경로는 이 목록 파일의 폴더를 기준으로 해석한다.

```json
[
  {"label": "갑 제1호증", "path": "attachments/evidence-1.pdf"},
  {"label": "갑 제2호증의 1", "path": "attachments/evidence-2-1.pdf"}
]
```

증거의 하위 번호는 실제 파일별로 적고, 증거 외 첨부는 문서에 표시한 명칭을 사용한다. 목록의 내용과 실제 첨부 내용은 AI가 확인한다.

본문의 쉼표·가운뎃점·‘및’으로 묶은 증거번호와 ‘내지’ 범위도 개별 번호로 대조한다. 해석이 필요한 표기는 확인 항목으로 전달한다. 최종 파일에서 추가된 증거 참조는 첨부 목록과 함께 읽는다.

```sh
PYTHON "<skill>/scripts/format_check.py" "final.docx" --body "revised.txt" --form "form.json" --attachments "attachments.json" --output "format-result.json"
```

첨부가 없는 과제는 `--attachments`를 생략한다. 원본과 본문 파일은 보존하고 결과 파일 경로는 별도로 지정한다.

## 파일 확인

- TXT·MD: 중간 본문과 항목 대조에 사용한다.
- DOCX: 본문 XML의 문단·표 텍스트를 추출한다. 머리말·꼬리말·각주·도형·서명·배치는 최종 페이지에서 확인한다.
- HWPX: 본문 section의 문단 텍스트를 읽고 최종 페이지로 대조한다.
- PDF: 텍스트를 추출하고 비어 있는 페이지를 표시한다. 스캔·복잡한 표·읽기 순서는 페이지 또는 OCR 결과로 확인한다.
- HWP 및 기타 형식: 문서 도구로 DOCX·HWPX·PDF 확인본을 생성하고 원본과 함께 확인한다.

본문 대조는 공백을 정규화하여 문단이 순서대로 유지되는지 확인한다. 변환 중 번호·쪽 표시가 끼거나 표의 읽기 순서가 달라진 곳은 실제 페이지로 확인한다. 스크립트 대조 후 AI가 문서 전체의 항목 의미·첨부·표·겹침·잘림을 확인하고 사용자에게 제출 결정을 받는다.
