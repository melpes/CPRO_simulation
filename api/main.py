# -*- coding: utf-8 -*-
# CPRO 시뮬레이션 실행 API — POST 1개 + 대시보드별 GET 6개.
#
#   POST /api/v1/PO-납기일                                모델별 PO 수량·납기일 등록 후 시뮬 실행
#   GET  /api/v1/PO-납기일-현재-등록값                      현재 등록값 + 실행 상태
#   GET  /api/v1/dashboard/실시간/모델별-누적-생산량          대시보드 1
#   GET  /api/v1/dashboard/실시간/작업자-라인별-점유비율       대시보드 2
#   GET  /api/v1/dashboard/실시간/생산진행수량               대시보드 3 (전체)
#   GET  /api/v1/dashboard/실시간/생산진행수량-모델별          대시보드 3b (모델별)
#   GET  /api/v1/dashboard/실시간/가동-전력                 대시보드 4
#   GET  /api/v1/dashboard/실시간/전력-사용-비율             대시보드 5 (전체/조립 라인별/SMT 설비별)
#
# GET 응답은 해당 대시보드를 가공 없이 그대로 그릴 수 있는 시계열이다.
# 실행 중이면 GET 은 202(not_ready) — 200 이 될 때까지 폴링한다.
import threading
import time
from concurrent.futures import ProcessPoolExecutor
from contextlib import asynccontextmanager
from typing import Dict, Optional

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from . import aas_po, config, jobs, runner, views
from .auth import require_api_key

STORE = jobs.JobStore()
POOL: ProcessPoolExecutor = None
INFLIGHT: dict = {}          # run_id -> (future, 시작시각)
_STOP = threading.Event()


class PoDueDateRequest(BaseModel):
    """모델별 PO 수량 + 모델별 납기일(day)."""
    model_config = ConfigDict(extra='forbid', populate_by_name=True, json_schema_extra={
        'example': {
            '모델별 PO 수량'    : {'MODEL_A': 180, 'MODEL_B': 180, 'MODEL_C': 180},
            '모델별 납기일(day)': {'MODEL_A': 3, 'MODEL_B': 3, 'MODEL_C': 3},
        }})
    order_quantity: Dict[str, int] = Field(..., alias='모델별 PO 수량')
    due_day: Dict[str, int] = Field(..., alias='모델별 납기일(day)')


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


@asynccontextmanager
async def lifespan(app: FastAPI):
    global POOL
    STORE.reap_orphans()
    POOL = ProcessPoolExecutor(
        max_workers=config.WORKERS,
        initializer=runner.init_worker,
        initargs=(config.CKPT_PATH, config.AAS_DIR),
    )
    app.state.model_info = POOL.submit(runner.model_info).result()   # 워커 워밍업 겸용
    done = STORE.list(status=jobs.DONE)
    app.state.current_run_id = done[0]['run_id'] if done else None   # 재시작 시 최근 완료 실행 복원
    watchdog = threading.Thread(target=_watchdog, daemon=True)
    watchdog.start()
    yield
    _STOP.set()
    POOL.shutdown(wait=False, cancel_futures=True)


app = FastAPI(
    title='CPRO 시뮬레이션 실행 API',
    version='1.0.0',
    description='모델별 PO 수량·납기일을 넣고 실행하면 대시보드별 데이터를 제공한다.',
    lifespan=lifespan,
    docs_url='/docs',     # Swagger UI — 브라우저에서 직접 호출·확인용
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


@app.get('/api/v1/PO-납기일-현재-등록값', tags=['PO-납기일'], summary='현재 등록된 PO 수량·납기일 확인',
         dependencies=[Depends(require_api_key)])
def get_current_po_due_date():
    """현재 대시보드 GET 이 출력하는 PO 수량·납기일과 실행 상태."""
    run_id = app.state.current_run_id
    if run_id is None:
        _error(404, 'no_run', '실행 이력이 없습니다. 먼저 POST /api/v1/PO-납기일 을 호출하세요.')
    status = STORE.get(run_id)
    if status is None:
        _error(404, 'no_run', '실행 기록이 삭제되었습니다. 다시 POST 하세요.')
    po = (STORE.input(run_id) or {}).get('po') or {}
    return {'상태': status['status'],
            '모델별 PO 수량'    : {m: spec['qty'] for m, spec in po.items()},
            '모델별 납기일(day)': {m: spec['due_day'] for m, spec in po.items()}}


# ---------------------------------------------------------------- PO-납기일 (입력·실행)
def _finish(run_id: str, future):
    if INFLIGHT.pop(run_id, None) is None:
        return                                                 # 워치독이 이미 timeout 처리
    try:
        info = future.result()
        STORE.mark_done(run_id, info['summary_line'])
    except Exception as exc:                                   # noqa: BLE001
        STORE.mark_failed(run_id, type(exc).__name__, str(exc)[:2000])


@app.post('/api/v1/PO-납기일', status_code=202, tags=['PO-납기일'],
          summary='PO 수량·납기일 등록 후 시뮬레이션 실행', dependencies=[Depends(require_api_key)])
def post_po_due_date(request: PoDueDateRequest, response: Response,
                     force: bool = Query(False, description='같은 입력의 기존 결과 무시하고 새로 실행')):
    """모델별 PO 수량·납기일을 AAS(PurchaseOrder)에 기록하고 시뮬레이션을 실행한다.
    완료 여부는 대시보드 GET 폴링으로 확인(202 not_ready → 200)."""
    updates = {m: {} for m in set(request.order_quantity) | set(request.due_day)}
    for m, qty in request.order_quantity.items():
        updates[m]['qty'] = qty
    for m, day in request.due_day.items():
        updates[m]['due_day'] = day
    merged = {m: {**spec, **updates.get(m, {})} for m, spec in aas_po.read_po(config.AAS_DIR).items()}
    if sum(spec['qty'] for spec in merged.values()) == 0:
        _error(400, 'invalid_purchase_order', '전체 주문 수량이 0 입니다 — 최소 한 모델은 1 이상이어야 합니다.')
    try:
        aas_po.write_po(config.AAS_DIR, updates)
    except ValueError as exc:
        _error(400, 'invalid_purchase_order', str(exc))

    run_input = {'po': aas_po.read_po(config.AAS_DIR)}
    seed = config.DEFAULT_SEED

    if not force:
        cached = STORE.find_done_by_hash(jobs.input_hash(run_input, seed))
        if cached:
            app.state.current_run_id = cached['run_id']
            response.status_code = 200
            response.headers['X-Cache'] = 'hit'
            return {'상태': 'done'}

    if len(INFLIGHT) >= config.QUEUE_MAX:
        response.headers['Retry-After'] = '10'
        _error(429, 'queue_full', f'대기 중인 실행이 상한({config.QUEUE_MAX})에 도달했습니다.')

    status = STORE.create(run_input, seed)
    run_id = status['run_id']
    STORE.mark_running(run_id)
    future = POOL.submit(runner.execute, run_input, seed, str(STORE.run_dir(run_id)))
    INFLIGHT[run_id] = (future, time.time())
    future.add_done_callback(lambda f, rid=run_id: _finish(rid, f))
    app.state.current_run_id = run_id

    response.headers['Retry-After'] = '5'
    return {'상태': jobs.RUNNING}


# ---------------------------------------------------------------- 대시보드 GET 6개
def _current_artifacts() -> dict:
    run_id = app.state.current_run_id
    if run_id is None:
        _error(404, 'no_run', '실행 이력이 없습니다. 먼저 POST /api/v1/PO-납기일 을 호출하세요.')
    status = STORE.get(run_id)
    if status is None:
        _error(404, 'no_run', '실행 기록이 삭제되었습니다. 다시 POST 하세요.')
    if status['status'] == jobs.FAILED:
        _error(500, 'run_failed', '시뮬레이션 실행이 실패했습니다.', error=status.get('error'))
    if status['status'] != jobs.DONE:
        _error(202, 'not_ready', '실행 중입니다. 잠시 후 다시 요청하세요.')
    return STORE.artifacts(run_id)


@app.get('/api/v1/dashboard/실시간/모델별-누적-생산량', tags=['대시보드'],
         summary='모델별 누적 생산량', dependencies=[Depends(require_api_key)])
def get_production_by_model():
    """대시보드 1 — 모델별 누적 생산량."""
    return views.production_by_model(_current_artifacts())


@app.get('/api/v1/dashboard/실시간/작업자-라인별-점유비율', tags=['대시보드'],
         summary='라인별 작업자 점유비율', dependencies=[Depends(require_api_key)])
def get_line_occupancy():
    """대시보드 2 — 라인별 작업자 점유비율 (0~1)."""
    return views.line_occupancy(_current_artifacts())


@app.get('/api/v1/dashboard/실시간/생산진행수량', tags=['대시보드'],
         summary='생산 진행 수량 (전체)', dependencies=[Depends(require_api_key)])
def get_wip_total():
    """대시보드 3 — 생산 진행 수량 (전체)."""
    return views.wip_total(_current_artifacts())


@app.get('/api/v1/dashboard/실시간/생산진행수량-모델별', tags=['대시보드'],
         summary='생산 진행 수량 (모델별)', dependencies=[Depends(require_api_key)])
def get_wip_by_model():
    """대시보드 3b — 생산 진행 수량 (모델별)."""
    return views.wip_by_model(_current_artifacts())


@app.get('/api/v1/dashboard/실시간/가동-전력', tags=['대시보드'],
         summary='공장 가동 전력', dependencies=[Depends(require_api_key)])
def get_instant_power():
    """대시보드 4 — 공장 실시간 가동 전력 (kW)."""
    return views.instant_power(_current_artifacts())


@app.get('/api/v1/dashboard/실시간/전력-사용-비율', tags=['대시보드'],
         summary='전력 사용 비율', dependencies=[Depends(require_api_key)])
def get_power_usage_ratio():
    """대시보드 5 — 전력 사용 비율 3종: 전체(조립 공정/SMT 공정/기저 부하) · 조립 라인별 · SMT 설비별."""
    return views.power_usage_ratio(_current_artifacts())
