from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, QThread, Qt, Signal, Slot
from PySide6.QtGui import QDragEnterEvent, QDropEvent, QTextCursor
from PySide6.QtWidgets import (
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMainWindow,
    QMessageBox,
    QProgressDialog,
    QPushButton,
    QSplitter,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from .analyzer import PublicLanguageAnalyzer
from .batch import (
    MAX_BATCH_FILES,
    BatchLimitError,
    analyze_files,
    format_bytes,
    select_batch_files,
    validate_source_sizes,
)
from .data_store import DataStore, DataStoreError
from .document_loader import DocumentLoadError, SUPPORTED_EXTENSIONS, load_document
from .drop_utils import supported_files
from .models import AnalysisResult, BatchDocumentResult, Issue


class DocumentTextEdit(QTextEdit):
    """파일 드롭은 경로 문자열 삽입 대신 실제 문서 열기로 전달한다."""

    filesDropped = Signal(object)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            local_paths = [
                url.toLocalFile()
                for url in event.mimeData().urls()
                if url.isLocalFile()
            ]
            files = supported_files(local_paths, SUPPORTED_EXTENSIONS)
            if files:
                event.acceptProposedAction()
                return
        super().dragEnterEvent(event)

    def dropEvent(self, event: QDropEvent) -> None:
        if event.mimeData().hasUrls():
            local_paths = [
                url.toLocalFile()
                for url in event.mimeData().urls()
                if url.isLocalFile()
            ]
            files = supported_files(local_paths, SUPPORTED_EXTENSIONS)
            if files:
                self.filesDropped.emit(files)
                event.acceptProposedAction()
                return
        super().dropEvent(event)


class BatchWorker(QObject):
    progress = Signal(int, int, str)
    finished = Signal(object)
    failed = Signal(str)

    def __init__(self, paths: list[Path], terms: list[dict], rules: dict) -> None:
        super().__init__()
        self.paths = paths
        self.terms = terms
        self.rules = rules

    @Slot()
    def run(self) -> None:
        try:
            analyzer = PublicLanguageAnalyzer(self.terms, self.rules)
            results = analyze_files(
                self.paths,
                analyzer,
                progress=lambda done, total, name: self.progress.emit(done, total, name),
            )
            self.finished.emit(results)
        except Exception as exc:
            self.failed.emit(str(exc))


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.store = DataStore()
        self.current_path: Path | None = None
        self.current_issues: list[Issue] = []
        self.batch_results: list[BatchDocumentResult] = []
        self.batch_thread: QThread | None = None
        self.batch_worker: BatchWorker | None = None
        self.batch_progress: QProgressDialog | None = None

        self.setWindowTitle("공공언어 검사기 v2.3")
        self.resize(1460, 900)
        self.setAcceptDrops(True)

        self.editor = DocumentTextEdit()
        self.editor.filesDropped.connect(self.handle_dropped_files)
        self.editor.setPlaceholderText(
            "문서를 끌어 놓거나 [문서 열기]를 누르세요.\n"
            "2개 이상 파일을 한 번에 놓으면 파일 비교 분석을 시작합니다.\n"
            "텍스트를 직접 붙여 넣고 검사할 수도 있습니다."
        )

        self.score_label = QLabel("—")
        self.score_label.setAlignment(Qt.AlignCenter)
        score_font = self.score_label.font()
        score_font.setPointSize(34)
        score_font.setBold(True)
        self.score_label.setFont(score_font)

        self.score_caption = QLabel("공공언어 적합도 / 100")
        self.score_caption.setAlignment(Qt.AlignCenter)

        self.category_form = QFormLayout()
        self.category_labels: dict[str, QLabel] = {}
        for category, maximum in [
            ("알기 쉬운 용어", 35),
            ("알기 쉬운 문장", 35),
            ("어문규범", 20),
            ("한글 사용", 10),
        ]:
            label = QLabel(f"— / {maximum}")
            self.category_labels[category] = label
            self.category_form.addRow(category, label)

        self.dictionary_label = QLabel(self.store.dictionary_summary())
        self.dictionary_label.setWordWrap(True)

        self.summary_label = QLabel("검사 전")
        self.summary_label.setWordWrap(True)

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(
            ["등급", "영역", "문제", "개선안", "출처", "문맥"]
        )
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setWordWrap(True)
        self.table.setAlternatingRowColors(True)
        self.table.cellClicked.connect(self.jump_to_issue)

        self.batch_summary_label = QLabel(
            f"한 번에 최대 {MAX_BATCH_FILES}개 문서를 비교할 수 있습니다."
        )
        self.batch_summary_label.setWordWrap(True)

        self.batch_table = QTableWidget(0, 10)
        self.batch_table.setHorizontalHeaderLabels(
            [
                "파일명",
                "파일 크기",
                "본문 글자",
                "총점",
                "용어 /35",
                "문장 /35",
                "어문 /20",
                "한글 /10",
                "개선 후보",
                "처리 시간",
            ]
        )
        self.batch_table.horizontalHeader().setStretchLastSection(True)
        self.batch_table.setAlternatingRowColors(True)
        self.batch_table.setWordWrap(False)
        self.batch_table.cellDoubleClicked.connect(self.show_batch_detail)

        open_button = QPushButton("문서 열기")
        open_button.clicked.connect(self.open_document)

        batch_button = QPushButton("여러 문서 비교")
        batch_button.clicked.connect(self.open_documents_for_compare)

        analyze_button = QPushButton("검사하기")
        analyze_button.clicked.connect(self.analyze)

        update_button = QPushButton("업데이트 파일 가져오기")
        update_button.clicked.connect(self.import_update)

        online_update_button = QPushButton("검사 기준 업데이트 확인")
        online_update_button.clicked.connect(self.check_online_update)

        term_button = QPushButton("사용자 용어 추가")
        term_button.clicked.connect(self.add_user_term)

        api_button = QPushButton("공식 API 상세 조회")
        api_button.clicked.connect(self.lookup_api)

        detail_button = QPushButton("선택 문서 상세 보기")
        detail_button.clicked.connect(self.show_selected_batch_detail)

        top_buttons = QHBoxLayout()
        for button in (
            open_button,
            batch_button,
            analyze_button,
            update_button,
            online_update_button,
            term_button,
            api_button,
        ):
            top_buttons.addWidget(button)
        top_buttons.addStretch(1)

        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.addWidget(QLabel("문서 원문"))
        left_layout.addWidget(self.editor)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.addWidget(self.score_label)
        right_layout.addWidget(self.score_caption)
        right_layout.addLayout(self.category_form)
        right_layout.addWidget(self.dictionary_label)
        right_layout.addWidget(self.summary_label)
        right_layout.addWidget(QLabel("개선 후보 · 항목을 클릭하면 원문 위치로 이동합니다."))
        right_layout.addWidget(self.table, 1)

        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(left)
        splitter.addWidget(right)
        splitter.setSizes([680, 760])

        self.detail_page = QWidget()
        detail_layout = QVBoxLayout(self.detail_page)
        detail_layout.setContentsMargins(0, 0, 0, 0)
        detail_layout.addWidget(splitter)

        self.batch_page = QWidget()
        batch_layout = QVBoxLayout(self.batch_page)
        batch_layout.addWidget(self.batch_summary_label)
        batch_layout.addWidget(self.batch_table, 1)
        batch_footer = QHBoxLayout()
        batch_footer.addWidget(detail_button)
        batch_footer.addStretch(1)
        batch_layout.addLayout(batch_footer)

        self.tabs = QTabWidget()
        self.tabs.addTab(self.detail_page, "문서 상세")
        self.tabs.addTab(self.batch_page, "파일 비교")

        title = QLabel("공공언어 검사기 v2.3")
        title_font = title.font()
        title_font.setPointSize(19)
        title_font.setBold(True)
        title.setFont(title_font)

        subtitle = QLabel(
            "‘쉬운 공문서 쓰기’ 작성 원칙과 쉬운 우리말 공식 사전 스냅샷을 바탕으로 "
            "문서를 로컬에서 분석합니다. 최대 20개 문서의 결과를 한 화면에서 비교할 수 있습니다."
        )
        subtitle.setWordWrap(True)

        privacy = QLabel(
            "🔒 기본 로컬 검사 모드 · 문서 원문은 외부 서버로 전송하지 않습니다. "
            "공식 API 상세 조회를 실행할 때만 선택한 낱말 또는 직접 입력한 낱말을 전송합니다."
        )
        privacy.setWordWrap(True)

        root = QWidget()
        layout = QVBoxLayout(root)
        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addLayout(top_buttons)
        layout.addWidget(self.tabs, 1)
        layout.addWidget(privacy)
        self.setCentralWidget(root)

    def refresh_analyzer(self) -> PublicLanguageAnalyzer:
        return PublicLanguageAnalyzer(self.store.load_terms(), self.store.load_rules())

    def refresh_dictionary_label(self) -> None:
        self.dictionary_label.setText(self.store.dictionary_summary())

    def open_document(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "공공언어 검사 문서 열기",
            "",
            "지원 문서 (*.hwpx *.docx *.pdf *.txt);;모든 파일 (*.*)",
        )
        if path:
            self._load_path(Path(path))

    def open_documents_for_compare(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(
            self,
            f"비교할 문서 선택 - 최대 {MAX_BATCH_FILES}개",
            "",
            "지원 문서 (*.hwpx *.docx *.pdf *.txt);;모든 파일 (*.*)",
        )
        if paths:
            self.start_batch_analysis(paths)

    @Slot(object)
    def handle_dropped_files(self, files: object) -> None:
        paths = [str(x) for x in (files or [])]
        if not paths:
            return
        if len(paths) == 1:
            self._load_path(Path(paths[0]))
        else:
            self.start_batch_analysis(paths)

    def _load_path(self, path: Path) -> None:
        try:
            text = load_document(path)
        except DocumentLoadError as exc:
            QMessageBox.critical(self, "문서 열기 실패", str(exc))
            return

        self.current_path = path
        self.editor.setPlainText(text)
        self.statusBar().showMessage(f"불러옴: {path.name}")
        self.tabs.setCurrentWidget(self.detail_page)
        self.analyze()

    def analyze(self) -> None:
        text = self.editor.toPlainText()
        if not text.strip():
            QMessageBox.information(
                self, "검사할 내용 없음", "문서를 열거나 텍스트를 입력해 주세요."
            )
            return

        try:
            result = self.refresh_analyzer().analyze(text)
        except DataStoreError as exc:
            QMessageBox.critical(self, "데이터 오류", str(exc))
            return

        self._render_result(result)

    def _render_result(self, result: AnalysisResult) -> None:
        self.current_issues = result.issues
        self.score_label.setText(str(result.total_score))

        maximums = {
            "알기 쉬운 용어": 35,
            "알기 쉬운 문장": 35,
            "어문규범": 20,
            "한글 사용": 10,
        }
        for category, label in self.category_labels.items():
            label.setText(f"{result.scores.get(category, 0)} / {maximums[category]}")

        self.summary_label.setText(
            f"총 개선 후보 {result.stats.get('issues', 0)}건 · "
            f"공식 사전 {result.stats.get('official_unique', 0)}종/"
            f"{result.stats.get('official_hits', 0)}회 · "
            f"변경 권장 {result.stats.get('change', 0)}건 · "
            f"검토 권장 {result.stats.get('review', 0)}건 · "
            f"참고 {result.stats.get('reference', 0)}건"
        )

        self.table.setRowCount(len(result.issues))
        for row, issue in enumerate(result.issues):
            values = [
                issue.severity,
                issue.category,
                issue.message,
                issue.suggestion,
                issue.evidence,
                issue.sentence,
            ]
            for col, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setToolTip(value or issue.sentence)
                self.table.setItem(row, col, item)
        self.table.resizeRowsToContents()

    def start_batch_analysis(self, raw_paths: list[str]) -> None:
        paths = select_batch_files(raw_paths)

        if not paths:
            QMessageBox.information(
                self, "분석할 파일 없음", "지원되는 문서를 찾지 못했습니다."
            )
            return

        if len(raw_paths) > MAX_BATCH_FILES:
            QMessageBox.information(
                self,
                "파일 수 제한",
                f"한 번에 최대 {MAX_BATCH_FILES}개까지 분석합니다. "
                f"앞의 {MAX_BATCH_FILES}개 파일만 선택했습니다.",
            )

        if len(paths) == 1:
            self._load_path(paths[0])
            return

        try:
            validate_source_sizes(paths)
            terms = self.store.load_terms()
            rules = self.store.load_rules()
        except (BatchLimitError, DataStoreError, OSError) as exc:
            QMessageBox.critical(self, "배치 분석 불가", str(exc))
            return

        if self.batch_thread is not None and self.batch_thread.isRunning():
            QMessageBox.information(
                self, "분석 중", "현재 진행 중인 파일 비교 분석이 끝난 뒤 다시 시도해 주세요."
            )
            return

        self.batch_progress = QProgressDialog(
            "문서를 분석하고 있습니다.",
            "",
            0,
            len(paths),
            self,
        )
        self.batch_progress.setWindowTitle("파일 비교 분석")
        self.batch_progress.setCancelButton(None)
        self.batch_progress.setWindowModality(Qt.WindowModal)
        self.batch_progress.setMinimumDuration(0)
        self.batch_progress.setValue(0)

        self.batch_thread = QThread(self)
        self.batch_worker = BatchWorker(paths, terms, rules)
        self.batch_worker.moveToThread(self.batch_thread)

        self.batch_thread.started.connect(self.batch_worker.run)
        self.batch_worker.progress.connect(self._update_batch_progress)
        self.batch_worker.finished.connect(self._batch_finished)
        self.batch_worker.failed.connect(self._batch_failed)
        self.batch_worker.finished.connect(self.batch_thread.quit)
        self.batch_worker.failed.connect(self.batch_thread.quit)
        self.batch_thread.finished.connect(self._cleanup_batch_thread)

        self.batch_thread.start()

    @Slot(int, int, str)
    def _update_batch_progress(self, done: int, total: int, name: str) -> None:
        if self.batch_progress is None:
            return
        self.batch_progress.setMaximum(total)
        self.batch_progress.setValue(done)
        self.batch_progress.setLabelText(
            f"{done}/{total} · {name}" if name else f"{done}/{total}"
        )

    @Slot(object)
    def _batch_finished(self, results: object) -> None:
        self.batch_results = list(results or [])
        if self.batch_progress is not None:
            self.batch_progress.setValue(self.batch_progress.maximum())
            self.batch_progress.close()

        self._render_batch_table()
        self.tabs.setCurrentWidget(self.batch_page)

    @Slot(str)
    def _batch_failed(self, message: str) -> None:
        if self.batch_progress is not None:
            self.batch_progress.close()
        QMessageBox.critical(self, "파일 비교 분석 실패", message)

    @Slot()
    def _cleanup_batch_thread(self) -> None:
        if self.batch_worker is not None:
            self.batch_worker.deleteLater()
        if self.batch_thread is not None:
            self.batch_thread.deleteLater()
        self.batch_worker = None
        self.batch_thread = None
        self.batch_progress = None

    def _render_batch_table(self) -> None:
        successful = [item for item in self.batch_results if item.ok]
        failed = [item for item in self.batch_results if not item.ok]

        if successful:
            scores = [item.result.total_score for item in successful if item.result]
            average = sum(scores) / len(scores)
            total_issues = sum(
                item.result.stats.get("issues", 0)
                for item in successful
                if item.result
            )
            total_chars = sum(item.text_chars for item in successful)
            self.batch_summary_label.setText(
                f"분석 {len(successful)}개 · 오류 {len(failed)}개 · "
                f"평균 {average:.1f}점 · 최고 {max(scores)}점 · 최저 {min(scores)}점 · "
                f"총 개선 후보 {total_issues:,}건 · 추출 본문 {total_chars:,}자"
            )
        else:
            self.batch_summary_label.setText(
                f"성공한 문서가 없습니다. 오류 {len(failed)}개"
            )

        self.batch_table.setRowCount(len(self.batch_results))

        for row, item in enumerate(self.batch_results):
            first = QTableWidgetItem(item.name)
            first.setData(Qt.UserRole, row)
            first.setToolTip(item.error or item.path)
            self.batch_table.setItem(row, 0, first)

            if not item.ok or item.result is None:
                self.batch_table.setItem(row, 1, QTableWidgetItem(format_bytes(item.size_bytes)))
                for col in range(2, 10):
                    value = "오류" if col == 3 else ""
                    cell = QTableWidgetItem(value)
                    cell.setToolTip(item.error)
                    self.batch_table.setItem(row, col, cell)
                continue

            result = item.result
            values = [
                format_bytes(item.size_bytes),
                f"{item.text_chars:,}",
                str(result.total_score),
                f"{result.scores.get('알기 쉬운 용어', 0)} / 35",
                f"{result.scores.get('알기 쉬운 문장', 0)} / 35",
                f"{result.scores.get('어문규범', 0)} / 20",
                f"{result.scores.get('한글 사용', 0)} / 10",
                f"{result.stats.get('issues', 0):,}",
                f"{item.elapsed_seconds:.2f}초",
            ]
            for col, value in enumerate(values, start=1):
                self.batch_table.setItem(row, col, QTableWidgetItem(value))

        self.batch_table.resizeColumnsToContents()

    def show_selected_batch_detail(self) -> None:
        row = self.batch_table.currentRow()
        if row < 0:
            QMessageBox.information(
                self, "문서 선택", "상세히 볼 문서를 먼저 선택해 주세요."
            )
            return
        self.show_batch_detail(row, 0)

    def show_batch_detail(self, row: int, _column: int) -> None:
        first = self.batch_table.item(row, 0)
        if first is None:
            return

        index = first.data(Qt.UserRole)
        if not isinstance(index, int) or index < 0 or index >= len(self.batch_results):
            return

        item = self.batch_results[index]
        if not item.ok or item.result is None:
            QMessageBox.warning(
                self, "분석 오류", item.error or "이 문서는 분석하지 못했습니다."
            )
            return

        self.current_path = Path(item.path)
        self.editor.setPlainText(item.text)
        self._render_result(item.result)
        self.statusBar().showMessage(
            f"배치 결과 상세: {item.name} · {item.result.total_score}점"
        )
        self.tabs.setCurrentWidget(self.detail_page)

    def jump_to_issue(self, row: int, _column: int) -> None:
        if row < 0 or row >= len(self.current_issues):
            return
        issue = self.current_issues[row]
        if issue.start < 0 or issue.end <= issue.start:
            return

        cursor = self.editor.textCursor()
        cursor.setPosition(issue.start)
        cursor.setPosition(issue.end, QTextCursor.KeepAnchor)
        self.editor.setTextCursor(cursor)
        self.editor.ensureCursorVisible()
        self.editor.setFocus()

    def import_update(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "사전·규칙 업데이트 파일 선택", "", "JSON 업데이트 (*.json)"
        )
        if not path:
            return
        try:
            version = self.store.import_update_bundle(path)
        except DataStoreError as exc:
            QMessageBox.critical(self, "업데이트 실패", str(exc))
            return

        self.refresh_dictionary_label()
        QMessageBox.information(
            self,
            "업데이트 완료",
            f"사전·규칙 데이터를 적용했습니다.\n버전: {version}\n"
            "기존 문서를 다시 검사하면 새 기준이 반영됩니다.",
        )
        if self.editor.toPlainText().strip():
            self.analyze()

    def check_online_update(self) -> None:
        try:
            changed, version = self.store.check_managed_update()
        except Exception as exc:
            QMessageBox.information(self, "검사 기준 업데이트", str(exc))
            return

        self.refresh_dictionary_label()
        if changed:
            QMessageBox.information(
                self,
                "검사 기준 업데이트 완료",
                f"새 사전·규칙 데이터를 설치했습니다.\n버전: {version}",
            )
            if self.editor.toPlainText().strip():
                self.analyze()
        else:
            QMessageBox.information(
                self,
                "검사 기준 업데이트",
                f"이미 최신 데이터입니다.\n버전: {version}",
            )

    def add_user_term(self) -> None:
        term, ok = QInputDialog.getText(self, "사용자 용어 추가", "검토할 용어:")
        if not ok or not term.strip():
            return

        alternatives, ok = QInputDialog.getText(
            self, "사용자 용어 추가", "권장 표현(여러 개면 쉼표로 구분):"
        )
        if not ok:
            return

        values = [x.strip() for x in alternatives.split(",") if x.strip()]
        self.store.add_user_term(term.strip(), values)
        self.refresh_dictionary_label()
        QMessageBox.information(
            self, "사용자 사전", f"‘{term.strip()}’을 사용자 사전에 추가했습니다."
        )
        if self.editor.toPlainText().strip():
            self.analyze()

    def lookup_api(self) -> None:
        keyword = ""
        row = self.table.currentRow()
        if 0 <= row < len(self.current_issues):
            issue = self.current_issues[row]
            if issue.source_type == "OFFICIAL" and issue.term:
                keyword = issue.term

        if not keyword:
            keyword, ok = QInputDialog.getText(
                self, "공식 API 상세 조회", "검색할 낱말:"
            )
            if not ok or not keyword.strip():
                return
            keyword = keyword.strip()

        try:
            results = self.store.lookup_official_api(keyword)
        except Exception as exc:
            QMessageBox.critical(self, "API 조회 실패", str(exc))
            return

        if not results:
            QMessageBox.information(self, "공식 API 조회", "검색 결과가 없습니다.")
            return

        lines: list[str] = []
        for item in results[:10]:
            key = item.get("keyword") or item.get("word") or keyword
            alt = item.get("alt") or item.get("alternative") or item.get("replace") or ""
            examples = item.get("example") or item.get("examples") or []
            if isinstance(examples, list):
                example_text = "\n".join(str(x) for x in examples)
            else:
                example_text = str(examples)
            lines.append(f"• {key} → {alt}\n{example_text}".rstrip())

        QMessageBox.information(
            self,
            f"공식 API 상세 조회 · {keyword}",
            "\n\n".join(lines),
        )

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            local_paths = [
                url.toLocalFile()
                for url in event.mimeData().urls()
                if url.isLocalFile()
            ]
            files = supported_files(local_paths, SUPPORTED_EXTENSIONS)
            if files:
                event.acceptProposedAction()
                return
        super().dragEnterEvent(event)

    def dropEvent(self, event: QDropEvent) -> None:
        if event.mimeData().hasUrls():
            local_paths = [
                url.toLocalFile()
                for url in event.mimeData().urls()
                if url.isLocalFile()
            ]
            files = supported_files(local_paths, SUPPORTED_EXTENSIONS)
            if files:
                self.handle_dropped_files(files)
                event.acceptProposedAction()
                return
        super().dropEvent(event)
