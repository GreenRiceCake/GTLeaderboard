"""First usable manual-entry desktop workflow."""

from copy import deepcopy
from pathlib import Path
import re

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QColor, QFont, QKeySequence
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QCheckBox, QComboBox, QDialog,
    QDialogButtonBox, QFileDialog, QFormLayout, QGridLayout, QGroupBox,
    QHBoxLayout, QHeaderView, QInputDialog, QLabel, QLineEdit, QListWidget, QMainWindow,
    QMenu, QMessageBox, QPushButton, QSpinBox, QTabWidget, QTableWidget,
    QTableWidgetItem, QTextEdit, QVBoxLayout, QWidget,
)

from . import __version__
from .catalog import load_catalog
from .domain import (
    Bonus, League, Result, Round, Rules, STATUSES, ValidationError,
    add_drivers, apply_results, score, standings, update_rules, validate_league,
)
from .storage import load_league, load_rules, save_league, save_rules, serialize_league
from .widgets import FixedTotalPane, SearchableComboBox, WrappedHeader
from .workflow_ui import WorkflowMixin


STATUS_LABELS = {"": "미입력", "FINISHED": "완주", "DNS": "DNS", "DNQ": "DNQ", "DNF": "DNF", "DSQ": "DSQ", "POINTS": "점수만 보존"}
STYLE = """
QMainWindow, QDialog { background: #f3f5f8; }
QWidget { color: #1d2b40; font-family: 'Malgun Gothic'; font-size: 13px; }
QLabel#brand { font-size: 25px; font-weight: 800; color: #14243c; }
QLabel#subtitle { color: #63738a; }
QLabel#metrics { background: #14243c; color: #f5fcff; padding: 18px; border-radius: 9px; font-size: 15px; }
QPushButton { background: white; border: 1px solid #cad4df; border-radius: 5px; padding: 8px 14px; }
QPushButton:hover { background: #eaf2f7; border-color: #8eabba; }
QPushButton:disabled { color: #697586; background: #dce1e7; border: 1px solid #b8c1cc; }
QPushButton#primary { background: #007f79; color: white; border: 1px solid #007f79; font-weight: bold; }
QPushButton#primary:hover:enabled { background: #006b66; }
QPushButton#primary:disabled { color: #697586; background: #dce1e7; border: 1px solid #b8c1cc; }
QFrame#ocrCommitPanel { background: white; border: 1px solid #bbc7d4; border-radius: 7px; }
QLabel#ocrCommitTitle { font-weight: bold; }
QLabel#ocrCommitHint { color: #596779; }
QCheckBox#ocrReviewed { font-weight: bold; spacing: 9px; }
QCheckBox#ocrReviewed::indicator { width: 20px; height: 20px; }
QLineEdit, QSpinBox, QComboBox, QTextEdit { background: white; border: 1px solid #cbd5df; border-radius: 4px; padding: 5px; min-height: 20px; }
QComboBox::drop-down { width: 22px; border: none; }
QTableWidget { background: white; alternate-background-color: #f7f9fc; border: 1px solid #dce3eb; gridline-color: #e9eef4; }
QTableWidget::item { padding: 4px; }
QTableWidget::item:selected { background: #d9eee9; color: #123c3a; }
QHeaderView::section { background: #eaf0f5; padding: 10px 7px; border: none; border-bottom: 1px solid #d3dee9; font-weight: bold; }
QTabWidget::pane { border: 0; padding-top: 8px; }
QTabBar::tab { padding: 12px 22px; color: #67758a; border-bottom: 3px solid transparent; }
QTabBar::tab:selected { color: #007f79; border-bottom: 3px solid #007f79; font-weight: bold; }
QGroupBox { border: 1px solid #d6dfe8; border-radius: 5px; margin-top: 16px; padding: 16px; }
QGroupBox::title { subcontrol-origin: margin; left: 14px; padding: 0 5px; font-weight: bold; }
QCheckBox { spacing: 7px; }
"""


def button(text, callback, primary=False):
    widget = QPushButton(text)
    if primary:
        widget.setObjectName("primary")
    widget.clicked.connect(callback)
    return widget


def spin(value=0, maximum=10000):
    widget = QSpinBox()
    widget.setRange(0, maximum)
    widget.setValue(value)
    return widget


def table(headers):
    widget = QTableWidget(0, len(headers))
    widget.setHorizontalHeaderLabels(headers)
    widget.verticalHeader().hide()
    widget.verticalHeader().setDefaultSectionSize(43)
    widget.setAlternatingRowColors(True)
    widget.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    widget.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    widget.horizontalHeader().setStretchLastSection(True)
    return widget


def item(text, center=False):
    value = QTableWidgetItem(str(text))
    if center:
        value.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
    return value


class RulesDialog(QDialog):
    def __init__(self, league, parent=None):
        super().__init__(parent)
        self.setWindowTitle("리그 이름 · 배점과 보너스")
        self.resize(740, 700)
        layout = QVBoxLayout(self)
        self.name = QLineEdit(league.name)
        self.name.setMaxLength(200)
        form = QFormLayout()
        form.addRow("리그 이름", self.name)
        layout.addLayout(form)
        notice = QLabel("설정을 적용하면 경기 결과를 새 규칙으로 다시 계산합니다. 종합표에서 점수만 보존한 기록은 고정됩니다.")
        notice.setWordWrap(True)
        layout.addWidget(notice)
        points_box = QGroupBox("결승 순위별 배점 · 정수 점수")
        grid = QGridLayout(points_box)
        self.points = []
        for index, points in enumerate(league.rules.position_points):
            field = spin(points)
            self.points.append(field)
            row, col = divmod(index, 4)
            grid.addWidget(QLabel(f"{index + 1}위"), row, col * 2)
            grid.addWidget(field, row, col * 2 + 1)
        layout.addWidget(points_box)
        status_box = QGroupBox("출전 상태별 기본 점수")
        statuses = QHBoxLayout(status_box)
        self.statuses = {}
        for status, points in league.rules.status_points.items():
            field = spin(points)
            self.statuses[status] = field
            statuses.addWidget(QLabel(status))
            statuses.addWidget(field)
        layout.addWidget(status_box)
        self.bonuses = []
        for title, rule in (("예선 폴 포지션", league.rules.pole), ("패스티스트랩", league.rules.fastest)):
            box = QGroupBox(title)
            row = QHBoxLayout(box)
            enabled = QCheckBox("사용")
            enabled.setChecked(rule.enabled)
            points = spin(rule.points)
            finished = QCheckBox("완주자만")
            finished.setChecked(rule.finished_only)
            top_n = spin(rule.top_n, 16)
            top_n.setSpecialValueText("순위 제한 없음")
            top_n.setSuffix("위 이내")
            for widget in (enabled, QLabel("점수"), points, finished, top_n):
                row.addWidget(widget)
            self.bonuses.append((enabled, points, finished, top_n))
            layout.addWidget(box)
        self.stacking = QCheckBox("폴 + 패스티스트랩 중복 지급 (해제하면 자격을 만족하는 보너스 중 큰 점수 1개만 지급)")
        self.stacking.setChecked(league.rules.stack_bonuses)
        layout.addWidget(self.stacking)
        layout.addStretch()
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Save).setText("설정 적용")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("취소")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def values(self):
        bonuses = [Bonus(a.isChecked(), b.value(), c.isChecked(), d.value()) for a, b, c, d in self.bonuses]
        return Rules([p.value() for p in self.points], {s: p.value() for s, p in self.statuses.items()}, *bonuses, self.stacking.isChecked())


class RoundDialog(QDialog):
    def __init__(self, name, catalog, parent=None):
        super().__init__(parent)
        self.setWindowTitle("라운드 추가")
        self.resize(600, 230)
        self.catalog = catalog
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.name = QLineEdit(name)
        self.name.setMaxLength(80)
        self.track = SearchableComboBox()
        self.track.addItem("코스 미정", None)
        for track in catalog["tracks"]:
            self.track.addItem(track["name"], track)
        self.track.setEditable(True)
        self.track.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.track.completer().setFilterMode(Qt.MatchFlag.MatchContains)
        self.track.completer().setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        form.addRow("라운드 이름", self.name)
        form.addRow("공식 코스 · 레이아웃", self.track)
        layout.addLayout(form)
        layout.addWidget(QLabel(f"공식 한국어 목록 · {len(catalog['tracks'])}개 레이아웃 · {catalog['retrieved_at']} 기준"))
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def value(self):
        index = self.track.findText(self.track.currentText(), Qt.MatchFlag.MatchExactly)
        if index < 0:
            raise ValidationError("목록의 코스·레이아웃을 선택하세요.")
        track = self.track.itemData(index)
        return Round(self.name.text().strip(), track["id"] if track else "", track["name"] if track else "미정", self.catalog["retrieved_at"] if track else "")


class MainWindow(WorkflowMixin, QMainWindow):
    def __init__(self, league=None):
        super().__init__()
        self.league = league or League()
        self.path = None
        self.png_suggestion = None
        self.png_scale = 1
        self.dirty = False
        self.editor_dirty = False
        self.current_round_id = None
        self.row_widgets = {}
        self.catalog = load_catalog()
        self.resize(1240, 820)
        self.setMinimumSize(980, 650)
        self.setStyleSheet(STYLE)
        root = QWidget()
        outer = QVBoxLayout(root)
        outer.setContentsMargins(28, 22, 28, 18)
        outer.setSpacing(16)
        heading = QHBoxLayout()
        title_box = QVBoxLayout()
        brand = QLabel("GTLeaderboard")
        brand.setObjectName("brand")
        subtitle = QLabel("리그의 기록을 한곳에. 경기 결과부터 시즌 순위까지.")
        subtitle.setObjectName("subtitle")
        title_box.addWidget(brand)
        title_box.addWidget(subtitle)
        heading.addLayout(title_box)
        heading.addStretch()
        for label, callback in (("새 리그", self.new_league), ("열기", self.open_league), ("저장", self.save), ("다른 이름으로 저장", self.save_as), ("배점 설정", self.edit_rules)):
            heading.addWidget(button(label, callback, label == "저장"))
        export_button = QPushButton("내보내기")
        export_menu = QMenu(export_button)
        export_menu.addAction("GTLB로 저장", self.export_league)
        export_menu.addAction("CSV로 저장", self.export_csv)
        export_button.setMenu(export_menu)
        heading.addWidget(export_button)
        outer.addLayout(heading)
        self.metrics = QLabel()
        self.metrics.setObjectName("metrics")
        outer.addWidget(self.metrics)
        self.tabs = QTabWidget()
        outer.addWidget(self.tabs, 1)
        self.build_standings()
        self.build_rounds()
        self.build_drivers()
        self.setCentralWidget(root)
        file_menu = self.menuBar().addMenu("파일")
        file_menu.addAction("PNG 저장", self.save)
        save_as_action = file_menu.addAction("다른 이름으로 저장…", self.save_as)
        save_as_action.setShortcut(QKeySequence.StandardKey.SaveAs)
        self.init_workflow(file_menu)
        help_menu = self.menuBar().addMenu("도움말")
        help_menu.addAction("버전 · 업데이트", self.show_updates)
        self.statusBar().showMessage(f"v{__version__} · 로컬 OCR · 수동 정정 · 종합표 PNG")
        for shortcut, callback in ((QKeySequence.StandardKey.Save, self.save), (QKeySequence.StandardKey.Open, self.open_league), (QKeySequence.StandardKey.New, self.new_league)):
            action = QAction(self)
            action.setShortcut(shortcut)
            action.triggered.connect(callback)
            self.addAction(action)
        self.refresh()

    def build_standings(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        self.welcome = QGroupBox('시즌 운영 시작하기')
        welcome_layout = QVBoxLayout(self.welcome)
        row = QHBoxLayout()
        row.addWidget(button('새 시즌 만들기 · 이름 → 참가자 → 첫 라운드', self.start_season, True))
        row.addWidget(button('기존 리그 열기', self.open_league))
        welcome_layout.addLayout(row)
        welcome_layout.addWidget(QLabel('최근 리그 · 더블클릭해서 계속 작업'))
        self.recent_hint = QLabel('저장하거나 열었던 리그가 여기에 표시됩니다.')
        welcome_layout.addWidget(self.recent_hint)
        self.recent_list = QListWidget()
        self.recent_list.setMaximumHeight(120)
        self.recent_list.itemDoubleClicked.connect(lambda _: self.open_recent(self.recent_files()[self.recent_list.currentRow()]))
        welcome_layout.addWidget(self.recent_list)
        layout.addWidget(self.welcome)
        self.overview_hint = QLabel()
        self.overview_hint.setWordWrap(True)
        layout.addWidget(self.overview_hint)
        self.standings_table = table(["순위", "드라이버", "총 포인트"])
        self.standings_table.setHorizontalHeader(WrappedHeader(self.standings_table))
        self.standings_pane = FixedTotalPane(self.standings_table)
        layout.addWidget(self.standings_pane)
        layout.addWidget(QLabel("동점은 공동 순위로 표시합니다 (예: 1 · 1 · 3). 미진행 라운드는 점수에 포함하지 않습니다."))
        self.tabs.addTab(page, "종합 순위")

    def show_updates(self):
        from .update_ui import UpdateDialog
        UpdateDialog(self).exec()

    def build_rounds(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        controls = QHBoxLayout()
        self.round_combo = QComboBox()
        self.round_combo.setMinimumWidth(290)
        self.round_combo.currentIndexChanged.connect(self.switch_round)
        controls.addWidget(self.round_combo, 1)
        controls.addWidget(button("라운드 추가", self.add_round))
        self.manage_rounds_button = button("라운드 관리", self.manage_rounds)
        controls.addWidget(self.manage_rounds_button)
        self.track_button = button("코스 변경", self.edit_track)
        controls.addWidget(self.track_button)
        self.history_button = button("변경 이력", self.show_history)
        controls.addWidget(self.history_button)
        self.ocr_button = button("스크린샷 가져오기", self.import_screenshots, True)
        controls.addWidget(self.ocr_button)
        layout.addLayout(controls)
        self.round_info = QLabel()
        self.round_info.setWordWrap(True)
        layout.addWidget(self.round_info)
        hint = QLabel("순위나 상태를 입력한 뒤 결과를 반영하세요. 미입력 드라이버는 자동 DNS가 됩니다.\n심사 정정 시 영향받는 순위를 함께 수정하고 변경 사유를 남겨 주세요.")
        hint.setObjectName("subtitle")
        layout.addWidget(hint)
        self.results_table = table(["드라이버", "상태", "결승 순위", "예선 폴", "패스티스트랩", "벌점", "메모 / 벌점 사유"])
        for col, width in enumerate((185, 115, 95, 70, 115, 85)):
            self.results_table.setColumnWidth(col, width)
        layout.addWidget(self.results_table, 1)
        bottom = QHBoxLayout()
        self.reason = QLineEdit()
        self.reason.setMaxLength(2000)
        self.reason.setPlaceholderText("변경 사유 · 예: R01 2번 드라이버 심사 결과 반영")
        self.reason.textEdited.connect(self.editor_changed)
        bottom.addWidget(self.reason, 1)
        self.apply_button = button("결과 반영 · 미입력 DNS", self.apply_editor, True)
        bottom.addWidget(self.apply_button)
        layout.addLayout(bottom)
        self.tabs.addTab(page, "라운드 결과")

    def build_drivers(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        controls = QHBoxLayout()
        controls.addWidget(QLabel("시즌 전체 드라이버 · 한 로비의 16명 제한과 별도로 등록할 수 있습니다."), 1)
        controls.addWidget(button("이름 수정", self.rename_driver))
        controls.addWidget(button("드라이버 추가", self.add_driver_dialog, True))
        layout.addLayout(controls)
        self.drivers_table = table(["번호", "드라이버 이름"])
        self.drivers_table.setColumnWidth(0, 80)
        layout.addWidget(self.drivers_table)
        row = QHBoxLayout()
        row.addWidget(QLabel("규칙 파일로 다른 시즌의 배점을 재사용할 수 있습니다."), 1)
        row.addWidget(button("배점 파일 열기", self.import_rules))
        row.addWidget(button("배점 파일 저장", self.export_rules))
        layout.addLayout(row)
        self.tabs.addTab(page, "드라이버 · 파일")

    def current_round(self):
        return next((r for r in self.league.rounds if r.id == self.current_round_id), None)

    def update_title(self):
        marker = " *" if self.dirty or self.editor_dirty else ""
        self.setWindowTitle(f"{self.league.name}{marker} — GTLeaderboard")
        self.refresh_workflow()

    def mark_dirty(self):
        self.dirty = True
        self.changed_workflow()
        self.update_title()

    def editor_changed(self, *_):
        self.editor_dirty = True
        self.update_title()
        self.schedule_recovery()

    def error(self, exc):
        QMessageBox.warning(self, "확인이 필요합니다", str(exc))

    def refresh(self):
        self.round_combo.blockSignals(True)
        self.round_combo.clear()
        for rnd in self.league.rounds:
            self.round_combo.addItem(f"{rnd.name} · {'반영됨' if rnd.confirmed else '미진행'}", rnd.id)
        index = self.round_combo.findData(self.current_round_id)
        self.round_combo.setCurrentIndex(max(0, index))
        self.current_round_id = self.round_combo.currentData()
        self.round_combo.blockSignals(False)
        self.render_results()
        self.render_standings()
        self.drivers_table.setRowCount(len(self.league.drivers))
        for row, driver in enumerate(self.league.drivers):
            self.drivers_table.setItem(row, 0, item(row + 1, True))
            self.drivers_table.setItem(row, 1, item(driver.name))
        self.update_title()

    def render_standings(self):
        confirmed = sum(r.confirmed for r in self.league.rounds)
        self.metrics.setText(f"{self.league.name}     /     드라이버 {len(self.league.drivers)}명     /     진행 {confirmed} / {len(self.league.rounds)} 라운드")
        headers = ["순위", "드라이버"] + [f"{r.name}\n{r.track_name}" for r in self.league.rounds] + ["총 포인트"]
        grid = self.standings_table
        grid.setColumnCount(len(headers))
        grid.setHorizontalHeaderLabels(headers)
        grid.setRowCount(len(self.league.drivers))
        grid.setColumnWidth(0, 70)
        grid.setColumnWidth(1, 195)
        for col in range(2, len(headers) - 1):
            grid.setColumnWidth(col, 200)
        rows = standings(self.league)
        for row, standing in enumerate(rows):
            grid.setItem(row, 0, item(standing["rank"] if confirmed else "—", True))
            grid.setItem(row, 1, item(standing["name"]))
            for col, (rnd, points) in enumerate(zip(self.league.rounds, standing["points"]), 2):
                result = rnd.results.get(standing["id"]) if rnd.confirmed else None
                display = "—" if points is None else str(points)
                if result and result.status not in ("FINISHED", "POINTS"):
                    display = f"{result.status} · {points}"
                cell = item(display, True)
                if result:
                    cell.setToolTip(f"{STATUS_LABELS[result.status]} / 순위 {result.position or '—'} / 폴 {result.pole} / 패스티스트랩 {result.fastest}\n{result.note}")
                    if result.status == "POINTS":
                        cell.setToolTip(f"종합표 점수 {points}점 · 결승 순위·완주 상태·보너스 내역 미확인\n{result.note}")
                grid.setItem(row, col, cell)
            total = item(standing["total"], True)
            total.setForeground(QColor("#007f79"))
            font = total.font()
            font.setBold(True)
            total.setFont(font)
            grid.setItem(row, len(headers) - 1, total)
        has_points = any(result.status == "POINTS" for rnd in self.league.rounds for result in rnd.results.values())
        self.standings_pane.sync_columns()
        self.overview_hint.setText("종합표에서 옮긴 점수는 고정 보존됩니다. 결승 순위·보너스 내역은 미확인이며 배점 변경으로 재계산되지 않습니다." if has_points else ("드라이버를 등록하고 라운드를 추가해 첫 결과를 입력하세요." if not rows else "반영된 경기 결과를 바탕으로 자동 계산한 시즌 순위입니다."))

    def render_results(self):
        rnd = self.current_round()
        self.row_widgets = {}
        self.results_table.setRowCount(0)
        self.reason.setText("")
        self.editor_dirty = False
        for b in (self.apply_button, self.track_button, self.history_button, self.ocr_button, self.manage_rounds_button):
            b.setEnabled(rnd is not None)
        if not rnd:
            self.round_info.setText("라운드를 추가하면 여기에서 경기 결과를 입력할 수 있습니다.")
            return
        drivers = [d for d in self.league.drivers if not rnd.confirmed or d.id in rnd.roster]
        self.round_info.setText(f"{rnd.track_name}  ·  라운드 명단 {len(drivers)}명  ·  {'현재 개정 ' + str(len(rnd.history)) if rnd.confirmed else '아직 종합 순위에 반영하지 않았습니다'}")
        self.results_table.setRowCount(len(drivers))
        for row, driver in enumerate(drivers):
            result = rnd.results.get(driver.id)
            name = item(driver.name)
            if result and result.raw:
                name.setToolTip(f"OCR 원본 이름: {result.raw.get('name', '')}\n화면 순위: {result.screen_position}\nTIME: {result.raw.get('time', '')}\nBEST LAP: {result.raw.get('best_lap', '')}\n{result.raw.get('file', '')}")
            if result and result.source == "auto_dns":
                name.setText(f"{driver.name}  [자동 DNS]")
                name.setToolTip("결과에서 누락되어 자동 지정했습니다. 상태·순위를 수정할 수 있습니다.")
            self.results_table.setItem(row, 0, name)
            status = QComboBox()
            for code, label in STATUS_LABELS.items():
                if code == "POINTS" and (not result or result.status != "POINTS"):
                    continue
                status.addItem(label, code)
            if result and result.status == "POINTS":
                status.setItemText(status.findData("POINTS"), f"점수만 보존 ({result.recorded_points}점)")
            status.setCurrentIndex(status.findData(result.status if result else ""))
            position = spin(result.position if result and result.position else 0, 16)
            position.setSpecialValueText("—")
            pole, fastest = QCheckBox(), QCheckBox()
            pole.setChecked(result.pole if result else False)
            fastest.setChecked(result.fastest if result else False)
            penalty = spin(result.penalty if result else 0)
            note = QLineEdit(result.note if result else "")
            note.setMaxLength(2000)
            self.row_widgets[driver.id] = (status, position, pole, fastest, penalty, note)
            for col, widget in enumerate(self.row_widgets[driver.id], 1):
                self.results_table.setCellWidget(row, col, widget)
            status.currentIndexChanged.connect(lambda _, s=status, p=position: self.status_changed(s, p))
            position.valueChanged.connect(lambda value, s=status: self.position_changed(value, s))
            pole.toggled.connect(lambda checked, key=driver.id: self.bonus_changed(key, 2, checked))
            fastest.toggled.connect(lambda checked, key=driver.id: self.bonus_changed(key, 3, checked))
            penalty.valueChanged.connect(self.editor_changed)
            note.textEdited.connect(self.editor_changed)
        self.update_title()

    def bonus_changed(self, driver_id, column, checked):
        if checked:
            for other_id, fields in self.row_widgets.items():
                if other_id != driver_id:
                    fields[column].setChecked(False)
        self.editor_changed()

    def status_changed(self, status, position):
        if status.currentData() != "FINISHED":
            position.setValue(0)
        self.editor_changed()

    def position_changed(self, value, status):
        if value > 0:
            status.setCurrentIndex(status.findData("FINISHED"))
        self.editor_changed()

    def collect_results(self):
        supplied = {}
        rnd = self.current_round()
        for driver_id, (status, position, pole, fastest, penalty, note) in self.row_widgets.items():
            code = status.currentData()
            if not code:
                if position.value() or pole.isChecked() or fastest.isChecked() or penalty.value() or note.text().strip():
                    raise ValidationError("기록이 있는 행의 출전 상태를 선택하세요.")
                continue
            result = Result(code, position.value() or None, pole.isChecked(), fastest.isChecked(), penalty.value(), note.text().strip())
            old = rnd.results.get(driver_id)
            if old:
                if code == "POINTS":
                    result.recorded_points = old.recorded_points
                result.screen_position = old.screen_position
                result.best_lap_ms = old.best_lap_ms
                result.raw = deepcopy(old.raw)
                if all(getattr(result, key) == getattr(old, key) for key in ("status", "position", "pole", "fastest", "penalty", "note")):
                    result.source = old.source
            supplied[driver_id] = result
        return supplied

    def apply_editor(self):
        rnd = self.current_round()
        if not rnd:
            return False
        try:
            reason = self.reason.text().strip() or ("최초 결과 입력" if not rnd.confirmed else "")
            changed = apply_results(self.league, rnd.id, self.collect_results(), reason)
        except ValidationError as exc:
            self.error(exc)
            return False
        if changed:
            self.mark_dirty()
        self.refresh()
        self.statusBar().showMessage("결과를 반영했습니다. 파일 저장으로 변경 내용을 보관하세요.")
        return True

    def import_screenshots(self):
        if not self.resolve_editor() or not self.current_round():
            return
        from .ocr_ui import OcrDialog
        dialog = OcrDialog(self.league, self.current_round_id, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.league = dialog.updated_league
            self.mark_dirty()
            self.refresh()
            self.statusBar().showMessage("인식 결과를 반영했습니다. 저장 버튼으로 리그 파일을 보관하세요.")

    def export_png(self, *, suggested_path=None):
        if not self.resolve_editor():
            return False
        from .export_ui import ExportDialog
        try:
            dialog = ExportDialog(self.league, self, suggested_path=suggested_path)
        except (ValueError, MemoryError) as exc:
            self.error(exc)
            return False
        saved = False

        def on_saved(path, document, scale):
            nonlocal saved
            self.png_saved(path, document, scale)
            if document is not None and not self.dirty and self.path == Path(path):
                saved = True

        dialog.saved.connect(on_saved)
        dialog.exec()
        return saved and self.path is not None and not (self.dirty or self.editor_dirty)

    def png_saved(self, path, document, scale):
        target = Path(path)
        if document is None:
            if self.path and self.path.resolve() == target.resolve():
                self.path = None
                self.mark_dirty()
            return
        if not self.editor_dirty and serialize_league(self.league) == document:
            self.path, self.png_scale, self.dirty = target, scale, False
            self.saved_workflow()
            self.update_title()
            self.statusBar().showMessage(f"리그 저장됨 · {target} · Ctrl+S로 PNG 갱신")

    def resolve_editor(self):
        if not self.editor_dirty:
            return True
        dialog = QMessageBox(QMessageBox.Icon.Question, "입력 중인 결과", "입력 중인 결과를 먼저 반영할까요?", parent=self)
        apply = dialog.addButton("반영", QMessageBox.ButtonRole.AcceptRole)
        discard = dialog.addButton("입력 취소", QMessageBox.ButtonRole.DestructiveRole)
        dialog.addButton("돌아가기", QMessageBox.ButtonRole.RejectRole)
        dialog.exec()
        if dialog.clickedButton() == apply:
            return self.apply_editor()
        if dialog.clickedButton() == discard:
            self.render_results()
            return True
        return False

    def switch_round(self, _):
        target = self.round_combo.currentData()
        if not self.resolve_editor():
            self.round_combo.blockSignals(True)
            self.round_combo.setCurrentIndex(self.round_combo.findData(self.current_round_id))
            self.round_combo.blockSignals(False)
            return
        self.current_round_id = target
        self.round_combo.blockSignals(True)
        self.round_combo.setCurrentIndex(self.round_combo.findData(target))
        self.round_combo.blockSignals(False)
        self.render_results()

    def manage_rounds(self):
        if not self.resolve_editor() or not self.league.rounds:
            return
        from .rounds_ui import RoundManagerDialog
        selected = self.current_round_id
        dialog = RoundManagerDialog(self.league, selected, self)
        if dialog.exec() != QDialog.DialogCode.Accepted or dialog.league.rounds == self.league.rounds:
            return
        validate_league(dialog.league)
        self.league = dialog.league
        if not any(rnd.id == selected for rnd in self.league.rounds):
            self.current_round_id = dialog.selected_id()
        self.mark_dirty()
        self.refresh()
        self.statusBar().showMessage("라운드 구성을 변경하고 종합 순위를 갱신했습니다. PNG 저장으로 보관하세요.")

    def add_round(self):
        if not self.resolve_editor():
            return
        number = len(self.league.rounds) + 1
        names = {rnd.name for rnd in self.league.rounds}
        while f"R{number:02}" in names:
            number += 1
        dialog = RoundDialog(f"R{number:02}", self.catalog, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            rnd = dialog.value()
            candidate = deepcopy(self.league)
            candidate.rounds.append(rnd)
            validate_league(candidate)
            self.league = candidate
        except ValidationError as exc:
            self.error(exc)
            return
        self.current_round_id = rnd.id
        self.mark_dirty()
        self.refresh()
        self.tabs.setCurrentIndex(1)

    def edit_track(self):
        if not self.resolve_editor():
            return
        rnd = self.current_round()
        if not rnd:
            return
        dialog = RoundDialog(rnd.name, self.catalog, self)
        dialog.setWindowTitle("라운드 이름 · 코스 변경")
        index = dialog.track.findText(rnd.track_name)
        dialog.track.setCurrentIndex(max(0, index))
        if dialog.exec() == QDialog.DialogCode.Accepted:
            try:
                value = dialog.value()
                candidate = deepcopy(self.league)
                target = next(r for r in candidate.rounds if r.id == rnd.id)
                target.name, target.track_id, target.track_name, target.catalog_date = value.name, value.track_id, value.track_name, value.catalog_date
                validate_league(candidate)
                self.league = candidate
                self.mark_dirty()
                self.refresh()
            except ValidationError as exc:
                self.error(exc)

    def add_driver_dialog(self):
        if not self.resolve_editor():
            return
        value, accepted = QInputDialog.getMultiLineText(self, "드라이버 추가", "드라이버 이름을 한 줄에 한 명씩 입력하세요.")
        if accepted and value.strip():
            try:
                add_drivers(self.league, value.splitlines())
                self.mark_dirty()
                self.refresh()
            except ValidationError as exc:
                self.error(exc)

    def rename_driver(self):
        if not self.resolve_editor():
            return
        row = self.drivers_table.currentRow()
        if row < 0:
            self.error("이름을 수정할 드라이버를 선택하세요.")
            return
        value, accepted = QInputDialog.getText(self, "드라이버 이름 수정", "경기 기록은 그대로 유지됩니다.", text=self.league.drivers[row].name)
        if accepted:
            candidate = deepcopy(self.league)
            candidate.drivers[row].name = value.strip()
            try:
                validate_league(candidate)
                self.league = candidate
                self.mark_dirty()
                self.refresh()
            except ValidationError as exc:
                self.error(exc)

    def edit_rules(self):
        if not self.resolve_editor():
            return
        dialog = RulesDialog(self.league, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            try:
                candidate = deepcopy(self.league)
                candidate.name = dialog.name.text().strip()
                update_rules(candidate, dialog.values())
                validate_league(candidate)
                self.league = candidate
                self.mark_dirty()
                self.refresh()
            except ValidationError as exc:
                self.error(exc)

    def show_history(self):
        if not self.resolve_editor():
            return
        rnd = self.current_round()
        if not rnd:
            return
        dialog = QDialog(self)
        dialog.setWindowTitle(f"{rnd.name} · 결과 변경 이력")
        dialog.resize(760, 560)
        layout = QVBoxLayout(dialog)
        viewer = QTextEdit()
        viewer.setReadOnly(True)
        names = {d.id: d.name for d in self.league.drivers}
        lines = []
        for revision in reversed(rnd.history):
            lines.append(f"개정 {revision.number}  |  {revision.at}\n사유: {revision.reason}")
            for driver_id, result in revision.results.items():
                lines.append(f"  {names[driver_id]} · {result.position or '—'}위 / {STATUS_LABELS[result.status]} / 폴 {result.pole} / 패스티스트랩 {result.fastest} / 벌점 {result.penalty}\n    {result.note}")
            lines.append("")
        viewer.setPlainText("\n".join(lines) or "아직 반영한 경기 결과가 없습니다.")
        layout.addWidget(viewer)
        if len(rnd.history) > 1:
            choices = QComboBox()
            for revision in rnd.history[:-1]:
                choices.addItem(f'개정 {revision.number} · {revision.reason}', revision.number)
            layout.addWidget(choices)

            def restore():
                reason, accepted = QInputDialog.getText(dialog, '이전 결과 복원', '복원 사유 (기존 이력을 유지하고 새 개정으로 추가합니다)')
                if not accepted:
                    return
                try:
                    changed = self.restore_revision(choices.currentData(), reason)
                    if changed:
                        dialog.accept()
                        self.statusBar().showMessage('이전 결과를 새 개정으로 복원했습니다. PNG로 저장하세요.')
                    else:
                        QMessageBox.information(dialog, '결과 복원', '현재 결과와 동일합니다.')
                except ValidationError as exc:
                    self.error(exc)

            layout.addWidget(button('선택한 개정으로 결과 복원', restore, True))
        layout.addWidget(button("닫기", dialog.accept))
        dialog.exec()

    def maybe_save(self):
        if not (self.dirty or self.editor_dirty):
            return True
        answer = QMessageBox.question(self, "변경 내용 저장", "저장하지 않은 변경 내용이 있습니다. 저장할까요?", QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel)
        if answer == QMessageBox.StandardButton.Save:
            return self.save()
        return answer == QMessageBox.StandardButton.Discard

    def new_league(self):
        if self.maybe_save():
            self.league, self.path, self.current_round_id = League(), None, None
            self.png_scale = 1
            self.png_suggestion = None
            self.dirty = self.editor_dirty = False
            self.reset_history()
            self.refresh()
            self.schedule_recovery()

    def open_league(self):
        if not self.maybe_save():
            return
        path, _ = QFileDialog.getOpenFileName(self, "리그 파일 · 데이터 포함 PNG 열기", "", "리그 및 데이터 포함 PNG (*.gtlb *.png);;GTLeaderboard 리그 (*.gtlb);;데이터 포함 PNG (*.png)")
        if path:
            return self.load_path(path, check_save=False)

    def load_path(self, path, *, check_save=True):
        if check_save and not self.maybe_save():
            return False
        if path:
            try:
                league = load_league(path)
                from_png = Path(path).suffix.lower() == ".png"
                self.league, self.path, self.current_round_id = league, Path(path) if from_png else None, None
                self.png_suggestion = Path(path).with_suffix(".png")
                self.png_scale = 1
                self.dirty = self.editor_dirty = False
                self.reset_history()
                self.refresh()
                self.remember_file(path)
                self.schedule_recovery()
                if from_png:
                    self.statusBar().showMessage("PNG에서 리그를 열었습니다. Ctrl+S로 그림과 리그 데이터를 함께 갱신합니다.")
                else:
                    self.statusBar().showMessage("GTLB 데이터를 열었습니다. 저장하면 데이터 포함 PNG로 보관합니다. GTLB는 내보내기에서 만들 수 있습니다.")
                return True
            except (OSError, ValidationError) as exc:
                self.error(exc)
        return False

    def suggested_filename(self, suffix):
        name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", self.league.name).strip(" .")[:100] or "리그"
        return f"{name}_종합{suffix}"

    def choose_output_path(self, title, suggested, file_filter, suffix):
        path, _ = QFileDialog.getSaveFileName(self, title, str(suggested), file_filter)
        if not path:
            return None
        original = Path(path)
        target = original if original.suffix.lower() == suffix else original.with_suffix(suffix)
        # The native dialog only confirms its selected name, before suffix normalization.
        if target != original and target.exists():
            answer = QMessageBox.question(self, "파일 덮어쓰기", f"이미 존재하는 파일입니다. 덮어쓸까요?\n{target}", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
            if answer != QMessageBox.StandardButton.Yes:
                return None
        return target

    def save_as(self):
        return self.save(force_choose=True)

    def save(self, checked=False, *, force_choose=False):
        if self.editor_dirty and not self.apply_editor():
            return False
        target = self.path
        if force_choose or target is None or target.suffix.lower() != ".png":
            suggested = self.path.with_suffix(".png") if self.path else self.png_suggestion or self.suggested_filename(".png")
            return self.export_png(suggested_path=suggested)
        try:
            from .export_png import render_sheet, save_png
            document = serialize_league(self.league)
            save_png(target, render_sheet(self.league, self.png_scale), document)
            self.path = target
            self.dirty = False
            self.saved_workflow()
            self.update_title()
            self.statusBar().showMessage(f"저장됨 · {target}")
            return True
        except (OSError, ValidationError, MemoryError) as exc:
            self.error(exc)
            return False

    def export_league(self):
        self.export_document("gtlb")

    def export_csv(self):
        self.export_document("csv")

    def export_document(self, kind):
        if not self.resolve_editor():
            return
        label = "리그 데이터" if kind == "gtlb" else "보이는 리더보드"
        suffix = f".{kind}"
        target = self.choose_output_path(f"{label} 내보내기", self.suggested_filename(suffix), f"{label} (*{suffix})", suffix)
        if target is None:
            return
        try:
            if kind == "gtlb":
                save_league(target, self.league)
            else:
                from .export_csv import save_csv
                save_csv(target, self.league)
            self.statusBar().showMessage(f"내보내기 완료 · {target} · 기본 저장 파일은 PNG입니다.")
        except (OSError, ValidationError) as exc:
            self.error(exc)

    def import_rules(self):
        if not self.resolve_editor():
            return
        path, _ = QFileDialog.getOpenFileName(self, "배점 파일 열기", "", "GTLeaderboard 규칙 (*.gtlr)")
        if path:
            try:
                rules = load_rules(path)
                preview = deepcopy(self.league)
                preview.rules = rules
                dialog = RulesDialog(preview, self)
                if dialog.exec() == QDialog.DialogCode.Accepted:
                    candidate = deepcopy(self.league)
                    candidate.name = dialog.name.text().strip()
                    update_rules(candidate, dialog.values())
                    validate_league(candidate)
                    self.league = candidate
                    self.mark_dirty()
                    self.refresh()
            except (OSError, ValidationError) as exc:
                self.error(exc)

    def export_rules(self):
        path, _ = QFileDialog.getSaveFileName(self, "배점 파일 저장", "rules.gtlr", "GTLeaderboard 규칙 (*.gtlr)")
        if path:
            target = Path(path)
            if target.suffix.lower() != ".gtlr":
                target = target.with_suffix(".gtlr")
            try:
                save_rules(target, self.league.rules)
            except (OSError, ValidationError) as exc:
                self.error(exc)

    def closeEvent(self, event):
        if self.maybe_save():
            self.finish_session()
            event.accept()
        else:
            event.ignore()
