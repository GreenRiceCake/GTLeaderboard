"""Session recovery, recent files and a guided first-season workflow."""
from copy import deepcopy
from datetime import datetime
import json
from pathlib import Path

from PySide6.QtCore import QSettings, QStandardPaths, QTimer, QUrl
from PySide6.QtGui import QAction, QDesktopServices, QKeySequence
from PySide6.QtWidgets import QDialog, QFormLayout, QInputDialog, QLabel, QLineEdit, QListWidget, QMessageBox, QPushButton, QTextEdit, QVBoxLayout, QWizard, QWizardPage

from .domain import League, Round, ValidationError, add_drivers, apply_results, validate_league
from .session import RecoveryStore, UndoHistory
from .storage import serialize_league
from .widgets import SearchableComboBox


class SeasonWizard(QWizard):
    def __init__(self, catalog, parent=None):
        super().__init__(parent)
        self.setWindowTitle('새 시즌 만들기')
        self.setWizardStyle(QWizard.WizardStyle.ModernStyle)
        self.resize(660, 490)
        self.league = League()
        for key, label in ((QWizard.BackButton, '이전'), (QWizard.NextButton, '다음'), (QWizard.FinishButton, '시즌 만들기'), (QWizard.CancelButton, '취소')):
            self.setButtonText(key, label)
        first = QWizardPage()
        first.setTitle('1. 리그 이름과 배점')
        form = QFormLayout(first)
        self.name = QLineEdit('새 리그')
        self.name.setMaxLength(200)
        form.addRow('리그 이름', self.name)
        self.rules_info = QLabel('기본 배점을 사용합니다. 예선 폴·패스티스트랩 각각 3점.')
        self.rules_info.setWordWrap(True)
        form.addRow(self.rules_info)
        rules = QPushButton('배점과 보너스 설정')
        rules.clicked.connect(self.edit_rules)
        form.addRow(rules)
        self.addPage(first)
        second = QWizardPage()
        second.setTitle('2. 시즌 참가자 (선택)')
        layout = QVBoxLayout(second)
        layout.addWidget(QLabel('지금 등록하려면 이름을 한 줄에 한 명씩 입력하세요. 시즌 명단은 16명을 넘어도 됩니다.\n비워 두고 ‘다음’을 눌러도 됩니다. 나중에 드라이버 · 파일에서 추가할 수 있습니다.'))
        self.drivers = QTextEdit()
        self.drivers.setPlaceholderText('선택 입력 · 비워 두면 나중에 등록합니다.\n\n드라이버 A\n드라이버 B')
        layout.addWidget(self.drivers)
        self.addPage(second)
        third = QWizardPage()
        third.setTitle('3. 첫 라운드')
        form = QFormLayout(third)
        self.round_name = QLineEdit('R01')
        self.round_name.setMaxLength(80)
        self.track = SearchableComboBox()
        self.track.addItem('코스 미정', None)
        for track in catalog['tracks']:
            self.track.addItem(track['name'], track)
        self.track.setEditable(True)
        self.track.setInsertPolicy(SearchableComboBox.InsertPolicy.NoInsert)
        form.addRow('라운드 이름', self.round_name)
        form.addRow('코스 · 이름 일부로 검색', self.track)
        self.catalog = catalog
        self.addPage(third)

    def edit_rules(self):
        from .ui import RulesDialog
        candidate = deepcopy(self.league)
        candidate.name = self.name.text().strip() or '새 리그'
        dialog = RulesDialog(candidate, self)
        if dialog.exec() == QDialog.Accepted:
            candidate.name = dialog.name.text().strip()
            candidate.rules = dialog.values()
            try:
                validate_league(candidate)
            except ValidationError as exc:
                QMessageBox.warning(self, '배점 확인', str(exc))
                return
            self.league = candidate
            self.name.setText(candidate.name)
            self.rules_info.setText('사용자 지정 배점과 보너스 설정을 적용했습니다.')

    def validateCurrentPage(self):
        try:
            candidate = deepcopy(self.league)
            candidate.name = self.name.text().strip()
            if self.currentId() >= 1:
                candidate.drivers = []
                add_drivers(candidate, self.drivers.toPlainText().splitlines())
            if self.currentId() == 2:
                index = self.track.findText(self.track.currentText())
                if index < 0:
                    raise ValidationError('목록에서 코스를 선택하세요.')
                track = self.track.itemData(index)
                candidate.rounds = [Round(self.round_name.text().strip(), track['id'] if track else '', track['name'] if track else '미정', self.catalog['retrieved_at'] if track else '')]
            validate_league(candidate)
            self.league = candidate
            return True
        except ValidationError as exc:
            QMessageBox.warning(self, '시즌 정보 확인', str(exc))
            return False


class WorkflowMixin:
    def init_workflow(self, file_menu):
        self.session_settings = None
        self.recovery = None
        self.recovery_timer = QTimer(self)
        self.recovery_timer.setSingleShot(True)
        self.recovery_timer.setInterval(1000)
        self.recovery_timer.timeout.connect(self.write_recovery)
        self.history = UndoHistory(self.league)
        self.saved_document = serialize_league(self.league)
        edit_menu = self.menuBar().addMenu('편집')
        self.undo_action = QAction('작업 실행 취소', self)
        self.undo_action.setShortcut(QKeySequence.Undo)
        self.undo_action.triggered.connect(lambda: self.undo_work(True))
        self.redo_action = QAction('작업 다시 실행', self)
        self.redo_action.setShortcuts([QKeySequence.Redo, QKeySequence('Ctrl+Shift+Z')])
        self.redo_action.triggered.connect(lambda: self.undo_work(False))
        edit_menu.addActions([self.undo_action, self.redo_action])
        file_menu.addAction('새 시즌 만들기…', self.start_season)
        self.recent_menu = file_menu.addMenu('최근 리그')
        file_menu.addAction('현재 PNG 폴더 열기', self.open_current_folder)
        file_menu.addAction('복구할 작업 찾기…', self.offer_recovery)
        self.saved_folder_button = QPushButton('저장 폴더 열기')
        self.saved_folder_button.clicked.connect(self.open_current_folder)
        self.statusBar().addPermanentWidget(self.saved_folder_button)
        self.refresh_recent()
        self.refresh_workflow()

    def enable_session(self, settings=None, directory=None):
        self.session_settings = settings if settings is not None else QSettings('GTLeaderboard', 'GTLeaderboard')
        try:
            directory = directory or Path(QStandardPaths.writableLocation(QStandardPaths.AppLocalDataLocation)) / 'recovery'
            self.recovery = RecoveryStore(directory)
        except OSError as exc:
            self.statusBar().showMessage(f'자동 복구를 시작하지 못했습니다. 수동 저장을 이용하세요: {exc}')
        self.refresh_recent()

    def reset_history(self):
        self.history = UndoHistory(self.league)
        self.saved_document = serialize_league(self.league)
        self.refresh_workflow()

    def refresh_workflow(self):
        if not hasattr(self, 'undo_action'):
            return
        self.undo_action.setEnabled(bool(self.history.undo) or self.editor_dirty)
        self.redo_action.setEnabled(bool(self.history.redo) and not self.editor_dirty)
        self.saved_folder_button.setEnabled(self.path is not None)
        if hasattr(self, 'welcome'):
            self.welcome.setVisible(not self.league.drivers and not self.league.rounds)

    def changed_workflow(self):
        if hasattr(self, 'history'):
            self.history.record(self.league)
            self.refresh_workflow()
            self.schedule_recovery()

    def undo_work(self, backwards):
        # An unfinished table is its own draft; do not silently commit it on undo.
        if self.editor_dirty:
            answer = QMessageBox.question(self, '입력 중인 결과', '현재 라운드의 미반영 입력을 취소할까요?\n이미 반영된 결과는 유지됩니다.', QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if answer == QMessageBox.Yes:
                self.render_results()
                self.update_title()
                self.schedule_recovery()
            return
        restored = self.history.move(backwards)
        if restored is None:
            return
        self.league = restored
        self.dirty = serialize_league(self.league) != self.saved_document
        self.refresh()
        self.refresh_workflow()
        self.schedule_recovery()
        self.statusBar().showMessage('작업을 되돌렸습니다. PNG 저장으로 보관하세요.' if backwards else '작업을 다시 실행했습니다. PNG 저장으로 보관하세요.')

    def saved_workflow(self):
        self.saved_document = serialize_league(self.league)
        self.remember_file(self.path)
        self.write_recovery()

    def schedule_recovery(self):
        if self.recovery is not None:
            if not self.recovery_timer.isActive():
                self.recovery_timer.start()

    def write_recovery(self):
        if self.recovery is None:
            return
        try:
            if not (self.dirty or self.editor_dirty):
                self.recovery.clear()
                return True
            draft = {}
            if self.editor_dirty:
                for key, (status, position, pole, fastest, penalty, note) in self.row_widgets.items():
                    draft[key] = [status.currentData(), position.value(), pole.isChecked(), fastest.isChecked(), penalty.value(), note.text()]
            self.recovery.write({'league': json.loads(serialize_league(self.league)), 'round_id': self.current_round_id,
                                 'draft': draft, 'reason': self.reason.text(), 'scale': self.png_scale,
                                 'source': str(self.path or self.png_suggestion or '')})
            return True
        except (OSError, ValueError) as exc:
            self.statusBar().showMessage(f'자동 복구 저장 실패 · PNG를 직접 저장해 주세요: {exc}')
            return False

    def offer_recovery(self):
        if self.recovery is None:
            return
        try:
            paths = self.recovery.candidates()
        except OSError as exc:
            self.error(exc)
            return
        if not paths:
            self.statusBar().showMessage('복구할 미저장 작업이 없습니다.')
            return
        dialog = QDialog(self)
        dialog.setWindowTitle('이전 미저장 작업 복구')
        dialog.resize(660, 340)
        layout = QVBoxLayout(dialog)
        label = QLabel('작업을 선택하면 별도 복구본으로 엽니다. 원본 PNG는 변경하지 않습니다.\n나중에 파일 → 복구할 작업 찾기에서 다시 열 수 있습니다.')
        label.setWordWrap(True)
        layout.addWidget(label)
        listing = QListWidget()
        layout.addWidget(listing)
        valid = []
        for path in paths:
            try:
                data, league = self.recovery.read(path)
                listing.addItem(f"{league.name} · {data['at']}\n{data['source'] or '아직 저장하지 않은 리그'}")
                valid.append(path)
            except (OSError, ValueError, KeyError):
                listing.addItem(f'읽을 수 없는 복구 파일 · {path.name}')
                valid.append(None)
        listing.setCurrentRow(0)
        restore = QPushButton('선택한 작업 복구')
        restore.clicked.connect(dialog.accept)
        listing.currentRowChanged.connect(lambda index: restore.setEnabled(index >= 0 and valid[index] is not None))
        restore.setEnabled(valid[0] is not None)
        layout.addWidget(restore)
        later = QPushButton('나중에')
        later.clicked.connect(dialog.reject)
        layout.addWidget(later)
        if dialog.exec() == QDialog.Accepted and self.maybe_save():
            path = valid[listing.currentRow()]
            lock = self.recovery.lock_for(path)
            if not lock.tryLock(0):
                self.error('다른 창에서 복구 중입니다.')
                return
            try:
                data, league = self.recovery.read(path)
                self.restore_snapshot(data, league)
                if self.write_recovery():
                    path.unlink()
            except (OSError, ValueError) as exc:
                self.error(exc)
            finally:
                lock.unlock()

    def restore_snapshot(self, data, league):
        self.league = league
        self.path = None
        source = Path(data['source']) if data['source'] else Path('리그.png')
        self.png_suggestion = source.with_name(source.stem + '_복구.png')
        self.png_scale = data['scale']
        self.current_round_id = data['round_id']
        self.editor_dirty = False
        self.reset_history()
        self.saved_document = None
        self.dirty = True
        self.refresh()
        for key, values in data['draft'].items():
            fields = self.row_widgets[key]
            for field in fields:
                field.blockSignals(True)
            status, position, pole, fastest, penalty, note = fields
            status.setCurrentIndex(status.findData(values[0]))
            position.setValue(values[1])
            pole.setChecked(values[2])
            fastest.setChecked(values[3])
            penalty.setValue(values[4])
            note.setText(values[5])
            for field in fields:
                field.blockSignals(False)
        self.reason.setText(data['reason'])
        self.editor_dirty = bool(data['draft'])
        if self.editor_dirty:
            self.tabs.setCurrentIndex(1)
        self.update_title()
        self.refresh_workflow()
        self.statusBar().showMessage('복구본을 열었습니다. 미반영 입력을 확인한 뒤 새 PNG로 저장하세요.')

    def finish_session(self):
        self.recovery_timer.stop()
        if self.recovery is not None:
            try:
                self.recovery.close()
            except OSError:
                self.recovery.lock.unlock()

    def recent_files(self):
        if self.session_settings is None:
            return []
        try:
            values = json.loads(self.session_settings.value('files/recent', '[]'))
            return [p for p in values if isinstance(p, str) and len(p) <= 4096][:10] if isinstance(values, list) else []
        except (ValueError, TypeError):
            return []

    def remember_file(self, path):
        if path is None or self.session_settings is None:
            return
        path = str(Path(path).resolve())
        values = [p for p in self.recent_files() if p.casefold() != path.casefold()]
        self.session_settings.setValue('files/recent', json.dumps([path, *values][:10], ensure_ascii=False))
        self.session_settings.sync()
        self.refresh_recent()

    def refresh_recent(self):
        self.recent_menu.clear()
        if hasattr(self, 'recent_list'):
            self.recent_list.clear()
            self.recent_list.setVisible(bool(self.recent_files()))
            self.recent_hint.setVisible(not self.recent_files())
        for path in self.recent_files():
            target = Path(path)
            label = f'{target.stem} · {target.parent}'
            try:
                label += f" · {datetime.fromtimestamp(target.stat().st_mtime):%Y-%m-%d %H:%M}"
            except OSError:
                label += ' (파일 위치 확인 필요)'
            action = self.recent_menu.addAction(label)
            action.triggered.connect(lambda checked=False, p=path: self.open_recent(p))
            if hasattr(self, 'recent_list'):
                self.recent_list.addItem(label)
        self.recent_menu.setEnabled(bool(self.recent_files()))

    def open_recent(self, path):
        if not Path(path).is_file():
            from PySide6.QtWidgets import QFileDialog
            replacement, _ = QFileDialog.getOpenFileName(self, '이동한 리그 파일 찾기', str(Path(path).parent), '리그 (*.png *.gtlb)')
            if not replacement:
                return
            if self.load_path(replacement):
                values = [p for p in self.recent_files() if p != path]
                self.session_settings.setValue('files/recent', json.dumps(values, ensure_ascii=False))
                self.refresh_recent()
            return
        self.load_path(path)

    def open_current_folder(self):
        if self.path:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.path.resolve().parent)))
        else:
            self.statusBar().showMessage('먼저 PNG로 저장해 주세요.')

    def start_season(self):
        dialog = SeasonWizard(self.catalog, self)
        if dialog.exec() != QDialog.Accepted or not self.maybe_save():
            return
        self.league = dialog.league
        self.path = self.png_suggestion = None
        self.png_scale = 1
        self.current_round_id = self.league.rounds[0].id
        self.editor_dirty = False
        self.reset_history()
        self.saved_document = None
        self.dirty = True
        self.refresh()
        self.tabs.setCurrentIndex(1)
        self.schedule_recovery()

    def restore_revision(self, number, reason):
        if not reason.strip() or len(reason) > 1900:
            raise ValidationError('복원 사유를 1~1900자로 입력하세요.')
        if not self.resolve_editor():
            return False
        rnd = self.current_round()
        if rnd is None or not 1 <= number <= len(rnd.history):
            raise ValidationError('복원할 개정을 선택하세요.')
        changed = apply_results(self.league, rnd.id, deepcopy(rnd.history[number - 1].results), f'개정 {number} 복원 · {reason.strip()}')
        if changed:
            self.mark_dirty()
            self.refresh()
        return changed
