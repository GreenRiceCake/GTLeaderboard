"""Verified file replacement after the running Windows app has exited."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
from uuid import uuid4

from .domain import ValidationError
from .releases import MANIFEST, digest_file, safe_payload_name, version_tuple


def installation_directory():
    return Path(sys.executable).resolve().parent if getattr(sys, 'frozen', False) else None


def check_directory(directory):
    directory = Path(directory).absolute()
    for part in (directory, *directory.parents):
        if part.is_symlink() or part.is_junction():
            raise ValidationError('업데이트 대상에 연결된 폴더가 있습니다. 일반 폴더를 사용하세요.')
    if not directory.is_dir():
        raise ValidationError('업데이트 대상 폴더가 없습니다.')
    return directory.resolve()


def payload_files(stage):
    stage = check_directory(stage)
    manifest = json.loads((stage / MANIFEST).read_text(encoding='utf-8'))
    if manifest['format'] != 'GTLeaderboardRelease' or manifest['schemaVersion'] != 1:
        raise ValidationError('준비된 배포 정보가 올바르지 않습니다.')
    version_tuple(manifest['version'])
    files = dict(manifest['files'])
    if 'GTLeaderboard.exe' not in files or len(files) > 1000:
        raise ValidationError('실행 파일 또는 배포 파일 목록이 올바르지 않습니다.')
    model = manifest['model']
    model_name = safe_payload_name(model['file'])
    if not model_name.startswith('models/') or not model_name.endswith('.onnx'):
        raise ValidationError('모델 경로가 올바르지 않습니다.')
    # Update ZIPs reuse a verified model that is not listed in their payload.
    if model_name not in files:
        files[model_name] = {'size': (stage / model_name).stat().st_size, 'sha256': model['sha256']}
    if len({name.casefold() for name in files}) != len(files):
        raise ValidationError('배포 파일 이름이 중복됩니다.')
    for name, expected in files.items():
        safe_payload_name(name)
        path = stage / name
        check_directory(path.parent)
        if path.is_symlink() or not path.is_file() or type(expected['size']) is not int or path.stat().st_size != expected['size'] or digest_file(path) != expected['sha256']:
            raise ValidationError(f'준비된 파일이 손상되었거나 변경되었습니다: {name}')
    if digest_file(stage / model_name) != model['sha256']:
        raise ValidationError('준비된 모델이 배포 정보와 다릅니다.')
    return [*files, MANIFEST]


def legacy_installation(current):
    """Recognize only version folders created below another GTLeaderboard app."""
    current = Path(current).resolve()
    candidate = current
    found = None
    while candidate.name.startswith('GTLeaderboard-'):
        try:
            version_tuple(candidate.name.removeprefix('GTLeaderboard-'))
        except ValidationError:
            break
        parent = candidate.parent
        if not (parent / 'GTLeaderboard.exe').is_file() or not (parent / MANIFEST).is_file():
            break
        try:
            info = json.loads((parent / MANIFEST).read_text(encoding='utf-8'))
            if info['format'] != 'GTLeaderboardRelease':
                break
            version_tuple(info['version'])
            check_directory(parent)
        except (OSError, ValueError, KeyError, ValidationError):
            break
        found = parent
        candidate = parent
    return found


def write_json(path, data):
    temporary = path.with_suffix('.tmp')
    with temporary.open('w', encoding='utf-8') as stream:
        json.dump(data, stream, ensure_ascii=False, indent=2)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def reject_downgrade(stage, target):
    if (target / MANIFEST).is_file():
        current = json.loads((target / MANIFEST).read_text(encoding='utf-8'))
        prepared = json.loads((stage / MANIFEST).read_text(encoding='utf-8'))
        if version_tuple(current['version']) > version_tuple(prepared['version']):
            raise ValidationError('기존 설치 위치에 더 새로운 버전이 있습니다. 해당 위치의 실행 파일을 사용하세요.')


def create_job(stage, target, arguments=(), *, parent_pid=None):
    stage, target = check_directory(stage), check_directory(target)
    names = payload_files(stage)
    if stage == target or stage.is_relative_to(target) or target.is_relative_to(stage):
        raise ValidationError('업데이트 준비 폴더와 설치 폴더가 겹칩니다.')
    if not (target / 'GTLeaderboard.exe').is_file():
        raise ValidationError('기존 GTLeaderboard 실행 파일이 없는 폴더입니다.')
    executable = target / 'GTLeaderboard.exe'
    if executable.is_symlink():
        raise ValidationError('기존 실행 파일이 연결된 파일입니다.')
    for name in names:
        destination = target / name
        for part in (destination, *destination.parents):
            if part == target:
                break
            if part.is_symlink() or part.is_junction():
                raise ValidationError('업데이트 대상 파일이 설치 폴더 밖으로 연결되어 있습니다.')
        if destination.exists() and not destination.is_file():
            raise ValidationError(f'배포 파일 위치에 폴더가 있습니다: {name}')
    reject_downgrade(stage, target)
    job = stage.parent / 'install-job.json'
    if job.exists():
        raise ValidationError('이미 준비된 업데이트 작업입니다.')
    write_json(job, {'format': 'GTLeaderboardInstall', 'schema': 1, 'stage': str(stage), 'target': str(target), 'files': names,
                     'pid': os.getpid() if parent_pid is None else parent_pid, 'arguments': list(arguments), 'phase': 'ready'})
    return job


def start_helper(job):
    if not getattr(sys, 'frozen', False):
        raise ValidationError('프로그램 파일 교체는 배포용 EXE에서 사용할 수 있습니다.')
    helper = Path(job).parent / 'GTLeaderboardUpdater.exe'
    updater = Path(sys.executable).parent / 'GTLeaderboardUpdater.exe'
    if not updater.is_file():
        raise ValidationError('전용 업데이터가 없습니다. 전체 ZIP을 다시 풀어 주세요.')
    shutil.copyfile(updater, helper)
    subprocess.Popen([str(helper), '--apply-job', str(job)], cwd=str(helper.parent), creationflags=subprocess.CREATE_NO_WINDOW)


def wait_for_exit(pid, timeout=120):
    if not pid:
        return
    if sys.platform != 'win32':
        raise ValidationError('Windows에서만 실행 파일을 교체할 수 있습니다.')
    import ctypes
    from ctypes import wintypes
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel.OpenProcess(0x00100000, False, pid)
    if not handle:
        if ctypes.get_last_error() == 87:  # process already exited
            return
        raise ValidationError('실행 중인 프로그램의 종료 여부를 확인하지 못했습니다.')
    try:
        if kernel.WaitForSingleObject(handle, int(timeout * 1000)) != 0:
            raise ValidationError('기존 프로그램이 종료되지 않아 업데이트를 적용하지 않았습니다.')
    finally:
        kernel.CloseHandle(handle)


def replace_file(source, destination, timeout=60):
    """Copy first, then atomically replace; allow the onefile launcher to exit."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name('.' + destination.name + '.gtleaderboard-update')
    if temporary.exists():
        raise ValidationError(f'이전 교체 임시 파일이 남아 있습니다: {temporary}')
    try:
        shutil.copyfile(source, temporary)
        deadline = time.monotonic() + timeout
        while True:
            try:
                os.replace(temporary, destination)
                return
            except PermissionError:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(.2)
    finally:
        if temporary.is_file() and not temporary.is_symlink():
            temporary.unlink()


def launch_app(target, arguments):
    return subprocess.Popen([str(target / 'GTLeaderboard.exe'), *arguments], cwd=str(target))


def launch_confirmed(target, arguments, acknowledgement, timeout=90):
    process = launch_app(target, ['--update-ready', str(acknowledgement), *arguments])
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if acknowledgement.is_file():
            try:
                result = json.loads(acknowledgement.read_text(encoding='utf-8'))
                if result.get('ready') is True and Path(result['executable']).resolve() == (target / 'GTLeaderboard.exe').resolve():
                    return
            except (ValueError, KeyError):
                pass
        if process.poll() is not None:
            raise ValidationError('새 버전이 시작을 완료하지 못하고 종료되었습니다.')
        time.sleep(.2)
    process.terminate()
    process.wait(timeout=10)
    raise ValidationError('새 버전의 시작 완료를 확인하지 못했습니다.')


def acknowledge_startup(path):
    if path:
        destination = Path(path).resolve()
        if destination.name != 'app-ready.json' or not destination.parent.name.startswith('.gtleaderboard-update-'):
            raise ValidationError('업데이트 시작 확인 경로가 올바르지 않습니다.')
        write_json(destination, {'ready': True, 'executable': sys.executable})


def apply_job(job_path, *, wait=wait_for_exit, replace=replace_file, launch=None):
    """Back up only declared app files. Keep the journal and backup for recovery."""
    job_path = Path(job_path).resolve()
    directory = check_directory(job_path.parent)
    if not directory.name.startswith('.gtleaderboard-update-') or job_path.name != 'install-job.json':
        raise ValidationError('업데이트 작업 경로가 올바르지 않습니다.')
    job = json.loads(job_path.read_text(encoding='utf-8'))
    if job['format'] != 'GTLeaderboardInstall' or job['schema'] != 1 or type(job['pid']) is not int or job['pid'] < 0:
        raise ValidationError('업데이트 작업 정보가 올바르지 않습니다.')
    target, stage = check_directory(job['target']), check_directory(job['stage'])
    if stage.parent != directory or target == directory or directory.is_relative_to(target) or target.is_relative_to(directory):
        raise ValidationError('설치 폴더와 업데이트 준비 경로가 올바르지 않습니다.')
    names = payload_files(stage)
    if names != job['files'] or not isinstance(job['arguments'], list) or not all(isinstance(arg, str) for arg in job['arguments']):
        raise ValidationError('업데이트 파일 목록 또는 실행 인수가 변경되었습니다.')
    for name in names:
        path = target / name
        for part in (path, *path.parents):
            if part == target:
                break
            if part.is_symlink() or part.is_junction():
                raise ValidationError('대상 파일에 연결 경로가 있습니다.')
        if path.exists() and not path.is_file():
            raise ValidationError('대상 파일 위치에 폴더가 있습니다.')
    backup = directory / 'backup'
    wait(job['pid'])
    reject_downgrade(stage, target)
    if job['phase'] == 'complete':
        return target
    if job['phase'] not in ('ready', 'applying'):
        raise ValidationError('종료된 업데이트 작업입니다. 새로 준비하세요.')
    changed = False
    try:
        if job['phase'] == 'applying':
            changed = True
            raise ValidationError('중단된 업데이트를 발견하여 이전 파일로 복구합니다.')
        backup.mkdir(exist_ok=False)
        job['originals'] = {}
        for name in names:
            source = target / name
            job['originals'][name] = source.is_file()
            if source.is_file():
                saved = backup / name
                saved.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, saved)
        job['phase'] = 'applying'
        write_json(job_path, job)
        changed = True
        for name in names:
            replace(stage / name, target / name)
        job['phase'] = 'complete'
        write_json(job_path, job)
        write_json(directory / 'result.json', {'ok': True, 'target': str(target)})
        if launch is None:
            launch_confirmed(target, job['arguments'], directory / 'app-ready.json')
        else:
            launch(target, job['arguments'])
        return target
    except Exception as exc:
        errors = []
        if changed:
            for name in reversed(names):
                try:
                    if job['originals'][name]:
                        saved, destination = backup / name, target / name
                        if not destination.is_file() or digest_file(destination) != digest_file(saved):
                            replace(saved, destination)
                    elif (target / name).exists():
                        (target / name).unlink()
                except Exception as rollback_error:
                    errors.append(f'{name}: {rollback_error}')
        job['phase'] = 'recovery-needed' if errors else 'rolled-back'
        write_json(job_path, job)
        write_json(directory / 'result.json', {'ok': False, 'error': str(exc), 'rollback_errors': errors, 'backup': str(backup)})
        if changed and not errors:
            try:
                (launch or launch_app)(target, job['arguments'])
            except Exception:
                pass
        detail = f'\n복구 파일: {backup}' if errors else '\n기존 프로그램 파일은 유지하거나 복원했습니다.'
        raise ValidationError(f'업데이트 적용 실패: {exc}{detail}\n기록: {directory / "result.json"}') from exc


def helper_main(job_path):
    try:
        apply_job(job_path)
        return 0
    except Exception as exc:
        if sys.platform == 'win32':
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, str(exc), 'GTLeaderboard 업데이트', 0x10)
        return 1


def temporary_workspace():
    path = Path(tempfile.gettempdir()) / f'.gtleaderboard-update-{uuid4().hex}'
    path.mkdir()
    return path


def prepare_repair(current, workspace):
    """Copy the installed, verified release; never copy leagues or extra files."""
    names = payload_files(current)
    stage = Path(workspace) / 'repair'
    stage.mkdir()
    for name in names:
        output = stage / name
        output.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(Path(current) / name, output)
    payload_files(stage)
    return stage
