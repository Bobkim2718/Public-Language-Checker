from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests

from .paths import PACKAGE_DATA_DIR, user_data_dir


class DataStoreError(RuntimeError):
    pass


class DataStore:
    def __init__(self) -> None:
        self.user_dir = user_data_dir()
        self.user_terms_path = self.user_dir / "user_terms.json"
        self.synced_bundle_path = self.user_dir / "synced_bundle.json"

    def _read_json(self, path: Path, default: Any) -> Any:
        if not path.exists():
            return default
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise DataStoreError(f"데이터 파일을 읽을 수 없습니다: {path.name}") from exc

    def load_rules(self) -> dict:
        base = self._read_json(PACKAGE_DATA_DIR / "rules.json", {})
        synced = self._read_json(self.synced_bundle_path, {})
        if isinstance(synced, dict) and isinstance(synced.get("rules"), dict):
            base = _deep_merge(base, synced["rules"])
        return base

    def load_terms(self) -> list[dict]:
        terms: list[dict] = []
        terms.extend(self._read_json(PACKAGE_DATA_DIR / "default_terms.json", []))

        synced = self._read_json(self.synced_bundle_path, {})
        if isinstance(synced, dict):
            terms.extend(synced.get("terms", []) or [])

        terms.extend(self._read_json(self.user_terms_path, []))

        merged: dict[str, dict] = {}
        for item in terms:
            if not isinstance(item, dict):
                continue
            term = str(item.get("term", "")).strip()
            if term:
                merged[term] = item
        return list(merged.values())

    def add_user_term(
        self,
        term: str,
        alternatives: list[str],
        severity: str = "review",
        note: str = "",
    ) -> None:
        items = self._read_json(self.user_terms_path, [])
        items = [x for x in items if x.get("term") != term]
        items.append(
            {
                "term": term,
                "alternatives": alternatives,
                "severity": severity,
                "source": "사용자 사전",
                "note": note,
            }
        )
        self.user_terms_path.write_text(
            json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def current_bundle_version(self) -> str | None:
        bundle = self._read_json(self.synced_bundle_path, {})
        if isinstance(bundle, dict):
            value = bundle.get("version")
            return str(value) if value is not None else None
        return None

    def install_update_bundle(self, bundle: dict) -> str:
        _validate_bundle(bundle)
        self.synced_bundle_path.write_text(
            json.dumps(bundle, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return str(bundle.get("version", "버전 정보 없음"))

    def import_update_bundle(self, path: str | Path) -> str:
        source = Path(path)
        bundle = self._read_json(source, None)
        return self.install_update_bundle(bundle)

    def check_managed_update(self, timeout: float = 10.0) -> tuple[bool, str]:
        config = self._read_json(PACKAGE_DATA_DIR / "update_sources.json", {})
        manifest_url = config.get("managed_update_manifest")
        if not manifest_url:
            raise DataStoreError(
                "관리형 업데이트 주소가 아직 설정되지 않았습니다. "
                "현재는 [업데이트 파일 가져오기]로 오프라인 업데이트를 사용할 수 있습니다."
            )

        _require_https(manifest_url, "업데이트 manifest")
        response = requests.get(
            manifest_url,
            timeout=timeout,
            headers={"User-Agent": "PublicLanguageChecker/0.1"},
        )
        response.raise_for_status()

        try:
            manifest = response.json()
        except ValueError as exc:
            raise DataStoreError("업데이트 manifest를 JSON으로 해석하지 못했습니다.") from exc

        if not isinstance(manifest, dict):
            raise DataStoreError("업데이트 manifest 형식이 올바르지 않습니다.")

        version = str(manifest.get("version", "")).strip()
        bundle_url = str(manifest.get("bundle_url", "")).strip()
        expected_sha256 = str(manifest.get("sha256", "")).strip().lower()

        if not version or not bundle_url:
            raise DataStoreError("업데이트 manifest에 version 또는 bundle_url이 없습니다.")

        if version == self.current_bundle_version():
            return False, version

        _require_https(bundle_url, "업데이트 번들")
        bundle_response = requests.get(
            bundle_url,
            timeout=timeout,
            headers={"User-Agent": "PublicLanguageChecker/0.1"},
        )
        bundle_response.raise_for_status()
        raw = bundle_response.content

        if expected_sha256:
            actual = hashlib.sha256(raw).hexdigest()
            if actual != expected_sha256:
                raise DataStoreError("업데이트 파일 무결성(SHA-256) 검증에 실패했습니다.")

        try:
            bundle = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise DataStoreError("업데이트 번들을 JSON으로 해석하지 못했습니다.") from exc

        installed = self.install_update_bundle(bundle)
        if installed != version:
            raise DataStoreError(
                f"manifest 버전({version})과 번들 버전({installed})이 일치하지 않습니다."
            )
        return True, installed

    def lookup_official_api(self, keyword: str, timeout: float = 8.0) -> list[dict]:
        config = self._read_json(PACKAGE_DATA_DIR / "update_sources.json", {})
        endpoint = config.get("official_keyword_api")
        if not endpoint:
            raise DataStoreError("공식 API 주소가 설정되어 있지 않습니다.")

        response = requests.get(
            endpoint,
            params={"keyword": keyword},
            timeout=timeout,
            headers={"User-Agent": "PublicLanguageChecker/0.1"},
        )
        response.raise_for_status()

        try:
            payload = response.json()
        except ValueError as exc:
            raise DataStoreError("공식 API 응답을 JSON으로 해석하지 못했습니다.") from exc

        if isinstance(payload, list):
            return [x for x in payload if isinstance(x, dict)]
        if isinstance(payload, dict):
            for key in ("data", "result", "items", "list"):
                value = payload.get(key)
                if isinstance(value, list):
                    return [x for x in value if isinstance(x, dict)]
            return [payload]
        return []


def _validate_bundle(bundle: Any) -> None:
    if not isinstance(bundle, dict):
        raise DataStoreError("업데이트 파일은 JSON 객체여야 합니다.")
    if "version" not in bundle:
        raise DataStoreError("업데이트 파일에 version 항목이 없습니다.")
    if "terms" in bundle and not isinstance(bundle["terms"], list):
        raise DataStoreError("terms 항목은 목록이어야 합니다.")
    if "rules" in bundle and not isinstance(bundle["rules"], dict):
        raise DataStoreError("rules 항목은 객체여야 합니다.")


def _deep_merge(base: dict, incoming: dict) -> dict:
    result = dict(base)
    for key, value in incoming.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def _require_https(url: str, label: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme.lower() != "https":
        raise DataStoreError(f"{label} 주소는 HTTPS여야 합니다.")
