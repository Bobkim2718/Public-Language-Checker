# 공공언어 검사기 (Public Language Checker)

공공기관 내부 문서를 Windows PC에서 로컬 분석하여 **공공언어 적합도**와 개선 후보를 제시하는 데스크톱 앱입니다.

평가 구조는 ‘쉬운 우리말을 쓰자’의 **쉬운 공문서 쓰기 작성 원칙**을 참고해 다음 4개 영역으로 구성했습니다.

- 알기 쉬운 용어: 35점
- 알기 쉬운 문장: 35점
- 어문규범: 20점
- 한글 사용: 10점

> 표시되는 100점 점수는 정부기관의 공식 평가 점수가 아니라 작성 원칙을 바탕으로 한 자체 분석 점수입니다.

## 현재 MVP 기능

- Windows 데스크톱 UI(PySide6)
- 문서 드래그앤드롭
- HWPX / DOCX / PDF / TXT 텍스트 추출
- 텍스트 직접 붙여넣기
- 4대 영역 점수와 총점
- 변경 권장 / 검토 권장 / 참고 분류
- 100자 초과 장문, 복잡한 연결 표현, 영문 직접 사용 등 규칙 기반 검사
- 업데이트 가능한 용어 사전
- 사용자 사전
- 오프라인 JSON 업데이트 번들
- 관리형 HTTPS 업데이트 manifest 연결 지점
- ‘쉬운 우리말을 쓰자’ 공개 API 낱말 조회
- GitHub Actions Windows 테스트
- GitHub Actions 단일 EXE 빌드

## 개인정보 보호 원칙

기본 검사는 PC 내부에서 수행합니다.

- HWPX/DOCX/PDF/TXT 원문: 외부 서버 전송 없음
- 로컬 사전/규칙 검사: 외부 서버 전송 없음
- 공식 API 낱말 조회: 사용자가 직접 입력한 **낱말만** API로 전송
- 향후 AI 문장 개선 기능은 기본 기능과 분리하여 명시적 선택 기능으로 추가 예정

## 실행

Python 3.12 권장.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python run.py
```

## Windows EXE 만들기

GitHub의 **Actions → build-windows → Run workflow**를 실행하면
`PublicLanguageChecker-Windows` 아티팩트로 EXE를 받을 수 있습니다.

로컬 빌드:

```powershell
pyinstaller --noconfirm --clean --onefile --windowed --name PublicLanguageChecker --add-data "data;data" run.py
```

## 사전·규칙 업데이트 구조

프로그램 코드를 다시 설치하지 않아도 검사 데이터를 갱신할 수 있도록 실행 파일과 데이터를 분리했습니다.

### 1. 기본 데이터

- `data/default_terms.json`: 앱에 포함된 초기 용어
- `data/rules.json`: 점수 배점과 문장 검사 기준
- `data/update_sources.json`: 공식 API와 관리형 업데이트 주소

초기 용어 데이터는 **기능 시연용 seed 데이터**입니다. 공식 공개 API와 대조해 검증·확장하는 작업이 다음 단계에 포함됩니다.

### 2. 사용자 사전

앱의 **사용자 용어 추가** 기능으로 등록한 데이터는 Windows 사용자 AppData 영역에 저장됩니다.

따라서 앱을 새 버전으로 교체해도 사용자 사전을 유지할 수 있습니다.

### 3. 오프라인 업데이트

보안망 또는 인터넷 사용이 제한된 기관은 관리자가 JSON 업데이트 파일을 배포할 수 있습니다.

예제:

`updates/example_bundle.json`

형식:

```json
{
  "version": "2026.10.07",
  "terms": [
    {
      "term": "외국어",
      "alternatives": ["쉬운 표현"],
      "severity": "review",
      "source": "자료 출처"
    }
  ],
  "rules": {
    "sentence": {
      "recommended_max_chars": 100
    }
  }
}
```

앱에서 **업데이트 파일 가져오기**를 누르면 반영됩니다.

### 4. 관리형 온라인 업데이트

`data/update_sources.json`의 `managed_update_manifest`에 기관이 관리하는 HTTPS manifest 주소를 넣으면 **온라인 업데이트 확인** 기능을 사용할 수 있습니다.

manifest 예:

```json
{
  "version": "2026.11.01",
  "bundle_url": "https://example.go.kr/public-language/bundle-2026.11.01.json",
  "sha256": "..."
}
```

앱은 다음을 확인합니다.

1. 현재 버전과 새 버전 비교
2. HTTPS 주소 확인
3. 업데이트 번들 다운로드
4. SHA-256 값이 제공된 경우 무결성 검증
5. 사전과 문장 규칙을 동시에 업데이트

이 구조를 통해 **새 외국어·외래어, 권장 대체어, 문장 길이 기준, 새로운 문장 검사 규칙** 등을 앱 재설치 없이 계속 갱신할 수 있습니다.

## 공식 공개 API

낱말 검색용 API 주소는 설정 파일에서 관리합니다.

```text
https://plainkorean.kr/api.jsp?keyword=검색어
```

현재 MVP에서는 전체 문서 원문을 API에 보내지 않습니다.

## 점수 계산

현재 점수 체계:

| 영역 | 만점 |
|---|---:|
| 알기 쉬운 용어 | 35 |
| 알기 쉬운 문장 | 35 |
| 어문규범 | 20 |
| 한글 사용 | 10 |
| 합계 | 100 |

현재 버전은 규칙 기반 MVP이므로, 특히 **어문규범과 문맥에 따른 자연스러운 대체 표현 판단**은 향후 고도화가 필요합니다.

## 로드맵

### 0.1 MVP
- [x] Windows 데스크톱 UI
- [x] HWPX/DOCX/PDF/TXT
- [x] 공공언어 적합도
- [x] 사전/규칙 분리
- [x] 사용자 사전
- [x] 오프라인 업데이트
- [x] 온라인 관리형 업데이트 구조
- [x] 공식 API 개별 낱말 조회

### 다음 단계
- [ ] 공식 쉬운 우리말 사전 데이터 확충 및 검증
- [ ] API 응답 스키마 실데이터 테스트
- [ ] 문제 표현 원문 하이라이트 및 위치 이동
- [ ] 검사 결과 Excel/PDF 내보내기
- [ ] HWPX/DOCX 수정본 생성
- [ ] 문장 호응/수식 관계 고도화
- [ ] 기관 공통 사용자 사전 배포
- [ ] 선택형 AI 문장 개선
- [ ] 코드 서명 및 기관 배포 패키지
