import json
import os
from dataclasses import dataclass, field

from aas_preprocessing import aas_reader
from aas_preprocessing.process_rated_power import PROCESS_RATED_POWER_KW


# ================================================ AAS 템플릿 식별자: Simulation Submodel id, 제품 Submodel semanticId, MCF Submodel semanticId, 설비 정격전력 요소 semanticId ================================================
SIMULATION_SUBMODEL_ID = 'https://www.smart-factory.kr/ids/sm/Simulation/1/0'
PRODUCT_SUBMODEL_SEMANTIC_ID = 'https://admin-shell.io/idta/HierarchicalStructures/1/1/Submodel'
MCF_SUBMODEL_SEMANTIC_ID = 'https://www.smart-factory.kr/ids/sm/MCF/MCF/1/0'
MACHINE_RATED_POWER_SEMANTIC_ID = '0173-1#02-AAC970#009'


# ================================================ Simulation Submodel의 SourceModels에서 Process·Resource·Warehouse Submodel을 가리키는 참조 요소의 idShort ================================================
SOURCE_MODEL_REFERENCE_ID_SHORTS = {
    'process': 'ProcessModelRef',
    'resource': 'ResourceModelRef',
    'warehouse': 'WarehouseModelRef',
}


# ================================================ KG 노드 사이의 관계(Edge)를 읽는 AAS 참조 요소 경로 ================================================
AAS_REFERENCE_ELEMENT_PATHS = {
    'process_to_electricity': 'ManufacturingProcess.Recipes.ProcessCode',
    'process_to_input_item': 'Recipes.InputItemCodeList',
    'process_to_machine_or_worker': 'Recipes.ResourceGroupRef',
    'machine_to_worker_of_same_process': 'MachineGroup.RequiresOperator',
    'previous_process_to_process': 'ProcessFlows',
    'previous_process_to_process_with_entry_condition': 'ProcessFlows.EntryConditionList',
}


# ================================================ 설비 정격전력을 다루는 단위: 설비 AAS에서 읽는 자리에서 한 번 이 단위로 변환 ================================================
RATED_POWER_UNIT = 'kW'


# ================================================ Events의 이벤트 종류를 가리는 발생 분포(TriggerDistribution): 불량 이벤트는 발생 간격의 단위가 OutputItem(산출 품목 수), 개별 자원 대상 이벤트는 RecipeChange(그 자원이 든 라인의 생산 품목이 바뀐 횟수)이고 TargetUnitResourceRef가 있음. 평균이 들어 있는 Parameters 순번 ================================================
DEFECT_EVENT_TRIGGER_DISTRIBUTION = {
    'DistributionType': 'Exponential',
    'DistributionUnit': 'OutputItem',
}
TARGET_UNIT_RESOURCE_EVENT_TRIGGER_DISTRIBUTION = {
    'DistributionType': 'Exponential',
    'DistributionUnit': 'RecipeChange',
}
MEAN_PARAMETER_INDEX = 0


# ================================================ 제품과 무관한 공정의 product_code에 적는 표시 값 ================================================
PRODUCT_INDEPENDENT = 'ALL'


# ================================================ 레시피가 여럿인 공정에서 대표로 읽는 레시피 순번(첫 레시피) ================================================
REPRESENTATIVE_RECIPE_INDEX = 0


# ================================================ MCF의 ResourceName(여러 언어 글자)에서 읽는 언어 순번(첫 언어) ================================================
RESOURCE_NAME_LANGUAGE_INDEX = 0


# ================================================ MCF의 전력 요소 목록(AncillaryInputs.Electricity)에서 시뮬레이션의 전력량을 적는 항목 순번(첫 항목. 시뮬레이션은 MCF마다 전력량 하나를 냄) ================================================
ELECTRICITY_ITEM_INDEX_OF_SIMULATED_ELECTRICITY = 0


# ================================================ SMT 라인 노드의 속성 합산 시작 값 ================================================
SMT_LINE_NODE_STARTING_ATTRIBUTES = {
    'is_defect_event_target_process': False,
    'is_defect_event_handling_process': False,
    'requires_no_worker_and_no_machine': False,
    'CycleTime': 0,
    'defect_probability_per_output_item': 0.0,
    'process_rated_power_kw': 0.0,
    'RequiresWorker': False,
    'worker_work_time_sec': 0.0,
}


# ================================================ 제품 BOM 품목을 나누는 entityType ================================================
BOM_ENTITY_TYPES = ['CoManagedEntity', 'SelfManagedEntity']


# ================================================ 작업자 그룹들이 함께 쓰는 근무표 수 ================================================
REQUIRED_WORK_SCHEDULE_COUNT = 1


# ================================================ AAS에 값이 없을 때 쓰는 값 ================================================
SIMULTANEOUS_PROCESSING_QUANTITY_WITHOUT_UNITS_PER_WORKER = 1
GROUP_CODE_WITHOUT_GROUP = ''
REQUIRES_OPERATOR_WITHOUT_GROUP = True
MACHINE_RATED_POWER_KW_WITHOUT_MACHINE_AAS = 0.0
PROCESS_RATED_POWER_KW_WITHOUT_VALUE = 0.0


# ================================================ 작업자를 필요로 하지 않는 공정(AAS의 RequiresWorker가 거짓)의 작업자 작업시간(초) ================================================
WORKER_WORK_TIME_SEC_WITHOUT_WORKER = 0.0


# ================================================ config.json 임시값(AAS에 없는 값): 이름과 config.json에 없을 때 쓰는 값 ================================================
TEMPORARY_VALUES_KEY = 'temporary_values'
TEMPORARY_VALUE_DEFAULTS = {
    'minimum_stock_lots_by_item_code': {},
    'lot_size_by_item_code': {},
    'replenishment_lead_time_day': None,
    'replenishment_ratio_by_category_code': {},
    'replenishment_ratio_without_category': None,
}
MINIMUM_STOCK_LOTS_WITHOUT_TEMPORARY_VALUE = 0
LOT_SIZE_WITHOUT_TEMPORARY_VALUE = 1


# ================================================ 공정 기록과 창고 재고 기준의 자료형 ================================================
@dataclass
class ProcessRecord:
    ProcessCode: aas_reader.Property
    Recipes: list = field(default_factory=list)
    previous_processes: list = field(default_factory=list)
    following_processes: list = field(default_factory=list)
    defect_probability_per_output_item: float = 0.0
    BranchProbability: float = None
    is_defect_event_target_process: bool = False
    is_defect_event_handling_process: bool = False
    requires_no_worker_and_no_machine: bool = False
    product_code: str = PRODUCT_INDEPENDENT
    smt_line_first_process_code: str = None
    process_flow_order_in_smt_line: int = 0


@dataclass
class StockPolicy:
    minimum_stock_quantity: float
    capacity_quantity: float
    replenishment_ratio: float


# ================================================ config.json 임시값 읽기 ================================================
def load_temporary_values(config_file_path):
    temporary_values = dict(TEMPORARY_VALUE_DEFAULTS)
    if not os.path.exists(config_file_path):
        return temporary_values
    with open(config_file_path, encoding='utf-8') as config_file:
        config = json.load(config_file)
    if TEMPORARY_VALUES_KEY in config:
        temporary_values.update(config[TEMPORARY_VALUES_KEY])
    return temporary_values


# ================================================ 제품 Submodel과 ProductCode 찾기 ================================================
def find_product_submodels(submodels):
    product_submodels = []
    for submodel in submodels.values():
        if submodel.semanticId == PRODUCT_SUBMODEL_SEMANTIC_ID:
            product_submodels.append(submodel)
    return product_submodels


def read_product_code(product_submodel):
    for element in product_submodel.values():
        if isinstance(element, aas_reader.Entity):
            return element.ProductCode.value
    return None


# ================================================ MCF Submodel 찾기와 읽기: semanticId가 MCF 템플릿인 Submodel, MCF의 전력 요소(AncillaryInputs.Electricity)를 가리키는 KG 노드 경로, MCF의 Recipes가 가리키는 공정의 ProcessCode ================================================
def find_mcf_submodels(submodels):
    mcf_submodels = []
    for submodel in submodels.values():
        if submodel.semanticId == MCF_SUBMODEL_SEMANTIC_ID:
            mcf_submodels.append(submodel)
    return mcf_submodels


def electricity_kg_node_path_of_mcf(MCF):
    Electricity = MCF.AncillaryInputs.Electricity
    return idShort_path_from_submodel(Electricity)


def idShort_path_from_submodel(submodel_element):
    idShorts_from_end = []
    current_element = submodel_element
    while not isinstance(current_element, aas_reader.Submodel):
        idShorts_from_end.append(current_element.idShort)
        current_element = current_element.parent_element
    idShorts_from_end.append(current_element.idShort)
    idShorts = reversed(idShorts_from_end)
    return aas_reader.KG_NODE_PATH_SEPARATOR.join(idShorts)


def process_codes_in_mcf_recipes(MCF):
    process_codes = []
    for recipe in MCF.ManufacturingProcess.Recipes:
        process_code = aas_reader.referenced_code_value(recipe.ProcessCode)
        if process_code not in process_codes:
            process_codes.append(process_code)
    return process_codes


# ================================================ MCF 레시피 구조 읽기: MCF의 ResourceName, MCF 레시피의 산출물(Output의 OutputItemCode)이 가리키는 Simulation 레시피, 참조 요소가 가리키는 값(참조가 비어 있으면 없음) ================================================
def read_mcf_ResourceName(MCF):
    ResourceName = MCF.ManufacturingProcess.ProcessResource.ResourceName
    return ResourceName.value[RESOURCE_NAME_LANGUAGE_INDEX]['text']


def simulation_recipe_of_OutputItemCode_reference(OutputItemCode_reference):
    OutputItemCode = OutputItemCode_reference.target
    return OutputItemCode.parent_element


def referenced_value_or_none(reference_element):
    if not reference_element.value:
        return None
    return reference_element.target.value


# ================================================ Submodel에서 요소까지의 경로(MCF 인스턴스에서 계산값을 적는 요소의 위치에 씀): 경로의 한 칸은 idShort이고 목록(SubmodelElementList)의 항목은 순번 ================================================
def sme_path_from_submodel(submodel_element):
    sme_path_from_end = []
    current_element = submodel_element
    while not isinstance(current_element, aas_reader.Submodel):
        parent_element = current_element.parent_element
        if isinstance(parent_element, aas_reader.SubmodelElementList):
            index_in_list = aas_reader.index_in_submodel_element_list(
                parent_element, current_element)
            sme_path_from_end.append(index_in_list)
        else:
            sme_path_from_end.append(current_element.idShort)
        current_element = parent_element
    return list(reversed(sme_path_from_end))


# ================================================ Events의 이벤트 종류 가리기: 발생 분포의 유형과 단위가 주어진 것과 같은지, 불량 이벤트인지, 개별 자원 대상 이벤트(TargetUnitResourceRef가 있음)인지 ================================================
def has_trigger_distribution(event, trigger_distribution):
    TriggerDistribution = event.TriggerDistribution
    DistributionType = TriggerDistribution.DistributionType.value
    DistributionUnit = TriggerDistribution.DistributionUnit.value
    has_same_type = DistributionType == trigger_distribution['DistributionType']
    has_same_unit = DistributionUnit == trigger_distribution['DistributionUnit']
    return has_same_type and has_same_unit


def is_defect_event(event):
    return has_trigger_distribution(event, DEFECT_EVENT_TRIGGER_DISTRIBUTION)


def is_target_unit_resource_event(event):
    has_target_unit_resource = bool(event.TargetUnitResourceRef.value)
    has_recipe_change_distribution = has_trigger_distribution(
        event, TARGET_UNIT_RESOURCE_EVENT_TRIGGER_DISTRIBUTION)
    return has_target_unit_resource and has_recipe_change_distribution


def read_mean_of_trigger_distribution(event):
    mean_parameter = event.TriggerDistribution.Parameters[MEAN_PARAMETER_INDEX]
    return float(mean_parameter.DistributionParameter.value)


# ================================================ 공정 기록에서 앞 공정·다음 공정 코드 읽기 ================================================
def previous_process_codes(process_record):
    return [previous['process_code'] for previous in process_record.previous_processes]


def following_process_codes(process_record):
    return [following['process_code'] for following in process_record.following_processes]


# ================================================ 공정의 대표 레시피에서 자원 읽기: 자원 그룹(ResourceGroupRef가 가리키는 하나, 참조가 비어 있으면 없음), 설비, 작업자 ================================================
def representative_recipe(process_record):
    return process_record.Recipes[REPRESENTATIVE_RECIPE_INDEX]


def process_resource_groups(process_record):
    recipe = representative_recipe(process_record)
    ResourceGroupRef = recipe.ResourceGroupRef
    if not ResourceGroupRef.value:
        return []
    group_code_element = ResourceGroupRef.target
    return [group_code_element.parent_element]


def process_machine_unit_code_elements(process_record):
    recipe = representative_recipe(process_record)
    ResourceUnitRef = recipe.ResourceUnitRef
    if ResourceUnitRef.value:
        return [ResourceUnitRef.target]
    machine_unit_code_elements = []
    for resource_group in process_resource_groups(process_record):
        if 'MachinePool' in resource_group:
            for machine_unit_reference in resource_group.MachinePool.MachineUnitList:
                machine_unit_code_elements.append(machine_unit_reference.target)
    return machine_unit_code_elements


def process_worker_unit_code_elements(process_record):
    worker_unit_code_elements = []
    for resource_group in process_resource_groups(process_record):
        if 'WorkerPool' in resource_group:
            for worker_unit_reference in resource_group.WorkerPool.WorkerUnitList:
                worker_unit_code_elements.append(worker_unit_reference.target)
    return worker_unit_code_elements


# ================================================ 공정의 동시 가공 수량: 설비가 있는 공정은 설비의 CapacityPerCycle, 설비가 없는 공정은 작업자 그룹의 UnitsPerWorker ================================================
def process_simultaneous_processing_quantity(process_record):
    capacity_per_cycle_values = []
    for machine_unit_code_element in process_machine_unit_code_elements(process_record):
        machine_unit = machine_unit_code_element.parent_element
        capacity_per_cycle_values.append(int(machine_unit.CapacityPerCycle.value))
    if capacity_per_cycle_values:
        return max(capacity_per_cycle_values)
    units_per_worker_values = []
    for resource_group in process_resource_groups(process_record):
        if 'UnitsPerWorker' in resource_group:
            units_per_worker_values.append(int(resource_group.UnitsPerWorker.value))
    if not units_per_worker_values:
        return SIMULTANEOUS_PROCESSING_QUANTITY_WITHOUT_UNITS_PER_WORKER
    return max(units_per_worker_values)


# ================================================ 작업자 작업시간(초): 작업자를 필요로 하는 공정(AAS의 RequiresWorker가 참)은 그 공정의 CycleTime, 아니면 0 ================================================
def calculate_worker_work_time_sec(RequiresWorker, CycleTime):
    if RequiresWorker:
        return CycleTime
    return WORKER_WORK_TIME_SEC_WITHOUT_WORKER


# ================================================ AAS 코드 요소 목록을 KG 노드 경로 목록으로 ================================================
def kg_node_paths_from_smes(code_elements):
    return [aas_reader.kg_node_path_from_sme(code_element) for code_element in code_elements]


# ================================================ 설비 AAS에서 정격전력 요소 찾기 ================================================
def find_machine_rated_power_element(machine_shell):
    for submodel in machine_shell.values():
        for element in aas_reader.iterate_all_sub_elements(submodel):
            if element.semanticId == MACHINE_RATED_POWER_SEMANTIC_ID:
                return element
    return None


# ================================================ AAS 요소 사이 참조 적기: 출발 KG 노드 경로 → 도착 KG 노드 경로 → AAS 참조 요소 경로 → 참조에 딸린 값 ================================================
def add_aas_element_reference(aas_element_references, source_kg_node_path, target_kg_node_path,
                              reference_element_path, reference_values):
    if source_kg_node_path == target_kg_node_path:
        return
    if source_kg_node_path not in aas_element_references:
        aas_element_references[source_kg_node_path] = {}
    references_from_source = aas_element_references[source_kg_node_path]
    if target_kg_node_path not in references_from_source:
        references_from_source[target_kg_node_path] = {}
    references_to_target = references_from_source[target_kg_node_path]
    references_to_target[reference_element_path] = reference_values


# ================================================ AAS 템플릿을 정해진 경로로 파싱: 불러온 AAS와 config.json 임시값에서 KG 노드·관계와 시뮬레이션 입력 값 추출 ================================================
class PathExtractor:

    def __init__(self, aas_directory):
        aas_file_reader = aas_reader.AASReader(aas_directory)
        self.aas_list = aas_file_reader.aas_list
        config_file_path = os.path.join(aas_directory, aas_reader.SCENARIO_CONFIG_FILE)
        self.temporary_values = load_temporary_values(config_file_path)
        self.simulation_submodel = self.aas_list.submodels[SIMULATION_SUBMODEL_ID]
        self.process_submodel = self.find_source_submodel('process')
        self.resource_submodel = self.find_source_submodel('resource')
        self.warehouse_submodel = self.find_source_submodel('warehouse')
        self.product_submodels = find_product_submodels(self.aas_list.submodels)
        self.mcf_submodels = find_mcf_submodels(self.aas_list.submodels)
        self.product_codes = []
        for product_submodel in self.product_submodels:
            self.product_codes.append(read_product_code(product_submodel))
        self.process_records = {}
        self.reachable_product_codes_by_process = {}
        self.build_process_records()
        self.mcf_electricity_kg_node_paths_by_process_code = {}
        self.record_mcf_electricity_kg_node_paths_of_processes()

    def find_source_submodel(self, source_model_name):
        SourceModels = self.simulation_submodel.SimConnector.SourceModels
        reference_idShort = SOURCE_MODEL_REFERENCE_ID_SHORTS[source_model_name]
        source_model_reference = SourceModels[reference_idShort]
        return source_model_reference.target

    # ================================================ 공정 기록 만들기: 공정 목록에 레시피·공정 흐름·불량 이벤트를 공정 코드별로 묶기 ================================================
    def build_process_records(self):
        Relations = self.simulation_submodel.SimConnector.Relations
        for Process in self.process_submodel.ProcessCategories:
            process_code = Process.ProcessCode.value
            self.process_records[process_code] = ProcessRecord(ProcessCode=Process.ProcessCode)
        for recipe in Relations.Recipes:
            process_code = aas_reader.referenced_code_value(recipe.ProcessCode)
            self.process_records[process_code].Recipes.append(recipe)
        for process_flow in Relations.ProcessFlows:
            from_process_code = aas_reader.referenced_code_value(process_flow.FromProcessRef)
            to_process_code = aas_reader.referenced_code_value(process_flow.ToProcessRef)
            self.process_records[from_process_code].following_processes.append({
                'process_code': to_process_code,
                'BranchProbability': float(process_flow.BranchProbability.value),
            })
            self.process_records[to_process_code].previous_processes.append({
                'process_code': from_process_code,
                'has_entry_condition': bool(process_flow.EntryConditionList),
            })
        self.record_defect_events(Relations.Events)
        self.record_BranchProbability_of_skippable_processes()
        self.record_processes_without_worker_and_machine()
        self.record_product_codes()

    def record_defect_events(self, Events):
        for event in Events:
            if is_target_unit_resource_event(event):
                continue
            if not is_defect_event(event):
                raise ValueError(f'{event.EventCode.value}: 지원하지 않는 발생 분포')
            mean_output_items_per_defect = read_mean_of_trigger_distribution(event)
            target_process_code = aas_reader.referenced_code_value(event.TargetProcessRef)
            handling_process_code = aas_reader.referenced_code_value(event.HandlingProcessRef)
            target_process_record = self.process_records[target_process_code]
            target_process_record.defect_probability_per_output_item = (
                1 / mean_output_items_per_defect)
            target_process_record.is_defect_event_target_process = True
            handling_process_record = self.process_records[handling_process_code]
            handling_process_record.is_defect_event_handling_process = True

    def record_BranchProbability_of_skippable_processes(self):
        for process_record in self.process_records.values():
            for following_process in process_record.following_processes:
                candidate_process_code = following_process['process_code']
                other_following_process_codes = []
                for other_process_code in following_process_codes(process_record):
                    if other_process_code != candidate_process_code:
                        other_following_process_codes.append(other_process_code)
                if not other_following_process_codes:
                    continue
                candidate_process_record = self.process_records[candidate_process_code]
                process_codes_after_candidate = following_process_codes(candidate_process_record)
                candidate_leads_to_all_others = True
                for other_process_code in other_following_process_codes:
                    if other_process_code not in process_codes_after_candidate:
                        candidate_leads_to_all_others = False
                if candidate_leads_to_all_others:
                    BranchProbability = following_process['BranchProbability']
                    candidate_process_record.BranchProbability = BranchProbability

    def record_processes_without_worker_and_machine(self):
        for process_record in self.process_records.values():
            Process = process_record.ProcessCode.parent_element
            RequiresWorker = Process.RequiresWorker.value
            RequiresMachine = Process.RequiresMachine.value
            if not RequiresWorker and not RequiresMachine:
                process_record.requires_no_worker_and_no_machine = True

    # ================================================ 공정의 product_code 정하기: 공정 흐름을 따라가 닿는 제품이 하나면 그 ProductCode, 아니면 PRODUCT_INDEPENDENT ================================================
    def record_product_codes(self):
        process_codes_without_product = []
        for process_code, process_record in self.process_records.items():
            reachable_product_codes = self.find_reachable_product_codes(process_code, [])
            reaches_single_product = len(reachable_product_codes) == 1
            if reaches_single_product:
                reachable_product_code_list = list(reachable_product_codes)
                only_product_code = reachable_product_code_list[0]
                process_record.product_code = only_product_code
            else:
                process_record.product_code = PRODUCT_INDEPENDENT
            if not reachable_product_codes:
                process_codes_without_product.append(process_code)
        self.record_smt_lines(process_codes_without_product)

    def find_reachable_product_codes(self, process_code, visited_process_codes):
        if process_code in self.reachable_product_codes_by_process:
            return self.reachable_product_codes_by_process[process_code]
        process_record = self.process_records[process_code]
        reachable_product_codes = set()
        for recipe in process_record.Recipes:
            output_item_code = recipe.OutputItemCode.value
            if output_item_code in self.product_codes:
                reachable_product_codes.add(output_item_code)
        for following_process_code in following_process_codes(process_record):
            following_process_record = self.process_records[following_process_code]
            can_be_skipped = following_process_record.BranchProbability is not None
            if can_be_skipped or following_process_code in visited_process_codes:
                continue
            product_codes_after_following = self.find_reachable_product_codes(
                following_process_code, visited_process_codes + [process_code])
            reachable_product_codes.update(product_codes_after_following)
        self.reachable_product_codes_by_process[process_code] = reachable_product_codes
        return reachable_product_codes

    # ================================================ SMT 라인 찾기: 제품에 닿지 않고 다른 공정의 투입 품목을 만드는 공정 묶음에 첫 공정 코드와 단계 순서 적기 ================================================
    def record_smt_lines(self, process_codes_without_product):
        consumed_item_codes = set()
        for process_record in self.process_records.values():
            for recipe in process_record.Recipes:
                for input_item in recipe.InputItemCodeList:
                    item_code = aas_reader.referenced_code_value(input_item.InputItemCodeRef)
                    consumed_item_codes.add(item_code)
        connected_process_groups = self.group_connected_processes(process_codes_without_product)
        for member_process_codes in connected_process_groups:
            output_item_codes = set()
            for process_code in member_process_codes:
                for recipe in self.process_records[process_code].Recipes:
                    output_item_codes.add(recipe.OutputItemCode.value)
            consumed_output_item_codes = output_item_codes & consumed_item_codes
            if not consumed_output_item_codes:
                continue
            ordered_process_codes = self.order_processes_by_process_flow(member_process_codes)
            first_process_code = ordered_process_codes[0]
            for process_code in member_process_codes:
                process_record = self.process_records[process_code]
                process_record.smt_line_first_process_code = first_process_code
                process_record.product_code = first_process_code
                process_record.process_flow_order_in_smt_line = ordered_process_codes.index(
                    process_code)

    def group_connected_processes(self, process_codes):
        connected_process_groups = []
        for process_code in self.process_records:
            if process_code not in process_codes:
                continue
            is_already_grouped = False
            for grouped_process_codes in connected_process_groups:
                if process_code in grouped_process_codes:
                    is_already_grouped = True
            if is_already_grouped:
                continue
            connected_process_codes = []
            process_codes_to_visit = [process_code]
            while process_codes_to_visit:
                current_process_code = process_codes_to_visit.pop()
                if current_process_code in connected_process_codes:
                    continue
                connected_process_codes.append(current_process_code)
                current_process_record = self.process_records[current_process_code]
                neighbor_process_codes = previous_process_codes(current_process_record)
                neighbor_process_codes += following_process_codes(current_process_record)
                for neighbor_process_code in neighbor_process_codes:
                    if neighbor_process_code in process_codes:
                        process_codes_to_visit.append(neighbor_process_code)
            member_process_codes = []
            for listed_process_code in self.process_records:
                if listed_process_code in connected_process_codes:
                    member_process_codes.append(listed_process_code)
            connected_process_groups.append(member_process_codes)
        return connected_process_groups

    def order_processes_by_process_flow(self, member_process_codes):
        ordered_process_codes = []
        while len(ordered_process_codes) < len(member_process_codes):
            for process_code in member_process_codes:
                if process_code in ordered_process_codes:
                    continue
                process_record = self.process_records[process_code]
                all_previous_processes_ordered = True
                for previous_process_code in previous_process_codes(process_record):
                    if previous_process_code not in ordered_process_codes:
                        all_previous_processes_ordered = False
                if all_previous_processes_ordered:
                    ordered_process_codes.append(process_code)
        return ordered_process_codes

    # ================================================ 제품 코드 추출 ================================================
    def extract_product_codes(self):
        return list(self.product_codes)

    # ================================================ Process 노드 추출: 공정별 속성, SMT 라인 공정들은 노드 하나로 합산 ================================================
    def extract_process_nodes(self):
        process_nodes = {}
        for process_code, process_record in self.process_records.items():
            kg_node_path = self.process_kg_node_path(process_code)
            attributes = self.process_attributes(process_code)
            if not process_record.smt_line_first_process_code:
                process_nodes[kg_node_path] = attributes
                continue
            if kg_node_path not in process_nodes:
                smt_line_attributes = dict(attributes)
                smt_line_attributes.update(SMT_LINE_NODE_STARTING_ATTRIBUTES)
                process_nodes[kg_node_path] = smt_line_attributes
            smt_line_attributes = process_nodes[kg_node_path]
            smt_line_pass_rate = 1 - smt_line_attributes['defect_probability_per_output_item']
            step_pass_rate = 1 - float(attributes['defect_probability_per_output_item'])
            smt_line_attributes['CycleTime'] += attributes['CycleTime']
            smt_line_attributes['process_rated_power_kw'] += float(
                attributes['process_rated_power_kw'])
            if attributes['RequiresWorker']:
                smt_line_attributes['RequiresWorker'] = True
            smt_line_attributes['worker_work_time_sec'] += attributes['worker_work_time_sec']
            smt_line_attributes['defect_probability_per_output_item'] = (
                1 - smt_line_pass_rate * step_pass_rate)
            smt_line_attributes['simultaneous_processing_quantity'] = max(
                smt_line_attributes['simultaneous_processing_quantity'],
                attributes['simultaneous_processing_quantity'])
        return process_nodes

    def process_kg_node_path(self, process_code):
        process_record = self.process_records[process_code]
        smt_line_first_process_code = process_record.smt_line_first_process_code
        if smt_line_first_process_code:
            smt_line_first_process_record = self.process_records[smt_line_first_process_code]
            return aas_reader.kg_node_path_from_sme(smt_line_first_process_record.ProcessCode)
        return aas_reader.kg_node_path_from_sme(process_record.ProcessCode)

    def process_attributes(self, process_code):
        process_record = self.process_records[process_code]
        recipe = representative_recipe(process_record)
        is_target_process = process_record.is_defect_event_target_process
        is_handling_process = process_record.is_defect_event_handling_process
        requires_no_resource = process_record.requires_no_worker_and_no_machine
        process_rated_power_kw = PROCESS_RATED_POWER_KW.get(
            process_code, PROCESS_RATED_POWER_KW_WITHOUT_VALUE)
        Process = process_record.ProcessCode.parent_element
        RequiresWorker = bool(Process.RequiresWorker.value)
        CycleTime = recipe.CycleTime.value
        return {
            'product_code': process_record.product_code,
            'is_defect_event_target_process': is_target_process,
            'is_defect_event_handling_process': is_handling_process,
            'requires_no_worker_and_no_machine': requires_no_resource,
            'CycleTime': CycleTime,
            'simultaneous_processing_quantity': process_simultaneous_processing_quantity(
                process_record),
            'defect_probability_per_output_item': process_record.defect_probability_per_output_item,
            'process_rated_power_kw': process_rated_power_kw,
            'BranchProbability': process_record.BranchProbability,
            'RequiresWorker': RequiresWorker,
            'worker_work_time_sec': calculate_worker_work_time_sec(RequiresWorker, CycleTime),
        }

    # ================================================ SMT 라인 단계 추출: SMT 라인에 속한 공정별 속성, 단계 순서, Process·Machine·Worker 노드 경로 ================================================
    def extract_smt_line_steps(self):
        smt_line_steps = {}
        for process_code, process_record in self.process_records.items():
            if not process_record.smt_line_first_process_code:
                continue
            machine_unit_code_elements = process_machine_unit_code_elements(process_record)
            worker_unit_code_elements = process_worker_unit_code_elements(process_record)
            step_attributes = self.process_attributes(process_code)
            step_attributes['process_flow_order_in_smt_line'] = (
                process_record.process_flow_order_in_smt_line)
            step_attributes['process_kg_node_path'] = self.process_kg_node_path(process_code)
            step_attributes['machine_kg_node_paths'] = kg_node_paths_from_smes(
                machine_unit_code_elements)
            step_attributes['worker_kg_node_paths'] = kg_node_paths_from_smes(
                worker_unit_code_elements)
            step_kg_node_path = aas_reader.kg_node_path_from_sme(process_record.ProcessCode)
            smt_line_steps[step_kg_node_path] = step_attributes
        return smt_line_steps

    # ================================================ Machine 노드 추출: 설비별 그룹 코드, 정격전력(kW), MaxCapacity(설비가 동시에 받는 수), CapacityPerCycle(한 번 가동에 함께 가공하는 수량), RequiresOperator ================================================
    def extract_machine_nodes(self):
        Machine = self.resource_submodel.ResourceCategories.Machine
        machine_group_by_unit_code = {}
        for machine_group in Machine.MachineGroup:
            for machine_unit_reference in machine_group.MachinePool.MachineUnitList:
                machine_unit_code = machine_unit_reference.target.value
                machine_group_by_unit_code[machine_unit_code] = machine_group
        machine_nodes = {}
        for machine_unit in Machine.MachineUnit:
            machine_unit_code = machine_unit.MachineUnitCode.value
            if machine_unit_code in machine_group_by_unit_code:
                machine_group = machine_group_by_unit_code[machine_unit_code]
                MachineGroupCode = machine_group.MachineGroupCode.value
                RequiresOperator = bool(machine_group.RequiresOperator.value)
            else:
                MachineGroupCode = GROUP_CODE_WITHOUT_GROUP
                RequiresOperator = REQUIRES_OPERATOR_WITHOUT_GROUP
            kg_node_path = aas_reader.kg_node_path_from_sme(machine_unit.MachineUnitCode)
            machine_nodes[kg_node_path] = {
                'MachineGroupCode': MachineGroupCode,
                'rated_power_kw': self.machine_rated_power_kw(machine_unit),
                'MaxCapacity': int(machine_unit.MaxCapacity.value),
                'CapacityPerCycle': int(machine_unit.CapacityPerCycle.value),
                'RequiresOperator': RequiresOperator,
            }
        return machine_nodes

    def machine_rated_power_kw(self, machine_unit):
        MachineAASRef = machine_unit.MachineAASRef
        machine_shell = None
        if MachineAASRef.value:
            machine_shell = MachineAASRef.target
        if machine_shell is None:
            self.aas_list.aas_reading_problem_messages.append(
                f'{machine_unit.MachineUnitCode.value}: 설비 AAS 없음 — 정격전력 0')
            return MACHINE_RATED_POWER_KW_WITHOUT_MACHINE_AAS
        rated_power_element = find_machine_rated_power_element(machine_shell)
        rated_power_with_unit = aas_reader.read_value_with_unit(rated_power_element)
        rated_power_kw = aas_reader.convert_unit(rated_power_with_unit, RATED_POWER_UNIT)
        return rated_power_kw

    # ================================================ Worker 노드 추출: 공정 레시피에 연결된 작업자의 그룹 코드. 어느 공정에도 연결되지 않은 작업자는 AAS의 Resource에만 있고 노드로 만들지 않음 ================================================
    def extract_worker_nodes(self):
        worker_kg_node_paths_of_processes = self.worker_kg_node_paths_required_by_processes()
        Worker = self.resource_submodel.ResourceCategories.Worker
        worker_nodes = {}
        for worker_group in Worker.WorkerGroup:
            WorkerGroupCode = worker_group.WorkerGroupCode.value
            for worker_unit_reference in worker_group.WorkerPool.WorkerUnitList:
                kg_node_path = aas_reader.kg_node_path_from_sme(worker_unit_reference.target)
                if kg_node_path in worker_kg_node_paths_of_processes:
                    worker_nodes[kg_node_path] = {'WorkerGroupCode': WorkerGroupCode}
        for worker_unit in Worker.WorkerUnit:
            kg_node_path = aas_reader.kg_node_path_from_sme(worker_unit.WorkerUnitCode)
            is_required_by_process = kg_node_path in worker_kg_node_paths_of_processes
            if is_required_by_process and kg_node_path not in worker_nodes:
                worker_nodes[kg_node_path] = {'WorkerGroupCode': GROUP_CODE_WITHOUT_GROUP}
        return worker_nodes

    def worker_kg_node_paths_required_by_processes(self):
        worker_kg_node_paths = []
        for process_record in self.process_records.values():
            for worker_unit_code_element in process_worker_unit_code_elements(process_record):
                kg_node_path = aas_reader.kg_node_path_from_sme(worker_unit_code_element)
                if kg_node_path not in worker_kg_node_paths:
                    worker_kg_node_paths.append(kg_node_path)
        return worker_kg_node_paths

    # ================================================ Warehouse 노드 추출: 창고 품목별 KG 노드 경로 ================================================
    def extract_warehouse_nodes(self):
        warehouse_nodes = {}
        for stored_item_subcategory in self.stored_item_subcategories():
            kg_node_path = stored_item_subcategory['kg_node_path']
            warehouse_nodes[kg_node_path] = {}
        return warehouse_nodes

    def stored_item_subcategories(self):
        stored_item_subcategories = []
        for section in self.warehouse_submodel.Sections:
            for stored_item in section.StoredItems:
                for sub_category in stored_item.SubCategories:
                    ItemCodeRef = sub_category.ItemCodeRef
                    item_code = aas_reader.referenced_code_value(ItemCodeRef)
                    stored_item_subcategories.append({
                        'item_code': item_code,
                        'kg_node_path': aas_reader.kg_node_path_from_sme(ItemCodeRef, item_code),
                        'stored_item': stored_item,
                        'sub_category': sub_category,
                    })
        return stored_item_subcategories

    # ================================================ MCF·Electricity 노드 추출: MCF 노드는 만들지 않음. Electricity 노드는 MCF Submodel마다 전력 요소(AncillaryInputs.Electricity)의 경로로 만들고, 경로가 같은 전력 요소는 노드 하나 ================================================
    def extract_mcf_nodes(self):
        mcf_nodes = {}
        return mcf_nodes

    def extract_electricity_nodes(self):
        electricity_nodes = {}
        for MCF in self.mcf_submodels:
            electricity_nodes[electricity_kg_node_path_of_mcf(MCF)] = {}
        return electricity_nodes

    # ================================================ 공정의 전력이 들어가는 MCF 전력 요소: Recipes의 ProcessCode가 그 공정을 가리키는 MCF Submodel의 전력 요소 경로. 전기를 쓰는 공정이 어느 MCF의 Recipes에도 없으면 AAS 판독 문제로 적음 ================================================
    def record_mcf_electricity_kg_node_paths_of_processes(self):
        paths_by_process_code = self.mcf_electricity_kg_node_paths_by_process_code
        for MCF in self.mcf_submodels:
            electricity_kg_node_path = electricity_kg_node_path_of_mcf(MCF)
            for process_code in process_codes_in_mcf_recipes(MCF):
                if process_code not in paths_by_process_code:
                    paths_by_process_code[process_code] = []
                electricity_kg_node_paths = paths_by_process_code[process_code]
                if electricity_kg_node_path not in electricity_kg_node_paths:
                    electricity_kg_node_paths.append(electricity_kg_node_path)

    def mcf_electricity_kg_node_paths_of_process(self, process_code):
        if process_code in self.mcf_electricity_kg_node_paths_by_process_code:
            return self.mcf_electricity_kg_node_paths_by_process_code[process_code]
        problem_message = (
            f'{process_code}: 전기를 쓰는 공정인데 MCF Recipes에 없음 — 공정 → 전력 관계 없음')
        if problem_message not in self.aas_list.aas_reading_problem_messages:
            self.aas_list.aas_reading_problem_messages.append(problem_message)
        return []

    # ================================================ MCF 레시피 구조 추출(MCF 탄소배출량 계산에 씀): MCF마다 ResourceType, ResourceName, 레시피가 가리키는 Simulation 레시피의 순번, 계산값을 적는 요소의 위치. Simulation 레시피마다 공정의 ProcessCode, OutputItemCode, 투입 품목(품목 코드, InputItemQuantity, 중간재이면 그 중간재를 만든 Simulation 레시피의 순번). MCF 레시피의 투입 품목은 MCF의 InputItemCodeList에서 읽고, InputItemCode가 Simulation 레시피의 OutputItemCode를 가리키면 중간재, 아니면 창고 품목 ================================================
    def extract_mcf_recipe_structure(self):
        simulation_recipes = self.simulation_submodel.SimConnector.Relations.Recipes
        mcf_resources = []
        recipes_by_simulation_recipe_index = {}
        for MCF in self.mcf_submodels:
            ProcessResource = MCF.ManufacturingProcess.ProcessResource
            simulation_recipe_indexes = []
            for mcf_recipe in MCF.ManufacturingProcess.Recipes:
                input_items = self.input_items_of_mcf_recipe(mcf_recipe)
                for output in mcf_recipe.Output:
                    simulation_recipe = simulation_recipe_of_OutputItemCode_reference(
                        output.OutputItemCode)
                    simulation_recipe_index = aas_reader.index_in_submodel_element_list(
                        simulation_recipes, simulation_recipe)
                    simulation_recipe_indexes.append(simulation_recipe_index)
                    recipes_by_simulation_recipe_index[simulation_recipe_index] = {
                        'ProcessCode': aas_reader.referenced_code_value(mcf_recipe.ProcessCode),
                        'OutputItemCode': simulation_recipe.OutputItemCode.value,
                        'input_items': input_items,
                        'is_in_mcf': True,
                    }
            mcf_resources.append({
                'ResourceType': ProcessResource.ResourceType.value,
                'ResourceName': read_mcf_ResourceName(MCF),
                'simulation_recipe_indexes': simulation_recipe_indexes,
                'value_element_positions': self.value_element_positions_of_mcf(MCF),
            })
        for simulation_recipe_index, simulation_recipe in enumerate(simulation_recipes):
            if simulation_recipe_index not in recipes_by_simulation_recipe_index:
                recipes_by_simulation_recipe_index[simulation_recipe_index] = (
                    self.simulation_recipe_without_mcf(simulation_recipe))
        return {
            'mcf_resources': mcf_resources,
            'recipes_by_simulation_recipe_index': recipes_by_simulation_recipe_index,
        }

    def input_items_of_mcf_recipe(self, mcf_recipe):
        simulation_recipes = self.simulation_submodel.SimConnector.Relations.Recipes
        input_items = []
        for input_item in mcf_recipe.InputItemCodeList:
            referenced_element = input_item.InputItemCode.target
            source_simulation_recipe_index = aas_reader.index_in_submodel_element_list(
                simulation_recipes, referenced_element.parent_element)
            input_items.append({
                'item_code': aas_reader.referenced_code_value(input_item.InputItemCode),
                'InputItemQuantity': referenced_value_or_none(input_item.InputItemQuantity),
                'source_simulation_recipe_index': source_simulation_recipe_index,
            })
        return input_items

    # ================================================ MCF 인스턴스에서 계산값을 적는 요소의 위치(MCF 인스턴스 기록에 씀): MCF Submodel의 id와, OperatingTime, 전력 요소 첫 항목의 Amount, 그 전력 항목을 가리키는 AncillaryInputEmissions 줄의 ContributionCO2eq, SumCO2eq의 경로. Allocation 줄마다 OutputItemCodeRef가 가리키는 Simulation 레시피의 순번과 AllocatedFactor·AllocatedCO2eq의 경로. InputMaterialEmissions 줄마다 ActivityDataRef가 가리키는 투입 항목이 든 MCF 레시피의 Simulation 레시피 순번, 그 투입 항목의 InputItemCodeList 순번, ContributionCO2eq의 경로. 전력 항목이 없는 MCF는 Amount와 전력 줄의 위치가 없음 ================================================
    def simulation_recipe_indexes_of_mcf_recipe(self, mcf_recipe):
        simulation_recipes = self.simulation_submodel.SimConnector.Relations.Recipes
        simulation_recipe_indexes = []
        for output in mcf_recipe.Output:
            simulation_recipe = simulation_recipe_of_OutputItemCode_reference(
                output.OutputItemCode)
            simulation_recipe_indexes.append(aas_reader.index_in_submodel_element_list(
                simulation_recipes, simulation_recipe))
        return simulation_recipe_indexes

    def electricity_value_element_positions_of_mcf(self, MCF):
        electricity_value_element_positions = {
            'Amount': None,
            'ContributionCO2eq_of_electricity': None,
        }
        Electricity = MCF.AncillaryInputs.Electricity
        if len(Electricity) <= ELECTRICITY_ITEM_INDEX_OF_SIMULATED_ELECTRICITY:
            return electricity_value_element_positions
        electricity_item = Electricity[ELECTRICITY_ITEM_INDEX_OF_SIMULATED_ELECTRICITY]
        electricity_value_element_positions['Amount'] = sme_path_from_submodel(
            electricity_item.Amount)
        AncillaryInputEmissions = MCF.MCFEmissions.ProcessEmissions.AncillaryInputEmissions
        for ancillary_input_emission in AncillaryInputEmissions:
            if ancillary_input_emission.ActivityDataRef.target is electricity_item:
                electricity_value_element_positions['ContributionCO2eq_of_electricity'] = (
                    sme_path_from_submodel(ancillary_input_emission.ContributionCO2eq))
        return electricity_value_element_positions

    def value_element_positions_of_mcf(self, MCF):
        simulation_recipes = self.simulation_submodel.SimConnector.Relations.Recipes
        ProcessEmissions = MCF.MCFEmissions.ProcessEmissions
        Allocation = []
        for allocation in MCF.MCFEmissions.Allocation:
            simulation_recipe = simulation_recipe_of_OutputItemCode_reference(
                allocation.OutputItemCodeRef)
            Allocation.append({
                'simulation_recipe_index': aas_reader.index_in_submodel_element_list(
                    simulation_recipes, simulation_recipe),
                'AllocatedFactor': sme_path_from_submodel(allocation.AllocatedFactor),
                'AllocatedCO2eq': sme_path_from_submodel(allocation.AllocatedCO2eq),
            })
        InputMaterialEmissions = []
        for input_material_emission in ProcessEmissions.InputMaterialEmissions:
            input_item = input_material_emission.ActivityDataRef.target
            InputItemCodeList = input_item.parent_element
            mcf_recipe = InputItemCodeList.parent_element
            InputMaterialEmissions.append({
                'simulation_recipe_indexes': self.simulation_recipe_indexes_of_mcf_recipe(
                    mcf_recipe),
                'input_item_index': aas_reader.index_in_submodel_element_list(
                    InputItemCodeList, input_item),
                'ContributionCO2eq': sme_path_from_submodel(
                    input_material_emission.ContributionCO2eq),
            })
        value_element_positions = {
            'submodel_id': MCF.id,
            'OperatingTime': sme_path_from_submodel(MCF.ManufacturingProcess.OperatingTime),
            'SumCO2eq': sme_path_from_submodel(ProcessEmissions.SumCO2eq),
            'Allocation': Allocation,
            'InputMaterialEmissions': InputMaterialEmissions,
        }
        value_element_positions.update(self.electricity_value_element_positions_of_mcf(MCF))
        return value_element_positions

    # ================================================ 어느 MCF에도 없는 Simulation 레시피(자원이 없는 공정)의 투입 품목 규칙: 공정 흐름(ProcessFlows)의 앞 공정이 만든 중간재. 앞 공정의 레시피가 하나가 아니면 어느 중간재인지 정할 수 없어 AAS 판독 문제로 적고 투입에서 뺌 ================================================
    def simulation_recipe_without_mcf(self, simulation_recipe):
        simulation_recipes = self.simulation_submodel.SimConnector.Relations.Recipes
        process_code = aas_reader.referenced_code_value(simulation_recipe.ProcessCode)
        input_items = []
        for previous_process_code in previous_process_codes(self.process_records[process_code]):
            previous_recipes = self.process_records[previous_process_code].Recipes
            has_single_recipe = len(previous_recipes) == REPRESENTATIVE_RECIPE_INDEX + 1
            if not has_single_recipe:
                self.aas_list.aas_reading_problem_messages.append(
                    f'{process_code}: MCF가 없는 공정인데 앞 공정 {previous_process_code}의 레시피가 '
                    f'하나가 아님 — 앞 공정의 탄소배출량을 넘기지 않음')
                continue
            previous_recipe = previous_recipes[REPRESENTATIVE_RECIPE_INDEX]
            input_items.append({
                'item_code': previous_recipe.OutputItemCode.value,
                'InputItemQuantity': None,
                'source_simulation_recipe_index': aas_reader.index_in_submodel_element_list(
                    simulation_recipes, previous_recipe),
            })
        return {
            'ProcessCode': process_code,
            'OutputItemCode': simulation_recipe.OutputItemCode.value,
            'input_items': input_items,
            'is_in_mcf': False,
        }

    # ================================================ 공정의 전기 사용 여부(MCF 전력 요소에 전력이 들어가는 공정): 공정별 정격전력(PROCESS_RATED_POWER_KW)이 있거나 담당 설비의 정격전력이 0보다 큰 공정 ================================================
    def is_electricity_consuming_process(self, process_code, process_record):
        if process_code in PROCESS_RATED_POWER_KW:
            return True
        for machine_unit_code_element in process_machine_unit_code_elements(process_record):
            machine_unit = machine_unit_code_element.parent_element
            if not machine_unit.MachineAASRef.value:
                continue
            if self.machine_rated_power_kw(machine_unit) > 0:
                return True
        return False

    # ================================================ AAS 요소 사이 참조 추출: 공정과 전력·투입 품목·설비·작업자·앞 공정, 같은 공정의 설비와 작업자 ================================================
    def extract_aas_element_references(self):
        warehouse_kg_node_path_by_item_code = {}
        for stored_item_subcategory in self.stored_item_subcategories():
            item_code = stored_item_subcategory['item_code']
            warehouse_kg_node_path_by_item_code[item_code] = stored_item_subcategory['kg_node_path']
        aas_element_references = {}
        for process_code, process_record in self.process_records.items():
            process_path = self.process_kg_node_path(process_code)
            machine_paths = kg_node_paths_from_smes(
                process_machine_unit_code_elements(process_record))
            worker_paths = kg_node_paths_from_smes(
                process_worker_unit_code_elements(process_record))
            recipe = representative_recipe(process_record)
            electricity_paths = []
            if self.is_electricity_consuming_process(process_code, process_record):
                electricity_paths = self.mcf_electricity_kg_node_paths_of_process(
                    process_code)
            for electricity_path in electricity_paths:
                add_aas_element_reference(
                    aas_element_references, process_path, electricity_path,
                    AAS_REFERENCE_ELEMENT_PATHS['process_to_electricity'], {})
            for input_item in recipe.InputItemCodeList:
                item_code = aas_reader.referenced_code_value(input_item.InputItemCodeRef)
                add_aas_element_reference(
                    aas_element_references, process_path,
                    warehouse_kg_node_path_by_item_code[item_code],
                    AAS_REFERENCE_ELEMENT_PATHS['process_to_input_item'],
                    {'InputItemQuantity': input_item.InputItemQuantity.value})
            for machine_path in machine_paths:
                add_aas_element_reference(
                    aas_element_references, process_path, machine_path,
                    AAS_REFERENCE_ELEMENT_PATHS['process_to_machine_or_worker'], {})
                for worker_path in worker_paths:
                    add_aas_element_reference(
                        aas_element_references, machine_path, worker_path,
                        AAS_REFERENCE_ELEMENT_PATHS['machine_to_worker_of_same_process'], {})
            for worker_path in worker_paths:
                add_aas_element_reference(
                    aas_element_references, process_path, worker_path,
                    AAS_REFERENCE_ELEMENT_PATHS['process_to_machine_or_worker'], {})
            for previous_process in process_record.previous_processes:
                previous_process_path = self.process_kg_node_path(previous_process['process_code'])
                if previous_process['has_entry_condition']:
                    reference_element_path = AAS_REFERENCE_ELEMENT_PATHS[
                        'previous_process_to_process_with_entry_condition']
                else:
                    reference_element_path = AAS_REFERENCE_ELEMENT_PATHS[
                        'previous_process_to_process']
                add_aas_element_reference(
                    aas_element_references, previous_process_path, process_path,
                    reference_element_path, {})
        return aas_element_references

    # ================================================ 제품 BOM 품목 코드 추출: entityType과 창고 CategoryCode별로 묶기(창고에 없는 품목 제외) ================================================
    def extract_bom_item_codes(self):
        category_code_by_item_code = {}
        for stored_item_subcategory in self.stored_item_subcategories():
            item_code = stored_item_subcategory['item_code']
            stored_item = stored_item_subcategory['stored_item']
            category_code_by_item_code[item_code] = stored_item.CategoryCode.value
        bom_item_codes = {}
        for entity_type in BOM_ENTITY_TYPES:
            bom_item_codes[entity_type] = {}
        for product_submodel in self.product_submodels:
            for element in aas_reader.iterate_all_sub_elements(product_submodel):
                if not isinstance(element, aas_reader.Entity):
                    continue
                if 'ItemCode' not in element:
                    continue
                item_code = element.ItemCode.value
                if item_code not in category_code_by_item_code:
                    continue
                category_code = category_code_by_item_code[item_code]
                item_codes_by_category = bom_item_codes[element.entityType.value]
                if category_code not in item_codes_by_category:
                    item_codes_by_category[category_code] = []
                if item_code not in item_codes_by_category[category_code]:
                    item_codes_by_category[category_code].append(item_code)
        return bom_item_codes

    # ================================================ 창고 재고 기준 추출: 분류(CategoryCode)별 기준, 같은 분류에서는 마지막 품목의 값이 남음 ================================================
    def extract_stock_policies(self):
        bom_item_codes = self.extract_bom_item_codes()
        category_code_by_bom_item_code = {}
        for item_codes_by_category in bom_item_codes.values():
            for category_code, item_codes in item_codes_by_category.items():
                for item_code in item_codes:
                    category_code_by_bom_item_code[item_code] = category_code
        lot_size_by_item_code = self.temporary_values['lot_size_by_item_code']
        minimum_stock_lots_by_item_code = self.temporary_values['minimum_stock_lots_by_item_code']
        replenishment_ratio_by_category_code = self.temporary_values[
            'replenishment_ratio_by_category_code']
        stock_policies = {}
        for stored_item_subcategory in self.stored_item_subcategories():
            item_code = stored_item_subcategory['item_code']
            sub_category = stored_item_subcategory['sub_category']
            category_code = category_code_by_bom_item_code.get(item_code)
            lot_size = LOT_SIZE_WITHOUT_TEMPORARY_VALUE
            if item_code in lot_size_by_item_code:
                lot_size = int(lot_size_by_item_code[item_code])
            minimum_stock_lots = MINIMUM_STOCK_LOTS_WITHOUT_TEMPORARY_VALUE
            if item_code in minimum_stock_lots_by_item_code:
                minimum_stock_lots = int(minimum_stock_lots_by_item_code[item_code])
            CapacityLots = int(sub_category.CapacityLots.value)
            if category_code in replenishment_ratio_by_category_code:
                replenishment_ratio = replenishment_ratio_by_category_code[category_code]
            else:
                replenishment_ratio = self.temporary_values['replenishment_ratio_without_category']
            stock_policies[category_code] = StockPolicy(
                minimum_stock_quantity=minimum_stock_lots * lot_size,
                capacity_quantity=CapacityLots * lot_size,
                replenishment_ratio=replenishment_ratio)
        return stock_policies

    # ================================================ 근무시간 추출: 작업자 그룹이 가리키는 근무표의 근무 시작·종료, 휴게 시작·종료 시각(초) ================================================
    def extract_work_schedule(self):
        Worker = self.resource_submodel.ResourceCategories.Worker
        work_schedules = []
        for worker_group in Worker.WorkerGroup:
            work_schedule_code_element = worker_group.WorkScheduleRef.target
            work_schedule = work_schedule_code_element.parent_element
            is_already_listed = False
            for listed_work_schedule in work_schedules:
                if listed_work_schedule is work_schedule:
                    is_already_listed = True
            if not is_already_listed:
                work_schedules.append(work_schedule)
        if len(work_schedules) != REQUIRED_WORK_SCHEDULE_COUNT:
            raise ValueError(f'작업자 그룹 근무표가 하나가 아님: {len(work_schedules)}')
        only_work_schedule = work_schedules[0]
        BreakStartTime = only_work_schedule.BreakStartTime.value
        BreakDurationTime = int(only_work_schedule.BreakDurationTime.value)
        return {
            'WorkStartTime': only_work_schedule.WorkStartTime.value,
            'WorkEndTime': only_work_schedule.WorkEndTime.value,
            'BreakStartTime': BreakStartTime,
            'break_end_sec': BreakStartTime + BreakDurationTime,
        }

    # ================================================ 개별 자원 대상 이벤트 추출: Events 가운데 발생 간격의 단위가 RecipeChange(생산 품목이 바뀐 횟수)이고 TargetUnitResourceRef가 있는 이벤트의 EventCode, 생산 품목이 한 번 바뀔 때 발생할 확률(평균 발생 간격의 역수), 대상 자원의 UnitCode, 대상 공정의 ProcessCode ================================================
    def extract_target_unit_resource_events(self):
        target_unit_resource_events = []
        for event in self.simulation_submodel.SimConnector.Relations.Events:
            if not is_target_unit_resource_event(event):
                continue
            mean_recipe_changes_per_event = read_mean_of_trigger_distribution(event)
            target_unit_resource_events.append({
                'EventCode': event.EventCode.value,
                'occurrence_probability_per_recipe_change': 1 / mean_recipe_changes_per_event,
                'target_unit_code': aas_reader.referenced_code_value(
                    event.TargetUnitResourceRef),
                'target_process_code': aas_reader.referenced_code_value(event.TargetProcessRef),
            })
        return target_unit_resource_events

    # ================================================ 자재 보충 소요시간(초)과 실행 길이(RunLength) 추출 ================================================
    def extract_replenishment_lead_time_sec(self):
        replenishment_lead_time_day = int(self.temporary_values['replenishment_lead_time_day'])
        return replenishment_lead_time_day * aas_reader.SECONDS_PER_DAY

    def extract_run_length(self):
        RunLength = self.simulation_submodel.SimulationConfiguration.Run.RunLength
        return float(RunLength.value)
