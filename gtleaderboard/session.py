"""Bounded undo history and private crash-recovery snapshots."""
from datetime import datetime, timezone
import json
from pathlib import Path
from uuid import uuid4
import zlib

from PySide6.QtCore import QLockFile

from .domain import ValidationError
from .storage import atomic_write, deserialize_league, serialize_league


class UndoHistory:
    def __init__(self, league):
        self.current = self.pack(league)
        self.undo = []
        self.redo = []

    @staticmethod
    def pack(league):
        return zlib.compress(serialize_league(league))

    def record(self, league):
        document = self.pack(league)
        if document == self.current:
            return
        self.undo.append(self.current)
        self.current = document
        self.redo.clear()
        self.trim()

    def trim(self):
        while self.undo and (len(self.undo) > 30 or sum(map(len, self.undo + self.redo)) > 64 * 1024 * 1024):
            self.undo.pop(0)

    def move(self, backwards=True):
        source, destination = (self.undo, self.redo) if backwards else (self.redo, self.undo)
        if not source:
            return None
        destination.append(self.current)
        self.current = source.pop()
        return deserialize_league(zlib.decompress(self.current))


class RecoveryStore:
    """Each running window owns one locked snapshot; never touch another live one."""
    def __init__(self, directory):
        self.directory = Path(directory).resolve()
        self.directory.mkdir(parents=True, exist_ok=True)
        self.path = self.directory / f'{uuid4().hex}.recovery.json'
        self.lock = self.lock_for(self.path)
        if not self.lock.tryLock(0):
            raise OSError('작업 복구 파일을 잠글 수 없습니다.')

    @staticmethod
    def lock_for(path):
        lock = QLockFile(str(path) + '.lock')
        lock.setStaleLockTime(0)
        return lock

    def write(self, snapshot):
        content = json.dumps({'format': 'GTLeaderboardRecovery', 'version': 1,
                              'at': datetime.now(timezone.utc).isoformat(), **snapshot}, ensure_ascii=False).encode('utf-8')
        if len(content) > 40 * 1024 * 1024:
            raise ValidationError('자동 복구 데이터가 40 MB를 초과합니다. PNG로 저장해 주세요.')
        atomic_write(self.path, content)

    def clear(self):
        self.path.unlink(missing_ok=True)

    def close(self):
        self.clear()
        self.lock.unlock()

    def read(self, path):
        path = Path(path).resolve()
        if path.parent != self.directory or path.suffixes[-2:] != ['.recovery', '.json']:
            raise ValidationError('작업 복구 파일 경로가 올바르지 않습니다.')
        with path.open('rb') as stream:
            raw = stream.read(40 * 1024 * 1024 + 1)
        try:
            if len(raw) > 40 * 1024 * 1024:
                raise ValueError()
            data = json.loads(raw)
            if data['format'] != 'GTLeaderboardRecovery' or type(data['version']) is not int or data['version'] != 1:
                raise ValueError()
            league = deserialize_league(json.dumps(data['league'], ensure_ascii=False).encode('utf-8'))
            if data['round_id'] is not None and data['round_id'] not in {r.id for r in league.rounds}:
                raise ValueError()
            if type(data['draft']) is not dict or type(data['reason']) is not str or len(data['reason']) > 2000:
                raise ValueError()
            if type(data['source']) is not str or len(data['source']) > 4096:
                raise ValueError()
            if type(data['scale']) is not int or data['scale'] not in (1, 2):
                raise ValueError()
            rnd = next((r for r in league.rounds if r.id == data['round_id']), None)
            allowed = set(rnd.roster if rnd and rnd.confirmed else [d.id for d in league.drivers])
            if data['draft'] and not rnd:
                raise ValueError()
            for key, values in data['draft'].items():
                if key not in allowed or not isinstance(values, list) or len(values) != 6:
                    raise ValueError()
                status, position, pole, fastest, penalty, note = values
                if status not in ('', 'FINISHED', 'DNS', 'DNQ', 'DNF', 'DSQ', 'POINTS'):
                    raise ValueError()
                if status == 'POINTS' and (key not in rnd.results or rnd.results[key].status != 'POINTS'):
                    raise ValueError()
                if type(position) is not int or not 0 <= position <= 16 or type(penalty) is not int or not 0 <= penalty <= 10000:
                    raise ValueError()
                if type(pole) is not bool or type(fastest) is not bool or type(note) is not str or len(note) > 2000:
                    raise ValueError()
            return data, league
        except (ValueError, KeyError, TypeError, AttributeError, RecursionError) as exc:
            raise ValidationError('작업 복구 파일을 읽을 수 없습니다. 원본은 유지됩니다.') from exc

    def candidates(self):
        available = []
        now = datetime.now(timezone.utc).timestamp()
        for path in sorted(self.directory.glob('*.recovery.json'), key=lambda p: p.stat().st_mtime, reverse=True):
            if path == self.path:
                continue
            lock = self.lock_for(path)
            if not lock.tryLock(0):
                continue
            try:
                # Retain at most ten inactive snapshots for up to thirty days.
                if now - path.stat().st_mtime > 30 * 86400 or len(available) >= 10:
                    path.unlink()
                else:
                    available.append(path)
            finally:
                lock.unlock()
        return available
