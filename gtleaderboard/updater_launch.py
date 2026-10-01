"""Launch the separate updater from a private temporary workspace."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

from .domain import ValidationError
from .installer import check_directory, temporary_workspace, write_json

UPDATER_NAME = 'GTLeaderboardUpdater.exe'


def start_updater(current_install, target, mode, arguments=(), *, package=None):
    current_install, target = check_directory(current_install), check_directory(target)
    updater = current_install / UPDATER_NAME
    if not updater.is_file() or updater.is_symlink():
        raise ValidationError('GTLeaderboardUpdater.exe가 없습니다. 전체 ZIP을 다시 풀거나 전용 업데이터를 실행 파일 옆에 넣어 주세요.')
    workspace = temporary_workspace()
    executable = workspace / UPDATER_NAME
    shutil.copyfile(updater, executable)
    request = workspace / 'updater-request.json'
    write_json(request, {'format': 'GTLeaderboardUpdaterRequest', 'schema': 1, 'target': str(target),
                         'source': str(current_install), 'mode': mode, 'package': str(package) if package else None,
                         'arguments': list(arguments), 'pid': os.getpid()})
    subprocess.Popen([str(executable), '--request', str(request)], cwd=workspace, creationflags=subprocess.CREATE_NO_WINDOW)
    return request


def read_request(path):
    path = Path(path).resolve()
    workspace = check_directory(path.parent)
    if path.name != 'updater-request.json' or not workspace.name.startswith('.gtleaderboard-update-'):
        raise ValidationError('업데이터 요청 위치가 올바르지 않습니다.')
    data = json.loads(path.read_text(encoding='utf-8'))
    if data['format'] != 'GTLeaderboardUpdaterRequest' or data['schema'] != 1:
        raise ValidationError('업데이터 요청 정보가 올바르지 않습니다.')
    data['target'], data['source'] = check_directory(data['target']), check_directory(data['source'])
    if not (data['target'] / 'GTLeaderboard.exe').is_file():
        raise ValidationError('기존 실행 파일이 없는 설치 위치입니다.')
    if data['mode'] not in ('online', 'local', 'repair', 'prepared') or type(data['pid']) is not int or data['pid'] < 0:
        raise ValidationError('업데이트 요청 방식 또는 프로세스 정보가 올바르지 않습니다.')
    if not isinstance(data['arguments'], list) or not all(isinstance(arg, str) for arg in data['arguments']):
        raise ValidationError('리그 파일 정보가 올바르지 않습니다.')
    if data['mode'] in ('local', 'prepared') and not isinstance(data['package'], str):
        raise ValidationError('업데이트 패키지가 지정되지 않았습니다.')
    data['workspace'] = workspace
    return data


def updater_ready(request):
    path = Path(request).parent / 'updater-ready.json'
    if not path.exists():
        return False
    data = json.loads(path.read_text(encoding='utf-8'))
    return data.get('ready') is True and Path(data['executable']).resolve() == (path.parent / UPDATER_NAME).resolve()
