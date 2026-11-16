from json import load
from pathlib import Path
from shutil import copyfile
from time import time

from aas_preprocessing.aas_reader import (
    AAS_FILE_NAME_PATTERN, ALL_SUBFOLDERS_PATTERN, SCENARIO_CONFIG_FILE)
from api import api_jobs


# ================================================ AAS JSON 파일에서 읽는 키: Submodel 목록, Submodel의 id, 요소의 idShort와 값, Submodel 바로 아래 요소 목록 ================================================
AAS_JSON_KEYS = {
    'submodels': 'submodels',
    'submodel_id': 'id',
    'idShort': 'idShort',
    'value': 'value',
    'submodel_elements': 'submodelElements',
}


# ================================================ MCF 인스턴스 기록: 실행 작업 폴더에 둔 MCF 인스턴스 사본에 계산된 MCF 탄소배출량을 적음. aas_data의 원본은 고치지 않음. 실행을 시작할 때 그 시나리오의 AAS 파일 가운데 MCF Submodel이 든 파일을 실행 작업 폴더로 복사하고, 발행 때마다 값을 적어 파일을 새로 씀 ================================================
class McfInstanceRecord:

    def __init__(self, job_directory, aas_directory, mcf_recipe_structure):
        self.instance_directory = (
            Path(job_directory) / api_jobs.JOB_FILE_NAMES['mcf_instance_folder'])
        self.aas_file_json_by_file_path = {}
        self.value_elements_by_ResourceName = {}
        self.record_count = 0
        self.record_wall_sec = 0.0
        self.copy_aas_files_with_mcf_submodel(
            Path(aas_directory), mcf_recipe_structure['mcf_resources'])

    # ================================================ MCF 인스턴스 복사: 시나리오 AAS 폴더의 AAS 파일마다 MCF 레시피 구조의 MCF Submodel(id가 같은 것)이 들어 있으면 폴더 구조 그대로 실행 작업 폴더에 복사하고, 그 Submodel에서 계산값을 적는 요소를 찾아 둠 ================================================
    def copy_aas_files_with_mcf_submodel(self, aas_directory, mcf_resources):
        mcf_resource_by_submodel_id = {}
        for mcf_resource in mcf_resources:
            submodel_id = mcf_resource['value_element_positions']['submodel_id']
            mcf_resource_by_submodel_id[submodel_id] = mcf_resource
        aas_file_path_pattern = f'{ALL_SUBFOLDERS_PATTERN}/{AAS_FILE_NAME_PATTERN}'
        for aas_file_path in sorted(aas_directory.glob(aas_file_path_pattern)):
            if aas_file_path.name == SCENARIO_CONFIG_FILE:
                continue
            with open(aas_file_path, encoding='utf-8') as aas_file:
                aas_file_json = load(aas_file)
            has_mcf_submodel = False
            for submodel_json in aas_file_json.get(AAS_JSON_KEYS['submodels'], []):
                submodel_id = submodel_json[AAS_JSON_KEYS['submodel_id']]
                if submodel_id in mcf_resource_by_submodel_id:
                    has_mcf_submodel = True
                    mcf_resource = mcf_resource_by_submodel_id[submodel_id]
                    self.value_elements_by_ResourceName[mcf_resource['ResourceName']] = (
                        find_value_elements(
                            submodel_json, mcf_resource['value_element_positions']))
            if has_mcf_submodel:
                copied_file_path = (
                    self.instance_directory / aas_file_path.relative_to(aas_directory))
                copied_file_path.parent.mkdir(parents=True, exist_ok=True)
                copyfile(aas_file_path, copied_file_path)
                self.aas_file_json_by_file_path[copied_file_path] = aas_file_json

    # ================================================ 기록: MCF마다 기록 규칙대로 값을 적고 복사한 파일을 모두 새로 씀. 기록한 횟수와 걸린 실제 시간을 더해 둠 ================================================
    def record(self, mcf_carbon_emissions):
        record_start_wall_sec = time()
        for mcf_carbon_emission in mcf_carbon_emissions:
            value_elements = self.value_elements_by_ResourceName[
                mcf_carbon_emission['ResourceName']]
            record_OperatingTime(value_elements, mcf_carbon_emission)
            record_Amount(value_elements, mcf_carbon_emission)
            record_ContributionCO2eq_of_electricity(value_elements, mcf_carbon_emission)
            record_ContributionCO2eq_of_input_items(value_elements, mcf_carbon_emission)
            record_SumCO2eq(value_elements, mcf_carbon_emission)
            record_AllocatedFactor_and_AllocatedCO2eq(value_elements, mcf_carbon_emission)
        for file_path, aas_file_json in self.aas_file_json_by_file_path.items():
            api_jobs.write_json_file(file_path, aas_file_json)
        self.record_count += 1
        self.record_wall_sec += time() - record_start_wall_sec


# ================================================ 계산값을 적는 요소 찾기: MCF 레시피 구조가 알려 준 위치(Submodel에서 요소까지의 경로. idShort, 목록 항목은 순번)를 따라가 AAS JSON의 요소를 찾음. 위치가 없는 값(전력 항목이 없는 MCF의 Amount 등)은 요소도 없음 ================================================
def sub_element_json_at(submodel_json, sme_path):
    if sme_path is None:
        return None
    element_json = submodel_json
    child_element_jsons = submodel_json[AAS_JSON_KEYS['submodel_elements']]
    for sme_path_part in sme_path:
        if isinstance(sme_path_part, int):
            element_json = child_element_jsons[sme_path_part]
        else:
            for child_element_json in child_element_jsons:
                if child_element_json[AAS_JSON_KEYS['idShort']] == sme_path_part:
                    element_json = child_element_json
        child_element_jsons = element_json.get(AAS_JSON_KEYS['value'])
    return element_json


def find_value_elements(mcf_submodel_json, value_element_positions):
    Allocation = []
    for allocation_position in value_element_positions['Allocation']:
        Allocation.append({
            'simulation_recipe_index': allocation_position['simulation_recipe_index'],
            'AllocatedFactor': sub_element_json_at(
                mcf_submodel_json, allocation_position['AllocatedFactor']),
            'AllocatedCO2eq': sub_element_json_at(
                mcf_submodel_json, allocation_position['AllocatedCO2eq']),
        })
    InputMaterialEmissions = []
    for input_material_emission_position in value_element_positions['InputMaterialEmissions']:
        InputMaterialEmissions.append({
            'simulation_recipe_indexes': (
                input_material_emission_position['simulation_recipe_indexes']),
            'input_item_index': input_material_emission_position['input_item_index'],
            'ContributionCO2eq': sub_element_json_at(
                mcf_submodel_json, input_material_emission_position['ContributionCO2eq']),
        })
    return {
        'OperatingTime': sub_element_json_at(
            mcf_submodel_json, value_element_positions['OperatingTime']),
        'Amount': sub_element_json_at(mcf_submodel_json, value_element_positions['Amount']),
        'ContributionCO2eq_of_electricity': sub_element_json_at(
            mcf_submodel_json, value_element_positions['ContributionCO2eq_of_electricity']),
        'SumCO2eq': sub_element_json_at(mcf_submodel_json, value_element_positions['SumCO2eq']),
        'Allocation': Allocation,
        'InputMaterialEmissions': InputMaterialEmissions,
    }


# ================================================ 값 적기: 템플릿의 자료형(xs:float)대로 실수를 글자로 적음. 적을 요소가 없으면 적지 않음 ================================================
def write_float_value(element_json, float_value):
    if element_json is None:
        return
    element_json[AAS_JSON_KEYS['value']] = repr(float(float_value))


# ================================================ 기록 규칙 ① ManufacturingProcess.OperatingTime: 그 MCF의 가동 시간(시간, 겹친 시간은 한 번만 셈. 설비 MCF는 설비가 켜져 있던 시간, 작업자 그룹 MCF는 그 그룹의 공정이 하나라도 진행 중이던 시간, 기저부하 MCF는 근무 시작부터 종료까지) ================================================
def record_OperatingTime(value_elements, mcf_carbon_emission):
    write_float_value(value_elements['OperatingTime'], mcf_carbon_emission['OperatingTime'])


# ================================================ 기록 규칙 ② AncillaryInputs.Electricity 첫 항목의 Amount: 그 MCF의 시간대 가중 전력량(kWh) ================================================
def record_Amount(value_elements, mcf_carbon_emission):
    write_float_value(value_elements['Amount'], mcf_carbon_emission['Amount'])


# ================================================ 기록 규칙 ③ MCFEmissions.ProcessEmissions.AncillaryInputEmissions에서 그 전력 항목을 가리키는 줄의 ContributionCO2eq: Amount × RefEmissionFactor(kgCO2eq) ================================================
def record_ContributionCO2eq_of_electricity(value_elements, mcf_carbon_emission):
    write_float_value(
        value_elements['ContributionCO2eq_of_electricity'],
        mcf_carbon_emission['ContributionCO2eq_of_electricity'])


# ================================================ 기록 규칙 ④ MCFEmissions.ProcessEmissions.InputMaterialEmissions 줄의 ContributionCO2eq: 그 줄이 가리키는 투입 항목(MCF 레시피의 InputItemCodeList 순번)의 계산값(사용 수량 × (1개의 누적 배출량 − 이 MCF에서 이미 세어진 몫)). 같은 MCF 안에서 만들어 넘긴 중간재는 인스턴스에 줄이 없어 적지 않음. 계산값이 없는 줄(배출계수 자료가 없는 창고 품목)은 빈 칸 그대로 ================================================
def record_ContributionCO2eq_of_input_items(value_elements, mcf_carbon_emission):
    allocation_by_simulation_recipe_index = {}
    for allocation in mcf_carbon_emission['Allocation']:
        allocation_by_simulation_recipe_index[allocation['simulation_recipe_index']] = allocation
    for input_material_emission_row in value_elements['InputMaterialEmissions']:
        ContributionCO2eq_values = []
        for simulation_recipe_index in input_material_emission_row['simulation_recipe_indexes']:
            allocation = allocation_by_simulation_recipe_index[simulation_recipe_index]
            input_material_emission = allocation['input_item_emissions'][
                input_material_emission_row['input_item_index']]
            if input_material_emission['ContributionCO2eq'] is not None:
                ContributionCO2eq_values.append(input_material_emission['ContributionCO2eq'])
        if ContributionCO2eq_values:
            write_float_value(
                input_material_emission_row['ContributionCO2eq'], sum(ContributionCO2eq_values))


# ================================================ 기록 규칙 ⑤ MCFEmissions.ProcessEmissions.SumCO2eq: 그 MCF에 남은 InputMaterialEmissions 줄의 ContributionCO2eq 합 + 전력 줄의 ContributionCO2eq ================================================
def record_SumCO2eq(value_elements, mcf_carbon_emission):
    write_float_value(value_elements['SumCO2eq'], mcf_carbon_emission['SumCO2eq'])


# ================================================ 기록 규칙 ⑥ MCFEmissions.Allocation 줄의 AllocatedFactor와 AllocatedCO2eq: 그 줄의 OutputItemCodeRef가 가리키는 Simulation 레시피의 계산값 ================================================
def record_AllocatedFactor_and_AllocatedCO2eq(value_elements, mcf_carbon_emission):
    allocation_by_simulation_recipe_index = {}
    for allocation in mcf_carbon_emission['Allocation']:
        allocation_by_simulation_recipe_index[allocation['simulation_recipe_index']] = allocation
    for allocation_row in value_elements['Allocation']:
        allocation = allocation_by_simulation_recipe_index[
            allocation_row['simulation_recipe_index']]
        write_float_value(allocation_row['AllocatedFactor'], allocation['AllocatedFactor'])
        write_float_value(allocation_row['AllocatedCO2eq'], allocation['AllocatedCO2eq'])
