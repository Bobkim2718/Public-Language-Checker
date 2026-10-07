from __future__ import annotations

import gc
import time
import tracemalloc

from app.analyzer import PublicLanguageAnalyzer
from app.data_store import DataStore


CLEAN_LINE = (
    "본 사업은 학생의 학습 활동을 지원한다. "
    "운영 결과를 정리하여 다음 계획에 반영한다.\n"
)
ISSUE_LINE = "사업 진행 상황을 모니터링하고 피드백을 정리한다.\n"
BLOCK = CLEAN_LINE * 80 + ISSUE_LINE


def make_text(target_mb: float) -> str:
    target_bytes = int(target_mb * 1024 * 1024)
    block_bytes = len(BLOCK.encode("utf-8"))
    repeats = max(1, target_bytes // block_bytes + 1)
    text = BLOCK * repeats

    # 대략 목표 UTF-8 용량까지 문자 단위로 줄인다.
    ratio = min(1.0, target_bytes / max(1, len(text.encode("utf-8"))))
    text = text[: max(1, int(len(text) * ratio))]
    return text


def measure_one(analyzer: PublicLanguageAnalyzer, target_mb: float) -> dict:
    gc.collect()
    tracemalloc.start()
    text = make_text(target_mb)
    actual_bytes = len(text.encode("utf-8"))

    started = time.perf_counter()
    result = analyzer.analyze(text)
    elapsed = time.perf_counter() - started
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    row = {
        "target_mb": target_mb,
        "actual_mb": actual_bytes / 1024 / 1024,
        "chars": len(text),
        "seconds": elapsed,
        "peak_mb": peak / 1024 / 1024,
        "issues": result.stats.get("issues", 0),
    }
    del result
    del text
    gc.collect()
    return row


def measure_batch(analyzer: PublicLanguageAnalyzer, files: int, each_mb: float) -> dict:
    gc.collect()
    tracemalloc.start()
    texts = [make_text(each_mb) for _ in range(files)]
    total_bytes = sum(len(x.encode("utf-8")) for x in texts)

    started = time.perf_counter()

    retained = []
    for text in texts:
        retained.append((text, analyzer.analyze(text)))

    elapsed = time.perf_counter() - started
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    total_issues = sum(result.stats.get("issues", 0) for _, result in retained)
    row = {
        "files": files,
        "each_mb": each_mb,
        "total_mb": total_bytes / 1024 / 1024,
        "seconds": elapsed,
        "peak_mb": peak / 1024 / 1024,
        "issues": total_issues,
    }

    del retained
    del texts
    gc.collect()
    return row


def main() -> None:
    store = DataStore()
    analyzer = PublicLanguageAnalyzer(store.load_terms(), store.load_rules())

    print("=== SINGLE DOCUMENT BENCHMARK ===")
    print("target_MB\tactual_MB\tchars\tseconds\tpeak_MB\tissues")
    for size in (0.1, 0.5, 1, 2, 5, 10):
        row = measure_one(analyzer, size)
        print(
            f"{row['target_mb']}\t{row['actual_mb']:.2f}\t{row['chars']}\t"
            f"{row['seconds']:.3f}\t{row['peak_mb']:.2f}\t{row['issues']}"
        )

    print("=== 20 FILE BATCH BENCHMARK ===")
    print("files\teach_MB\ttotal_MB\tseconds\tpeak_MB\tissues")
    for each_mb in (0.5, 1.0):
        row = measure_batch(analyzer, 20, each_mb)
        print(
            f"{row['files']}\t{row['each_mb']}\t{row['total_mb']:.2f}\t"
            f"{row['seconds']:.3f}\t{row['peak_mb']:.2f}\t{row['issues']}"
        )


if __name__ == "__main__":
    main()
