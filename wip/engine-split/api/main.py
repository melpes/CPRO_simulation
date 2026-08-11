# -*- coding: utf-8 -*-
# CPRO 시뮬레이션 실행 API — 시나리오를 돌리고, 산출물을 "데이터 의미별"로 노출한다.
import csv
import io
import json
import os
import sys
import threading
import time
from concurrent.futures import ProcessPoolExecutor
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, StreamingResponse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from . import config, jobs, runner, views
from .auth import require_api_key
from .schemas import RunRequest

STORE = jobs.JobStore()
POOL: ProcessPoolExecutor = None
INFLIGHT: dict = {}          # run_id -> (future, 시작시각)
_STOP = threading.Event()


def _watchdog():
    """잡이 CPRO_JOB_TIMEOUT_SEC 를 넘기면 failed(timeout) 로 표시하고 워커를 강제 종료한다.
    실행 중인 프로세스는 취소가 안 되므로, 풀을 통째로 재생성한다(드문 이벤트)."""
    global POOL
    while not _STOP.wait(10):
        now = time.time()
        expired = [rid for rid, (_, started) in list(INFLIGHT.items())
                   if now - started > config.JOB_TIMEOUT_SEC]
        if not expired:
            continue
        for run_id in expired:
            INFLIGHT.pop(run_id, None)
            try:
                STORE.mark_failed(run_id, 'timeout',
                                  f'실행이 제한시간({config.JOB_TIMEOUT_SEC}s)을 초과했습니다.')
            except KeyError:
                pass
        old, POOL = POOL, ProcessPoolExecutor(
            max_workers=config.WORKERS,
            initializer=runner.init_worker,
            initargs=(config.CKPT_PATH, config.AAS_DIR))
        for proc in list(getattr(old, '_processes', {}).values()):
            proc.terminate()
        old.shutdown(wait=False, cancel_futures=True)


def _load_scenarios() -> dict:
    from run_trained import SCENARIOS
    return SCENARIOS


@asynccontextmanager
async def lifespan(app: FastAPI):
    global POOL
    reaped = STORE.reap_orphans()
    POOL = ProcessPoolExecutor(
        max_workers=config.WORKERS,
        initializer=runner.init_worker,
        initargs=(config.CKPT_PATH, config.AAS_DIR),
    )
    app.state.scenarios = sorted(_load_scenarios())
    app.state.reaped = reaped
    app.state.model_info = POOL.submit(runner.model_info).result()   # 워커 워밍업 겸용
    watchdog = threading.Thread(target=_watchdog, daemon=True)
    watchdog.start()
    yield
    _STOP.set()
    POOL.shutdown(wait=False, cancel_futures=True)


app = FastAPI(
    title='CPRO 시뮬레이션 실행 API',
    version='1.0.0',
    description='4개 시나리오를 실행하고 산출물을 데이터 의미별(metrics·events·timeseries·aggregates)로 제공한다.',
    lifespan=lifespan,
    docs_url=None,        # 사람용 HTML 화면(Swagger UI) 비활성 — API 는 JSON 만 응답한다
    redoc_url=None,
    openapi_url='/openapi.json',   # 기계가 읽는 API 명세(JSON). UI 아님.
)


def _error(status: int, type_: str, message: str, **detail):
    raise HTTPException(status_code=status,
                        detail={'type': type_, 'message': message, **detail})


@app.exception_handler(HTTPException)
async def _http_error(request: Request, exc: HTTPException):
    detail = exc.detail if isinstance(exc.detail, dict) else {'type': 'error', 'message': str(exc.detail)}
    return JSONResponse(status_code=exc.status_code, content={'error': detail})


@app.exception_handler(RequestValidationError)
async def _validation_error(request: Request, exc: RequestValidationError):
    # 스키마 위반도 같은 {"error": {...}} 형식으로 통일한다.
    return JSONResponse(status_code=422, content={'error': {
        'type'   : 'validation_error',
        'message': '요청 스키마 위반',
        'detail' : jsonable_encoder(exc.errors()),
    }})


# ---------------------------------------------------------------- 메타
@app.get('/healthz', tags=['meta'])
def healthz():
    return {'ok': True, 'workers': config.WORKERS, 'inflight': len(INFLIGHT),
            'job_timeout_sec': config.JOB_TIMEOUT_SEC, 'queue_max': config.QUEUE_MAX}


def _example_input(name: str):
    # repo 에선 deploy/ 아래, 자족 패키지에선 루트에 놓인다 — 둘 다 찾는다.
    for base in (config.ROOT, config.ROOT / 'deploy'):
        path = base / f'scenario.{name}.json'
        if path.exists():
            return json.loads(path.read_text(encoding='utf-8'))
    return None


@app.get('/v1/scenarios', tags=['meta'], dependencies=[Depends(require_api_key)])
def list_scenarios():
    from run_trained import ALLOWED_OVERRIDES
    return {'scenarios': [{'name': name, 'example_input': _example_input(name)}
                          for name in app.state.scenarios],
            'allowed_overrides': sorted(ALLOWED_OVERRIDES)}


@app.get('/v1/models', tags=['meta'], dependencies=[Depends(require_api_key)])
def list_models():
    return app.state.model_info


# ---------------------------------------------------------------- 실행
def _finish(run_id: str, future):
    if INFLIGHT.pop(run_id, None) is None:
        return                                                 # 워치독이 이미 timeout 처리
    try:
        info = future.result()
        STORE.mark_done(run_id, info['summary_line'], info['candidate_count'])
    except Exception as exc:                                   # noqa: BLE001
        STORE.mark_failed(run_id, type(exc).__name__, str(exc)[:2000])


def _check_models(payload: dict) -> None:
    """모델명이 등장하는 곳: po(전 시나리오) + infinite 의 points(모델별 수량).
    aging 의 points 는 설비 구성이라 모델명이 아니다."""
    known = set(app.state.model_info['models'])
    used = set(payload.get('po') or {})
    if payload['scenario'] == 'infinite':
        for point in payload.get('points', []):
            used |= set(point)
    unknown = sorted(used - known)
    if unknown:
        _error(400, 'unknown_model',
               f'학습된 모델셋에 없는 모델: {unknown}. StateDim 고정 — 모델 추가/삭제는 재학습 필요.',
               known_models=sorted(known))


@app.post('/v1/runs', status_code=202, tags=['runs'], dependencies=[Depends(require_api_key)])
def create_run(request: RunRequest, response: Response,
               force: bool = Query(False, description='중복 캐시 무시하고 새로 실행')):
    body = request.model_dump(exclude_none=True)   # None 제거 — run_trained 는 키 존재로 분기
    scenario = body['scenario']
    _check_models(body)

    seed = int((body.get('overrides') or {}).get('seed', config.DEFAULT_SEED))

    if not force:
        cached = STORE.find_done_by_hash(jobs.input_hash(body, seed))
        if cached:
            response.status_code = 200
            response.headers['X-Cache'] = 'hit'
            return {'run_id': cached['run_id'], 'scenario': scenario,
                    'status': cached['status'], 'cached': True}

    if len(INFLIGHT) >= config.QUEUE_MAX:
        response.headers['Retry-After'] = '10'
        _error(429, 'queue_full', f'대기 잡이 상한({config.QUEUE_MAX})에 도달했습니다.')

    status = STORE.create(body, seed)
    run_id = status['run_id']
    STORE.mark_running(run_id)
    future = POOL.submit(runner.execute, body, seed, str(STORE.run_dir(run_id)))
    INFLIGHT[run_id] = (future, time.time())
    future.add_done_callback(lambda f, rid=run_id: _finish(rid, f))

    response.headers['Location'] = f'/v1/runs/{run_id}'
    response.headers['Retry-After'] = '5'
    return {'run_id': run_id, 'scenario': scenario, 'status': jobs.RUNNING}


@app.get('/v1/runs', tags=['runs'], dependencies=[Depends(require_api_key)])
def list_runs(scenario: str = None, status: str = None):
    return {'runs': STORE.list(scenario=scenario, status=status)}


@app.get('/v1/runs/{run_id}', tags=['runs'], dependencies=[Depends(require_api_key)])
def get_run(run_id: str):
    status = STORE.get(run_id)
    if status is None:
        _error(404, 'run_not_found', f'run_id 를 찾을 수 없습니다: {run_id}')
    return status


@app.delete('/v1/runs/{run_id}', tags=['runs'], dependencies=[Depends(require_api_key)])
def delete_run(run_id: str):
    if not STORE.delete(run_id):
        _error(404, 'run_not_found', f'run_id 를 찾을 수 없습니다: {run_id}')
    return {'deleted': run_id}


# ---------------------------------------------------------------- 산출물
def _require_done(run_id: str) -> dict:
    status = STORE.get(run_id)
    if status is None:
        _error(404, 'run_not_found', f'run_id 를 찾을 수 없습니다: {run_id}')
    if status['status'] != jobs.DONE:
        _error(409, 'not_ready', f"결과가 아직 없습니다 (status={status['status']}).",
               status=status['status'], error=status.get('error'))
    return status


def _require_candidate(run_id: str, candidate_id: int) -> dict:
    _require_done(run_id)
    candidate = STORE.candidate(run_id, candidate_id)
    if candidate is None:
        index = STORE.candidates_index(run_id) or []
        _error(404, 'candidate_not_found', f'candidate_id={candidate_id} 없음',
               available=[c['candidate_id'] for c in index])
    return candidate


@app.get('/v1/runs/{run_id}/config', tags=['results'], dependencies=[Depends(require_api_key)])
def run_config(run_id: str):
    if STORE.get(run_id) is None:
        _error(404, 'run_not_found', f'run_id 를 찾을 수 없습니다: {run_id}')
    return {'input': STORE.input(run_id)}


@app.get('/v1/runs/{run_id}/candidates', tags=['results'], dependencies=[Depends(require_api_key)])
def run_candidates(run_id: str,
                   flag: str = Query(None, description='optimum | pareto | target_met — 해당 플래그인 최적해 후보만')):
    """최적해 후보 인덱스(condition + flags + metric). 이력·시계열은 제외돼 가볍다.
    최적해는 flags.is_optimum / is_pareto 로 표시되므로 이 한 번의 호출로 찾을 수 있다."""
    _require_done(run_id)
    candidates = STORE.candidates_index(run_id) or []
    if flag:
        key = {'optimum': 'is_optimum', 'pareto': 'is_pareto', 'target_met': 'target_met'}.get(flag)
        if key is None:
            _error(422, 'unknown_flag', f'flag 는 optimum|pareto|target_met 중 하나: {flag}')
        candidates = [c for c in candidates if c['flags'].get(key)]
    result = STORE.result(run_id) or {}
    return {'objective': result.get('objective'),
            'scenario': result.get('scenario'),
            'candidates': candidates}


@app.get('/v1/runs/{run_id}/candidates/{candidate_id}/metric', tags=['results'], dependencies=[Depends(require_api_key)])
def candidate_metric(run_id: str, candidate_id: int):
    """생산성·전력 지표 (스칼라 집계)."""
    return views.metric(_require_candidate(run_id, candidate_id))


@app.get('/v1/runs/{run_id}/candidates/{candidate_id}/history', tags=['results'], dependencies=[Depends(require_api_key)])
def candidate_history(run_id: str, candidate_id: int,
                      type: str = Query(..., description='process | equipment | warehouse | realloc'),
                      workstation: str = None, process_code: str = None,
                      from_sec: float = None, to_sec: float = None,
                      limit: int = Query(1000, ge=1, le=100000), offset: int = 0,
                      format: str = Query('json', pattern='^(json|csv)$')):
    """공정·설비 수행 이력 (이산 이벤트)."""
    candidate = _require_candidate(run_id, candidate_id)
    try:
        if format == 'csv':
            columns, rows = views.history_csv_rows(
                candidate, type, workstation=workstation, process_code=process_code,
                from_sec=from_sec, to_sec=to_sec)
            buf = io.StringIO()
            writer = csv.writer(buf)
            writer.writerow(columns)
            writer.writerows(rows)
            buf.seek(0)
            return StreamingResponse(buf, media_type='text/csv', headers={
                'Content-Disposition': f'attachment; filename="{run_id}_{candidate_id}_{type}.csv"'})
        return views.history(candidate, type, workstation=workstation, process_code=process_code,
                             from_sec=from_sec, to_sec=to_sec, limit=limit, offset=offset)
    except KeyError:
        _error(404, 'history_type_not_found', f'이 최적해 후보에 없는 이력 종류: {type}',
               available=views.history_types(candidate))


@app.get('/v1/runs/{run_id}/candidates/{candidate_id}/timeseries', tags=['results'], dependencies=[Depends(require_api_key)])
def candidate_timeseries(run_id: str, candidate_id: int,
                         features: str = Query(None, description='쉼표구분. 생략 시 전체')):
    """시간별 추이 (일정 간격 시계열)."""
    candidate = _require_candidate(run_id, candidate_id)
    wanted = [f.strip() for f in features.split(',')] if features else None
    try:
        return views.timeseries(candidate, wanted)
    except KeyError as exc:
        _error(404, 'feature_not_found', f'없는 feature: {exc}',
               available=list(candidate['timeseries']['features']))


@app.get('/v1/runs/{run_id}/candidates/{candidate_id}/summary', tags=['results'], dependencies=[Depends(require_api_key)])
def candidate_summary(run_id: str, candidate_id: int,
                      by: str = Query(..., description='process | process_slot | line | equipment | worker | item')):
    """항목별 집계."""
    candidate = _require_candidate(run_id, candidate_id)
    try:
        return views.summary(candidate, by)
    except KeyError:
        _error(404, 'summary_not_found', f'없는 집계 단위: {by}',
               available=views.summary_kinds(candidate))


@app.get('/v1/runs/{run_id}/result', tags=['results'], dependencies=[Depends(require_api_key)])
def run_result(run_id: str):
    """원본 통짜(탈출구). case 본문은 /cases/{id}/... 로 받는 편이 가볍다."""
    _require_done(run_id)
    return STORE.result(run_id)
