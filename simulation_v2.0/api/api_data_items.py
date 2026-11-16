# ================================================ 내보내는 값의 소수 자릿수: 시뮬레이션 시각(초), 순간 전력(kW), 누적 전력 사용량(kWh), 탄소배출량(kgCO2e) ================================================
DECIMAL_PLACES = {
    'simulation_time_sec': 1,
    'power_kw': 3,
    'energy_kwh': 4,
    'carbon_emission_kgco2e': 4,
}


# ================================================ 라인 이름: 작업자 그룹 이름에서 이 글자를 뺀 것 ================================================
WORKER_GROUP_NAME_PART_NOT_SHOWN_IN_LINE_NAME = 'WWM_'


# ================================================ SMT 라인의 표시 이름: 옛 API(1.1.0)가 내보내던 이름(텔로스 정의서의 허용값). 시뮬레이션의 SMT 라인 이름(그 라인의 첫 단계 공정 코드)마다 라인 이름, AOI 단계의 시뮬레이션 공정 코드마다 불량 이벤트에 적는 라인 이름 ================================================
SMT_LINE_NAMES_SHOWN = {
    'line_name_by_smt_line': {
        'Line_1_Loader': 'SMT_Line_1',
        'Line_2_Loader': 'SMT_Line_2',
    },
    'line_name_by_aoi_process_code': {
        'AOI_U1': 'SMT_Line_1_AOI',
        'AOI_U2': 'SMT_Line_2_AOI',
    },
}


# ================================================ 제품코드: 제품 한 대의 번호를 이 자릿수로 채운 글자(예: 3번째 제품은 0003) ================================================
PRODUCT_UNIT_CODE_DIGITS = 4
UNIT_NUMBER_WHEN_UNKNOWN = 0


# ================================================ 작업자 그룹도 SMT 라인도 없는 공정에서 난 불량 이벤트의 라인 이름: 빈 글자 ================================================
LINE_NAME_WHEN_NO_WORKER_GROUP = ''


# ================================================ 창고 이벤트의 구분 값: 시뮬레이션 기록의 이름(왼쪽)을 내보내는 값(오른쪽)으로. 여기에 없는 기록(발주 order)은 내보내지 않음 ================================================
WAREHOUSE_EVENT_NAMES = {
    'consume': 'consume',
    'produce': 'produce',
    'arrive': 'order-arrive',
}


# ================================================ 공통 표시: 시뮬레이션 시각, 라인 이름(SMT 라인은 옛 API의 이름, 작업자 그룹은 WWM_을 뺀 이름), 불량 이벤트의 라인 이름(AOI 단계 공정은 그 단계의 이름), 제품코드 ================================================
def shown_simulation_time_sec(simulation_time_sec):
    return round(simulation_time_sec, DECIMAL_PLACES['simulation_time_sec'])


def line_name_of_worker_group(worker_group):
    line_name_by_smt_line = SMT_LINE_NAMES_SHOWN['line_name_by_smt_line']
    if worker_group in line_name_by_smt_line:
        return line_name_by_smt_line[worker_group]
    return worker_group.replace(WORKER_GROUP_NAME_PART_NOT_SHOWN_IN_LINE_NAME, '')


def line_name_of_defect_event(worker_group, process_code):
    line_name_by_aoi_process_code = SMT_LINE_NAMES_SHOWN['line_name_by_aoi_process_code']
    if process_code in line_name_by_aoi_process_code:
        return line_name_by_aoi_process_code[process_code]
    if worker_group is None:
        return LINE_NAME_WHEN_NO_WORKER_GROUP
    return line_name_of_worker_group(worker_group)


def product_unit_code(unit_number):
    if unit_number is None:
        unit_number = UNIT_NUMBER_WHEN_UNKNOWN
    return str(int(unit_number)).zfill(PRODUCT_UNIT_CODE_DIGITS)


# ================================================ 실시간 데이터(REST 응답)의 항목: 모델별 누적 생산량, 모델별 생산 진행 수량, 라인별 작업 인원, 전력, 탄소배출량, SMT 필름교체·Chip보충 이벤트 ================================================
def real_time_data_items(simulation_time_sec, real_time_state, carbon_emission):
    return {
        '시뮬레이션 시간(s)': shown_simulation_time_sec(simulation_time_sec),
        '모델별 누적 생산량': quantity_items(real_time_state['production_quantity_by_product']),
        '모델별 생산 진행 수량': quantity_items(
            real_time_state['in_progress_quantity_by_product']),
        '라인별 작업 인원': worker_count_items(
            real_time_state['worker_count_by_worker_group'],
            real_time_state['running_job_count_by_worker_group']),
        '전력': power_items(real_time_state),
        '탄소배출량': carbon_emission_items(carbon_emission),
        'SMT 필름교체·Chip보충 이벤트': smt_material_event_items(
            real_time_state['smt_material_events']),
    }


def quantity_items(quantity_by_product):
    items = {}
    for product_code, quantity in quantity_by_product.items():
        items[product_code] = int(quantity)
    return items


def worker_count_items(worker_count_by_worker_group, running_job_count_by_worker_group):
    items = {}
    for worker_group, worker_count in worker_count_by_worker_group.items():
        assigned_worker_count = int(worker_count)
        running_job_count = int(running_job_count_by_worker_group[worker_group])
        items[line_name_of_worker_group(worker_group)] = {
            '배정 인원': assigned_worker_count,
            '작업 중': min(assigned_worker_count, running_job_count),
        }
    return items


def power_item(power_kw, weighted_energy_kwh):
    return {
        '순간 전력(kW)': round(float(power_kw), DECIMAL_PLACES['power_kw']),
        '누적 전력 사용량(kWh)': round(float(weighted_energy_kwh), DECIMAL_PLACES['energy_kwh']),
    }


def power_items(real_time_state):
    machine_items = {}
    for machine_name, power_kw in real_time_state['power_kw_by_machine'].items():
        weighted_energy_kwh = real_time_state['weighted_energy_kwh_by_machine'][machine_name]
        machine_items[machine_name] = power_item(power_kw, weighted_energy_kwh)
    line_items = {}
    for worker_group, power_kw in real_time_state['power_kw_by_worker_group'].items():
        weighted_energy_kwh = real_time_state['weighted_energy_kwh_by_worker_group'][worker_group]
        line_items[line_name_of_worker_group(worker_group)] = power_item(
            power_kw, weighted_energy_kwh)
    return {
        '설비별': machine_items,
        '라인별': line_items,
        '기저부하': power_item(
            real_time_state['base_load_power_kw'],
            real_time_state['base_load_weighted_energy_kwh']),
    }


# ================================================ 탄소배출량(REST 응답)의 항목: 공정별·라인별·기저부하·공장 합의 탄소배출량. 값은 전력 사용량(시간대 가중) × 배출계수이고 투입 재료에서 넘어온 몫은 들어 있지 않음(MCF의 AllocatedCO2eq·SumCO2eq와 다른 값) ================================================
def carbon_emission_kgco2e(carbon_emission_value):
    return round(float(carbon_emission_value), DECIMAL_PLACES['carbon_emission_kgco2e'])


def carbon_emission_item(electricity_carbon_emission):
    return {
        '탄소배출량(kgCO2e)': carbon_emission_kgco2e(electricity_carbon_emission),
    }


def carbon_emission_items(carbon_emission):
    process_items = {}
    electricity_carbon_emission_by_process = (
        carbon_emission['electricity_carbon_emission_by_process'])
    for process_code, electricity_carbon_emission in (
            electricity_carbon_emission_by_process.items()):
        worker_group = carbon_emission['worker_group_by_process'][process_code]
        process_items[process_code] = {
            '라인': line_name_of_worker_group(worker_group),
        }
        process_items[process_code].update(carbon_emission_item(electricity_carbon_emission))
    line_items = {}
    electricity_carbon_emission_by_worker_group = (
        carbon_emission['electricity_carbon_emission_by_worker_group'])
    for worker_group, electricity_carbon_emission in (
            electricity_carbon_emission_by_worker_group.items()):
        line_items[line_name_of_worker_group(worker_group)] = carbon_emission_item(
            electricity_carbon_emission)
    return {
        '공정별': process_items,
        '라인별': line_items,
        '기저부하': carbon_emission_item(
            carbon_emission['base_load_electricity_carbon_emission']),
        '공장 합': carbon_emission_item(
            carbon_emission['factory_electricity_carbon_emission']),
    }


# ================================================ SMT 필름교체·Chip보충 이벤트(REST 응답)의 항목: 지금까지 발생한 이벤트마다 구분(필름교체, Chip보충), 라인, 설비, 시작 시각, 종료 시각(진행 중이면 null) ================================================
def smt_material_event_items(smt_material_events):
    items = []
    for smt_material_event in smt_material_events:
        end_sec = smt_material_event['end_sec']
        if end_sec is not None:
            end_sec = shown_simulation_time_sec(end_sec)
        items.append({
            '구분': smt_material_event['event'],
            '라인': line_name_of_worker_group(smt_material_event['smt_line']),
            '설비': smt_material_event['machine_name'],
            '시작 시각(s)': shown_simulation_time_sec(smt_material_event['start_sec']),
            '종료 시각(s)': end_sec,
        })
    return items


# ================================================ 기준 정보(REST 응답)의 항목: 모델별 완료 공정코드, 모델별 박스당 제품 수량 ================================================
def reference_information_items(reference_information):
    return {
        '모델별 완료 공정코드': dict(reference_information['completion_process_code_by_product']),
        '모델별 박스당 제품 수량': quantity_items(
            reference_information['product_quantity_per_box_by_product']),
    }


# ================================================ 이벤트 데이터(MQTT)의 구간: 직전 발행 시각부터 이번 발행 시각까지 ================================================
def event_period(start_sec, end_sec):
    return {
        '시작': shown_simulation_time_sec(start_sec),
        '종료': shown_simulation_time_sec(end_sec),
    }


# ================================================ 이벤트 데이터(MQTT)의 항목: 설비, 작업자-공정, 창고-입출고, 불량, 박스-완료(시각은 그 박스의 마지막 제품이 완성된 시뮬레이션 시각, 박스 번호는 그 모델의 몇 번째 박스인지) ================================================
def machine_event_items(machine_events):
    items = []
    for machine_event in machine_events:
        items.append({
            '시각(s)': shown_simulation_time_sec(machine_event['sec']),
            '구분': machine_event['event'],
            '설비': machine_event['machine_name'],
        })
    return items


def worker_process_event_items(worker_process_events):
    items = []
    for worker_process_event in worker_process_events:
        items.append({
            '시각(s)': shown_simulation_time_sec(worker_process_event['sec']),
            '구분': worker_process_event['event'],
            '모델': worker_process_event['product_code'],
            '라인': line_name_of_worker_group(worker_process_event['worker_group']),
            '공정코드': worker_process_event['process_code'],
            '제품코드': product_unit_code(worker_process_event['unit_number']),
        })
    return items


def warehouse_event_items(warehouse_events):
    items = []
    for warehouse_event in warehouse_events:
        if warehouse_event['event'] in WAREHOUSE_EVENT_NAMES:
            items.append({
                '시각(s)': shown_simulation_time_sec(warehouse_event['sec']),
                '구분': WAREHOUSE_EVENT_NAMES[warehouse_event['event']],
                '품목코드': warehouse_event['item_code'],
                '수량': warehouse_event['quantity'],
                '현재고': warehouse_event['present_stock'],
            })
    return items


def defect_event_items(defect_events):
    items = []
    for defect_event in defect_events:
        items.append({
            '시각(s)': shown_simulation_time_sec(defect_event['sec']),
            '모델': defect_event['product_code'],
            '라인': line_name_of_defect_event(
                defect_event['worker_group'], defect_event['process_code']),
            '공정코드': defect_event['process_code'],
            '제품코드': product_unit_code(defect_event['unit_number']),
        })
    return items


def box_completion_event_items(box_completion_events):
    items = []
    for box_completion_event in box_completion_events:
        items.append({
            '시각(s)': shown_simulation_time_sec(box_completion_event['sec']),
            '모델': box_completion_event['product_code'],
            '박스 번호': int(box_completion_event['box_number']),
            '박스당 제품 수량': int(box_completion_event['product_quantity_per_box']),
        })
    return items
