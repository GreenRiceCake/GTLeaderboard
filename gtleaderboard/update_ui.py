"""Background release discovery and user-driven HTTPS or local ZIP updates."""
from urllib.error import HTTPError, URLError
from PySide6.QtCore import QProcess, QSettings, QThread, QTimer, Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QCheckBox, QDialog, QFileDialog, QHBoxLayout, QLabel, QMessageBox, QProgressBar, QTextEdit, QVBoxLayout

from . import __version__
from .catalog import model_directory
from .releases import inspect_package, prepare_update, version_tuple
from .online_updates import UpdateCancelled, default_manifest_url, download_and_prepare, fetch_manifest
from .ui import button


class PackageWorker(QThread):
    succeeded = Signal(object)
    failed = Signal(str)
    cancelled = Signal()
    progress = Signal(int, int)

    def __init__(self, operation, parent):
        super().__init__(parent)
        self.operation = operation

    def run(self):
        try:
            self.succeeded.emit(self.operation(self))
        except UpdateCancelled:
            self.cancelled.emit()
        except HTTPError as exc:
            self.failed.emit("업데이트 파일이 아직 게시되지 않았거나 주소가 올바르지 않습니다. (HTTP 404)" if exc.code == 404 else f"업데이트 서버에서 오류가 발생했습니다. (HTTP {exc.code})")
        except (URLError, TimeoutError):
            self.failed.emit("업데이트 서버에 연결할 수 없습니다. 인터넷 연결을 확인한 뒤 다시 시도하세요.")
        except Exception as exc:
            self.failed.emit(str(exc))


def update_settings():
    return QSettings('GTLeaderboard', 'GTLeaderboard')


class UpdateDialog(QDialog):
    def __init__(self, parent=None, *, release=None, settings=None):
        super().__init__(parent)
        self.setWindowTitle("버전 · 업데이트")
        self.resize(760, 620)
        self.settings = settings if settings is not None else update_settings()
        self.online_release = None
        self.worker = None
        self.package = None
        self.prepared = None
        self.closing = False
        layout = QVBoxLayout(self)
        title = QLabel(f"GTLeaderboard  {__version__}")
        title.setObjectName("brand")
        layout.addWidget(title)
        description = QLabel("GitHub의 최신 버전을 확인하고 업데이트를 내려받습니다.\n새 버전은 별도 폴더에 준비하며 기존 앱·리그 파일은 유지합니다.")
        description.setWordWrap(True)
        layout.addWidget(description)
        layout.addWidget(QLabel("업데이트 배포 주소 · 프로그램에 고정됨"))
        self.source_label = QLabel(default_manifest_url())
        self.source_label.setTextFormat(Qt.TextFormat.PlainText)
        self.source_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.source_label.setWordWrap(True)
        layout.addWidget(self.source_label)
        self.automatic = QCheckBox("프로그램 시작 시 새 버전 자동 확인")
        self.automatic.setChecked(self.settings.value('updates/automatic', True, type=bool))
        self.automatic.toggled.connect(lambda checked: self.settings.setValue('updates/automatic', checked))
        layout.addWidget(self.automatic)
        online = QHBoxLayout()
        self.check = button("지금 업데이트 확인", self.check_online)
        self.download = button("다운로드 · 업데이트 준비", self.download_online, True)
        self.cancel_button = button("작업 취소", self.cancel_operation)
        for widget in (self.check, self.download, self.cancel_button):
            online.addWidget(widget)
        layout.addLayout(online)
        self.changelog = QTextEdit()
        self.changelog.setReadOnly(True)
        self.changelog.setPlaceholderText("새 버전의 변경 사항이 여기에 표시됩니다.")
        layout.addWidget(self.changelog, 1)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        layout.addWidget(self.progress)
        self.status = QLabel("전체 패키지와 업데이트용 패키지를 모두 사용할 수 있습니다.")
        self.status.setWordWrap(True)
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.status)
        note = QLabel("파일 검사는 손상 여부를 확인합니다. 신뢰하는 배포자가 제공한 패키지를 사용하세요.\n업데이트 전에 리그를 저장하고, 새 버전에서 원본 리그 파일을 열면 됩니다.")
        note.setWordWrap(True)
        layout.addWidget(note)
        self.launch = button('현재 리그 저장 후 새 버전 실행', self.launch_prepared, True)
        layout.addWidget(self.launch)
        row = QHBoxLayout()
        self.choose = button("업데이트 ZIP 선택", self.choose_package)
        self.prepare = button("새 버전 폴더 준비", self.prepare_package, True)
        self.folder = button("준비된 폴더 열기", self.open_folder)
        self.close_button = button("닫기", self.reject)
        for widget in (self.choose, self.prepare, self.folder, self.close_button):
            row.addWidget(widget)
        layout.addLayout(row)
        self.refresh_buttons()
        if release is not None:
            self.online_checked(release)
            self.refresh_buttons()

    def refresh_buttons(self):
        busy = self.worker is not None
        self.choose.setEnabled(not busy)
        self.prepare.setEnabled(not busy and self.package is not None and self.prepared is None)
        self.folder.setEnabled(not busy and self.prepared is not None)
        self.launch.setEnabled(not busy and self.prepared is not None and hasattr(self.parent(), 'save'))
        self.check.setEnabled(not busy)
        self.download.setEnabled(not busy and self.online_release is not None and self.prepared is None)
        self.cancel_button.setEnabled(busy and not self.closing)

    def check_online(self):
        url = default_manifest_url()
        self.online_release = self.package = self.prepared = None
        self.changelog.clear()
        self.status.setText("최신 버전 정보를 확인하고 있습니다…")
        self.run_operation(lambda worker: fetch_manifest(url, worker.isInterruptionRequested), self.online_checked)

    def online_checked(self, release):
        self.online_release = None
        self.changelog.setPlainText(f"{release.title}\n\n{release.changelog}")
        if version_tuple(release.version) > version_tuple(__version__):
            self.online_release = release
            self.status.setText(f"새 버전이 있습니다: {__version__} → {release.version}\n다운로드 {release.size / 1024 / 1024:.1f} MB · 업데이트 준비를 눌러 저장 위치를 고르세요.")
        elif release.version == __version__:
            self.status.setText(f"최신 버전입니다. ({__version__})")
        else:
            self.status.setText(f"현재 버전 {__version__}이 게시된 버전 {release.version}보다 최신입니다.")

    def download_online(self):
        release = self.online_release
        if release is None:
            return
        parent = QFileDialog.getExistingDirectory(self, "새 버전 폴더를 만들 위치 선택", str(model_directory().parent.parent))
        if not parent:
            return
        self.status.setText("업데이트를 내려받고 크기·SHA-256·패키지 내용을 검사합니다…")
        self.run_operation(lambda worker: download_and_prepare(release, parent, model_directory(), __version__, worker.progress.emit, worker.isInterruptionRequested), self.prepared_package)

    def show_progress(self, received, total):
        self.progress.setRange(0, 100)
        self.progress.setValue(int(received * 100 / total))
        if received == total:
            self.status.setText("다운로드 완료. 파일 검증과 새 버전 폴더 준비 중입니다…")

    def cancel_operation(self):
        if self.worker is not None:
            self.worker.requestInterruption()
            self.status.setText("취소 요청 중… 파일 적용이 이미 시작되었다면 준비를 마친 뒤 종료합니다.")

    def cancelled_operation(self):
        self.status.setText("업데이트 작업을 취소했습니다. 기존 앱과 리그 파일은 유지됩니다.")

    def run_operation(self, operation, success):
        self.worker = PackageWorker(operation, self)
        self.worker.succeeded.connect(success)
        self.worker.failed.connect(self.failed)
        self.worker.cancelled.connect(self.cancelled_operation)
        self.worker.progress.connect(self.show_progress)
        self.worker.finished.connect(self.operation_finished)
        self.progress.setRange(0, 0)
        self.refresh_buttons()
        self.worker.start()

    def choose_package(self):
        path, _ = QFileDialog.getOpenFileName(self, "배포 ZIP 선택", "", "GTLeaderboard 배포 패키지 (*.zip)")
        if not path:
            return
        self.package = self.prepared = self.online_release = None
        self.status.setText("버전과 파일을 검사하고 있습니다…")
        self.run_operation(lambda worker: inspect_package(path), self.inspected)

    def inspected(self, package):
        if version_tuple(package.manifest["version"]) <= version_tuple(__version__):
            self.status.setText("현재 버전보다 새로운 패키지를 선택하세요.")
            return
        self.package = package
        kind = "OCR 모델 포함" if package.manifest["kind"] == "full" else "기존 OCR 모델 재사용"
        self.status.setText(f"{__version__} → {package.manifest['version']}\n파일 검사 완료 · {kind}\n‘새 버전 폴더 준비’를 눌러 저장 위치를 선택하세요.")

    def prepare_package(self):
        parent = QFileDialog.getExistingDirectory(self, "새 버전 폴더를 만들 위치 선택", str(model_directory().parent.parent))
        if not parent:
            return
        package = self.package
        self.status.setText("새 버전 파일과 OCR 모델을 준비하고 있습니다…")
        self.run_operation(lambda worker: prepare_update(package.path, parent, model_directory(), __version__), self.prepared_package)

    def prepared_package(self, target):
        self.prepared = target
        self.status.setText(f"준비 완료: {target}\n현재 앱을 닫은 뒤 새 폴더의 GTLeaderboard.exe를 실행하세요.\n문제가 있으면 기존 폴더의 실행 파일로 돌아갈 수 있습니다.")

    def open_folder(self):
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.prepared)))

    def launch_prepared(self):
        from pathlib import Path
        window = self.parent()
        if self.worker is not None or self.prepared is None or not hasattr(window, 'save'):
            return
        executable = Path(self.prepared) / 'GTLeaderboard.exe'
        if not executable.is_file():
            self.failed('준비된 실행 파일이 없습니다. 업데이트를 다시 준비하세요.')
            return
        has_content = bool(window.league.drivers or window.league.rounds)
        if window.dirty or window.editor_dirty or (has_content and window.path is None):
            if not window.save():
                self.status.setText('리그 저장이 완료되지 않아 현재 앱을 유지합니다.')
                return
        arguments = [str(window.path.resolve())] if window.path is not None else []
        started, _ = QProcess.startDetached(str(executable), arguments, str(executable.parent))
        if not started:
            self.failed('새 버전을 실행하지 못했습니다. 현재 앱은 유지됩니다. 준비된 폴더에서 다시 실행하세요.')
            return
        self.reject()
        window.close()

    def failed(self, message):
        self.status.setText(message)
        if not self.closing:
            QMessageBox.warning(self, "업데이트 준비 확인", message)

    def operation_finished(self):
        worker, self.worker = self.worker, None
        worker.deleteLater()
        self.progress.setRange(0, 100)
        self.progress.setValue(100 if self.prepared is not None else 0)
        self.refresh_buttons()
        if self.closing:
            super().reject()

    def reject(self):
        if self.worker is not None:
            self.closing = True
            self.worker.requestInterruption()
            self.close_button.setEnabled(False)
            self.status.setText("현재 파일 작업을 마친 뒤 닫습니다…")
            return
        super().reject()


class StartupUpdateCheck(PackageWorker):
    """One quiet background check per normal launch; no download without a click."""
    def __init__(self, window):
        self.window = window
        self.settings = update_settings()
        self.stopping = False
        url = default_manifest_url()
        super().__init__(lambda worker: fetch_manifest(url, worker.isInterruptionRequested), window)
        self.succeeded.connect(self.available)
        self.failed.connect(self.unavailable)

    def schedule(self):
        if self.settings.value('updates/automatic', True, type=bool):
            QTimer.singleShot(1000, self.begin)

    def begin(self):
        if not self.stopping:
            self.start()

    def stop(self):
        self.stopping = True
        self.requestInterruption()
        self.wait()

    def unavailable(self, message):
        if not self.stopping and self.window.isVisible():
            self.window.statusBar().showMessage("업데이트를 확인하지 못했습니다. 도움말 → 버전 · 업데이트에서 다시 확인할 수 있습니다.", 10000)

    def available(self, release):
        if self.stopping or not self.window.isVisible() or version_tuple(release.version) <= version_tuple(__version__):
            return
        notice = QMessageBox(QMessageBox.Icon.Information, "새 업데이트", f"GTLeaderboard {release.version} 버전이 있습니다.\n현재 버전: {__version__}\n\n변경 사항을 확인할까요?", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, self.window)
        notice.setTextFormat(Qt.TextFormat.PlainText)
        notice.button(QMessageBox.StandardButton.Yes).setText("업데이트 보기")
        notice.button(QMessageBox.StandardButton.No).setText("나중에")
        notice.finished.connect(lambda result: self.show_release(release) if result == QMessageBox.StandardButton.Yes else None)
        self.notice = notice
        notice.open()

    def show_release(self, release):
        if not self.stopping and self.window.isVisible():
            UpdateDialog(self.window, release=release).exec()
