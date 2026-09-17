"""Fit-all preview and lossless PNG output of the same frozen season snapshot."""

from copy import deepcopy
from pathlib import Path
import re

from PySide6.QtCore import Signal, Qt, QUrl
from PySide6.QtGui import QDesktopServices, QPainter, QPixmap, QTransform
from PySide6.QtWidgets import QComboBox, QDialog, QFileDialog, QGraphicsScene, QGraphicsView, QHBoxLayout, QLabel, QMessageBox, QSpinBox, QVBoxLayout

from .export_png import render_sheet, save_png
from .storage import serialize_league
from .ui import button


class SheetView(QGraphicsView):
    zoom_changed = Signal(int)

    def __init__(self):
        super().__init__()
        self.setScene(QGraphicsScene(self))
        self.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setStyleSheet("background: #d7dfe7; border: 0;")
        self.zoom_percent = 100
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

    @property
    def fitted(self):
        return self.zoom_percent == 100

    def fit_all(self):
        self.set_zoom(100)

    def set_zoom(self, percent):
        self.zoom_percent = max(25, min(800, int(percent)))
        self.apply_zoom()
        self.zoom_changed.emit(self.zoom_percent)

    def apply_zoom(self):
        scene = self.sceneRect()
        if scene.isEmpty():
            return
        available = self.viewport().rect().adjusted(4, 4, -4, -4)
        base = min(available.width() / scene.width(), available.height() / scene.height())
        factor = max(0.0001, base * self.zoom_percent / 100)
        self.setTransform(QTransform.fromScale(factor, factor))
        if self.fitted:
            self.centerOn(scene.center())

    def wheelEvent(self, event):
        delta = event.angleDelta().y() or event.pixelDelta().y()
        if delta:
            cursor = event.position().toPoint()
            before = self.mapToScene(cursor)
            self.set_zoom(self.zoom_percent + (max(1, round(abs(delta) / 120 * 25)) * (1 if delta > 0 else -1)))
            if not self.fitted:
                after = self.mapToScene(cursor)
                self.centerOn(self.mapToScene(self.viewport().rect().center()) + before - after)
        event.accept()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.apply_zoom()


class ExportDialog(QDialog):
    saved = Signal(str, object, int)

    def __init__(self, league, parent=None, *, suggested_path=None):
        super().__init__(parent)
        self.league = deepcopy(league)
        self.suggested_path = suggested_path
        self.setWindowTitle("종합 리더보드 · PNG 내보내기")
        self.resize(1180, 860)
        self.setMinimumSize(800, 600)
        layout = QVBoxLayout(self)
        bar = QHBoxLayout()
        self.info = QLabel()
        bar.addWidget(self.info, 1)
        self.scale = QComboBox()
        self.scale.addItem("기본 해상도", 1)
        self.scale.addItem("고해상도 · 2배", 2)
        bar.addWidget(self.scale)
        self.view = SheetView()
        bar.addWidget(QLabel("전체 보기 기준"))
        self.zoom = QSpinBox()
        self.zoom.setRange(25, 800)
        self.zoom.setSingleStep(25)
        self.zoom.setSuffix("%")
        self.zoom.setValue(100)
        self.zoom.valueChanged.connect(self.view.set_zoom)
        self.view.zoom_changed.connect(self.sync_zoom)
        bar.addWidget(self.zoom)
        bar.addWidget(button("전체 보기 · 100%", self.view.fit_all))
        layout.addLayout(bar)
        layout.addWidget(self.view, 1)
        hint = QLabel("전체 보기 = 100% · 마우스 휠로 확대·축소, 드래그로 이동합니다. 미리보기 배율은 PNG 저장 해상도에 영향을 주지 않습니다.")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        bottom = QHBoxLayout()
        self.data_hint = QLabel("편집용 리그 데이터가 함께 저장됩니다. 앱의 ‘열기’에서 이 PNG로 편집을 이어갈 수 있습니다.")
        self.data_hint.setWordWrap(True)
        bottom.addWidget(self.data_hint, 1)
        self.saved_path = None
        self.open_saved = button('저장 폴더 열기', self.open_saved_folder)
        self.open_saved.setEnabled(False)
        bottom.addWidget(self.open_saved)
        bottom.addWidget(button("닫기", self.reject))
        bottom.addWidget(button("PNG 저장", self.save, True))
        layout.addLayout(bottom)
        self.regenerate()
        self.scale.currentIndexChanged.connect(self.change_scale)

    def open_saved_folder(self):
        if self.saved_path is not None:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.saved_path.resolve().parent)))

    def sync_zoom(self, percent):
        self.zoom.blockSignals(True)
        self.zoom.setValue(percent)
        self.zoom.blockSignals(False)

    def regenerate(self):
        document = serialize_league(self.league)
        image = render_sheet(self.league, self.scale.currentData())
        self.league_document = document
        self.image = image
        self.view.scene().clear()
        item = self.view.scene().addPixmap(QPixmap.fromImage(image))
        item.setTransformationMode(Qt.TransformationMode.SmoothTransformation)
        self.view.setSceneRect(0, 0, image.width(), image.height())
        self.view.fit_all()
        self.info.setText(f"{len(self.league.drivers)}명 · {len(self.league.rounds)}라운드  |  {image.width()} × {image.height()} px")

    def change_scale(self):
        try:
            self.regenerate()
        except (ValueError, MemoryError) as exc:
            self.scale.blockSignals(True)
            self.scale.setCurrentIndex(1 if self.scale.currentIndex() == 0 else 0)
            self.scale.blockSignals(False)
            QMessageBox.warning(self, "이미지 크기 확인", str(exc))

    def save(self):
        name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", self.league.name).strip(" .")[:100] or "리그"
        path, _ = QFileDialog.getSaveFileName(self, "종합 리더보드 PNG 저장", str(self.suggested_path or f"{name}_종합.png"), "PNG 이미지 (*.png)")
        if not path:
            return
        original = Path(path)
        target = original if original.suffix.lower() == ".png" else original.with_suffix(".png")
        if target != original and target.exists():
            answer = QMessageBox.question(self, "파일 덮어쓰기", f"이미 존재하는 파일입니다. 덮어쓸까요?\n{target}", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
            if answer != QMessageBox.StandardButton.Yes:
                return
        path = str(target)
        try:
            save_png(path, self.image, self.league_document)
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "저장 실패", str(exc))
            return
        self.saved.emit(path, self.league_document, self.scale.currentData())
        self.saved_path = target
        self.open_saved.setEnabled(True)
        QMessageBox.information(self, "PNG 저장 완료", f"편집용 리그 데이터가 포함된 종합표를 저장했습니다.\n{path}")
