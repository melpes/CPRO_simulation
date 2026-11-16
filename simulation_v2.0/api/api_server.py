from concurrent.futures import ProcessPoolExecutor
from contextlib import asynccontextmanager
from functools import partial
from typing import Dict, Literal, Optional

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import AliasChoices, BaseModel, ConfigDict, Field

from api import api_data_items, api_jobs, api_settings, mqtt_publisher
from api import real_time_simulation_run, simulation_engine
from api.api_authentication import require_api_key


# ================================================ API 정보: 명세(openapi)에 적히는 제목, 버전, 설명 ================================================
API_INFORMATION = {
    'title': 'CPRO 시뮬레이션 실행 API',
    'version': '1.1.0',
    'description': '모델별 PO 수량·납기일을 넣고 실행하면 실시간 데이터(HTTP)와 이벤트 데이터(MQTT)를 제공한다.',
}


# ================================================ REST 경로: 경로, 묶음 이름, 요약, 설명. operation_id는 지금 API(1.1.0)의 명세에 적힌 값 그대로 ================================================
REST_ROUTES = {
    'current_registration': {
        'path': '/api/v1/PO-납기일-현재-등록값',
        'tags': ['PO-납기일'],
        'summary': '현재 등록된 PO 수량·납기일 확인',
        'description': (
            '현재 대시보드 GET 이 출력하는 PO 수량·납기일과 실행 상태. '
            '실시간 실행이면 진행 중인 시뮬레이션 시각도.'),
        'operation_id': 'get_current_po_due_date_api_v1_PO_납기일_현재_등록값_get',
    },
    'start_run': {
        'path': '/api/v1/PO-납기일',
        'status_code': 202,
        'tags': ['PO-납기일'],
        'summary': 'PO 수량·납기일 등록 후 시뮬레이션 실행',
        'description': (
            '모델별 PO 수량·납기일을 등록하고 시뮬레이션을 실행한다(생략한 모델은 현재 등록값 유지).\n'
            '무한가동이면 PO 없이 생산 가능한 수량을 계속 만든다 — 모델별 PO 수량·납기일을 받지 않는다.\n'
            '1회 발행은 완료 후 GET 200 (그전 202).'),
        'operation_id': 'post_po_due_date_api_v1_PO_납기일_post',
    },
    'stop_run': {
        'path': '/api/v1/PO-납기일-중지',
        'tags': ['PO-납기일'],
        'summary': '실행 중지',
        'description': (
            '현재 실행에 중지 신호를 보낸다. 워커는 다음 발행 때 마지막 산출물을 쓰고 끝난다(상태 done).\n'
            '이미 끝났거나 1회 발행 실행이면 그대로 둔다.'),
        'operation_id': 'post_stop_api_v1_PO_납기일_중지_post',
    },
    'production_quantity': {
        'path': '/api/v1/실시간-데이터/모델별-누적-생산량',
        'tags': ['실시간 데이터'],
        'summary': '모델별 누적 생산량',
        'operation_id': 'get_series_production_api_v1_실시간_데이터_모델별_누적_생산량_get',
    },
    'in_progress_quantity': {
        'path': '/api/v1/실시간-데이터/생산진행수량-모델별',
        'tags': ['실시간 데이터'],
        'summary': '모델별 생산 진행 수량 (착수했으나 최종 공정 전)',
        'operation_id': 'get_series_wip_api_v1_실시간_데이터_생산진행수량_모델별_get',
    },
    'worker_count': {
        'path': '/api/v1/실시간-데이터/라인별-작업인원',
        'tags': ['실시간 데이터'],
        'summary': '라인별 작업 인원과 배정 인원',
        'operation_id': 'get_series_staffing_api_v1_실시간_데이터_라인별_작업인원_get',
    },
    'power': {
        'path': '/api/v1/실시간-데이터/전력',
        'tags': ['실시간 데이터'],
        'summary': '설비별·라인별·기저부하의 순간 전력과 누적 전력 사용량',
        'operation_id': 'get_series_power_api_v1_실시간_데이터_전력_get',
    },
    'carbon_emission': {
        'path': '/api/v1/실시간-데이터/탄소배출량',
        'tags': ['실시간 데이터'],
        'summary': '공정별·라인별·기저부하·공장 합의 탄소배출량(전력 사용량에 배출계수를 곱한 값)',
    },
    'smt_material_events': {
        'path': '/api/v1/실시간-데이터/SMT-필름교체-Chip보충-이벤트',
        'tags': ['실시간 데이터'],
        'summary': (
            'SMT 생산 대상 PCB가 바뀔 때 발생한 필름교체·Chip보충 이벤트의 '
            '구분, 라인, 설비, 시작 시각, 종료 시각(진행 중이면 null)'),
    },
    'reference_information': {
        'path': '/api/v1/기준-정보/모델별-완료-공정코드-박스당-제품-수량',
        'tags': ['기준 정보'],
        'summary': '모델별 완료 공정코드와 박스당 제품 수량',
    },
}


# ================================================ 실행 방식: 실행 요청에서 고르는 값. 생략하면 시나리오 1 ================================================
ExecutionMethod = Literal['As-is', '시나리오 1', '시나리오 2', '시나리오 3']
DEFAULT_EXECUTION_METHOD = '시나리오 1'


# ================================================ 실행 요청 항목의 이름: 약속한 이름(앞)과 지금 API가 함께 받는 영어 이름(뒤) ================================================
REQUEST_ITEM_NAMES = {
    'target_quantity_by_product': AliasChoices('모델별 PO 수량', 'order_quantity'),
    'due_day_by_product': AliasChoices('모델별 납기일(day)', 'due_day'),
    'execution_method': AliasChoices('실행 방식'),
    'infinite_operation': AliasChoices('무한가동', 'infinite'),
    'simulation_period_day': AliasChoices('시뮬레이션 기간(day)', 'horizon_day'),
    'simulation_speed': AliasChoices('시뮬레이션 배속', 'sim_speed'),
    'defect_rate_for_check': AliasChoices('불량률(확인용)', 'defect_rate'),
}


# ================================================ 실행 요청 항목의 설명: 명세(openapi)에 적힘 ================================================
REQUEST_ITEM_DESCRIPTIONS = {
    'execution_method': (
        'As-is(강화학습 적용 전, 선입선출), 시나리오 1(기본), 시나리오 2(작업자 재배치), '
        '시나리오 3(근무 연장) 가운데 하나. 한 번에 하나만 실행한다. 생략하면 시나리오 1.'),
    'infinite_operation': (
        '참이면 PO 없이 생산 가능한 수량을 계속 만드는 실시간 연속 운전. '
        '이때 모델별 PO 수량·납기일은 받지 않는다. '
        '거짓(기본)이면 등록한 수량만 한 번 만들고 끝난다.'),
    'simulation_period_day': (
        '시뮬레이션을 돌리는 상한(일). 생략하면 1회 발행은 PO 완료까지, 무한가동은 중지할 때까지.'),
    'simulation_speed': (
        '실시간 1초당 시뮬레이션 초. 생략 시 서버 기본(CPRO_LIVE_SPEED, 60). 0 = 최대 속도.'),
    'defect_rate_for_check': (
        'AAS 의 DefectRate 를 이 값으로 임시 덮어쓴다(원래 0 인 공정은 그대로). '
        '시뮬레이션 확인용이며 대외 API 명세가 아니다.'),
}


# ================================================ 실행 요청 값의 범위: PO 수량, 납기일(일), 시뮬레이션 기간(일), 시뮬레이션 배속, 불량률 ================================================
REQUEST_VALUE_LIMITS = {
    'minimum_target_quantity': 0,
    'minimum_due_day': 1,
    'minimum_simulation_period_day': 1,
    'minimum_simulation_speed': 0,
    'minimum_defect_rate': 0,
    'maximum_defect_rate': 1,
}


# ================================================ 실행 요청의 설명과 예시: 명세(openapi)에 적힘 ================================================
REQUEST_DESCRIPTION = (
    '모델별 PO 수량 + 모델별 납기일(day). '
    '무한가동이면 PO 없이 생산 가능한 수량을 계속 만들고(PO 수량·납기일을 받지 않는다),\n'
    '아니면 등록한 수량만 한 번 만들고 끝난다. 어느 쪽이든 실행 중에 실시간 GET·MQTT 이벤트가 나온다.')
REQUEST_EXAMPLE = {
    '모델별 PO 수량': {'MODEL_A': 180, 'MODEL_B': 180, 'MODEL_C': 180},
    '모델별 납기일(day)': {'MODEL_A': 3, 'MODEL_B': 3, 'MODEL_C': 3},
    '실행 방식': '시나리오 1',
    '무한가동': False,
    '시뮬레이션 기간(day)': 30,
    '시뮬레이션 배속': 60,
}


# ================================================ 오류 응답의 상태 코드: 오류 type마다 하나 ================================================
ERROR_STATUS_CODES = {
    'not_ready': 202,
    'invalid_purchase_order': 400,
    'no_run': 404,
    'not_live': 409,
    'validation_error': 422,
    'queue_full': 429,
    'run_failed': 500,
}


# ================================================ 응답에 쓰는 값: 실행 시작 응답의 다시 물어볼 간격(초), 중지 요청을 받았을 때의 상태, 실패 기록에 남기는 오류 글의 최대 길이 ================================================
RETRY_AFTER_SEC_OF_STARTED_RUN = '5'
STOP_REQUESTED_STATUS = 'stopping'
MAXIMUM_ERROR_MESSAGE_LENGTH = 2000


# ================================================ 서버가 갖는 것: 인증 확인, 실행 작업 기록 ================================================
API_KEY_CHECK = [Depends(require_api_key)]
JOB_STORE = api_jobs.JobStore(api_settings.JOBS_DIRECTORY)


# ================================================ 실행 요청 본문: PO 수량·납기일, 실행 방식, 무한가동, 기간, 배속 ================================================
class PoDueDateRequest(BaseModel):
    model_config = ConfigDict(extra='forbid', json_schema_extra={
        'description': REQUEST_DESCRIPTION,
        'example': REQUEST_EXAMPLE,
    })
    target_quantity_by_product: Optional[Dict[str, int]] = Field(
        None, validation_alias=REQUEST_ITEM_NAMES['target_quantity_by_product'])
    due_day_by_product: Optional[Dict[str, int]] = Field(
        None, validation_alias=REQUEST_ITEM_NAMES['due_day_by_product'])
    execution_method: Optional[ExecutionMethod] = Field(
        DEFAULT_EXECUTION_METHOD, validation_alias=REQUEST_ITEM_NAMES['execution_method'],
        description=REQUEST_ITEM_DESCRIPTIONS['execution_method'])
    infinite_operation: Optional[bool] = Field(
        False, validation_alias=REQUEST_ITEM_NAMES['infinite_operation'],
        description=REQUEST_ITEM_DESCRIPTIONS['infinite_operation'])
    simulation_period_day: Optional[float] = Field(
        None, validation_alias=REQUEST_ITEM_NAMES['simulation_period_day'],
        ge=REQUEST_VALUE_LIMITS['minimum_simulation_period_day'],
        description=REQUEST_ITEM_DESCRIPTIONS['simulation_period_day'])
    simulation_speed: Optional[float] = Field(
        None, validation_alias=REQUEST_ITEM_NAMES['simulation_speed'],
        ge=REQUEST_VALUE_LIMITS['minimum_simulation_speed'],
        description=REQUEST_ITEM_DESCRIPTIONS['simulation_speed'])
    defect_rate_for_check: Optional[float] = Field(
        None, validation_alias=REQUEST_ITEM_NAMES['defect_rate_for_check'],
        ge=REQUEST_VALUE_LIMITS['minimum_defect_rate'],
        le=REQUEST_VALUE_LIMITS['maximum_defect_rate'],
        description=REQUEST_ITEM_DESCRIPTIONS['defect_rate_for_check'])


# ================================================ 서버 시작과 종료: 시뮬레이션 실행기 준비, 기준 정보 읽기, 최근 완료 실행 복원, 내장 MQTT 브로커 시작 ================================================
@asynccontextmanager
async def lifespan(application):
    JOB_STORE.fail_unfinished_jobs()
    simulation_runner_pool = ProcessPoolExecutor(
        max_workers=api_settings.SIMULATION_RUNNER_COUNT,
        initializer=simulation_engine.prepare_simulation_runner,
        initargs=[api_settings.MODEL_FILE_PATH, api_settings.AAS_DATA_DIRECTORY])
    reference_information_future = simulation_runner_pool.submit(
        simulation_engine.read_reference_information)
    application.state.simulation_runner_pool = simulation_runner_pool
    application.state.reference_information = reference_information_future.result()
    application.state.running_job_futures = {}
    application.state.current_job_id = None
    done_statuses = JOB_STORE.list_done_statuses_newest_first()
    if done_statuses:
        application.state.current_job_id = done_statuses[0]['job_id']
    mqtt_publisher.start_embedded_broker()
    yield
    for job_id in list(application.state.running_job_futures):
        api_jobs.request_stop(JOB_STORE.job_directory(job_id))
    simulation_runner_pool.shutdown(wait=False, cancel_futures=True)


app = FastAPI(
    title=API_INFORMATION['title'],
    version=API_INFORMATION['version'],
    description=API_INFORMATION['description'],
    lifespan=lifespan,
    docs_url='/docs',
    redoc_url=None,
    openapi_url='/openapi.json',
)


# ================================================ 오류 응답: 모든 오류를 {"error": {"type", "message", ...}} 모양으로 ================================================
def api_error(error_type, message):
    return HTTPException(
        status_code=ERROR_STATUS_CODES[error_type],
        detail={'type': error_type, 'message': message})


@app.exception_handler(HTTPException)
async def respond_api_error(request: Request, error: HTTPException):
    if isinstance(error.detail, dict):
        detail = error.detail
    else:
        detail = {'type': 'error', 'message': str(error.detail)}
    return JSONResponse(status_code=error.status_code, content={'error': detail})


@app.exception_handler(RequestValidationError)
async def respond_request_validation_error(request: Request, error: RequestValidationError):
    return JSONResponse(status_code=ERROR_STATUS_CODES['validation_error'], content={'error': {
        'type': 'validation_error',
        'message': '요청 스키마 위반',
        'detail': jsonable_encoder(error.errors()),
    }})


# ================================================ 현재 등록값 조회: PO 수량·납기일, 실행 방식, 실행 상태, 진행 중인 시뮬레이션 시각 ================================================
@app.get(**REST_ROUTES['current_registration'], dependencies=API_KEY_CHECK)
def get_current_registration():
    job_id = app.state.current_job_id
    if job_id is None:
        raise api_error('no_run', '실행 이력이 없습니다. 먼저 POST /api/v1/PO-납기일 을 호출하세요.')
    status = JOB_STORE.read_status(job_id)
    if status is None:
        raise api_error('no_run', '실행 기록이 삭제되었습니다. 다시 POST 하세요.')
    run_input = JOB_STORE.read_run_input(job_id)
    current_registration = {
        '상태': status['status'],
        '모델별 PO 수량': run_input['target_quantity_by_product'],
        '모델별 납기일(day)': run_input['due_day_by_product'],
        '실행 방식': run_input['execution_method'],
        '무한가동': run_input['infinite_operation'],
        '시뮬레이션 기간(day)': run_input['simulation_period_day'],
        '시뮬레이션 배속': run_input['simulation_speed'],
    }
    real_time_data = api_jobs.read_real_time_data(JOB_STORE.job_directory(job_id))
    if real_time_data is not None:
        current_registration['시뮬레이션 시간(s)'] = real_time_data['시뮬레이션 시간(s)']
    return current_registration


# ================================================ 실행 요청: PO 수량·납기일 등록 → 돌던 실행 중지 → 새 실행 작업을 시뮬레이션 실행기에 맡김 ================================================
async def read_request_body(raw_request: Request):
    return await raw_request.json()


@app.post(**REST_ROUTES['start_run'], dependencies=API_KEY_CHECK)
def start_simulation_run(
        request: PoDueDateRequest, response: Response, request_body=Depends(read_request_body)):
    run_input = run_input_of_request(request, request_body)
    running_job_futures = app.state.running_job_futures
    if len(running_job_futures) >= api_settings.MAXIMUM_JOBS_IN_PROGRESS:
        raise api_error(
            'queue_full',
            f'대기 중인 실행이 상한({api_settings.MAXIMUM_JOBS_IN_PROGRESS})에 도달했습니다.')
    for running_job_id in list(running_job_futures):
        api_jobs.request_stop(JOB_STORE.job_directory(running_job_id))
    app.state.current_job_id = submit_job(run_input)
    response.headers['Retry-After'] = RETRY_AFTER_SEC_OF_STARTED_RUN
    return {'상태': api_jobs.JOB_STATUS['running']}


def run_input_of_request(request, request_body):
    infinite_operation = bool(request.infinite_operation)
    if infinite_operation:
        purchase_order = purchase_order_of_infinite_operation(
            request.target_quantity_by_product, request.due_day_by_product)
    else:
        missing_item_names = missing_purchase_order_item_names(
            request.target_quantity_by_product, request.due_day_by_product)
        if missing_item_names:
            raise missing_items_error(missing_item_names, request_body)
        purchase_order = purchase_order_updated_by_request(
            request.target_quantity_by_product, request.due_day_by_product)
    run_input = {
        'execution_method': request.execution_method,
        'infinite_operation': infinite_operation,
        'target_quantity_by_product': purchase_order['target_quantity_by_product'],
        'due_day_by_product': purchase_order['due_day_by_product'],
        'simulation_period_day': request.simulation_period_day,
        'simulation_speed': request.simulation_speed,
        'defect_rate_for_check': request.defect_rate_for_check,
        'publish_interval_sec': api_settings.PUBLISH_INTERVAL_SEC,
    }
    if run_input['execution_method'] is None:
        run_input['execution_method'] = DEFAULT_EXECUTION_METHOD
    if run_input['simulation_speed'] is None:
        run_input['simulation_speed'] = api_settings.DEFAULT_SIMULATION_SPEED
    return run_input


def submit_job(run_input):
    job_id = JOB_STORE.create_job(run_input, api_settings.RANDOM_SEED)['job_id']
    JOB_STORE.mark_running(job_id)
    simulation_runner_input = dict(run_input)
    if simulation_runner_input['simulation_period_day'] is None:
        simulation_runner_input['simulation_period_day'] = (
            api_settings.MAXIMUM_SIMULATION_PERIOD_DAY)
    job_future = app.state.simulation_runner_pool.submit(
        real_time_simulation_run.run_simulation_in_real_time,
        simulation_runner_input, api_settings.RANDOM_SEED, str(JOB_STORE.job_directory(job_id)))
    app.state.running_job_futures[job_id] = job_future
    job_future.add_done_callback(partial(record_job_result, job_id))
    return job_id


def record_job_result(job_id, job_future):
    app.state.running_job_futures.pop(job_id)
    try:
        JOB_STORE.mark_done(job_id, job_future.result())
    except Exception as error:
        error_message = str(error)[:MAXIMUM_ERROR_MESSAGE_LENGTH]
        JOB_STORE.mark_failed(job_id, type(error).__name__, error_message)


# ================================================ 실행 요청의 PO: 무한가동이면 PO 없음, 아니면 현재 등록값 위에 요청값을 덮어씀 ================================================
def purchase_order_of_infinite_operation(
        requested_target_quantity_by_product, requested_due_day_by_product):
    purchase_order_given = (
        requested_target_quantity_by_product is not None
        or requested_due_day_by_product is not None)
    if purchase_order_given:
        raise api_error(
            'invalid_purchase_order',
            '무한가동일 때는 모델별 PO 수량·납기일을 받지 않습니다 — PO 없이 계속 생산합니다.')
    return {'target_quantity_by_product': {}, 'due_day_by_product': {}}


def missing_purchase_order_item_names(
        requested_target_quantity_by_product, requested_due_day_by_product):
    missing_item_names = []
    if requested_target_quantity_by_product is None:
        missing_item_names.append(REQUEST_ITEM_NAMES['target_quantity_by_product'].choices[0])
    if requested_due_day_by_product is None:
        missing_item_names.append(REQUEST_ITEM_NAMES['due_day_by_product'].choices[0])
    return missing_item_names


def missing_items_error(missing_item_names, request_body):
    errors = []
    for item_name in missing_item_names:
        errors.append({
            'type': 'missing',
            'loc': ['body', item_name],
            'msg': 'Field required',
            'input': request_body,
        })
    return RequestValidationError(errors)


def current_purchase_order():
    run_input = None
    if app.state.current_job_id is not None:
        run_input = JOB_STORE.read_run_input(app.state.current_job_id)
    if run_input is not None and run_input['target_quantity_by_product']:
        return {
            'target_quantity_by_product': dict(run_input['target_quantity_by_product']),
            'due_day_by_product': dict(run_input['due_day_by_product']),
        }
    reference_information = app.state.reference_information
    default_target_quantity = reference_information['default_target_quantity_by_product']
    default_due_day = reference_information['default_due_day_by_product']
    target_quantity_by_product = {}
    due_day_by_product = {}
    for product_code in reference_information['product_codes']:
        target_quantity_by_product[product_code] = int(default_target_quantity[product_code])
        due_day_by_product[product_code] = int(default_due_day[product_code])
    return {
        'target_quantity_by_product': target_quantity_by_product,
        'due_day_by_product': due_day_by_product,
    }


def purchase_order_updated_by_request(
        requested_target_quantity_by_product, requested_due_day_by_product):
    purchase_order = current_purchase_order()
    target_quantity_by_product = purchase_order['target_quantity_by_product']
    due_day_by_product = purchase_order['due_day_by_product']
    requested_product_codes = (
        set(requested_target_quantity_by_product) | set(requested_due_day_by_product))
    unknown_product_codes = sorted(requested_product_codes - set(target_quantity_by_product))
    if unknown_product_codes:
        raise api_error(
            'invalid_purchase_order',
            f'등록할 수 없는 모델: {unknown_product_codes} — 모델 추가/삭제는 불가합니다. '
            f'등록 가능한 모델: {sorted(target_quantity_by_product)}')
    for product_code, target_quantity in requested_target_quantity_by_product.items():
        if target_quantity < REQUEST_VALUE_LIMITS['minimum_target_quantity']:
            raise api_error(
                'invalid_purchase_order',
                f'{product_code} 의 PO 수량은 0 이상이어야 합니다: {target_quantity}')
        target_quantity_by_product[product_code] = int(target_quantity)
    for product_code, due_day in requested_due_day_by_product.items():
        if due_day < REQUEST_VALUE_LIMITS['minimum_due_day']:
            raise api_error(
                'invalid_purchase_order',
                f'{product_code} 의 납기일은 1 이상이어야 합니다: {due_day}')
        due_day_by_product[product_code] = int(due_day)
    if sum(target_quantity_by_product.values()) == 0:
        raise api_error(
            'invalid_purchase_order',
            '전체 주문 수량이 0 입니다 — 최소 한 모델은 1 이상이어야 합니다.')
    return purchase_order


# ================================================ 실행 중지: 현재 실행에 중지 요청 ================================================
@app.post(**REST_ROUTES['stop_run'], dependencies=API_KEY_CHECK)
def stop_simulation_run():
    job_id = app.state.current_job_id
    if job_id is None or job_id not in app.state.running_job_futures:
        raise api_error('not_live', '중지할 실행이 없습니다.')
    api_jobs.request_stop(JOB_STORE.job_directory(job_id))
    return {'상태': STOP_REQUESTED_STATUS}


# ================================================ 실시간 데이터 조회: 현재 실행이 마지막으로 발행한 값 하나 ================================================
def current_real_time_data_item(item_name):
    job_id = app.state.current_job_id
    if job_id is None:
        raise api_error('no_run', '실행 이력이 없습니다. 먼저 POST /api/v1/PO-납기일 을 호출하세요.')
    status = JOB_STORE.read_status(job_id)
    if status is not None and status['status'] == api_jobs.JOB_STATUS['failed']:
        run_failed_error = api_error('run_failed', '시뮬레이션 실행이 실패했습니다.')
        run_failed_error.detail['error'] = status['error']
        raise run_failed_error
    real_time_data = api_jobs.read_real_time_data(JOB_STORE.job_directory(job_id))
    if real_time_data is None:
        raise api_error('not_ready', '아직 발행된 값이 없습니다. 잠시 후 다시 요청하세요.')
    return {
        '시뮬레이션 시간(s)': real_time_data['시뮬레이션 시간(s)'],
        item_name: real_time_data[item_name],
    }


@app.get(**REST_ROUTES['production_quantity'], dependencies=API_KEY_CHECK)
def get_real_time_production_quantity():
    return current_real_time_data_item('모델별 누적 생산량')


@app.get(**REST_ROUTES['in_progress_quantity'], dependencies=API_KEY_CHECK)
def get_real_time_in_progress_quantity():
    return current_real_time_data_item('모델별 생산 진행 수량')


@app.get(**REST_ROUTES['worker_count'], dependencies=API_KEY_CHECK)
def get_real_time_worker_count():
    return current_real_time_data_item('라인별 작업 인원')


@app.get(**REST_ROUTES['power'], dependencies=API_KEY_CHECK)
def get_real_time_power():
    return current_real_time_data_item('전력')


@app.get(**REST_ROUTES['carbon_emission'], dependencies=API_KEY_CHECK)
def get_real_time_carbon_emission():
    return current_real_time_data_item('탄소배출량')


@app.get(**REST_ROUTES['smt_material_events'], dependencies=API_KEY_CHECK)
def get_real_time_smt_material_events():
    return current_real_time_data_item('SMT 필름교체·Chip보충 이벤트')


# ================================================ 기준 정보 조회: 모델별 완료 공정코드와 박스당 제품 수량 ================================================
@app.get(**REST_ROUTES['reference_information'], dependencies=API_KEY_CHECK)
def get_reference_information():
    return api_data_items.reference_information_items(app.state.reference_information)
