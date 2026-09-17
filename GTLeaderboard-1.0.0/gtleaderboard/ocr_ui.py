"""Background recognition and explicit row-by-row review before a transactional import."""

from pathlib import Path

from PySide6.QtCore import QEvent, QThread, Signal, Qt
from PySide6.QtGui import QColor, QPixmap
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QFileDialog, QFrame, QHBoxLayout, QLabel,
    QLineEdit, QMessageBox, QVBoxLayout,
)

from .domain import ValidationError
from .ocr import TextRecognizer, OcrCancelled, combine_rows, parse_lap, recognize_screenshot
from .ocr_import import ImportChoice, matching_driver, merge_review
from .ui import STATUS_LABELS, button, item, spin, table


class OcrWorker(QThread):
    progress = Signal(str)
    completed = Signal(object)
    failed = Signal(str)

    def __init__(self, paths, parent=None):
        super().__init__(parent)
        self.paths = paths

    def run(self):
        try:
            self.progress.emit("한국어 OCR 모델을 불러오는 중…")
            recognizer = TextRecognizer()
            rows = []
            for path in self.paths:
                if self.isInterruptionRequested():
                    raise OcrCancelled()
                rows.extend(recognize_screenshot(path, recognizer, self.progress.emit, self.isInterruptionRequested))
            if not self.isInterruptionRequested():
                self.completed.emit(rows)
        except OcrCancelled:
            pass
        except Exception as exc:
            self.failed.emit(str(exc))


class OcrDialog(QDialog):
    def __init__(self, league, round_id, parent=None):
        super().__init__(parent)
        self.league = league
        self.round_id = round_id
        self.rnd = next(r for r in league.rounds if r.id == round_id)
        self.drivers = [d for d in league.drivers if not self.rnd.confirmed or d.id in self.rnd.roster]
        self.rows = []
        self.fields = []
        self.worker = None
        self.closing = False
        self.updated_league = None
        self.cache = {}
        self.setWindowTitle(f"{self.rnd.name} · 스크린샷 인식·확인")
        self.resize(1310, 820)
        self.setMinimumSize(1050, 650)
        layout = QVBoxLayout(self)
        top = QHBoxLayout()
        heading = QLabel(f"{self.rnd.name}  ·  {self.rnd.track_name}")
        heading.setTextFormat(Qt.TextFormat.PlainText)
        top.addWidget(heading, 1)
        self.add_button = button("스크린샷 추가 (여러 장 선택)", self.choose_files, True)
        top.addWidget(self.add_button)
        layout.addLayout(top)
        notice = QLabel("잘리지 않은 16:9 로비 결과 화면용입니다. 1~8위와 9위 이후 화면을 함께 추가하세요.\n이름이 일치하는 등록자는 연결하고, 불확실한 이름은 직접 선택합니다. 결과에 없는 등록자는 DNS로 채웁니다. 예선 폴·포인트 벌점은 사진에서 추측하지 않습니다.")
        notice.setWordWrap(True)
        layout.addWidget(notice)
        self.progress = QLabel("스크린샷을 선택하면 이 PC에서 인식합니다. 외부로 사진을 전송하지 않습니다.")
        self.progress.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.progress)
        self.preview = QLabel("행을 선택하면 원본의 해당 줄을 보여줍니다.")
        self.preview.setMinimumHeight(70)
        self.preview.setMaximumHeight(100)
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setStyleSheet("background: #13243b; color: white; border-radius: 5px; padding: 6px;")
        layout.addWidget(self.preview)
        self.grid = table(["포함", "표시 순위", "인식 이름 / 신규 이름", "등록 드라이버 연결", "상태", "BEST LAP", "기존 기록", "기존 교체", "확인 사항"])
        for col, width in enumerate((45, 78, 185, 195, 90, 110, 140, 80)):
            self.grid.setColumnWidth(col, width)
        self.grid.currentCellChanged.connect(lambda row, *_: self.show_original(row))
        layout.addWidget(self.grid, 1)
        self.summary = QLabel("아직 읽은 결과가 없습니다.")
        self.summary.setWordWrap(True)
        self.summary.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.summary)
        self.recalculate = QCheckBox("저장된 기록까지 합쳐 최단 랩으로 패스티스트랩 재계산 (기존 지정도 변경 · 동률은 수동 선택)")
        self.recalculate.setChecked(not self.rnd.confirmed)
        layout.addWidget(self.recalculate)
        self.aliases = QCheckBox("이번에 연결한 인식 이름을 드라이버 별칭으로 기억")
        self.aliases.setToolTip("OCR 오타를 별칭으로 기억할 수도 있으므로 필요한 이름만 연결했는지 확인하세요.")
        layout.addWidget(self.aliases)
        self.recalculate.toggled.connect(self.edited)
        self.aliases.toggled.connect(self.edited)
        self.reason = QLineEdit("스크린샷 최초 결과 입력" if not self.rnd.confirmed else "")
        self.reason.setMaxLength(2000)
        self.reason.setPlaceholderText("변경 사유 · 기존 기록을 바꾸는 경우 사유를 입력하세요")
        layout.addWidget(self.reason)
        panel = QFrame()
        panel.setObjectName("ocrCommitPanel")
        bottom = QHBoxLayout(panel)
        bottom.setContentsMargins(14, 10, 14, 10)
        bottom.setSpacing(16)
        confirmation = QVBoxLayout()
        confirmation.setSpacing(5)
        title = QLabel("반영 전 확인")
        title.setObjectName("ocrCommitTitle")
        confirmation.addWidget(title)
        self.reviewed = QCheckBox("전체 페이지·드라이버 연결·순위·상태 확인 완료")
        self.reviewed.setObjectName("ocrReviewed")
        self.reviewed.toggled.connect(self.update_enabled)
        confirmation.addWidget(self.reviewed)
        self.commit_hint = QLabel()
        self.commit_hint.setObjectName("ocrCommitHint")
        self.commit_hint.setWordWrap(True)
        confirmation.addWidget(self.commit_hint)
        bottom.addLayout(confirmation, 1)
        self.cancel_button = button("취소", self.reject)
        self.commit_button = button("라운드에 반영", self.commit, True)
        self.commit_button.setMinimumWidth(145)
        self.commit_button.setMinimumHeight(42)
        bottom.addWidget(self.cancel_button)
        bottom.addWidget(self.commit_button)
        layout.addWidget(panel)
        self.update_enabled()

    def update_enabled(self, *_):
        busy = self.worker is not None and self.worker.isRunning()
        self.commit_button.setEnabled(bool(self.rows) and self.reviewed.isChecked() and not busy)
        self.add_button.setEnabled(not busy)
        self.grid.setEnabled(not busy)
        self.reviewed.setEnabled(bool(self.rows) and not busy)
        if busy:
            hint = "스크린샷 인식 중입니다. 완료 후 결과를 확인해 주세요."
        elif not self.rows:
            hint = "스크린샷을 추가하면 결과 확인과 반영이 가능합니다."
        elif not self.reviewed.isChecked():
            hint = "위 확인란을 체크하면 ‘라운드에 반영’ 버튼이 활성화됩니다."
        else:
            hint = "확인 완료 · 오른쪽 버튼을 누르면 현재 라운드에 반영됩니다."
        self.commit_hint.setText(hint)
        self.commit_button.setToolTip(hint)

    def choose_files(self):
        paths, _ = QFileDialog.getOpenFileNames(self, "같은 라운드의 결과 스크린샷 선택", "", "스크린샷 (*.jpg *.jpeg *.png)")
        if paths:
            self.start_recognition(paths)

    def start_recognition(self, paths):
        if self.worker is not None and self.worker.isRunning():
            return
        if len(paths) > 8:
            QMessageBox.warning(self, "입력 확인", "한 번에 최대 8장까지 추가하세요.")
            return
        self.save_fields()
        self.reviewed.setChecked(False)
        self.worker = OcrWorker(paths, self)
        self.worker.progress.connect(self.progress.setText)
        self.worker.completed.connect(self.receive_rows)
        self.worker.failed.connect(self.show_failure)
        self.worker.finished.connect(self.worker_finished)
        self.worker.start()
        self.update_enabled()

    def receive_rows(self, rows):
        if self.closing:
            return
        self.rows = combine_rows(self.rows, rows)
        self.render_rows()
        self.progress.setText(f"누적 {len({r.image_hash for r in self.rows})}장 · {len(self.rows)}행 인식. 반영 전에 모든 이름과 기록을 확인하세요.")

    def show_failure(self, message):
        if not self.closing:
            self.progress.setText("인식하지 못했습니다. 이전에 읽은 결과는 유지됩니다.")
            QMessageBox.warning(self, "OCR 입력 확인", message)

    def worker_finished(self):
        worker = self.worker
        self.worker = None
        if worker:
            worker.deleteLater()
        self.update_enabled()
        if self.closing:
            super().reject()

    def save_fields(self):
        for row, fields in zip(self.rows, self.fields):
            include, pos, name, driver, status, lap, overwrite = fields
            self.cache[(row.image_hash, row.row_index)] = (include.isChecked(), pos.value(), name.text(), driver.currentData(), status.currentData(), lap.text(), overwrite.isChecked())

    def render_rows(self):
        self.fields = []
        self.grid.setRowCount(0)
        self.grid.setRowCount(len(self.rows))
        for index, row in enumerate(self.rows):
            include = QCheckBox()
            include.setChecked(True)
            pos = spin(row.position or 0, 16)
            pos.setSpecialValueText("확인")
            name = QLineEdit(row.name)
            name.setMaxLength(80)
            name.setToolTip(f"원본 인식: {row.name}\n이름 신뢰도: {row.scores.get('name', 0):.2f} (정답 확률은 아닙니다)")
            driver = QComboBox()
            driver.addItem("연결할 드라이버 선택", "")
            if not self.rnd.confirmed:
                driver.addItem("+ 왼쪽 이름으로 신규 등록", "__new__")
            for person in self.drivers:
                driver.addItem(person.name, person.id)
            match = matching_driver(row, self.drivers)
            driver.setCurrentIndex(driver.findData(match or ("__new__" if not self.drivers and not self.rnd.confirmed else "")))
            status = QComboBox()
            for code, label in STATUS_LABELS.items():
                if code == "POINTS":
                    continue
                status.addItem(label, code)
            status.setCurrentIndex(status.findData(row.status))
            lap = QLineEdit(row.best_lap_text if parse_lap(row.best_lap_text) is not None or row.status == "FINISHED" else "")
            lap.setMaxLength(30)
            lap.setPlaceholderText("2'15.371")
            overwrite = QCheckBox()
            overwrite.setToolTip("기존 기록의 순위·상태·베스트 랩을 이 행으로 바꿉니다. 예선 폴·점수 벌점·메모는 유지합니다.")
            saved = self.cache.get((row.image_hash, row.row_index))
            if saved:
                enabled, position, n, linked, state, best, replace = saved
                include.setChecked(enabled)
                pos.setValue(position)
                name.setText(n)
                driver.setCurrentIndex(driver.findData(linked))
                status.setCurrentIndex(status.findData(state))
                lap.setText(best)
                overwrite.setChecked(replace)
            fields = (include, pos, name, driver, status, lap, overwrite)
            self.fields.append(fields)
            for col, widget in ((0, include), (1, pos), (2, name), (3, driver), (4, status), (5, lap), (7, overwrite)):
                self.grid.setCellWidget(index, col, widget)
                widget.setProperty("ocr_row", index)
                widget.installEventFilter(self)
            issues = list(row.issues)
            if not match:
                issues.append("이름 연결 확인")
            if sum(r.position == row.position for r in self.rows) > 1:
                issues.append("같은 순위 중복")
            issue = item(" · ".join(issues) or "원본 대조")
            if issues:
                issue.setForeground(QColor("#a65b00"))
            self.grid.setItem(index, 8, issue)
            self.link_changed(index)
            driver.currentIndexChanged.connect(lambda _, i=index: self.link_changed(i))
            for signal in (include.toggled, pos.valueChanged, name.textEdited, driver.currentIndexChanged, status.currentIndexChanged, lap.textEdited, overwrite.toggled):
                signal.connect(self.edited)
        if self.rows:
            self.grid.setCurrentCell(0, 2)
            self.show_original(0)
        self.update_summary()

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.FocusIn and watched.property("ocr_row") is not None:
            row = watched.property("ocr_row")
            self.show_original(row)
        return super().eventFilter(watched, event)

    def link_changed(self, index):
        if index >= len(self.fields):
            return
        _, _, name, driver, _, _, overwrite = self.fields[index]
        name.setReadOnly(driver.currentData() != "__new__")
        previous = self.rnd.results.get(driver.currentData())
        protected = previous is not None and previous.source != "auto_dns"
        overwrite.setEnabled(protected)
        if not protected:
            overwrite.setChecked(False)
        label = "새 결과" if not previous else f"{previous.position or '—'}위 / {STATUS_LABELS[previous.status]}"
        if protected:
            label += " · 기본 유지"
        self.grid.setItem(index, 6, item(label))

    def edited(self, *_):
        self.reviewed.setChecked(False)
        self.update_summary()

    def update_summary(self):
        count = sum(fields[0].isChecked() for fields in self.fields)
        laps = [(parse_lap(f[5].text()), f[2].text()) for f in self.fields if f[0].isChecked() and parse_lap(f[5].text()) is not None]
        if laps:
            fastest = min(t for t, _ in laps)
            names = ", ".join(n for t, n in laps if t == fastest)
            value = f"{fastest // 60000}'{fastest // 1000 % 60:02}.{fastest % 1000:03}"
            extra = f"입력표의 최단 랩 후보: {names} · {value}"
        else:
            extra = "아직 비교할 베스트 랩 기록이 없습니다."
        self.summary.setText(f"반영 대상 {count}행  /  {extra}\n재계산 시 기존 라운드의 랩 기록도 비교합니다. 기존 교체를 체크하지 않은 기록은 유지됩니다.")
        self.update_enabled()

    def show_original(self, index):
        if not 0 <= index < len(self.rows):
            return
        row = self.rows[index]
        pixmap = QPixmap(row.image_path)
        if pixmap.isNull():
            self.preview.setText(f"원본 파일을 열 수 없습니다: {Path(row.image_path).name}")
            return
        x, y = pixmap.width() / 2048, pixmap.height() / 1152
        strip = pixmap.copy(round(138 * x), round((308 + row.row_index * 76.8) * y), round(1772 * x), round(73 * y))
        self.preview.setPixmap(strip.scaled(max(800, self.preview.width() - 16), 86, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        self.preview.setToolTip(f"{Path(row.image_path).name} · {row.row_index + 1}번째 행\nTIME: {row.time_text} · 게임 페널티: {row.game_penalty}")

    def choices(self):
        result = []
        for row, fields in zip(self.rows, self.fields):
            include, pos, name, driver, status, lap, overwrite = fields
            if include.isChecked():
                linked = driver.currentData()
                result.append(ImportChoice(row, linked if linked != "__new__" else "", name.text().strip() if linked == "__new__" else "", pos.value(), status.currentData(), lap.text(), overwrite.isChecked()))
        return result

    def commit(self):
        if not self.reviewed.isChecked() or (self.worker is not None and self.worker.isRunning()):
            return
        try:
            self.updated_league = merge_review(self.league, self.round_id, self.choices(), self.reason.text().strip(), self.recalculate.isChecked(), self.aliases.isChecked())
        except (ValidationError, ValueError) as exc:
            QMessageBox.warning(self, "결과 확인", str(exc))
            return
        super().accept()

    def reject(self):
        if self.worker is not None and self.worker.isRunning():
            self.closing = True
            self.worker.requestInterruption()
            self.progress.setText("현재 인식 작업을 정리하는 중…")
            self.cancel_button.setEnabled(False)
            return
        super().reject()
