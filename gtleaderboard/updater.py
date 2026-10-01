"""Dedicated updater GUI: download ZIP, verify, replace, and restart the app."""
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys
from urllib.error import HTTPError, URLError

from PySide6.QtCore import QThread, QTimer, Qt, Signal
from PySide6.QtWidgets import QApplication, QFileDialog, QHBoxLayout, QLabel, QMessageBox, QProgressBar, QPushButton, QTextEdit, QVBoxLayout, QWidget

from . import __version__
from .application import configure_app
from .domain import ValidationError
from .installer import (apply_job, check_directory, create_job, helper_main,
                        launch_app, legacy_installation, prepare_repair,
                        temporary_workspace, write_json)
from .online_updates import UpdateCancelled, default_manifest_url, download_and_prepare, fetch_manifest
from .releases import MANIFEST, prepare_update, version_tuple
from .updater_launch import UPDATER_NAME, read_request


def installed_version(target):
    path = Path(target) / MANIFEST
    if path.is_file():
        version = json.loads(path.read_text(encoding='utf-8'))['version']
    else:
        version_file = Path(target) / 'VERSION.txt'
        version = version_file.read_text(encoding='ascii').strip() if version_file.is_file() else '0.0.0'
    version_tuple(version)
    return version


def update_request(request, worker):
    target, source, workspace = request['target'], request['source'], request['workspace']
    current = installed_version(target)
    mode = request['mode']
    if mode == 'online':
        worker.phase.emit('최신 버전 정보를 확인합니다…')
        release = fetch_manifest(default_manifest_url(), worker.isInterruptionRequested)
        worker.release.emit(release)
        if version_tuple(release.version) <= version_tuple(current):
            raise ValidationError(f'설치 위치의 버전 {current}은 이미 최신입니다.')
        worker.phase.emit('업데이트 ZIP을 내려받고 검사합니다…')
        stage = download_and_prepare(release, workspace, source / 'models', current, worker.progress.emit, worker.isInterruptionRequested)
    elif mode == 'local':
        worker.phase.emit('선택한 ZIP과 OCR 모델을 검사합니다…')
        stage = prepare_update(request['package'], workspace, source / 'models', current)
    else:
        worker.phase.emit('현재 버전 파일을 검사하고 복구를 준비합니다…')
        stage = prepare_repair(source if mode == 'repair' else request['package'], workspace)
    if worker.isInterruptionRequested():
        raise UpdateCancelled()
    job = create_job(stage, target, request['arguments'], parent_pid=request['pid'])
    worker.applying.emit()
    worker.phase.emit('기존 앱 종료를 기다린 뒤 프로그램 파일을 교체하고 다시 실행합니다…')
    return apply_job(job)


class UpdateWorker(QThread):
    succeeded = Signal(object)
    failed = Signal(str)
    cancelled = Signal()
    progress = Signal(int, int)
    phase = Signal(str)
    applying = Signal()
    release = Signal(object)

    def __init__(self, operation, parent):
        super().__init__(parent)
        self.operation = operation

    def run(self):
        try:
            self.succeeded.emit(self.operation(self))
        except UpdateCancelled:
            self.cancelled.emit()
        except HTTPError as exc:
            self.failed.emit(f'업데이트 서버에서 파일을 받지 못했습니다. (HTTP {exc.code})')
        except (URLError, TimeoutError):
            self.failed.emit('업데이트 서버에 연결할 수 없습니다. 인터넷 연결을 확인해 주세요.')
        except Exception as exc:
            self.failed.emit(str(exc))


class UpdaterWindow(QWidget):
    def __init__(self, target=None, *, request=None):
        super().__init__()
        self.setWindowTitle('GTLeaderboard 전용 업데이터')
        self.resize(760, 560)
        self.request = request
        self.target = check_directory(target) if target and Path(target).is_dir() else None
        self.worker = None
        self.release = None
        self.applying = self.closing = False
        layout = QVBoxLayout(self)
        title = QLabel(f'GTLeaderboard Updater  {__version__}')
        title.setStyleSheet('font-size: 23px; font-weight: bold; color: #14273f;')
        layout.addWidget(title)
        description = QLabel('업데이트 ZIP을 내려받고 검사하여 기존 설치 폴더에 덮어씁니다.\n리그 파일과 설정은 보존하고, 교체 실패 시 이전 프로그램 파일을 복원합니다.')
        description.setWordWrap(True)
        layout.addWidget(description)
        self.location = QLabel()
        self.location.setTextFormat(Qt.TextFormat.PlainText)
        self.location.setWordWrap(True)
        layout.addWidget(self.location)
        self.version = QLabel()
        layout.addWidget(self.version)
        row = QHBoxLayout()
        self.choose = QPushButton('기존 설치 폴더 선택')
        self.choose.clicked.connect(self.choose_target)
        self.check = QPushButton('업데이트 확인')
        self.check.clicked.connect(self.check_online)
        self.install = QPushButton('ZIP 다운로드 후 설치')
        self.install.clicked.connect(self.install_online)
        for widget in (self.choose, self.check, self.install):
            row.addWidget(widget)
        layout.addLayout(row)
        self.notes = QTextEdit()
        self.notes.setReadOnly(True)
        self.notes.setPlaceholderText('새 버전의 변경 사항이 여기에 표시됩니다.')
        layout.addWidget(self.notes, 1)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        layout.addWidget(self.progress)
        self.status = QLabel('기존 GTLeaderboard 창을 닫은 뒤 설치하세요.')
        self.status.setWordWrap(True)
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.status)
        row = QHBoxLayout()
        self.local = QPushButton('다운로드한 ZIP으로 설치')
        self.local.clicked.connect(self.install_local)
        self.cancel = QPushButton('다운로드 취소')
        self.cancel.clicked.connect(self.cancel_operation)
        self.restart = QPushButton('설치된 프로그램 실행')
        self.restart.clicked.connect(self.restart_app)
        self.close_button = QPushButton('닫기')
        self.close_button.clicked.connect(self.close)
        for widget in (self.local, self.cancel, self.restart, self.close_button):
            row.addWidget(widget)
        layout.addLayout(row)
        self.refresh()

    def refresh(self):
        busy = self.worker is not None
        valid = self.target is not None and (self.target / 'GTLeaderboard.exe').is_file()
        self.location.setText(f'덮어쓸 설치 위치: {self.target}' if valid else 'GTLeaderboard.exe가 있는 기존 폴더를 선택하세요.')
        self.version.setText(f'설치된 버전: {installed_version(self.target)}' if valid else '')
        self.choose.setEnabled(not busy and self.request is None)
        self.check.setEnabled(not busy and valid)
        self.local.setEnabled(not busy and valid)
        self.install.setEnabled(not busy and valid and self.release is not None)
        self.restart.setEnabled(not busy and valid)
        self.cancel.setEnabled(busy and not self.applying and not self.closing)

    def choose_target(self):
        path = QFileDialog.getExistingDirectory(self, 'GTLeaderboard.exe가 있는 기존 설치 폴더 선택', str(self.target or Path.home()))
        if not path:
            return
        if not (Path(path) / 'GTLeaderboard.exe').is_file():
            QMessageBox.warning(self, '설치 위치 확인', '이 폴더에 GTLeaderboard.exe가 없습니다.')
            return
        self.target = check_directory(path)
        self.release = None
        self.refresh()
        self.check_online()

    def run_operation(self, operation, callback):
        self.worker = UpdateWorker(operation, self)
        self.worker.succeeded.connect(callback)
        self.worker.failed.connect(self.failed)
        self.worker.cancelled.connect(lambda: self.status.setText('다운로드를 취소했습니다. 기존 설치 파일은 변경하지 않았습니다.'))
        self.worker.progress.connect(self.show_progress)
        self.worker.phase.connect(self.status.setText)
        self.worker.applying.connect(self.begin_apply)
        self.worker.release.connect(self.show_release)
        self.worker.finished.connect(self.finished)
        self.progress.setRange(0, 0)
        self.refresh()
        self.worker.start()

    def check_online(self):
        if self.target is None or self.worker is not None:
            return
        self.status.setText('최신 버전을 확인합니다…')
        self.run_operation(lambda worker: fetch_manifest(default_manifest_url(), worker.isInterruptionRequested), self.show_release)

    def show_release(self, release):
        self.release = release if version_tuple(release.version) > version_tuple(installed_version(self.target)) else None
        self.notes.setPlainText(f'{release.title}\n\n{release.changelog}')
        if self.release:
            self.status.setText(f'새 버전 {release.version} · 다운로드 {release.size / 1024 / 1024:.1f} MB')
        else:
            self.status.setText(f'설치 위치의 버전 {installed_version(self.target)}은 최신입니다.')

    def new_request(self, mode, package=None):
        return {'target': self.target, 'source': self.target, 'workspace': temporary_workspace(),
                'mode': mode, 'package': package, 'arguments': [], 'pid': 0}

    def install_online(self):
        if self.release is not None and self.worker is None:
            self.begin_request(self.new_request('online'))

    def install_local(self):
        path, _ = QFileDialog.getOpenFileName(self, '업데이트 ZIP 선택', '', 'GTLeaderboard 패키지 (*.zip)')
        if path:
            self.begin_request(self.new_request('local', path))

    def begin_request(self, request):
        self.run_operation(lambda worker: update_request(request, worker), self.updated)

    def begin_apply(self):
        self.applying = True
        self.refresh()

    def show_progress(self, received, total):
        self.progress.setRange(0, 100)
        self.progress.setValue(int(received * 100 / total))

    def updated(self, target):
        self.status.setText(f'업데이트 완료: {target}\n설치된 프로그램을 다시 실행했습니다.')
        self.progress.setRange(0, 100)
        self.progress.setValue(100)
        if self.request is not None:
            QTimer.singleShot(1500, self.close)

    def failed(self, message):
        self.status.setText(f'업데이트를 완료하지 못했습니다.\n{message}')
        self.progress.setRange(0, 100)
        self.progress.setValue(0)

    def finished(self):
        worker, self.worker = self.worker, None
        worker.deleteLater()
        self.applying = False
        self.progress.setRange(0, 100)
        self.refresh()
        if self.closing:
            self.close()

    def cancel_operation(self):
        if self.worker is not None and not self.applying:
            self.worker.requestInterruption()
            self.status.setText('다운로드 취소 요청 중…')

    def restart_app(self):
        try:
            launch_app(self.target, self.request['arguments'] if self.request else [])
            self.close()
        except Exception as exc:
            self.failed(str(exc))

    def closeEvent(self, event):
        if self.worker is not None:
            self.closing = True
            self.cancel_operation()
            self.close_button.setEnabled(False)
            self.status.setText('현재 작업을 안전하게 마친 뒤 닫습니다…')
            event.ignore()
        else:
            event.accept()


def main():
    parser = argparse.ArgumentParser(description='GTLeaderboard 전용 업데이터')
    parser.add_argument('--request', type=Path)
    parser.add_argument('--install-dir', type=Path)
    parser.add_argument('--apply-job', type=Path)
    parser.add_argument('--self-test', type=Path)
    args = parser.parse_args()
    if args.apply_job:
        return helper_main(args.apply_job)
    # A standalone double-click must also release the updater's own install file.
    if getattr(sys, 'frozen', False) and not args.request and not args.self_test:
        target = args.install_dir or Path(sys.executable).resolve().parent
        target = (legacy_installation(target) or target) if (target / 'GTLeaderboard.exe').is_file() else target
        workspace = temporary_workspace()
        executable = workspace / UPDATER_NAME
        shutil.copyfile(sys.executable, executable)
        request = workspace / 'manual-target.json'
        write_json(request, {'target': str(target)})
        subprocess.Popen([str(executable), '--install-dir', str(target), '--request', str(request)], cwd=workspace, creationflags=subprocess.CREATE_NO_WINDOW)
        return 0
    app = QApplication(sys.argv)
    configure_app(app)
    app.setApplicationName('GTLeaderboardUpdater')
    request = None
    try:
        if args.request and args.request.name == 'manual-target.json':
            target = Path(json.loads(args.request.read_text(encoding='utf-8'))['target'])
        elif args.request:
            request = read_request(args.request)
            target = request['target']
        else:
            target = args.install_dir
        window = UpdaterWindow(target, request=request)
    except Exception as exc:
        QMessageBox.critical(None, '업데이터 실행 확인', str(exc))
        return 1
    window.show()
    if args.self_test:
        app.processEvents()
        args.self_test.parent.mkdir(parents=True, exist_ok=True)
        window.grab().save(str(args.self_test.with_suffix('.png')))
        write_json(args.self_test, {'ok': True, 'version': __version__, 'frozen': bool(getattr(sys, 'frozen', False)), 'updater': True, 'manifest_url': default_manifest_url()})
        window.close()
        return 0
    if request:
        write_json(request['workspace'] / 'updater-ready.json', {'ready': True, 'executable': sys.executable})
        QTimer.singleShot(0, lambda: window.begin_request(request))
    elif window.target is not None and (window.target / 'GTLeaderboard.exe').is_file():
        QTimer.singleShot(0, window.check_online)
    return app.exec()
