from aas_preprocessing.aas_reader import SECONDS_PER_DAY, SECONDS_PER_HOUR
from knowledge_graph import code_from_kg_node_path


# ================================================ 탄소배출 요소별 배출계수: 공정별 배출계수가 확정되지 않아 전력 1.0 적용(결과는 전력량 kWh 기준 비교) ================================================
EMISSION_FACTORS = {
    'electricity': 1.0,
}


# ================================================ MCF 탄소배출량 계산의 전력 배출계수(kgCO2e/kWh): 에코 CPRO_MCF_산정툴_v1.0_261108.xlsx의 DB_배출계수 시트 전력 값(베트남 계통, ecoinvent 3.12). 보상 계산이 쓰는 위 EMISSION_FACTORS와 따로 둠 ================================================
MCF_ELECTRICITY_REF_EMISSION_FACTOR = 0.620873


# ================================================ MCF 탄소배출량 계산의 AllocationBasis 글자(MCF 인스턴스의 AllocationBasis와 같은 글자): 레시피가 여럿인 MCF는 공유 배출을 전력 사용량 비율로 나눔(Simulation RuntimeStatus Records의 RecordName ElectricityAmount와 같은 이름), 레시피가 하나인 MCF는 나누지 않고 전량 귀속 ================================================
MCF_ALLOCATION_BASIS = {
    'several_recipes': 'Physical · ElectricityAmount',
    'single_recipe': 'Avoid allocation',
}
RECIPE_COUNT_OF_SINGLE_RECIPE_MCF = 1
ALLOCATED_FACTOR_OF_SINGLE_RECIPE_MCF = 1.0


# ================================================ MCF의 ResourceType 값: 설비 MCF의 Amount는 그 설비의 시간대 가중 전력량, 작업자 그룹 MCF의 Amount는 그 그룹 공정의 kW × 시간(시간대 가중) ================================================
MCF_RESOURCE_TYPES = {
    'machine': 'Machine',
    'worker': 'Worker',
}


# ================================================ 제품 한 대가 공정 1회에서 내는 산출 수량. SMT 라인의 어레이 1장은 그 어레이의 PCB 수량을 냄 ================================================
OUTPUT_ITEM_QUANTITY_OF_PRODUCT_UNIT = 1


# ================================================ MCF 탄소배출량 계산식(사용자 정의 2026-11-15, MCF 하나의 기간 합계): ContributionCO2eq는 배출 원천별 기여량(전력 줄은 Amount × RefEmissionFactor, 투입 품목 줄은 기간 사용 수량 × (그 품목 1개의 누적 배출량 − 그 가운데 이 MCF에서 이미 세어진 몫)). 투입 품목의 누적 배출량은 기간 사용 수량 × 그 품목 1개의 누적 배출량. 공유 배출은 전력(보조투입)과 잔류물의 ContributionCO2eq 합(지금은 전력 하나). SumCO2eq는 그 MCF에 남은 InputMaterialEmissions 줄의 ContributionCO2eq 합 + 공유 배출. AllocatedFactor는 레시피 실행에 쓴 전력량 ÷ Amount. AllocatedCO2eq는 그 레시피 투입 품목의 누적 배출량 합 + 공유 배출 × AllocatedFactor. 다음 공정으로 넘기는 산출물 1개당 배출량은 AllocatedCO2eq ÷ OutputItemQuantity ================================================
def calculate_ContributionCO2eq_of_electricity(Amount, RefEmissionFactor):
    return Amount * RefEmissionFactor


def calculate_cumulative_emission_of_input_item(used_quantity, emission_per_item):
    return used_quantity * emission_per_item


def calculate_ContributionCO2eq_of_input_item(
        used_quantity, emission_per_item, emission_per_item_counted_in_this_mcf):
    return used_quantity * (emission_per_item - emission_per_item_counted_in_this_mcf)


def calculate_shared_emission(ContributionCO2eq_of_ancillary_inputs_and_residuals):
    return sum(ContributionCO2eq_of_ancillary_inputs_and_residuals)


def calculate_SumCO2eq(ContributionCO2eq_of_input_items, shared_emission):
    return sum(ContributionCO2eq_of_input_items) + shared_emission


def calculate_AllocatedFactor(recipe_electricity_amount_kwh, Amount):
    if Amount <= 0.0:
        return 0.0
    return recipe_electricity_amount_kwh / Amount


def calculate_allocated_shared_emission(shared_emission, AllocatedFactor):
    return shared_emission * AllocatedFactor


def calculate_AllocatedCO2eq(cumulative_emission_of_input_items, allocated_shared_emission):
    return sum(cumulative_emission_of_input_items) + allocated_shared_emission


def calculate_emission_per_output_item(AllocatedCO2eq, OutputItemQuantity):
    if OutputItemQuantity <= 0:
        return 0.0
    return AllocatedCO2eq / OutputItemQuantity


# ================================================ 투입 품목의 기간 사용 수량: 창고 품목은 InputItemQuantity × 이 레시피의 OutputItemQuantity ================================================
def calculate_used_quantity_of_warehouse_item(InputItemQuantity, OutputItemQuantity):
    return InputItemQuantity * OutputItemQuantity


# ================================================ 전력량 집계 항목: 전력량, 전력 시간대 가중 전력량, 피크타임 전력량 ================================================
ENERGY_KEYS = ['kwh', 'weighted_kwh', 'peak_kwh']


# ================================================ 설비 가동·정지 기록의 사건 이름 ================================================
MACHINE_ON_OFF_EVENTS = {
    'on': '가동시작',
    'off': '가동종료',
}


# ================================================ 평시의 전력 시간대 가중치: 이보다 큰 시간대가 피크타임 ================================================
NORMAL_TIME_BAND_WEIGHT = 1.0


# ================================================ 공정별·설비별 전력량 결과의 소수 자릿수 ================================================
ENERGY_DECIMAL_PLACES = 4


# ================================================ 시간대 가중: 구간을 자정과 전력 시간대 경계에서 나눠 구간 시작 시각의 가중치를 곱함 ================================================
def time_band_weight(sec, electricity_time_band_weights):
    sec_in_day = sec % float(SECONDS_PER_DAY)
    weight_difference_from_normal = 0.0
    for time_band in electricity_time_band_weights:
        if time_band['start_sec'] <= sec_in_day < time_band['end_sec']:
            weight_difference_from_normal += time_band['weight'] - NORMAL_TIME_BAND_WEIGHT
    return NORMAL_TIME_BAND_WEIGHT + weight_difference_from_normal


def split_by_time_band(start_sec, end_sec, electricity_time_band_weights):
    periods = []
    period_start_sec = start_sec
    while period_start_sec < end_sec:
        day_start_sec = (period_start_sec // float(SECONDS_PER_DAY)) * float(SECONDS_PER_DAY)
        boundary_secs = [end_sec, day_start_sec + float(SECONDS_PER_DAY)]
        for time_band in electricity_time_band_weights:
            for sec_in_day in [time_band['start_sec'], time_band['end_sec']]:
                if period_start_sec < day_start_sec + sec_in_day:
                    boundary_secs.append(day_start_sec + sec_in_day)
        period_end_sec = min(boundary_secs)
        periods.append({'start_sec': period_start_sec, 'end_sec': period_end_sec})
        period_start_sec = period_end_sec
    return periods


def weighted_energy_kwh(start_sec, end_sec, power_kw, electricity_time_band_weights):
    weighted_kwh = 0.0
    for period in split_by_time_band(start_sec, end_sec, electricity_time_band_weights):
        duration_hours = (period['end_sec'] - period['start_sec']) / float(SECONDS_PER_HOUR)
        energy_kwh = duration_hours * power_kw
        weight = time_band_weight(period['start_sec'], electricity_time_band_weights)
        weighted_kwh += energy_kwh * weight
    return weighted_kwh


def peak_time_energy_kwh(start_sec, end_sec, power_kw, electricity_time_band_weights):
    peak_kwh = 0.0
    first_day = int(start_sec // SECONDS_PER_DAY)
    last_day = int(end_sec // SECONDS_PER_DAY)
    for day in range(first_day, last_day + 1):
        for time_band in electricity_time_band_weights:
            if time_band['weight'] > NORMAL_TIME_BAND_WEIGHT:
                peak_start_sec = max(start_sec, day * SECONDS_PER_DAY + time_band['start_sec'])
                peak_end_sec = min(end_sec, day * SECONDS_PER_DAY + time_band['end_sec'])
                peak_duration_sec = max(0.0, peak_end_sec - peak_start_sec)
                peak_kwh += peak_duration_sec * power_kw / float(SECONDS_PER_HOUR)
    return peak_kwh


def energy_by_time_band(start_sec, end_sec, power_kw, electricity_time_band_weights):
    if end_sec <= start_sec:
        return zero_energy()
    return {
        'kwh': (end_sec - start_sec) * power_kw / float(SECONDS_PER_HOUR),
        'weighted_kwh': weighted_energy_kwh(
            start_sec, end_sec, power_kw, electricity_time_band_weights),
        'peak_kwh': peak_time_energy_kwh(
            start_sec, end_sec, power_kw, electricity_time_band_weights),
    }


def base_load_weighted_energy_kwh_until(
        now_sec, WorkStartTime, WorkEndTime, base_load_kw, electricity_time_band_weights):
    work_duration_sec = max(0.0, WorkEndTime - WorkStartTime)
    passed_day_count = int(now_sec // float(SECONDS_PER_DAY))
    sec_in_day = now_sec - passed_day_count * float(SECONDS_PER_DAY)
    today_duration_sec = min(max(sec_in_day - WorkStartTime, 0.0), work_duration_sec)
    one_day_kwh = weighted_energy_kwh(
        WorkStartTime, WorkEndTime, base_load_kw, electricity_time_band_weights)
    today_kwh = weighted_energy_kwh(
        WorkStartTime, WorkStartTime + today_duration_sec, base_load_kw,
        electricity_time_band_weights)
    return passed_day_count * one_day_kwh + today_kwh


# ================================================ 탄소배출량 환산: 전력량 × 전력 배출계수 ================================================
def convert_to_carbon_emission(energy_kwh):
    return energy_kwh * EMISSION_FACTORS['electricity']


# ================================================ MCF 탄소배출량 계산 준비(MCF 레시피 구조에서 한 번): 품목 코드를 OutputItemCode로 내는 Simulation 레시피, 투입 품목을 만드는 레시피(중간재는 그 중간재를 만든 앞 레시피, 창고 품목은 OutputItemCode가 그 품목 코드인 레시피. SMT 마지막 공정 레시피의 OutputItemCode가 창고의 PCB 품목 코드), 계산 순서(투입 품목을 만드는 레시피가 모두 앞에 오게), 레시피의 마지막 산출 품목 ================================================
def list_simulation_recipe_indexes_by_OutputItemCode(recipes_by_simulation_recipe_index):
    simulation_recipe_indexes_by_OutputItemCode = {}
    for simulation_recipe_index, recipe in recipes_by_simulation_recipe_index.items():
        OutputItemCode = recipe['OutputItemCode']
        if OutputItemCode not in simulation_recipe_indexes_by_OutputItemCode:
            simulation_recipe_indexes_by_OutputItemCode[OutputItemCode] = []
        simulation_recipe_indexes_by_OutputItemCode[OutputItemCode].append(
            simulation_recipe_index)
    return simulation_recipe_indexes_by_OutputItemCode


def simulation_recipe_indexes_making_input_item(
        input_item, simulation_recipe_indexes_by_OutputItemCode):
    source_simulation_recipe_index = input_item['source_simulation_recipe_index']
    if source_simulation_recipe_index is not None:
        return [source_simulation_recipe_index]
    if input_item['item_code'] in simulation_recipe_indexes_by_OutputItemCode:
        return simulation_recipe_indexes_by_OutputItemCode[input_item['item_code']]
    return []


def order_recipes_by_input_item_flow(
        recipes_by_simulation_recipe_index, simulation_recipe_indexes_by_OutputItemCode):
    ordered_simulation_recipe_indexes = []
    is_ordered = dict.fromkeys(recipes_by_simulation_recipe_index, False)
    while len(ordered_simulation_recipe_indexes) < len(recipes_by_simulation_recipe_index):
        ordered_count_before = len(ordered_simulation_recipe_indexes)
        for simulation_recipe_index, recipe in recipes_by_simulation_recipe_index.items():
            if is_ordered[simulation_recipe_index]:
                continue
            are_all_input_items_ordered = True
            for input_item in recipe['input_items']:
                making_simulation_recipe_indexes = simulation_recipe_indexes_making_input_item(
                    input_item, simulation_recipe_indexes_by_OutputItemCode)
                for making_simulation_recipe_index in making_simulation_recipe_indexes:
                    if not is_ordered[making_simulation_recipe_index]:
                        are_all_input_items_ordered = False
            if are_all_input_items_ordered:
                ordered_simulation_recipe_indexes.append(simulation_recipe_index)
                is_ordered[simulation_recipe_index] = True
        if len(ordered_simulation_recipe_indexes) == ordered_count_before:
            raise ValueError('MCF 레시피의 투입 품목이 서로를 가리켜 계산 순서를 정할 수 없음')
    return ordered_simulation_recipe_indexes


def list_last_OutputItemCodes_by_simulation_recipe_index(
        recipes_by_simulation_recipe_index, recipe_calculation_order):
    following_simulation_recipe_indexes = {}
    for simulation_recipe_index in recipes_by_simulation_recipe_index:
        following_simulation_recipe_indexes[simulation_recipe_index] = []
    for simulation_recipe_index, recipe in recipes_by_simulation_recipe_index.items():
        for input_item in recipe['input_items']:
            source_simulation_recipe_index = input_item['source_simulation_recipe_index']
            if source_simulation_recipe_index is not None:
                following_simulation_recipe_indexes[source_simulation_recipe_index].append(
                    simulation_recipe_index)
    last_OutputItemCodes_by_simulation_recipe_index = {}
    for simulation_recipe_index in reversed(recipe_calculation_order):
        last_OutputItemCodes = []
        if not following_simulation_recipe_indexes[simulation_recipe_index]:
            recipe = recipes_by_simulation_recipe_index[simulation_recipe_index]
            last_OutputItemCodes.append(recipe['OutputItemCode'])
        for following_index in following_simulation_recipe_indexes[simulation_recipe_index]:
            for OutputItemCode in last_OutputItemCodes_by_simulation_recipe_index[following_index]:
                if OutputItemCode not in last_OutputItemCodes:
                    last_OutputItemCodes.append(OutputItemCode)
        last_OutputItemCodes_by_simulation_recipe_index[simulation_recipe_index] = (
            last_OutputItemCodes)
    return last_OutputItemCodes_by_simulation_recipe_index


# ================================================ MCF 탄소배출량 계산 ①: MCF마다 전력 줄의 ContributionCO2eq(Amount × RefEmissionFactor), 공유 배출, 레시피별 AllocatedFactor와 공유 배출 몫(공유 배출 × AllocatedFactor). 레시피가 하나인 MCF는 AllocatedFactor 1(전량 귀속) ================================================
def allocation_basis_and_factor_of_recipe(recipe_count, recipe_electricity_amount_kwh, Amount):
    if recipe_count == RECIPE_COUNT_OF_SINGLE_RECIPE_MCF:
        return {
            'AllocationBasis': MCF_ALLOCATION_BASIS['single_recipe'],
            'AllocatedFactor': ALLOCATED_FACTOR_OF_SINGLE_RECIPE_MCF,
        }
    return {
        'AllocationBasis': MCF_ALLOCATION_BASIS['several_recipes'],
        'AllocatedFactor': calculate_AllocatedFactor(recipe_electricity_amount_kwh, Amount),
    }


def calculate_shared_emission_and_allocation_of_mcf(
        mcf_resource, activity_data, recipes_by_simulation_recipe_index, recipe_records):
    Amount = activity_data['Amount']
    ContributionCO2eq_of_electricity = calculate_ContributionCO2eq_of_electricity(
        Amount, MCF_ELECTRICITY_REF_EMISSION_FACTOR)
    shared_emission = calculate_shared_emission([ContributionCO2eq_of_electricity])
    simulation_recipe_indexes = mcf_resource['simulation_recipe_indexes']
    electricity_amount_kwh_by_recipe = (
        activity_data['electricity_amount_kwh_by_simulation_recipe_index'])
    Allocation = []
    for simulation_recipe_index in simulation_recipe_indexes:
        recipe = recipes_by_simulation_recipe_index[simulation_recipe_index]
        recipe_electricity_amount_kwh = electricity_amount_kwh_by_recipe[simulation_recipe_index]
        allocation = {
            'simulation_recipe_index': simulation_recipe_index,
            'ProcessCode': recipe['ProcessCode'],
            'OutputItemCode': recipe['OutputItemCode'],
            'OutputItemQuantity': recipe_records[simulation_recipe_index]['OutputItemQuantity'],
            'electricity_amount_kwh': recipe_electricity_amount_kwh,
        }
        allocation.update(allocation_basis_and_factor_of_recipe(
            len(simulation_recipe_indexes), recipe_electricity_amount_kwh, Amount))
        allocation['allocated_shared_emission'] = calculate_allocated_shared_emission(
            shared_emission, allocation['AllocatedFactor'])
        Allocation.append(allocation)
    return {
        'ResourceType': mcf_resource['ResourceType'],
        'ResourceName': mcf_resource['ResourceName'],
        'is_base_load_mcf': activity_data['is_base_load_mcf'],
        'OperatingTime': activity_data['OperatingTime'],
        'Amount': Amount,
        'ContributionCO2eq_of_electricity': ContributionCO2eq_of_electricity,
        'shared_emission': shared_emission,
        'Allocation': Allocation,
    }


# ================================================ 어느 MCF에도 없는 레시피(자원이 없는 공정)의 규칙: 전력 몫 없이 투입 품목의 누적 배출량 합과 MCF별로 이미 세어진 몫을 그대로 다음 레시피로 넘김. 이런 레시피는 MCF의 ResourceName이 없고 같은 MCF의 레시피도 없음 ================================================
MCF_OF_RECIPE_WITHOUT_MCF = {
    'ResourceName': None,
    'simulation_recipe_indexes': [],
}


def allocation_of_recipe_without_mcf(simulation_recipe_index, recipe, recipe_record):
    return {
        'simulation_recipe_index': simulation_recipe_index,
        'ProcessCode': recipe['ProcessCode'],
        'OutputItemCode': recipe['OutputItemCode'],
        'OutputItemQuantity': recipe_record['OutputItemQuantity'],
        'electricity_amount_kwh': 0.0,
        'allocated_shared_emission': 0.0,
    }


def mcf_of_simulation_recipe(simulation_recipe_index, mcf_resource_by_simulation_recipe_index):
    if simulation_recipe_index in mcf_resource_by_simulation_recipe_index:
        return mcf_resource_by_simulation_recipe_index[simulation_recipe_index]
    return MCF_OF_RECIPE_WITHOUT_MCF


# ================================================ MCF 탄소배출량 계산 ②: 레시피의 투입 품목마다 사용 수량과 1개의 누적 배출량. 중간재는 시뮬레이션이 센 사용 수량(이 레시피를 실행한 제품 단위가 갖고 있던 앞 레시피 산출물 수량. 투입이 하나로 정해진 레시피에서는 이 레시피의 OutputItemQuantity와 같음)과 앞 레시피 산출물 1개당 배출량. 창고 품목은 그 품목을 만드는 레시피가 있으면(SMT가 만든 PCB) InputItemQuantity × OutputItemQuantity와 그 레시피들의 산출물 1개당 배출량, 없으면 배출계수 자료가 없어 값 없음 ================================================
def emission_per_item_made_by_recipes(making_allocations):
    AllocatedCO2eq_of_making_recipes = 0.0
    OutputItemQuantity_of_making_recipes = 0
    for making_allocation in making_allocations:
        AllocatedCO2eq_of_making_recipes += making_allocation['AllocatedCO2eq']
        OutputItemQuantity_of_making_recipes += making_allocation['OutputItemQuantity']
    return calculate_emission_per_output_item(
        AllocatedCO2eq_of_making_recipes, OutputItemQuantity_of_making_recipes)


# ================================================ SumCO2eq의 중복 제거 규칙(사용자 결정 2026-11-15): 산출물 1개마다 누적 배출량과 함께 MCF별로 이미 그 MCF를 거치며 세어진 몫을 따라감. MCF의 레시피가 만든 산출물은 그 MCF에서 세어진 몫이 누적 배출량(AllocatedCO2eq) 전체이고, 다른 MCF에서 세어진 몫은 투입 품목들이 갖고 온 그 MCF의 몫 합. 투입 품목 줄의 ContributionCO2eq는 사용 수량 × (1개의 누적 배출량 − 이 MCF에서 이미 세어진 몫)이라, 같은 MCF 안에서 만들어 넘긴 중간재는 0(InputMaterialEmissions 줄에서 뺌. 투입 목록에는 그대로), 다른 MCF에서 처음 들어온 중간재는 누적 배출량 전체, 다른 MCF를 거쳐 돌아온 중간재는 밖에서 더해진 몫만 ================================================
def emission_per_item_counted_by_mcf_made_by_recipes(making_allocations):
    OutputItemQuantity_of_making_recipes = 0
    emission_counted_by_mcf_ResourceName = {}
    for making_allocation in making_allocations:
        OutputItemQuantity_of_making_recipes += making_allocation['OutputItemQuantity']
        emission_counted_of_making_recipe = (
            making_allocation['emission_counted_by_mcf_ResourceName'])
        for ResourceName, emission_counted in emission_counted_of_making_recipe.items():
            if ResourceName not in emission_counted_by_mcf_ResourceName:
                emission_counted_by_mcf_ResourceName[ResourceName] = 0.0
            emission_counted_by_mcf_ResourceName[ResourceName] += emission_counted
    emission_per_item_counted_by_mcf_ResourceName = {}
    for ResourceName, emission_counted in emission_counted_by_mcf_ResourceName.items():
        emission_per_item_counted_by_mcf_ResourceName[ResourceName] = (
            calculate_emission_per_output_item(
                emission_counted, OutputItemQuantity_of_making_recipes))
    return emission_per_item_counted_by_mcf_ResourceName


def emission_counted_by_mcf_of_recipe_output(
        ResourceName_of_recipe_mcf, AllocatedCO2eq, input_item_emissions):
    emission_counted_by_mcf_ResourceName = {}
    for input_item_emission in input_item_emissions:
        if input_item_emission['cumulative_emission'] is None:
            continue
        emission_per_item_counted_by_mcf_ResourceName = (
            input_item_emission['emission_per_item_counted_by_mcf_ResourceName'])
        for ResourceName in emission_per_item_counted_by_mcf_ResourceName:
            if ResourceName not in emission_counted_by_mcf_ResourceName:
                emission_counted_by_mcf_ResourceName[ResourceName] = 0.0
            emission_counted_by_mcf_ResourceName[ResourceName] += (
                calculate_cumulative_emission_of_input_item(
                    input_item_emission['used_quantity'],
                    emission_per_item_counted_by_mcf_ResourceName[ResourceName]))
    if ResourceName_of_recipe_mcf is not None:
        emission_counted_by_mcf_ResourceName[ResourceName_of_recipe_mcf] = AllocatedCO2eq
    return emission_counted_by_mcf_ResourceName


def is_input_item_made_in_same_mcf(input_item_emission, simulation_recipe_indexes_of_mcf):
    source_simulation_recipe_index = input_item_emission['source_simulation_recipe_index']
    return source_simulation_recipe_index in simulation_recipe_indexes_of_mcf


# ================================================ MCF 탄소배출량 계산 ③: 레시피의 투입 품목마다 누적 배출량(AllocatedCO2eq에 들어감)과 ContributionCO2eq(SumCO2eq에 들어감). InputMaterialEmissions 줄은 투입 품목 가운데 같은 MCF 안에서 만들어 넘긴 중간재를 뺀 것 ================================================
def calculate_input_item_emission(
        input_item, input_item_index, OutputItemQuantity,
        used_quantity_by_source_simulation_recipe_index, making_allocations,
        ResourceName_of_recipe_mcf):
    source_simulation_recipe_index = input_item['source_simulation_recipe_index']
    input_item_emission = {
        'item_code': input_item['item_code'],
        'source_simulation_recipe_index': source_simulation_recipe_index,
        'input_item_index': input_item_index,
        'used_quantity': None,
        'emission_per_item': None,
        'emission_per_item_counted_by_mcf_ResourceName': {},
        'emission_per_item_counted_in_this_mcf': None,
        'cumulative_emission': None,
        'ContributionCO2eq': None,
    }
    if not making_allocations:
        return input_item_emission
    if source_simulation_recipe_index is None:
        used_quantity = calculate_used_quantity_of_warehouse_item(
            input_item['InputItemQuantity'], OutputItemQuantity)
    else:
        used_quantity = used_quantity_by_source_simulation_recipe_index.get(
            source_simulation_recipe_index, 0)
    emission_per_item = emission_per_item_made_by_recipes(making_allocations)
    emission_per_item_counted_by_mcf_ResourceName = (
        emission_per_item_counted_by_mcf_made_by_recipes(making_allocations))
    emission_per_item_counted_in_this_mcf = emission_per_item_counted_by_mcf_ResourceName.get(
        ResourceName_of_recipe_mcf, 0.0)
    input_item_emission['used_quantity'] = used_quantity
    input_item_emission['emission_per_item'] = emission_per_item
    input_item_emission['emission_per_item_counted_by_mcf_ResourceName'] = (
        emission_per_item_counted_by_mcf_ResourceName)
    input_item_emission['emission_per_item_counted_in_this_mcf'] = (
        emission_per_item_counted_in_this_mcf)
    input_item_emission['cumulative_emission'] = calculate_cumulative_emission_of_input_item(
        used_quantity, emission_per_item)
    input_item_emission['ContributionCO2eq'] = calculate_ContributionCO2eq_of_input_item(
        used_quantity, emission_per_item, emission_per_item_counted_in_this_mcf)
    return input_item_emission


def input_item_emissions_of_recipe(
        recipe, OutputItemQuantity, used_quantity_by_source_simulation_recipe_index,
        ResourceName_of_recipe_mcf, allocation_by_simulation_recipe_index,
        simulation_recipe_indexes_by_OutputItemCode):
    input_item_emissions = []
    for input_item_index, input_item in enumerate(recipe['input_items']):
        making_allocations = []
        making_simulation_recipe_indexes = simulation_recipe_indexes_making_input_item(
            input_item, simulation_recipe_indexes_by_OutputItemCode)
        for making_simulation_recipe_index in making_simulation_recipe_indexes:
            making_allocations.append(
                allocation_by_simulation_recipe_index[making_simulation_recipe_index])
        input_item_emissions.append(calculate_input_item_emission(
            input_item, input_item_index, OutputItemQuantity,
            used_quantity_by_source_simulation_recipe_index, making_allocations,
            ResourceName_of_recipe_mcf))
    return input_item_emissions


def list_InputMaterialEmissions_left_in_mcf(
        input_item_emissions, simulation_recipe_indexes_of_mcf):
    InputMaterialEmissions = []
    for input_item_emission in input_item_emissions:
        if not is_input_item_made_in_same_mcf(
                input_item_emission, simulation_recipe_indexes_of_mcf):
            InputMaterialEmissions.append(input_item_emission)
    return InputMaterialEmissions


def list_cumulative_emission_with_value(input_item_emissions):
    cumulative_emission_values = []
    for input_item_emission in input_item_emissions:
        if input_item_emission['cumulative_emission'] is not None:
            cumulative_emission_values.append(input_item_emission['cumulative_emission'])
    return cumulative_emission_values


def list_ContributionCO2eq_with_value(InputMaterialEmissions):
    ContributionCO2eq_values = []
    for input_material_emission in InputMaterialEmissions:
        if input_material_emission['ContributionCO2eq'] is not None:
            ContributionCO2eq_values.append(input_material_emission['ContributionCO2eq'])
    return ContributionCO2eq_values


# ================================================ MCF 탄소배출량 계산: ① MCF마다 공유 배출과 AllocatedFactor ② 계산 순서(공정 흐름의 앞 레시피부터)대로 레시피마다 투입 품목의 누적 배출량, 남은 InputMaterialEmissions 줄의 ContributionCO2eq, AllocatedCO2eq(투입 품목의 누적 배출량 합 + 공유 배출 몫), 산출물이 MCF별로 이미 세어진 몫 ③ MCF마다 SumCO2eq(남은 InputMaterialEmissions 줄의 ContributionCO2eq 합 + 공유 배출). 기저부하 MCF는 레시피가 없어 SumCO2eq(전력 줄)만 ================================================
def calculate_mcf_carbon_emissions(
        mcf_recipe_structure, activity_data_by_ResourceName, recipe_records,
        recipe_calculation_order, simulation_recipe_indexes_by_OutputItemCode):
    recipes_by_simulation_recipe_index = mcf_recipe_structure['recipes_by_simulation_recipe_index']
    mcf_carbon_emissions = []
    allocation_by_simulation_recipe_index = {}
    mcf_resource_by_simulation_recipe_index = {}
    for mcf_resource in mcf_recipe_structure['mcf_resources']:
        mcf_carbon_emission = calculate_shared_emission_and_allocation_of_mcf(
            mcf_resource, activity_data_by_ResourceName[mcf_resource['ResourceName']],
            recipes_by_simulation_recipe_index, recipe_records)
        mcf_carbon_emissions.append(mcf_carbon_emission)
        for allocation in mcf_carbon_emission['Allocation']:
            simulation_recipe_index = allocation['simulation_recipe_index']
            allocation_by_simulation_recipe_index[simulation_recipe_index] = allocation
            mcf_resource_by_simulation_recipe_index[simulation_recipe_index] = mcf_resource
    recipes_without_mcf = []
    for simulation_recipe_index, recipe in recipes_by_simulation_recipe_index.items():
        if simulation_recipe_index not in allocation_by_simulation_recipe_index:
            allocation = allocation_of_recipe_without_mcf(
                simulation_recipe_index, recipe, recipe_records[simulation_recipe_index])
            recipes_without_mcf.append(allocation)
            allocation_by_simulation_recipe_index[simulation_recipe_index] = allocation
    for simulation_recipe_index in recipe_calculation_order:
        allocation = allocation_by_simulation_recipe_index[simulation_recipe_index]
        recipe_record = recipe_records[simulation_recipe_index]
        mcf_of_recipe = mcf_of_simulation_recipe(
            simulation_recipe_index, mcf_resource_by_simulation_recipe_index)
        input_item_emissions = input_item_emissions_of_recipe(
            recipes_by_simulation_recipe_index[simulation_recipe_index],
            allocation['OutputItemQuantity'],
            recipe_record['used_quantity_by_source_simulation_recipe_index'],
            mcf_of_recipe['ResourceName'], allocation_by_simulation_recipe_index,
            simulation_recipe_indexes_by_OutputItemCode)
        allocation['input_item_emissions'] = input_item_emissions
        allocation['InputMaterialEmissions'] = list_InputMaterialEmissions_left_in_mcf(
            input_item_emissions, mcf_of_recipe['simulation_recipe_indexes'])
        allocation['AllocatedCO2eq'] = calculate_AllocatedCO2eq(
            list_cumulative_emission_with_value(input_item_emissions),
            allocation['allocated_shared_emission'])
        allocation['emission_counted_by_mcf_ResourceName'] = (
            emission_counted_by_mcf_of_recipe_output(
                mcf_of_recipe['ResourceName'], allocation['AllocatedCO2eq'],
                input_item_emissions))
    for mcf_carbon_emission in mcf_carbon_emissions:
        ContributionCO2eq_of_input_items = []
        for allocation in mcf_carbon_emission['Allocation']:
            ContributionCO2eq_of_input_items += list_ContributionCO2eq_with_value(
                allocation['InputMaterialEmissions'])
        mcf_carbon_emission['SumCO2eq'] = calculate_SumCO2eq(
            ContributionCO2eq_of_input_items, mcf_carbon_emission['shared_emission'])
    return {
        'mcf_carbon_emissions': mcf_carbon_emissions,
        'recipes_without_mcf': recipes_without_mcf,
    }


# ================================================ 기저부하 가동시간: 0초부터 지금까지 근무 시작과 근무 종료 사이에 든 시간(점심 포함, 기저부하 전력량과 같은 구간) ================================================
def base_load_operating_time_sec_until(now_sec, WorkStartTime, WorkEndTime):
    work_duration_sec = max(0.0, WorkEndTime - WorkStartTime)
    passed_day_count = int(now_sec // float(SECONDS_PER_DAY))
    sec_in_day = now_sec - passed_day_count * float(SECONDS_PER_DAY)
    today_duration_sec = min(max(sec_in_day - WorkStartTime, 0.0), work_duration_sec)
    return passed_day_count * work_duration_sec + today_duration_sec


# ================================================ 전력량 3항목 만들기와 더하기 ================================================
def zero_energy():
    return dict.fromkeys(ENERGY_KEYS, 0.0)


def add_energy(total, addition):
    for energy_key in ENERGY_KEYS:
        total[energy_key] += addition[energy_key]


# ================================================ 활동량(전력) 누적: 가동 중인 공정 전력 합계(kW)가 바뀔 때마다 그 시각까지의 시간대 가중 전력량을 누적 ================================================
class PowerIntegral:

    def __init__(self, electricity_time_band_weights):
        self.electricity_time_band_weights = electricity_time_band_weights
        self.recorded_sec = 0.0
        self.power_kw = 0.0
        self.recorded_weighted_energy_kwh = 0.0

    def weighted_energy_kwh_until(self, sec):
        weighted_kwh_after_record = weighted_energy_kwh(
            self.recorded_sec, sec, self.power_kw, self.electricity_time_band_weights)
        return self.recorded_weighted_energy_kwh + weighted_kwh_after_record

    def change_power(self, sec, power_change_kw):
        self.recorded_weighted_energy_kwh = self.weighted_energy_kwh_until(sec)
        self.recorded_sec = sec
        self.power_kw += power_change_kw


class CarbonComponents:

    # ================================================ 활동량(전력) 누적에 쓰는 속성 만들기 ================================================
    def reset_carbon_components(self):
        self.process_weighted_energy_kwh = 0.0
        self.process_weighted_energy_kwh_by_worker_group = {}
        self.machine_weighted_energy_kwh = {}
        self.machine_weighted_energy_kwh_by_worker_group = {}
        self.machine_use_count_by_worker_group = {}
        self.machine_energy_recorded_sec = {}
        for machine_name in self.machines:
            self.machine_weighted_energy_kwh[machine_name] = 0.0
            self.machine_weighted_energy_kwh_by_worker_group[machine_name] = {}
            self.machine_use_count_by_worker_group[machine_name] = {}
            self.machine_energy_recorded_sec[machine_name] = 0.0
        self.machine_on_off_records = []
        self.process_power_records = []
        self.process_power_integral = PowerIntegral(self.electricity_time_band_weights)
        self.operating_time_and_energy_by_process = {}
        self.operating_time_sec_by_process = {}
        self.reset_mcf_recipe_records()

    # ================================================ 활동량(가동시간) 누적: 공정별 처리 시간(공정 CycleTime)의 합. 실행된 공정인지 판정하는 데 씀 ================================================
    def accumulate_process_operating_time(self, process_code, duration_sec):
        operating_time_sec_before = self.operating_time_sec_by_process.get(process_code, 0.0)
        self.operating_time_sec_by_process[process_code] = operating_time_sec_before + duration_sec

    # ================================================ 활동량(전력) 누적: 공정 실행 구간 기록, 공정별 가동시간·전력량 ================================================
    def record_process_power_start(self, process_code, power_kw):
        start_sec = float(self.simpy_environment.now)
        process_power_record = {
            'process_code': process_code,
            'start_sec': start_sec,
            'end_sec': None,
            'power_kw': power_kw,
        }
        self.process_power_records.append(process_power_record)
        self.process_power_integral.change_power(start_sec, power_kw)
        return process_power_record

    def record_process_power_end(self, process_power_record):
        process_code = process_power_record['process_code']
        start_sec = process_power_record['start_sec']
        power_kw = process_power_record['power_kw']
        end_sec = float(self.simpy_environment.now)
        process_weighted_kwh = 0.0
        if power_kw:
            process_weighted_kwh = self.accumulate_operating_time_and_energy(
                process_code, start_sec, end_sec, power_kw)
        process_power_record['end_sec'] = end_sec
        self.process_power_integral.change_power(end_sec, -power_kw)
        return process_weighted_kwh

    def accumulate_operating_time_and_energy(self, process_code, start_sec, end_sec, power_kw):
        if process_code not in self.operating_time_and_energy_by_process:
            self.operating_time_and_energy_by_process[process_code] = {
                'worker_group': self.worker_group_of(process_code),
                'power_kw': power_kw,
                'operating_time_sec': 0.0,
                'kwh': 0.0,
                'weighted_kwh': 0.0,
                'peak_kwh': 0.0,
            }
        operating_time_and_energy = self.operating_time_and_energy_by_process[process_code]
        operating_time_and_energy['operating_time_sec'] += end_sec - start_sec
        energy = energy_by_time_band(
            start_sec, end_sec, power_kw, self.electricity_time_band_weights)
        add_energy(operating_time_and_energy, energy)
        return energy['weighted_kwh']

    def accumulate_process_weighted_energy(self, start_sec, end_sec, power_kw):
        weighted_kwh_before = self.process_weighted_energy_kwh
        self.process_weighted_energy_kwh += weighted_energy_kwh(
            start_sec, end_sec, power_kw, self.electricity_time_band_weights)
        return self.process_weighted_energy_kwh - weighted_kwh_before

    def accumulate_process_weighted_energy_of_worker_group(self, worker_group, weighted_kwh):
        weighted_kwh_by_worker_group = self.process_weighted_energy_kwh_by_worker_group
        weighted_kwh_before = weighted_kwh_by_worker_group.get(worker_group, 0.0)
        weighted_kwh_by_worker_group[worker_group] = weighted_kwh_before + weighted_kwh

    # ================================================ 활동량(전력) 누적: 설비 가동·정지 기록과 설비별 시간대 가중 전력량. 설비의 전력량은 그 구간에 설비를 쓰고 있던 MCF 레시피에 사용 수 비율로 나눠 레시피별 몫으로도 누적 ================================================
    def accumulate_machine_energy(self, machine_name):
        now_sec = self.simpy_environment.now
        use_count_by_worker_group = self.machine_use_count_by_worker_group[machine_name]
        if use_count_by_worker_group:
            weighted_kwh = weighted_energy_kwh(
                self.machine_energy_recorded_sec[machine_name], now_sec,
                self.machines[machine_name]['rated_power_kw'], self.electricity_time_band_weights)
            self.machine_weighted_energy_kwh[machine_name] += weighted_kwh
            total_use_count = sum(use_count_by_worker_group.values())
            weighted_kwh_by_worker_group = (
                self.machine_weighted_energy_kwh_by_worker_group[machine_name])
            for worker_group, use_count in use_count_by_worker_group.items():
                if worker_group is not None:
                    weighted_kwh_before = weighted_kwh_by_worker_group.get(worker_group, 0.0)
                    weighted_kwh_share = weighted_kwh * use_count / total_use_count
                    weighted_kwh_by_worker_group[worker_group] = (
                        weighted_kwh_before + weighted_kwh_share)
            self.accumulate_machine_energy_of_recipes(machine_name, weighted_kwh)
        self.machine_energy_recorded_sec[machine_name] = now_sec

    def accumulate_machine_energy_of_recipes(self, machine_name, weighted_kwh):
        use_count_by_recipe = self.machine_use_count_by_simulation_recipe_index[machine_name]
        total_use_count = sum(use_count_by_recipe.values())
        weighted_kwh_by_recipe = (
            self.machine_weighted_energy_kwh_by_simulation_recipe_index[machine_name])
        for simulation_recipe_index, use_count in use_count_by_recipe.items():
            weighted_kwh_before = weighted_kwh_by_recipe.get(simulation_recipe_index, 0.0)
            weighted_kwh_share = weighted_kwh * use_count / total_use_count
            weighted_kwh_by_recipe[simulation_recipe_index] = (
                weighted_kwh_before + weighted_kwh_share)

    def record_machine_start(self, machine_name, worker_group, simulation_recipe_index):
        self.accumulate_machine_energy(machine_name)
        use_count_by_worker_group = self.machine_use_count_by_worker_group[machine_name]
        if not use_count_by_worker_group:
            self.machine_on_off_records.append({
                'machine_name': machine_name,
                'event': MACHINE_ON_OFF_EVENTS['on'],
                'sec': float(self.simpy_environment.now),
            })
        use_count_before = use_count_by_worker_group.get(worker_group, 0)
        use_count_by_worker_group[worker_group] = use_count_before + 1
        use_count_by_recipe = self.machine_use_count_by_simulation_recipe_index[machine_name]
        recipe_use_count_before = use_count_by_recipe.get(simulation_recipe_index, 0)
        use_count_by_recipe[simulation_recipe_index] = recipe_use_count_before + 1

    def record_machine_stop(self, machine_name, worker_group, simulation_recipe_index):
        self.accumulate_machine_energy(machine_name)
        use_count_by_worker_group = self.machine_use_count_by_worker_group[machine_name]
        use_count_by_worker_group[worker_group] -= 1
        if use_count_by_worker_group[worker_group] == 0:
            del use_count_by_worker_group[worker_group]
        use_count_by_recipe = self.machine_use_count_by_simulation_recipe_index[machine_name]
        use_count_by_recipe[simulation_recipe_index] -= 1
        if use_count_by_recipe[simulation_recipe_index] == 0:
            del use_count_by_recipe[simulation_recipe_index]
        if not use_count_by_worker_group:
            self.machine_on_off_records.append({
                'machine_name': machine_name,
                'event': MACHINE_ON_OFF_EVENTS['off'],
                'sec': float(self.simpy_environment.now),
            })

    # ================================================ 집계: 지금까지의 시간대 가중 전력량(기저부하, 공정, 설비) ================================================
    def weighted_energy_kwh_of_operating_machine(self, machine_name, now_sec):
        if not self.machine_use_count_by_worker_group[machine_name]:
            return 0.0
        return weighted_energy_kwh(
            self.machine_energy_recorded_sec[machine_name], now_sec,
            self.machines[machine_name]['rated_power_kw'], self.electricity_time_band_weights)

    def base_load_weighted_energy_kwh(self):
        return base_load_weighted_energy_kwh_until(
            self.simpy_environment.now, self.WorkStartTime, self.WorkEndTime, self.base_load_kw,
            self.electricity_time_band_weights)

    def total_weighted_energy_kwh(self):
        machine_weighted_kwh = sum(self.machine_weighted_energy_kwh.values())
        base_load_weighted_kwh = self.base_load_weighted_energy_kwh()
        return base_load_weighted_kwh + self.process_weighted_energy_kwh + machine_weighted_kwh

    def cumulative_weighted_energy_kwh(self):
        now_sec = float(self.simpy_environment.now)
        machine_weighted_kwh = sum(self.machine_weighted_energy_kwh.values())
        for machine_name in self.machine_use_count_by_worker_group:
            if self.machine_use_count_by_worker_group[machine_name]:
                machine_weighted_kwh += self.weighted_energy_kwh_of_operating_machine(
                    machine_name, now_sec)
        base_load_weighted_kwh = self.base_load_weighted_energy_kwh()
        process_weighted_kwh = self.process_power_integral.weighted_energy_kwh_until(now_sec)
        return base_load_weighted_kwh + process_weighted_kwh + machine_weighted_kwh

    def machines_weighted_energy_kwh(self, machine_names):
        now_sec = float(self.simpy_environment.now)
        recorded_weighted_kwh = []
        for machine_name in machine_names:
            recorded_weighted_kwh.append(self.machine_weighted_energy_kwh[machine_name])
        weighted_kwh = sum(recorded_weighted_kwh)
        for machine_name in machine_names:
            if self.machine_use_count_by_worker_group[machine_name]:
                weighted_kwh += self.weighted_energy_kwh_of_operating_machine(
                    machine_name, now_sec)
        return float(weighted_kwh)

    # ================================================ 집계: 지정 시각까지의 전력량을 공정·설비·기저부하별과 합계로 계산 ================================================
    def aggregate_process_energy(self, until_sec):
        process_energy = zero_energy()
        energy_by_process = {}
        for process_power_record in self.process_power_records:
            record_end_sec = process_power_record['end_sec']
            if record_end_sec is None:
                record_end_sec = float(self.simpy_environment.now)
            energy = energy_by_time_band(
                process_power_record['start_sec'], min(until_sec, record_end_sec),
                process_power_record['power_kw'], self.electricity_time_band_weights)
            add_energy(process_energy, energy)
            process_code = process_power_record['process_code']
            if process_code not in energy_by_process:
                energy_by_process[process_code] = zero_energy()
            add_energy(energy_by_process[process_code], energy)
        return {'process_energy': process_energy, 'energy_by_process': energy_by_process}

    def list_machine_operating_periods(self, until_sec):
        operating_periods_by_machine = {}
        operating_start_sec_by_machine = {}
        for machine_on_off_record in self.machine_on_off_records:
            machine_name = machine_on_off_record['machine_name']
            if machine_on_off_record['sec'] > until_sec:
                break
            if machine_on_off_record['event'] == MACHINE_ON_OFF_EVENTS['on']:
                operating_start_sec_by_machine[machine_name] = machine_on_off_record['sec']
                continue
            if machine_name not in operating_periods_by_machine:
                operating_periods_by_machine[machine_name] = []
            operating_periods_by_machine[machine_name].append({
                'start_sec': operating_start_sec_by_machine.pop(machine_name),
                'end_sec': machine_on_off_record['sec'],
            })
        for machine_name, operating_start_sec in operating_start_sec_by_machine.items():
            if machine_name not in operating_periods_by_machine:
                operating_periods_by_machine[machine_name] = []
            operating_periods_by_machine[machine_name].append({
                'start_sec': operating_start_sec,
                'end_sec': until_sec,
            })
        return operating_periods_by_machine

    def aggregate_machine_energy(self, until_sec):
        machine_energy = zero_energy()
        energy_by_machine = {}
        operating_periods_by_machine = self.list_machine_operating_periods(until_sec)
        for machine_name, operating_periods in operating_periods_by_machine.items():
            energy_of_machine = zero_energy()
            for operating_period in operating_periods:
                energy = energy_by_time_band(
                    operating_period['start_sec'], min(until_sec, operating_period['end_sec']),
                    self.machines[machine_name]['rated_power_kw'],
                    self.electricity_time_band_weights)
                add_energy(energy_of_machine, energy)
            energy_by_machine[machine_name] = energy_of_machine
            add_energy(machine_energy, energy_of_machine)
        return {'machine_energy': machine_energy, 'energy_by_machine': energy_by_machine}

    def aggregate_base_load_energy(self, until_sec):
        base_load_energy = zero_energy()
        last_day = int(until_sec // SECONDS_PER_DAY)
        for day in range(last_day + 1):
            work_start_sec = day * SECONDS_PER_DAY + self.WorkStartTime
            work_end_sec = min(day * SECONDS_PER_DAY + self.WorkEndTime, until_sec)
            energy = energy_by_time_band(
                work_start_sec, work_end_sec, self.base_load_kw,
                self.electricity_time_band_weights)
            add_energy(base_load_energy, energy)
        return base_load_energy

    def list_smt_machine_names(self):
        smt_machine_names = set()
        for step_process_codes in self.step_process_codes_by_smt_line.values():
            for step_process_code in step_process_codes:
                step_process = self.simulation_processes.processes[step_process_code]
                smt_machine_names.update(step_process.machine_unit_codes)
        return sorted(smt_machine_names)

    def aggregate_energy(self, until_sec):
        aggregated_process_energy = self.aggregate_process_energy(until_sec)
        aggregated_machine_energy = self.aggregate_machine_energy(until_sec)
        base_load_energy = self.aggregate_base_load_energy(until_sec)
        energy_by_machine = aggregated_machine_energy['energy_by_machine']
        total_energy = zero_energy()
        add_energy(total_energy, aggregated_process_energy['process_energy'])
        add_energy(total_energy, aggregated_machine_energy['machine_energy'])
        add_energy(total_energy, base_load_energy)
        smt_machine_kwh = []
        smt_machine_peak_kwh = []
        for machine_name in self.list_smt_machine_names():
            if machine_name in energy_by_machine:
                smt_machine_kwh.append(energy_by_machine[machine_name]['kwh'])
                smt_machine_peak_kwh.append(energy_by_machine[machine_name]['peak_kwh'])
            else:
                smt_machine_kwh.append(0.0)
                smt_machine_peak_kwh.append(0.0)
        return {
            'physical_kwh': total_energy['kwh'],
            'weighted_kwh': total_energy['weighted_kwh'],
            'peak_kwh': total_energy['peak_kwh'],
            'energy_by_process': aggregated_process_energy['energy_by_process'],
            'energy_by_machine': energy_by_machine,
            'base_load_energy': base_load_energy,
            'smt_physical_kwh': sum(smt_machine_kwh),
            'smt_peak_kwh': sum(smt_machine_peak_kwh),
        }

    # ================================================ 공정이 속한 라인(API가 공정별·라인별 전력 배출량을 묶는 단위): 작업자 그룹이 있으면 그 그룹, 없으면 그 공정이 단계로 든 SMT 라인 ================================================
    def mcf_line_of_process(self, process_code):
        worker_group = self.worker_group_of(process_code)
        if worker_group is not None:
            return worker_group
        product_code = self.simulation_processes.processes[process_code].product_code
        if product_code in self.smt_production_plan:
            return product_code
        return None

    def list_process_codes_by_mcf_line(self):
        process_codes_by_mcf_line = {}
        for process_code in self.simulation_processes.processes:
            mcf_line = self.mcf_line_of_process(process_code)
            if mcf_line is None:
                continue
            if mcf_line not in process_codes_by_mcf_line:
                process_codes_by_mcf_line[mcf_line] = []
            process_codes_by_mcf_line[mcf_line].append(process_code)
        return process_codes_by_mcf_line

    # ================================================ MCF 레시피별 기록 만들기: Simulation 레시피마다 산출 수량·공정 전력량(kW × 시간, 시간대 가중)·앞 레시피 산출물 사용 수량, 공정마다 그 공정의 Simulation 레시피(공정의 AAS ProcessCode로 찾음), 설비마다 레시피별 사용 수와 전력량 몫, 제품 단위마다의 중간재 기록 ================================================
    def reset_mcf_recipe_records(self):
        recipes_by_simulation_recipe_index = (
            self.mcf_recipe_structure['recipes_by_simulation_recipe_index'])
        self.mcf_recipe_records = {}
        for simulation_recipe_index in recipes_by_simulation_recipe_index:
            self.mcf_recipe_records[simulation_recipe_index] = {
                'OutputItemQuantity': 0,
                'process_weighted_energy_kwh': 0.0,
                'used_quantity_by_source_simulation_recipe_index': {},
            }
        self.simulation_recipe_indexes_by_process_code = {}
        self.process_code_by_simulation_recipe_index = {}
        for process_code, process in self.simulation_processes.processes.items():
            ProcessCode = code_from_kg_node_path(process.process_sme_path)
            simulation_recipe_indexes = []
            for simulation_recipe_index, recipe in recipes_by_simulation_recipe_index.items():
                if recipe['ProcessCode'] == ProcessCode:
                    simulation_recipe_indexes.append(simulation_recipe_index)
                    self.process_code_by_simulation_recipe_index[simulation_recipe_index] = (
                        process_code)
            self.simulation_recipe_indexes_by_process_code[process_code] = (
                simulation_recipe_indexes)
        self.simulation_recipe_indexes_by_OutputItemCode = (
            list_simulation_recipe_indexes_by_OutputItemCode(recipes_by_simulation_recipe_index))
        self.mcf_recipe_calculation_order = order_recipes_by_input_item_flow(
            recipes_by_simulation_recipe_index, self.simulation_recipe_indexes_by_OutputItemCode)
        self.last_OutputItemCodes_by_simulation_recipe_index = (
            list_last_OutputItemCodes_by_simulation_recipe_index(
                recipes_by_simulation_recipe_index, self.mcf_recipe_calculation_order))
        self.machine_use_count_by_simulation_recipe_index = {}
        self.machine_weighted_energy_kwh_by_simulation_recipe_index = {}
        for machine_name in self.machines:
            self.machine_use_count_by_simulation_recipe_index[machine_name] = {}
            self.machine_weighted_energy_kwh_by_simulation_recipe_index[machine_name] = {}
        self.material_record_by_unit = {}

    # ================================================ 제품 단위(제품 한 대, SMT 라인은 어레이 1장)의 마지막 산출 품목과 공정 1회의 산출 수량: 제품은 그 제품 코드와 1, SMT 라인의 어레이는 그 라인이 생산 중인 PCB 품목 코드와 어레이 1장의 PCB 수량 ================================================
    def last_output_item_code_of_unit(self, unit_id):
        if unit_id not in self.product_by_unit:
            return None
        product = self.product_by_unit[unit_id]
        if product in self.pcb_array_in_production_by_smt_line:
            return self.pcb_array_in_production_by_smt_line[product]['pcb_item_code']
        return product

    def output_item_quantity_of_unit(self, unit_id):
        if unit_id in self.product_by_unit:
            product = self.product_by_unit[unit_id]
            if product in self.pcb_array_in_production_by_smt_line:
                return self.pcb_array_in_production_by_smt_line[product]['pcb_count_per_array']
        return OUTPUT_ITEM_QUANTITY_OF_PRODUCT_UNIT

    # ================================================ 제품 단위마다의 중간재 기록: 만들어 두고 아직 다음 공정에 쓰지 않은 산출물 수량, 샘플링으로 실행하기로 한 공정이 맡아 둔 투입 중간재, 실행하기로 했지만 아직 끝나지 않은 레시피, 그 레시피의 산출물을 기다리는 다음 레시피 ================================================
    def material_record_of_unit(self, unit_id):
        if unit_id not in self.material_record_by_unit:
            self.material_record_by_unit[unit_id] = {
                'unused_output_quantity': {},
                'reserved_recipe_execution_by_process_code': {},
                'expected_simulation_recipe_indexes': [],
                'waiting_simulation_recipe_index_by_source': {},
            }
        return self.material_record_by_unit[unit_id]

    # ================================================ 실행된 레시피 고르기 규칙(레시피가 여럿인 공정): ① 그 제품 단위가 만들어 두고 아직 다음 공정에 쓰지 않은 앞 레시피 산출물, 또는 실행하기로 한 앞 레시피의 산출물을 투입으로 가장 많이 가진 레시피(샘플링 검사를 하게 됐으면 검사 산출물을 받는 레시피, 건너뛰었으면 앞 공정 산출물을 받는 레시피) ② 그런 레시피가 여럿이면 마지막 산출 품목이 그 제품 단위의 것과 같은 레시피(공용 공정의 제품별 레시피, SMT 라인의 PCB 품목별 레시피) ③ 그래도 정해지지 않으면 첫 레시피 ================================================
    def held_input_item_count(self, simulation_recipe_index, material_record):
        recipe = self.mcf_recipe_structure['recipes_by_simulation_recipe_index'][
            simulation_recipe_index]
        unused_output_quantity = material_record['unused_output_quantity']
        expected_simulation_recipe_indexes = material_record['expected_simulation_recipe_indexes']
        held_input_item_count = 0
        for input_item in recipe['input_items']:
            source_simulation_recipe_index = input_item['source_simulation_recipe_index']
            is_unused = source_simulation_recipe_index in unused_output_quantity
            is_expected = source_simulation_recipe_index in expected_simulation_recipe_indexes
            if is_unused or is_expected:
                held_input_item_count += 1
        return held_input_item_count

    def executed_simulation_recipe_index(self, process_code, unit_id):
        simulation_recipe_indexes = self.simulation_recipe_indexes_by_process_code[process_code]
        material_record = self.material_record_of_unit(unit_id)
        held_input_item_counts = {}
        for simulation_recipe_index in simulation_recipe_indexes:
            held_input_item_counts[simulation_recipe_index] = self.held_input_item_count(
                simulation_recipe_index, material_record)
        most_held_input_item_count = max(held_input_item_counts.values())
        recipes_with_most_held_input_items = []
        for simulation_recipe_index in simulation_recipe_indexes:
            if held_input_item_counts[simulation_recipe_index] == most_held_input_item_count:
                recipes_with_most_held_input_items.append(simulation_recipe_index)
        last_output_item_code = self.last_output_item_code_of_unit(unit_id)
        for simulation_recipe_index in recipes_with_most_held_input_items:
            last_OutputItemCodes = (
                self.last_OutputItemCodes_by_simulation_recipe_index[simulation_recipe_index])
            if last_output_item_code in last_OutputItemCodes:
                return simulation_recipe_index
        first_recipe = recipes_with_most_held_input_items[0]
        return first_recipe

    # ================================================ 샘플링으로 실행하기로 한 공정(BranchProbability가 있는 공정)의 규칙: 이 공정은 다음 공정과 동시에 진행되므로, 실행하기로 정해진 순간 레시피를 고르고 그 레시피의 투입 중간재를 맡아 둠. 그래서 다음 공정은 앞 공정 산출물이 아니라 이 레시피의 산출물을 받는 레시피로 골라짐 ================================================
    def reserve_recipe_execution_of_sampled_process(self, process, completed_process_codes):
        unit_id = id(completed_process_codes)
        material_record = self.material_record_of_unit(unit_id)
        simulation_recipe_index = self.executed_simulation_recipe_index(
            process.process_code, unit_id)
        recipe = self.mcf_recipe_structure['recipes_by_simulation_recipe_index'][
            simulation_recipe_index]
        unused_output_quantity = material_record['unused_output_quantity']
        reserved_quantity_by_source = {}
        for input_item in recipe['input_items']:
            source_simulation_recipe_index = input_item['source_simulation_recipe_index']
            if source_simulation_recipe_index in unused_output_quantity:
                reserved_quantity_by_source[source_simulation_recipe_index] = (
                    unused_output_quantity.pop(source_simulation_recipe_index))
        material_record['reserved_recipe_execution_by_process_code'][process.process_code] = {
            'simulation_recipe_index': simulation_recipe_index,
            'reserved_quantity_by_source': reserved_quantity_by_source,
        }
        material_record['expected_simulation_recipe_indexes'].append(simulation_recipe_index)

    # ================================================ MCF 레시피 실행 기록: 공정 처리를 시작할 때 실행된 레시피와 산출 수량을 정하고(맡아 둔 레시피가 있으면 그 레시피), 공정이 끝나면 그 레시피에 산출 수량과 공정 전력량을 더함. 그 제품 단위가 갖고 있던(또는 맡아 둔) 앞 레시피 산출물은 이 레시피가 쓴 것으로 세고, 앞 레시피가 아직 끝나지 않았으면 그 산출물을 기다린다고 적음. 이 레시피의 산출물은 기다리는 다음 레시피가 있으면 그 레시피가 쓴 것으로 세고, 없으면 그 제품 단위가 갖고 있는 것으로 적음 ================================================
    def start_recipe_execution(self, process, completed_process_codes):
        unit_id = id(completed_process_codes)
        material_record = self.material_record_of_unit(unit_id)
        reserved_recipe_executions = material_record['reserved_recipe_execution_by_process_code']
        if process.process_code in reserved_recipe_executions:
            reserved_recipe_execution = reserved_recipe_executions.pop(process.process_code)
            simulation_recipe_index = reserved_recipe_execution['simulation_recipe_index']
            reserved_quantity_by_source = reserved_recipe_execution['reserved_quantity_by_source']
        else:
            simulation_recipe_index = self.executed_simulation_recipe_index(
                process.process_code, unit_id)
            reserved_quantity_by_source = {}
        return {
            'simulation_recipe_index': simulation_recipe_index,
            'unit_id': unit_id,
            'output_item_quantity': self.output_item_quantity_of_unit(unit_id),
            'reserved_quantity_by_source': reserved_quantity_by_source,
        }

    def add_used_quantity(self, simulation_recipe_index, source_simulation_recipe_index, quantity):
        recipe_record = self.mcf_recipe_records[simulation_recipe_index]
        used_quantity_by_source = recipe_record['used_quantity_by_source_simulation_recipe_index']
        used_quantity_before = used_quantity_by_source.get(source_simulation_recipe_index, 0)
        used_quantity_by_source[source_simulation_recipe_index] = used_quantity_before + quantity

    def record_recipe_execution(self, recipe_execution, process_weighted_kwh):
        simulation_recipe_index = recipe_execution['simulation_recipe_index']
        output_item_quantity = recipe_execution['output_item_quantity']
        reserved_quantity_by_source = recipe_execution['reserved_quantity_by_source']
        recipe = self.mcf_recipe_structure['recipes_by_simulation_recipe_index'][
            simulation_recipe_index]
        recipe_record = self.mcf_recipe_records[simulation_recipe_index]
        recipe_record['OutputItemQuantity'] += output_item_quantity
        recipe_record['process_weighted_energy_kwh'] += process_weighted_kwh
        material_record = self.material_record_of_unit(recipe_execution['unit_id'])
        unused_output_quantity = material_record['unused_output_quantity']
        expected_simulation_recipe_indexes = material_record['expected_simulation_recipe_indexes']
        waiting_by_source = material_record['waiting_simulation_recipe_index_by_source']
        for input_item in recipe['input_items']:
            source_simulation_recipe_index = input_item['source_simulation_recipe_index']
            if source_simulation_recipe_index in reserved_quantity_by_source:
                self.add_used_quantity(
                    simulation_recipe_index, source_simulation_recipe_index,
                    reserved_quantity_by_source[source_simulation_recipe_index])
            elif source_simulation_recipe_index in unused_output_quantity:
                self.add_used_quantity(
                    simulation_recipe_index, source_simulation_recipe_index,
                    unused_output_quantity.pop(source_simulation_recipe_index))
            elif source_simulation_recipe_index in expected_simulation_recipe_indexes:
                waiting_by_source[source_simulation_recipe_index] = simulation_recipe_index
        if simulation_recipe_index in expected_simulation_recipe_indexes:
            expected_simulation_recipe_indexes.remove(simulation_recipe_index)
        if simulation_recipe_index in waiting_by_source:
            waiting_simulation_recipe_index = waiting_by_source.pop(simulation_recipe_index)
            self.add_used_quantity(
                waiting_simulation_recipe_index, simulation_recipe_index, output_item_quantity)
        else:
            unused_quantity_before = unused_output_quantity.get(simulation_recipe_index, 0)
            unused_output_quantity[simulation_recipe_index] = (
                unused_quantity_before + output_item_quantity)

    # ================================================ MCF 탄소배출량 계산: MCF마다의 활동량. 기저부하 MCF 규칙은 Recipes가 없는 MCF이고 Amount는 기저부하의 시간대 가중 전력량. 설비 MCF의 Amount는 그 설비(ResourceName)의 시간대 가중 전력량이고 레시피별 전력량은 그 설비가 그 레시피를 처리한 몫. 작업자 그룹 MCF의 레시피별 전력량은 그 레시피 공정의 kW × 시간(시간대 가중)이고 Amount는 그 합. Amount는 시뮬레이션이 내는 전력량 그대로 ================================================
    def is_base_load_mcf(self, mcf_resource):
        return not mcf_resource['simulation_recipe_indexes']

    # ================================================ MCF 탄소배출량 계산: MCF마다의 OperatingTime(가동 시간, 겹친 시간은 한 번만 셈). 설비 MCF는 그 설비가 켜져 있던 시간, 작업자 그룹 MCF는 그 그룹의 공정이 하나라도 진행 중이던 시간, 기저부하 MCF는 근무 시작부터 종료까지 ================================================
    def operating_time_sec_by_machine(self):
        now_sec = float(self.simpy_environment.now)
        operating_time_sec_by_machine = {}
        operating_periods_by_machine = self.list_machine_operating_periods(now_sec)
        for machine_name, operating_periods in operating_periods_by_machine.items():
            operating_time_sec = 0.0
            for operating_period in operating_periods:
                operating_time_sec += operating_period['end_sec'] - operating_period['start_sec']
            operating_time_sec_by_machine[machine_name] = operating_time_sec
        return operating_time_sec_by_machine

    def worker_group_mcf_ResourceName_by_process_code(self):
        ResourceName_by_process_code = {}
        for mcf_resource in self.mcf_recipe_structure['mcf_resources']:
            if mcf_resource['ResourceType'] != MCF_RESOURCE_TYPES['worker']:
                continue
            for simulation_recipe_index in mcf_resource['simulation_recipe_indexes']:
                process_code = self.process_code_by_simulation_recipe_index[simulation_recipe_index]
                ResourceName_by_process_code[process_code] = mcf_resource['ResourceName']
        return ResourceName_by_process_code

    def operating_time_sec_by_worker_group_mcf(self):
        now_sec = float(self.simpy_environment.now)
        ResourceName_by_process_code = self.worker_group_mcf_ResourceName_by_process_code()
        operating_time_sec_by_ResourceName = {}
        operating_period_by_ResourceName = {}
        for process_power_record in self.process_power_records:
            process_code = process_power_record['process_code']
            if process_code not in ResourceName_by_process_code:
                continue
            ResourceName = ResourceName_by_process_code[process_code]
            start_sec = process_power_record['start_sec']
            end_sec = process_power_record['end_sec']
            if end_sec is None:
                end_sec = now_sec
            if ResourceName not in operating_period_by_ResourceName:
                operating_time_sec_by_ResourceName[ResourceName] = 0.0
                operating_period_by_ResourceName[ResourceName] = {
                    'start_sec': start_sec, 'end_sec': end_sec}
                continue
            operating_period = operating_period_by_ResourceName[ResourceName]
            if start_sec > operating_period['end_sec']:
                operating_time_sec_by_ResourceName[ResourceName] += (
                    operating_period['end_sec'] - operating_period['start_sec'])
                operating_period['start_sec'] = start_sec
                operating_period['end_sec'] = end_sec
            else:
                operating_period['end_sec'] = max(operating_period['end_sec'], end_sec)
        for ResourceName, operating_period in operating_period_by_ResourceName.items():
            operating_time_sec_by_ResourceName[ResourceName] += (
                operating_period['end_sec'] - operating_period['start_sec'])
        return operating_time_sec_by_ResourceName

    def operating_time_hours_by_mcf(self):
        operating_time_sec_by_machine = self.operating_time_sec_by_machine()
        operating_time_sec_by_worker_group_mcf = self.operating_time_sec_by_worker_group_mcf()
        operating_time_hours_by_ResourceName = {}
        for mcf_resource in self.mcf_recipe_structure['mcf_resources']:
            ResourceName = mcf_resource['ResourceName']
            if self.is_base_load_mcf(mcf_resource):
                operating_time_sec = base_load_operating_time_sec_until(
                    self.simpy_environment.now, self.WorkStartTime, self.WorkEndTime)
            elif mcf_resource['ResourceType'] == MCF_RESOURCE_TYPES['machine']:
                operating_time_sec = operating_time_sec_by_machine.get(ResourceName, 0.0)
            else:
                operating_time_sec = operating_time_sec_by_worker_group_mcf.get(ResourceName, 0.0)
            operating_time_hours_by_ResourceName[ResourceName] = (
                operating_time_sec / float(SECONDS_PER_HOUR))
        return operating_time_hours_by_ResourceName

    # ================================================ MCF 탄소배출량 계산: MCF마다의 활동량 모으기(OperatingTime, Amount, 레시피별 전력량) ================================================
    def activity_data_of_mcf(self, mcf_resource, OperatingTime):
        ResourceName = mcf_resource['ResourceName']
        is_machine_mcf = mcf_resource['ResourceType'] == MCF_RESOURCE_TYPES['machine']
        electricity_amount_kwh_by_simulation_recipe_index = {}
        for simulation_recipe_index in mcf_resource['simulation_recipe_indexes']:
            if is_machine_mcf:
                weighted_kwh_by_recipe = (
                    self.machine_weighted_energy_kwh_by_simulation_recipe_index[ResourceName])
                electricity_amount_kwh = weighted_kwh_by_recipe.get(simulation_recipe_index, 0.0)
            else:
                recipe_record = self.mcf_recipe_records[simulation_recipe_index]
                electricity_amount_kwh = recipe_record['process_weighted_energy_kwh']
            electricity_amount_kwh_by_simulation_recipe_index[simulation_recipe_index] = (
                electricity_amount_kwh)
        if self.is_base_load_mcf(mcf_resource):
            Amount = self.base_load_weighted_energy_kwh()
        elif is_machine_mcf:
            Amount = self.machine_weighted_energy_kwh[ResourceName]
        else:
            Amount = sum(electricity_amount_kwh_by_simulation_recipe_index.values())
        return {
            'is_base_load_mcf': self.is_base_load_mcf(mcf_resource),
            'OperatingTime': OperatingTime,
            'Amount': Amount,
            'electricity_amount_kwh_by_simulation_recipe_index': (
                electricity_amount_kwh_by_simulation_recipe_index),
        }

    def mcf_carbon_emissions(self):
        activity_data_by_ResourceName = {}
        operating_time_hours_by_ResourceName = self.operating_time_hours_by_mcf()
        for mcf_resource in self.mcf_recipe_structure['mcf_resources']:
            ResourceName = mcf_resource['ResourceName']
            activity_data_by_ResourceName[ResourceName] = self.activity_data_of_mcf(
                mcf_resource, operating_time_hours_by_ResourceName[ResourceName])
        return calculate_mcf_carbon_emissions(
            self.mcf_recipe_structure, activity_data_by_ResourceName, self.mcf_recipe_records,
            self.mcf_recipe_calculation_order, self.simulation_recipe_indexes_by_OutputItemCode)


# ================================================ 집계: 공정별·설비별 전력량을 SMT 라인, 조립 라인, 기저부하로 나눠 전력량·피크타임·평시·시간대 가중 4항목씩 계산 ================================================
def energy_by_line_type(energy_account, smt_process_codes, smt_machine_names):
    smt_energy = zero_energy()
    assembly_energy = zero_energy()
    energy_by_process_kwh = {}
    for process_code, energy in energy_account['energy_by_process'].items():
        if process_code in smt_process_codes:
            add_energy(smt_energy, energy)
        else:
            add_energy(assembly_energy, energy)
        energy_by_process_kwh[process_code] = round(float(energy['kwh']), ENERGY_DECIMAL_PLACES)
    energy_by_machine_kwh = {}
    for machine_name, energy in energy_account['energy_by_machine'].items():
        if machine_name in smt_machine_names:
            add_energy(smt_energy, energy)
        else:
            add_energy(assembly_energy, energy)
        energy_by_machine_kwh[machine_name] = round(float(energy['kwh']), ENERGY_DECIMAL_PLACES)
    energy_by_line_type_name = {
        'smt': smt_energy,
        'assembly': assembly_energy,
        'base_load': dict(energy_account['base_load_energy']),
    }
    result = {}
    for line_type_name, energy in energy_by_line_type_name.items():
        result[f'{line_type_name}_kwh'] = energy['kwh']
        result[f'{line_type_name}_peak_kwh'] = energy['peak_kwh']
        result[f'{line_type_name}_normal_kwh'] = energy['kwh'] - energy['peak_kwh']
        result[f'{line_type_name}_weighted_kwh'] = energy['weighted_kwh']
    result['energy_by_process_kwh'] = energy_by_process_kwh
    result['energy_by_machine_kwh'] = energy_by_machine_kwh
    return result
