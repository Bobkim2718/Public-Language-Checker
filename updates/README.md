# 사전·규칙 업데이트 운영

이 폴더는 설치된 공공언어 검사기의 **관리형 데이터 업데이트 채널**입니다.

## 파일

- `manifest.json`: 현재 배포 버전과 번들 주소/무결성 값
- `managed_bundle.json`: 실제 추가 용어와 규칙
- `example_bundle.json`: 오프라인 배포 예시

## 새 용어/규칙 배포 절차

1. `managed_bundle.json`의 `version`을 올립니다.
2. `terms` 또는 `rules`를 수정합니다.
3. 파일의 UTF-8 바이트 기준 SHA-256을 계산합니다.
4. `manifest.json`의 `version`과 `sha256`을 같은 값으로 갱신합니다.
5. main 브랜치에 반영합니다.
6. 설치된 앱에서 **온라인 업데이트 확인**을 실행합니다.

예시 PowerShell:

```powershell
(Get-FileHash .\updates\managed_bundle.json -Algorithm SHA256).Hash.ToLower()
```

## 용어 형식

```json
{
  "term": "검토할 표현",
  "alternatives": ["권장 표현 1", "권장 표현 2"],
  "severity": "change",
  "source": "근거 자료",
  "note": "문맥상 주의사항"
}
```

`severity` 값:

- `change`: 변경 권장
- `review`: 검토 권장
- `reference`: 참고

## 문장 규칙 형식

현재 MVP에서 바로 반영되는 규칙 예:

```json
{
  "rules": {
    "sentence": {
      "recommended_max_chars": 100,
      "severe_max_chars": 150
    }
  }
}
```

검사 엔진에 새로운 규칙 종류가 추가되면 동일한 업데이트 번들에서 해당 기준값을 배포할 수 있습니다.

## 공공기관 망

GitHub Raw 접속이 제한된 경우 `managed_bundle.json`을 내부망으로 배포한 뒤 앱의 **업데이트 파일 가져오기**를 사용합니다.
