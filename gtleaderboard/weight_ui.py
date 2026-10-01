"""Weight rules and editable per-race snapshots; all quantities are kilograms."""
from PySide6.QtWidgets import QCheckBox, QFormLayout, QGridLayout, QGroupBox, QLabel, QSpinBox, QVBoxLayout, QWidget
from PySide6.QtCore import Qt

from .domain import MAX_BALLAST_KG, WeightRecord, WeightRules, calculate_weight


def kg_spin(value=0, signed=False):
    field = QSpinBox()
    field.setRange(-MAX_BALLAST_KG if signed else 0, MAX_BALLAST_KG)
    field.setSuffix(' kg')
    field.setValue(value)
    return field


class WeightRulesPanel(QWidget):
    def __init__(self, rules, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        self.enabled = QCheckBox('웨이트 페널티 사용')
        self.enabled.setChecked(rules.enabled)
        layout.addWidget(self.enabled)
        self.cap = kg_spin(rules.max_total)
        form = QFormLayout()
        form.addRow('누적 웨이트 상한 (게임 최대 200kg)', self.cap)
        layout.addLayout(form)
        box = QGroupBox('결승 순위별 증감량 · 양수는 증량, 0은 유지, 음수는 감량')
        grid = QGridLayout(box)
        self.changes = []
        for index, value in enumerate(rules.position_changes):
            field = kg_spin(value, signed=True)
            self.changes.append(field)
            row, col = divmod(index, 4)
            grid.addWidget(QLabel(f'{index + 1}위'), row, col * 2)
            grid.addWidget(field, row, col * 2 + 1)
        layout.addWidget(box)
        hint = QLabel('예정 중량 = 실제 적용 중량 + 증감량 (0kg~리그 상한).\n'
                      'DNS·DNQ·DNF·DSQ·점수만 보존은 자동 증감 0kg입니다.\n'
                      'OCR 신규 선수는 실제 0kg, 다음 라운드는 이전 예정 중량을 기본값으로 씁니다.\n'
                      '실제 중량과 증감값은 나중에 수정할 수 있으며, 예정 중량은 자동 계산됩니다.\n'
                      '규칙 변경은 저장된 중량을 소급 변경하지 않습니다. 필요한 라운드에서 규칙 재계산을 사용하세요.')
        hint.setWordWrap(True)
        layout.addWidget(hint)
        layout.addStretch()

    def value(self):
        return WeightRules(self.enabled.isChecked(), [f.value() for f in self.changes], self.cap.value())


class WeightRow:
    def __init__(self, value, result, rules, changed):
        self.rules = rules
        self.result = result
        self.actual = kg_spin(value.actual)
        self.change = kg_spin(value.change, signed=True)
        # Past snapshots may exceed a newly lowered league cap. Show them intact.
        self.planned_value = value.planned
        self.planned = QLabel(f'{value.planned} kg')
        self.planned.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.planned.setStyleSheet('background: #e7f3ef; color: #006b66; font-weight: bold; padding: 5px;')
        self.change_manual = value.change_manual
        self.planned_manual = value.planned_manual
        self.changed = changed
        self.busy = False
        self.actual.setToolTip('이 경기에 실제 적용한 밸러스트. 과거 결과·규칙 변경으로 자동 변경되지 않습니다.')
        self.actual.valueChanged.connect(self.actual_changed)
        self.change.valueChanged.connect(self.change_changed)
        self.refresh_hints()

    @property
    def fields(self):
        return (self.actual, self.change, self.planned)

    def value(self):
        return WeightRecord(self.actual.value(), self.change.value(), self.planned_value, self.change_manual, self.planned_manual)

    def load(self, value):
        self.busy = True
        self.actual.setValue(value.actual)
        self.change.setValue(value.change)
        self.planned_value = value.planned
        self.planned.setText(f'{value.planned} kg')
        self.change_manual = value.change_manual
        self.planned_manual = value.planned_manual
        self.busy = False
        self.refresh_hints()

    def refresh_hints(self):
        self.change.setToolTip(('직접 지정' if self.change_manual else '순위 규칙 자동 계산') + ' · 음수는 감량. 규칙 재계산으로 자동값 복원.')
        self.planned.setToolTip(f'자동 계산 결과 · 실제 중량 + 증감량을 0~{self.rules.max_total}kg으로 제한합니다. 직접 입력할 수 없습니다. 과거 기록은 중량 수정 또는 규칙 재계산 전까지 유지됩니다.')

    def recalculate(self, result=None, reset=False):
        if result is not None:
            self.result = result
        value = self.value()
        if reset:
            value.change_manual = value.planned_manual = False
        self.load(calculate_weight(value, self.result, self.rules))

    def actual_changed(self):
        if not self.busy:
            self.recalculate()
            self.changed()

    def change_changed(self):
        if not self.busy:
            self.change_manual = True
            self.recalculate()
            self.changed()
