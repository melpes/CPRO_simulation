# -*- coding: utf-8 -*-
# 잡 스토어 — 파일시스템이 SoT. done/failed 는 재시작 생존.
import hashlib
import json
import os
import shutil
import time
import uuid
from pathlib import Path

from . import config

QUEUED, RUNNING, DONE, FAILED = 'queued', 'running', 'done', 'failed'


def _atomic_json(path: Path, obj) -> None:
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.parent.mkdir(parents=True, exist_ok=True)
    with open(tmp, 'w', encoding='utf-8') as fp:
        json.dump(obj, fp, ensure_ascii=False)
    os.replace(tmp, path)


def _read_json(path: Path):
    with open(path, encoding='utf-8') as fp:
        return json.load(fp)


def input_hash(scenario_input: dict, seed: int) -> str:
    canonical = json.dumps({'input': scenario_input, 'seed': seed},
                           sort_keys=True, ensure_ascii=False, separators=(',', ':'))
    ckpt = Path(config.CKPT_PATH)
    ckpt_tag = f'{ckpt.name}:{ckpt.stat().st_size}' if ckpt.exists() else 'no-ckpt'
    return hashlib.sha256((canonical + '|' + ckpt_tag).encode('utf-8')).hexdigest()


class JobStore:
    def __init__(self, runs_dir: Path = None):
        self.root = Path(runs_dir or config.RUNS_DIR)
        self.root.mkdir(parents=True, exist_ok=True)

    def run_dir(self, run_id: str) -> Path:
        return self.root / run_id

    def create(self, scenario_input: dict, seed: int) -> dict:
        run_id = uuid.uuid4().hex
        run_dir = self.run_dir(run_id)
        run_dir.mkdir(parents=True, exist_ok=True)
        _atomic_json(run_dir / 'input.json', scenario_input)
        status = {
            'run_id'    : run_id,
            'scenario'  : scenario_input.get('scenario'),
            'seed'      : seed,
            'status'    : QUEUED,
            'input_hash': input_hash(scenario_input, seed),
            'created_at': time.time(),
            'started_at': None,
            'finished_at': None,
            'candidate_count': None,
            'summary_line'   : None,
            'error'     : None,
        }
        _atomic_json(run_dir / 'status.json', status)
        return status

    def get(self, run_id: str):
        path = self.run_dir(run_id) / 'status.json'
        return _read_json(path) if path.exists() else None

    def _patch(self, run_id: str, **fields) -> dict:
        status = self.get(run_id)
        if status is None:
            raise KeyError(run_id)
        status.update(fields)
        _atomic_json(self.run_dir(run_id) / 'status.json', status)
        return status

    def mark_running(self, run_id: str):
        return self._patch(run_id, status=RUNNING, started_at=time.time())

    def mark_done(self, run_id: str, summary_line: str, candidate_count: int):
        return self._patch(run_id, status=DONE, finished_at=time.time(),
                           summary_line=summary_line, candidate_count=candidate_count)

    def mark_failed(self, run_id: str, error_type: str, message: str):
        return self._patch(run_id, status=FAILED, finished_at=time.time(),
                           error={'type': error_type, 'message': message})

    def list(self, scenario: str = None, status: str = None):
        out = []
        for d in self.root.iterdir():
            if not d.is_dir():
                continue
            path = d / 'status.json'
            if not path.exists():
                continue
            rec = _read_json(path)
            if scenario and rec.get('scenario') != scenario:
                continue
            if status and rec.get('status') != status:
                continue
            out.append(rec)
        return sorted(out, key=lambda r: r.get('created_at') or 0, reverse=True)

    def find_done_by_hash(self, digest: str):
        for rec in self.list(status=DONE):
            if rec.get('input_hash') == digest:
                return rec
        return None

    def delete(self, run_id: str) -> bool:
        d = self.run_dir(run_id)
        if not d.exists():
            return False
        shutil.rmtree(d)
        return True

    # ---- 산출물 읽기 ----
    def input(self, run_id: str):
        path = self.run_dir(run_id) / 'input.json'
        return _read_json(path) if path.exists() else None

    def result(self, run_id: str):
        path = self.run_dir(run_id) / 'result.json'
        return _read_json(path) if path.exists() else None

    def candidates_index(self, run_id: str):
        path = self.run_dir(run_id) / 'candidates.json'
        return _read_json(path) if path.exists() else None

    def candidate(self, run_id: str, candidate_id: int):
        path = self.run_dir(run_id) / 'candidates' / f'{candidate_id}.json'
        return _read_json(path) if path.exists() else None

    def reap_orphans(self) -> int:
        """기동 시 남아있는 queued/running 잡은 프로세스가 죽은 것 → failed(interrupted)."""
        n = 0
        for rec in self.list():
            if rec.get('status') in (QUEUED, RUNNING):
                self.mark_failed(rec['run_id'], 'interrupted', '서버 재시작으로 중단됨')
                n += 1
        return n
