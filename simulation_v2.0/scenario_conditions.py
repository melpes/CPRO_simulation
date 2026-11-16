from copy import deepcopy


# ================================================ 실험 공통 조건: 세 시나리오가 함께 쓰는 생산 목표·납기, 기저부하와 전력 시간대 가중, 재고, 무한가동 여부(False면 목표 수량을 채우면 끝나는 실행), SMT 착수 보류, 작업자 재배치, 학습 중 평가 시드 ================================================
COMMON_EXPERIMENT_CONDITIONS = {
    'production_quantity_per_product': 540,
    'due_day': 5,
    'base_load_kw': 148.221,
    'electricity_time_band_weights': [
        {'start_sec': 63000, 'end_sec': 81000, 'weight': 1.8537915984724496},
        {'start_sec': 0, 'end_sec': 21600, 'weight': 0.6492089470812875},
    ],
    'infinite_stock': True,
    'infinite_operation': False,
    'pcb_stock_limited': True,
    'pcb_initial_stock_ratio': 1.0,
    'start_delay_allowed_process_kg_node_paths': [
        'Process.ProcessCategories.Line_1_Loader',
        'Process.ProcessCategories.Line_2_Loader',
    ],
    'max_start_delay_sec': 21600.0,
    'worker_reallocation_conditions': {
        'source_worker_group': 'WWM_SemiAssemblyLine',
        'moved_worker_count_by_worker_group': {
            'WWM_FwInputLine': 4,
            'WWM_InspectionLine': 4,
            'WWM_AgingLine': 2,
        },
        'minimum_idle_worker_count': 10,
        'idle_duration_sec': 600,
        'check_interval_sec': 30,
        'require_source_completion': True,
    },
    'evaluation_seeds': [98102102, 98102103, 98102104],
}


# ================================================ 시나리오별 조건: AAS 폴더, 작업자 재배치 적용 여부, 전력 시간대 가중 적용 여부 ================================================
SCENARIO_CONDITIONS = {
    'S1': {
        'aas_directory': 'aas_data/S1',
        'worker_reallocation_enabled': False,
        'electricity_time_band_weights_applied': True,
    },
    'S1-1': {
        'aas_directory': 'aas_data/S1-1',
        'worker_reallocation_enabled': True,
        'electricity_time_band_weights_applied': True,
    },
    'S1-2': {
        'aas_directory': 'aas_data/S1-2',
        'worker_reallocation_enabled': False,
        'electricity_time_band_weights_applied': True,
    },
}
SCENARIO_NAMES = list(SCENARIO_CONDITIONS)


# ================================================ SMT 필름 교체·Chip 보충 이벤트 조건(임의값: 대기 시간 300초와 120초는 근거 자료가 없는 임의값. 발생 확률 0.25와 0.5도 임의값이며 Simulation AAS의 Events에 평균 발생 간격 4와 2로 있음): 적용 여부(기본은 꺼짐, API 실행에서만 켬), Simulation AAS의 EventCode별 대기 시간(초) ================================================
SMT_MATERIAL_EVENT_CONDITIONS = {
    'smt_material_events_applied': False,
    'smt_material_event_wait_sec_by_EventCode': {
        'EV_FILM_CHANGE_Mounter_U1': 300.0,
        'EV_CHIP_REFILL_Mounter_U1': 120.0,
        'EV_FILM_CHANGE_Mounter_U2': 300.0,
        'EV_CHIP_REFILL_Mounter_U2': 120.0,
    },
}


# ================================================ 무한가동 조건(PO 없이 생산 가능한 수량을 실행 길이까지 계속 생산. 실험 공통 조건의 infinite_operation이 True일 때만 쓰임): 제품별 비율, 비율 1당 유지 수량. 목표 구간 하나는 목표 수량 실행 한 번과 같은 조건이고 그 값은 실험 공통 조건에서 옴: 제품별 목표 구간 목표 수량은 제품별 비율 × production_quantity_per_product, 목표 구간 납기는 목표 구간 시작 + due_day, 목표 구간은 모든 제품이 목표 수량을 채우거나 납기가 지나면 끝남. 제품별 비율 × 비율 1당 유지 수량이 제품별로 유지하는 끝나지 않은 대수(중간재가 쌓일 수 있는 상한) ================================================
INFINITE_OPERATION_CONDITIONS = {
    'product_ratio': {
        'MODEL_A': 1,
        'MODEL_B': 1,
        'MODEL_C': 1,
    },
    'maintained_unfinished_quantity_per_ratio_unit': 540,
}


# ================================================ 시나리오 조건 조회: 실험 공통 조건에 시나리오별 조건, SMT 필름 교체·Chip 보충 이벤트 조건, 무한가동 조건을 합친 사본(부르는 쪽이 값을 바꿔 써도 위 dictionary는 그대로) ================================================
def conditions_of_scenario(scenario):
    conditions = deepcopy(COMMON_EXPERIMENT_CONDITIONS)
    conditions.update(deepcopy(SCENARIO_CONDITIONS[scenario]))
    conditions.update(deepcopy(SMT_MATERIAL_EVENT_CONDITIONS))
    conditions['infinite_operation_conditions'] = deepcopy(INFINITE_OPERATION_CONDITIONS)
    conditions['scenario'] = scenario
    return conditions
