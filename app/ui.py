from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import (
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from .analyzer import PublicLanguageAnalyzer
from .data_store import DataStore, DataStoreError
from .document_loader import DocumentLoadError, SUPPORTED_EXTENSIONS, load_document


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.store = DataStore()
        self.current_path: Path | None = None
        self.setWindowTitle("공공언어 검사기")
        self.resize(1280, 820)
        self.setAcceptDrops(True)

        self.editor = QTextEdit()
        self.editor.setPlaceholderText(
            "문서를 끌어 놓거나 [문서 열기]를 누르세요.\n"
            "텍스트를 직접 붙여 넣고 검사할 수도 있습니다."
        )

        self.score_label = QLabel("—")
        self.score_label.setAlignment(Qt.AlignCenter)
        score_font = self.score_label.font()
        score_font.setPointSize(34)
        score_font.setBold(True)
        self.score_label.setFont(score_font)

        self.score_caption = QLabel("공공언어 적합도")
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

        self.summary_label = QLabel("검사 전")
        self.summary_label.setWordWrap(True)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["등급", "영역", "문제", "개선안", "근거"])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setWordWrap(True)
        self.table.setAlternatingRowColors(True)

        open_button = QPushButton("문서 열기")
        open_button.clicked.connect(self.open_document)

        analyze_button = QPushButton("검사하기")
        analyze_button.clicked.connect(self.analyze)

        update_button = QPushButton("업데이트 파일 가져오기")
        update_button.clicked.connect(self.import_update)

        term_button = QPushButton("사용자 용어 추가")
        term_button.clicked.connect(self.add_user_term)

        api_button = QPushButton("공식 API 낱말 조회")
        api_button.clicked.connect(self.lookup_api)

        top_buttons = QHBoxLayout()
        for button in (open_button, analyze_button, update_button, term_button, api_button):
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
        right_layout.addWidget(self.summary_label)
        right_layout.addWidget(QLabel("개선 후보"))
        right_layout.addWidget(self.table, 1)

        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(left)
        splitter.addWidget(right)
        splitter.setSizes([650, 630])

        title = QLabel("공공언어 검사기")
        title_font = title.font()
        title_font.setPointSize(19)
        title_font.setBold(True)
        title.setFont(title_font)

        subtitle = QLabel(
            "‘쉬운 공문서 쓰기’ 작성 원칙을 바탕으로 문서를 로컬에서 분석합니다. "
            "점수는 공식 정부 평가 점수가 아닌 자체 분석 점수입니다."
        )
        subtitle.setWordWrap(True)

        privacy = QLabel(
            "🔒 기본 로컬 검사 모드 · 문서 원문은 외부 서버로 전송하지 않습니다. "
            "‘공식 API 낱말 조회’를 실행할 때만 입력한 낱말을 전송합니다."
        )
        privacy.setWordWrap(True)

        root = QWidget()
        layout = QVBoxLayout(root)
        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addLayout(top_buttons)
        layout.addWidget(splitter, 1)
        layout.addWidget(privacy)
        self.setCentralWidget(root)

    def refresh_analyzer(self) -> PublicLanguageAnalyzer:
        return PublicLanguageAnalyzer(self.store.load_terms(), self.store.load_rules())

    def open_document(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "공공언어 검사 문서 열기",
            "",
            "지원 문서 (*.hwpx *.docx *.pdf *.txt);;모든 파일 (*.*)",
        )
        if path:
            self._load_path(Path(path))

    def _load_path(self, path: Path) -> None:
        try:
            text = load_document(path)
        except DocumentLoadError as exc:
            QMessageBox.critical(self, "문서 열기 실패", str(exc))
            return
        self.current_path = path
        self.editor.setPlainText(text)
        self.statusBar().showMessage(f"불러옴: {path.name}")
        self.analyze()

    def analyze(self) -> None:
        text = self.editor.toPlainText().strip()
        if not text:
            QMessageBox.information(self, "검사할 내용 없음", "문서를 열거나 텍스트를 입력해 주세요.")
            return

        try:
            result = self.refresh_analyzer().analyze(text)
        except DataStoreError as exc:
            QMessageBox.critical(self, "데이터 오류", str(exc))
            return

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
            f"총 {result.stats.get('issues', 0)}건 · "
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
            ]
            for col, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setToolTip(issue.sentence or value)
                self.table.setItem(row, col, item)
        self.table.resizeRowsToContents()

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
        QMessageBox.information(
            self,
            "업데이트 완료",
            f"사전·규칙 데이터를 적용했습니다.\n버전: {version}\n기존 문서를 다시 검사하면 새 기준이 반영됩니다.",
        )
        if self.editor.toPlainText().strip():
            self.analyze()

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
        QMessageBox.information(self, "사용자 사전", f"‘{term.strip()}’을 사용자 사전에 추가했습니다.")
        if self.editor.toPlainText().strip():
            self.analyze()

    def lookup_api(self) -> None:
        keyword, ok = QInputDialog.getText(self, "공식 API 낱말 조회", "검색할 낱말:")
        if not ok or not keyword.strip():
            return
        try:
            results = self.store.lookup_official_api(keyword.strip())
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
            example = item.get("example") or item.get("examples") or ""
            lines.append(f"• {key} → {alt}\n  {example}".rstrip())
        QMessageBox.information(self, "공식 API 조회 결과", "\n\n".join(lines))

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            paths = [Path(url.toLocalFile()) for url in event.mimeData().urls()]
            if any(path.suffix.lower() in SUPPORTED_EXTENSIONS for path in paths):
                event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:
        for url in event.mimeData().urls():
            path = Path(url.toLocalFile())
            if path.suffix.lower() in SUPPORTED_EXTENSIONS:
                self._load_path(path)
                event.acceptProposedAction()
                return
