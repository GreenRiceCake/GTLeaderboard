"""Shared desktop widgets for readable headings and searchable track choices."""

from PySide6.QtCore import QEvent, QRect, QSize, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics
from PySide6.QtWidgets import QAbstractItemView, QComboBox, QCompleter, QHeaderView, QHBoxLayout, QStyle, QTableView, QToolButton, QVBoxLayout, QWidget


class WrappedHeader(QHeaderView):
    def __init__(self, parent=None):
        super().__init__(Qt.Orientation.Horizontal, parent)
        self.sectionResized.connect(self.update_height)
        self.setMinimumSectionSize(70)

    def heading_font(self):
        value = QFont(self.font())
        value.setBold(True)
        return value

    def sizeHint(self):
        height = 48
        if self.model():
            metrics = QFontMetrics(self.heading_font())
            for section in range(self.count()):
                if self.isSectionHidden(section):
                    continue
                value = self.model().headerData(section, self.orientation()) or ""
                area = metrics.boundingRect(QRect(0, 0, max(20, self.sectionSize(section) - 20), 10000), int(Qt.TextFlag.TextWordWrap | Qt.TextFlag.TextWrapAnywhere), str(value))
                height = max(height, area.height() + 24)
        return QSize(super().sizeHint().width(), height)

    def update_height(self, *_):
        self.setFixedHeight(self.sizeHint().height())
        self.viewport().update()

    def paintSection(self, painter, rect, index):
        if not rect.isValid():
            return
        painter.save()
        painter.fillRect(rect, QColor("#eaf0f5"))
        painter.setPen(QColor("#d3dee9"))
        painter.drawLine(rect.bottomLeft(), rect.bottomRight())
        painter.setPen(QColor("#1d2b40"))
        painter.setFont(self.heading_font())
        value = self.model().headerData(index, self.orientation()) or ""
        painter.drawText(rect.adjusted(10, 10, -10, -10), int(Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap | Qt.TextFlag.TextWrapAnywhere), str(value))
        painter.restore()


class FixedTotalPane(QWidget):
    """Two views of one table model, with its final column pinned on the right."""
    def __init__(self, grid, parent=None):
        super().__init__(parent)
        self.grid = grid
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(grid, 1)
        right = QWidget()
        right.setFixedWidth(128 + self.style().pixelMetric(QStyle.PixelMetric.PM_ScrollBarExtent))
        column = QVBoxLayout(right)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(0)
        self.totals = QTableView(right)
        self.totals.setModel(grid.model())
        self.totals.setSelectionModel(grid.selectionModel())
        self.totals.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.totals.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.totals.setAlternatingRowColors(True)
        self.totals.verticalHeader().hide()
        self.totals.verticalHeader().setDefaultSectionSize(grid.verticalHeader().defaultSectionSize())
        self.totals.horizontalHeader().setStretchLastSection(True)
        self.totals.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        self.totals.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.totals.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        grid.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.totals.setStyleSheet('''
            QTableView { background: #edf8f5; alternate-background-color: #e5f2ef;
                border: 1px solid #dce3eb; border-left: 2px solid #9fc9c1; gridline-color: #dcebe6; }
            QTableView::item { padding: 4px; }
            QTableView::item:selected { background: #bcded5; color: #123c3a; }
            QHeaderView::section { background: #dcefe9; color: #006b66; }
        ''')
        column.addWidget(self.totals, 1)
        # Reserve exactly the space occupied by the scrolling view's bottom bar.
        self.bottom_gap = QWidget(right)
        self.bottom_gap.setFixedHeight(0)
        column.addWidget(self.bottom_gap)
        layout.addWidget(right)
        for view in (grid, self.totals):
            view.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        grid.horizontalHeader().setStretchLastSection(False)
        grid.verticalScrollBar().valueChanged.connect(self.totals.verticalScrollBar().setValue)
        self.totals.verticalScrollBar().valueChanged.connect(grid.verticalScrollBar().setValue)
        grid.verticalHeader().sectionResized.connect(lambda row, old, height: self.totals.setRowHeight(row, height))
        for widget in (grid, grid.viewport(), grid.horizontalHeader(), grid.horizontalScrollBar()):
            widget.installEventFilter(self)
        self.sync_columns()

    def sync_columns(self):
        last = self.grid.columnCount() - 1
        for col in range(self.grid.columnCount()):
            self.grid.setColumnHidden(col, col == last)
            self.totals.setColumnHidden(col, col != last)
        for row in range(self.grid.rowCount()):
            self.totals.setRowHeight(row, self.grid.rowHeight(row))
        self.grid.horizontalHeader().update_height()
        self.sync_geometry()

    def sync_geometry(self):
        self.totals.horizontalHeader().setFixedHeight(self.grid.horizontalHeader().height())
        bar = self.grid.horizontalScrollBar()
        self.bottom_gap.setFixedHeight(bar.height() if bar.isVisible() else 0)

    def eventFilter(self, watched, event):
        if event.type() in (QEvent.Type.Resize, QEvent.Type.Show, QEvent.Type.Hide):
            self.sync_geometry()
        return super().eventFilter(watched, event)


class SearchableComboBox(QComboBox):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setEditable(True)
        self.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        completer = self.completer()
        completer.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
        completer.setFilterMode(Qt.MatchFlag.MatchContains)
        completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        completer.setMaxVisibleItems(12)
        completer.popup().setStyleSheet("QAbstractItemView { background: white; color: #1d2b40; font-family: 'Malgun Gothic'; font-size: 14px; border: 1px solid #aabcca; } QAbstractItemView::item { padding: 6px 10px; } QAbstractItemView::item:selected { background: #d9eee9; color: #123c3a; }")
        self.lineEdit().installEventFilter(self)
        self.lineEdit().textEdited.connect(self.filter_choices)
        self.arrow = QToolButton(self)
        self.arrow.setArrowType(Qt.ArrowType.DownArrow)
        self.arrow.setToolTip("코스 목록 열기 · 입력한 글자를 포함하는 코스 검색")
        self.arrow.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.arrow.setStyleSheet("QToolButton { border: none; background: #eaf0f5; color: #1d2b40; font-size: 18px; }")
        self.arrow.clicked.connect(self.showPopup)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.arrow.setGeometry(self.width() - 26, 2, 24, self.height() - 4)

    def filter_choices(self, value):
        self.completer().setCompletionPrefix(value)
        self.completer().complete()

    def showPopup(self):
        self.lineEdit().setFocus()
        text = self.currentText()
        self.filter_choices("" if self.findText(text, Qt.MatchFlag.MatchExactly) >= 0 else text)

    def eventFilter(self, watched, event):
        if watched is self.lineEdit() and event.type() == QEvent.Type.KeyPress and event.key() == Qt.Key.Key_Tab:
            completer = self.completer()
            if completer.popup().isVisible() and completer.completionCount():
                index = completer.popup().currentIndex()
                text = index.data() if index.isValid() else completer.currentCompletion()
                match = self.findText(text, Qt.MatchFlag.MatchExactly)
                if match >= 0:
                    self.setCurrentIndex(match)
                completer.popup().hide()
        return super().eventFilter(watched, event)
