"""Transactional round removal and ordering with stable result identities."""
from copy import deepcopy

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QMessageBox, QVBoxLayout

from .domain import remove_round, reorder_rounds
from .ui import button


class RoundManagerDialog(QDialog):
    def __init__(self, league, selected_id=None, parent=None):
        super().__init__(parent)
        self.league = deepcopy(league)
        self.setWindowTitle("라운드 관리")
        self.resize(760, 530)
        layout = QVBoxLayout(self)
        hint = QLabel("라운드를 선택한 뒤 위·아래로 이동하거나 삭제하세요.\n순서는 종합표·PNG·CSV에 함께 적용됩니다. 라운드 이름과 경기 기록은 그대로 유지됩니다.")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self.list = QListWidget()
        self.list.setSpacing(4)
        self.list.currentRowChanged.connect(self.update_buttons)
        layout.addWidget(self.list, 1)
        controls = QHBoxLayout()
        self.up = button("위로 이동", lambda: self.move(-1))
        self.down = button("아래로 이동", lambda: self.move(1))
        self.delete = button("선택 라운드 삭제", self.delete_selected)
        for widget in (self.up, self.down, self.delete):
            controls.addWidget(widget)
        controls.addStretch()
        layout.addLayout(controls)
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)
        bottom = QHBoxLayout()
        bottom.addStretch()
        bottom.addWidget(button("취소", self.reject))
        bottom.addWidget(button("변경 적용", self.accept, True))
        layout.addLayout(bottom)
        self.deleted_names = []
        self.refresh(selected_id)

    def selected_id(self):
        item = self.list.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def refresh(self, selected_id=None, fallback=0):
        self.list.blockSignals(True)
        self.list.clear()
        selected = fallback
        for index, rnd in enumerate(self.league.rounds):
            state = f"결과 {len(rnd.results)}명 · 이력 {len(rnd.history)}개" if rnd.confirmed else "미진행"
            item = QListWidgetItem(f"{index + 1}.  {rnd.name}   ·   {rnd.track_name}\n     {state}")
            item.setData(Qt.ItemDataRole.UserRole, rnd.id)
            self.list.addItem(item)
            if rnd.id == selected_id:
                selected = index
        self.list.setCurrentRow(min(selected, len(self.league.rounds) - 1))
        self.list.blockSignals(False)
        self.update_buttons()
        if self.deleted_names:
            self.summary.setText(f"삭제 예정 {len(self.deleted_names)}개: {', '.join(self.deleted_names)}\n‘변경 적용’을 눌러 반영합니다. 취소하면 순서와 삭제를 모두 되돌립니다.")
        else:
            self.summary.setText("변경 적용 후 PNG를 저장하면 파일에도 반영됩니다. 취소하면 원래 상태를 유지합니다.")

    def update_buttons(self, *_):
        index = self.list.currentRow()
        self.up.setEnabled(index > 0)
        self.down.setEnabled(0 <= index < self.list.count() - 1)
        self.delete.setEnabled(index >= 0)

    def move(self, offset):
        index = self.list.currentRow()
        target = index + offset
        if index < 0 or not 0 <= target < len(self.league.rounds):
            return
        rid = self.selected_id()
        order = [rnd.id for rnd in self.league.rounds]
        order[index], order[target] = order[target], order[index]
        reorder_rounds(self.league, order)
        self.refresh(rid)

    def delete_selected(self):
        index = self.list.currentRow()
        if index < 0:
            return
        rnd = self.league.rounds[index]
        detail = f"‘{rnd.name}’ 라운드를 삭제할까요?\n\n코스: {rnd.track_name}\n결과 {len(rnd.results)}명과 변경 이력 {len(rnd.history)}개가 함께 삭제되고, 이 라운드 점수는 종합 순위에서 제외됩니다.\n\n변경 적용 전에는 이 창의 취소로 되돌릴 수 있습니다."
        answer = QMessageBox.question(self, "라운드 삭제", detail, QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
        if answer != QMessageBox.StandardButton.Yes:
            return
        remove_round(self.league, rnd.id)
        self.deleted_names.append(rnd.name)
        self.refresh(fallback=index)
