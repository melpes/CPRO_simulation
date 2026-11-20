import argparse
import collections
import inspect
import itertools
import json
import math
import os
import random
import sys
from dataclasses import dataclass

import simpy

import path_extractor


# ================================================ 코드 규칙: AAS(SimConnector 등)로 표현되지 않는 값. 탄소 구성요소 시간당 활동량 사전, 이벤트 소요시간, 기본값, 템플릿 위치 ================================================
# 탄소 구성요소의 시간당 활동량을 AAS에서 찾는 곳: 분류 → 자원(설비) AAS 안 요소의 semanticId. 전력은 정격전력
ACTIVITY_DATA_BASIS_SEMANTIC_ID = {
    'Electricity': path_extractor.RATED_POWER_SEMANTIC_ID,
}

# AAS에서 시간당 활동량을 찾지 못한 공정의 값: 공정 코드 → 분류 → {rate, rate_unit}
CARBON_ACTIVITY_RATE_BY_PROCESS_CODE = {
    ProcessCode: {'Electricity': {'rate': rated_power_kw, 'rate_unit': 'kW'}}
    for ProcessCode, rated_power_kw in {
        'BT5_10': 1.391378368745966, 'BT5_100': 0.07865, 'BT5_11': 1.391378368745966,
        'BT5_110': 2.320458348334833, 'BT5_120': 1.391966041937527, 'BT5_121': 1.391966041937527,
        'BT5_122': 1.369206041937527, 'BT5_123': 1.369206041937527, 'BT5_12A': 1.391378368745966,
        'BT5_12B': 1.391378368745966, 'BT5_13A': 1.391378368745966, 'BT5_13B': 1.391378368745966,
        'BT5_14A': 1.391378368745966, 'BT5_14B': 1.391378368745966, 'BT5_20': 1.192778368745966,
        'BT5_30': 2.627118348334833, 'BT5_31': 2.627118348334833, 'BT5_40': 2.155304094509451,
        'BT5_41': 2.155304094509451, 'BT5_42': 2.094431094509451, 'BT5_50': 2.137842348334833,
        'BT5_51': 2.137842348334833, 'BT5_52': 2.137842348334833, 'BT5_60': 2.155304094509451,
        'BT5_61': 2.155304094509451, 'BT5_62': 2.137842348334833, 'BT5_70': 0.032833,
        'BT5_71': 0.032833, 'BT5_72': 0.032833, 'BT5_73': 0.032833, 'BT5_74': 0.032833,
        'BT5_75': 0.032833, 'BT5_80': 2.076969348334832, 'BT5_90': 2.824895094509452,
        'NVD_100': 2.627073348334833, 'NVD_110': 0.07865, 'NVD_120': 1.391966041937527,
        'NVD_121': 1.391966041937527, 'NVD_122': 1.369206041937527, 'NVD_123': 1.369206041937527,
        'NVD_20': 1.440978368745965, 'NVD_21': 1.440978368745965, 'NVD_22': 1.440978368745965,
        'NVD_23': 1.440978368745965, 'NVD_30': 1.192778368745966, 'NVD_40': 1.192778368745966,
        'NVD_50': 2.211668094509451, 'NVD_51': 2.319884094509451, 'NVD_52': 2.355956094509451,
        'NVD_53': 2.049915348334833, 'NVD_60': 2.428100094509452, 'NVD_61': 2.644535094509451,
        'NVD_70': 2.309196348334833, 'NVD_80': 2.072297094509452, 'NVD_81': 2.054835348334833,
        'NVD_82': 2.187648348334833, 'NVD_83': 2.217936348334833, 'NVD_90': 0.095758,
        'NVD_91': 0.095758, 'NVD_92': 0.095758, 'OQC': 0.4965, 'VD7_10': 1.440978368745965,
        'VD7_100': 0.07865, 'VD7_10_1': 1.440978368745965, 'VD7_10_2': 1.440978368745965,
        'VD7_10_3': 1.440978368745965, 'VD7_110': 1.391966041937527, 'VD7_110_1': 1.391966041937527,
        'VD7_110_2': 1.369206041937527, 'VD7_110_3': 1.369206041937527, 'VD7_20': 1.192778368745966,
        'VD7_20_1': 1.192778368745966, 'VD7_30': 1.192778368745966, 'VD7_40': 2.034093348334833,
        'VD7_40_1': 2.025363348334833, 'VD7_50': 2.409155094509451, 'VD7_50_1': 2.382963348334833,
        'VD7_50_2': 2.382963348334833, 'VD7_60': 2.901363348334833, 'VD7_70': 0.085076,
        'VD7_70_1': 0.085076, 'VD7_70_2': 0.085076, 'VD7_80': 2.287055094509451,
        'VD7_80_1': 2.287055094509451, 'VD7_90': 1.907643348334833, 'RMA': 0.08,
    }.items()
}

# 작업자 1인이 한 공정에서 동시에 맡는 수량
UNITS_PER_WORKER_BY_PROCESS_CODE = {'BT5_100': 45, 'NVD_110': 45, 'VD7_100': 45}
DEFAULT_UNITS_PER_WORKER = 1

# 설비 한 번 가동에 동시에 가공하는 수량(CapacityPerCycle)이 AAS에 없을 때
DEFAULT_CAPACITY_PER_CYCLE = 1


# ================================================ 인스턴스 값 만들기: AAS 추출 결과 → 실행 설정, 품목, 자원, 공정·레시피, 흐름, 진입 조건, 제품, 이벤트, 탄소 경계

# 제품 EntryNode 아래 모든 Node의 ItemCode(BOM 품목 코드)
def bom_item_codes(node):
    codes = set()
    for child_node in node.get('Node', []):
        codes |= {child_node['ItemCode']} | bom_item_codes(child_node)
    return codes


class SimulationGenerator:
    RUNTIME_MODEL_CLASS_NAME = 'SimulationModel'

    def __init__(self, extracted, aas_path):
        self.extracted = extracted
        self.aas_path = aas_path
        self.issues = []
        self.simulation = extracted.submodels_with_role('Simulation')[0]
        self.resource = extracted.submodels_with_role('Resource')[0]
        self.process = extracted.submodels_with_role('Process')[0]

    def generate(self):
        instance = {'InstanceInfo': {'aas_path': self.aas_path, 'generated_by': 'simulation_generator.py',
                                     'base_units': self.extracted.base_units}}
        instance['SimulationConfiguration'] = self.extract_SimulationConfiguration()

        instance['Products'] = self.extract_Products()

        instance['MachineUnits'] = self.extract_MachineUnits()
        instance['MachineGroups'] = self.extract_MachineGroups()

        instance['WorkSchedules'] = self.extract_WorkSchedules()
        instance['WorkerGroups'] = self.extract_WorkerGroups()

        instance['Processes'] = self.extract_Processes(instance)

        instance['ProcessFlows'] = self.extract_ProcessFlows()
        for ProcessCode, EntryConditions in self.extract_EntryConditions(instance).items():
            instance['Processes'][ProcessCode]['EntryConditions'] = EntryConditions

        for ProductCode, product_processes in self.extract_ProductProcesses(instance).items():
            instance['Products'][ProductCode].update(product_processes)

        instance['Events'] = self.extract_Events()
        
        instance['CarbonBoundaries'] = self.extract_CarbonBoundaries(instance)
        self.extract_module_values(instance)
        instance['issues'] = self.issues + [vars(issue) for issue in self.extracted.issues]
        return instance

    def extract_module_values(self, instance):
        pass

    # ---------------------------------------------------------------- 실행 설정
    def extract_SimulationConfiguration(self):
        SimulationConfiguration = self.simulation.SimulationConfiguration
        return {
            'RunLength': SimulationConfiguration.Run.RunLength.value,
            'Replications': SimulationConfiguration.Run.Replications.value,
        }

    # ---------------------------------------------------------------- 제품: HierarchicalStructures 구조 그대로(ArcheType, EntryNode, 하위 Node). Node마다 entityType과 Property 값
    def extract_Products(self):
        def node_values(entity):
            values = {'entityType': entity.entityType}
            for child in entity.children:
                if isinstance(child, path_extractor.Property):
                    values[child.idShort] = child.value
                elif isinstance(child, path_extractor.Entity):
                    values.setdefault('Node', []).append(node_values(child))
            return values

        Products = {}
        for hierarchical_structures in self.extracted.submodels_with_role('HierarchicalStructures'):
            entry_node = hierarchical_structures.children[0]
            Products[entry_node.ProductCode.value] = {'ArcheType': hierarchical_structures.ArcheType.value,
                                                      'EntryNode': node_values(entry_node)}
        return Products

    # ---------------------------------------------------------------- 설비 단위: 한 번 가동에 동시에 가공하는 수량, 설비 AAS id(MCF 경계 연결용)
    def extract_MachineUnits(self):
        MachineUnits = {}
        for unit in self.resource.ResourceCategories.Machine.MachineUnit:
            machine_aas = unit.MachineAASRef.jump
            MachineUnits[unit.MachineUnitCode.value] = {
                'MachineUnitCode': unit.MachineUnitCode.value,
                'CapacityPerCycle': unit.CapacityPerCycle.value or DEFAULT_CAPACITY_PER_CYCLE,
                'MaxCapacity': unit.MaxCapacity.value,
                'machine_aas_id': machine_aas.id,
            }
        return MachineUnits

    # ---------------------------------------------------------------- 설비 그룹: 묶인 설비 단위, 작업자 필요 여부
    def extract_MachineGroups(self):
        MachineGroups = {}
        for group in self.resource.ResourceCategories.Machine.MachineGroup:
            MachineGroups[group.MachineGroupCode.value] = {
                'MachineGroupCode': group.MachineGroupCode.value,
                'PoolSize': group.MachinePool.PoolSize.value,
                'MachineUnitCodes': [reference.jump.value for reference in group.MachinePool.MachineUnitList],
                'RequiresOperator': group.RequiresOperator.value,
            }
        return MachineGroups

    # ---------------------------------------------------------------- 근무표: 근무 시작·종료, 휴식 시작·길이
    def extract_WorkSchedules(self):
        WorkSchedules = {}
        for schedule in self.resource.ResourceCategories.Worker.WorkerWorkSchedule:
            WorkSchedules[schedule.WorkScheduleCode.value] = {
                'WorkScheduleCode': schedule.WorkScheduleCode.value,
                'WorkStartTime': schedule.WorkStartTime.value,
                'WorkEndTime': schedule.WorkEndTime.value,
                'BreakStartTime': schedule.BreakStartTime.value,
                'BreakDurationTime': schedule.BreakDurationTime.value or 0.0,
            }
        return WorkSchedules

    # ---------------------------------------------------------------- 작업자 그룹: 인원, 작업자 단위, 근무표
    def extract_WorkerGroups(self):
        WorkerGroups = {}
        for group in self.resource.ResourceCategories.Worker.WorkerGroup:
            WorkerGroupCode = group.WorkerGroupCode.value
            PoolSize = group.WorkerPool.PoolSize.value
            WorkerUnitCodes = [reference.jump.value for reference in group.WorkerPool.WorkerUnitList]
            if len(WorkerUnitCodes) != PoolSize:
                self.issues.append({'kind': '작업자 수', 'message': f'{WorkerGroupCode}: PoolSize {PoolSize}, WorkerUnitList {len(WorkerUnitCodes)}. '
                                                                   f'PoolSize만큼 번호를 붙여 씀'})
                WorkerUnitCodes = [f'{WorkerGroupCode}_{number:03d}' for number in range(1, PoolSize + 1)]
            WorkerGroups[WorkerGroupCode] = {
                'WorkerGroupCode': WorkerGroupCode,
                'PoolSize': PoolSize,
                'WorkerUnitCodes': WorkerUnitCodes,
                'WorkScheduleCode': group.WorkScheduleRef.jump.value,
            }
            if group.UnitsPerWorker:
                self.issues.append({'kind': '미사용 요소', 'message': f'{WorkerGroupCode}.UnitsPerWorker: 공정 값(UNITS_PER_WORKER_BY_PROCESS_CODE)을 씀'})
        return WorkerGroups

    # ---------------------------------------------------------------- 공정과 레시피: 산출 품목 코드만 다른 레시피는 하나로 묶음
    # 레시피 산출 품목 코드가 제품·BOM 품목이면 실제 품목으로 남기고, 없으면 중간재(실행 중 단위마다 코드를 붙임)
    def extract_Processes(self, instance):
        item_codes = set()
        for ProductCode, product in instance['Products'].items():
            item_codes |= {ProductCode} | bom_item_codes(product['EntryNode'])
        Processes = {}
        for category in self.process.ProcessCategories:
            Processes[category.ProcessCode.value] = {
                'ProcessCode': category.ProcessCode.value,
                'RequiresMachine': bool(category.RequiresMachine.value),
                'RequiresWorker': bool(category.RequiresWorker.value),
                'RequiresTransport': bool(category.RequiresTransport.value),
                'UnitsPerWorker': None,
                'Recipes': [],
                'EntryConditions': [],
            }
        recipe_by_key = {}
        for recipe in self.simulation.SimConnector.Relations.Recipes:
            ProcessCode = recipe.ProcessCode.jump.value
            recipe_values = self.recipe_values(recipe)
            key = json.dumps([ProcessCode, recipe_values], sort_keys=True)
            if key not in recipe_by_key:
                recipe_by_key[key] = {**recipe_values, 'recipe_indexes': [], 'OutputItemCodes': []}
                Processes[ProcessCode]['Recipes'].append(recipe_by_key[key])
            instance_recipe = recipe_by_key[key]
            instance_recipe['recipe_indexes'].append(recipe.index_in_parent)
            if recipe.OutputItemCode.value in item_codes:
                instance_recipe['OutputItemCodes'].append(recipe.OutputItemCode.value)
        for ProcessCode, process in Processes.items():
            self.check_process_resources(process, instance['MachineGroups'])
            process['UnitsPerWorker'] = self.units_per_worker_of_process(process)
        return Processes

    # 투입 품목: InputItemCodeRef → Warehouse ItemCodeRef → 품목 CD(idShort가 품목 코드)
    # 자원: ResourceGroupRef·ResourceUnitRef → Resource 코드 요소(WorkerGroupCode 등). 종류는 코드 요소 → 항목 → 목록 → Machine·Worker
    def recipe_values(self, recipe):
        InputItems = []
        for input_item in recipe.InputItemCodeList:
            InputItems.append({'ItemCode': input_item.InputItemCodeRef.jump.jump.idShort,
                               'InputItemQuantity': input_item.InputItemQuantity.value})
        group_code = recipe.ResourceGroupRef.jump
        unit_code = recipe.ResourceUnitRef.jump
        return {
            'InputItems': InputItems,
            'ResourceGroupType': group_code.parent.parent.parent.idShort,
            'ResourceGroupCode': group_code.value,
            'ResourceUnitType': unit_code.parent.parent.parent.idShort,
            'ResourceUnitCode': unit_code.value,
            'CycleTime': recipe.CycleTime.value,
        }

    def check_process_resources(self, process, MachineGroups):
        for recipe in process['Recipes']:
            uses_worker = recipe['ResourceGroupType'] == 'Worker'
            if uses_worker != process['RequiresWorker']:
                self.issues.append({'kind': '공정 자원', 'message': f"{process['ProcessCode']}: RequiresWorker {process['RequiresWorker']}, "
                                                                 f"레시피 자원 그룹 {recipe['ResourceGroupType']} {recipe['ResourceGroupCode']}"})
            uses_machine = recipe['ResourceGroupType'] == 'Machine' or recipe['ResourceUnitType'] == 'Machine'
            if uses_machine != process['RequiresMachine']:
                self.issues.append({'kind': '공정 자원', 'message': f"{process['ProcessCode']}: RequiresMachine {process['RequiresMachine']}, "
                                                                 f"레시피 설비 {recipe['ResourceGroupCode']} {recipe['ResourceUnitCode']}"})
            for MachineGroupCode in self.machine_group_codes_of_recipe(recipe, MachineGroups):
                RequiresOperator = MachineGroups[MachineGroupCode]['RequiresOperator']
                if RequiresOperator is not None and bool(RequiresOperator) != process['RequiresWorker']:
                    self.issues.append({'kind': '작업자 필요 여부', 'message': f"{process['ProcessCode']}: Process RequiresWorker {process['RequiresWorker']}, "
                                                                         f"MachineGroup {MachineGroupCode} RequiresOperator {RequiresOperator}"})

    # 레시피가 쓰는 설비 그룹: ResourceGroupRef가 설비 그룹이면 그 그룹, ResourceUnitRef가 설비면 그 설비가 속한 그룹
    def machine_group_codes_of_recipe(self, recipe, MachineGroups):
        if recipe['ResourceGroupType'] == 'Machine':
            return [recipe['ResourceGroupCode']]
        if recipe['ResourceUnitType'] == 'Machine':
            return [code for code, group in MachineGroups.items() if recipe['ResourceUnitCode'] in group['MachineUnitCodes']]
        return []

    # 작업자 1인이 이 공정에서 동시에 맡는 수량: 코드 사전 → 기본값
    def units_per_worker_of_process(self, process):
        if not process['RequiresWorker']:
            return None
        return UNITS_PER_WORKER_BY_PROCESS_CODE.get(process['ProcessCode'], DEFAULT_UNITS_PER_WORKER)

    # ---------------------------------------------------------------- 공정 흐름: 분기 확률, AAS 진입 조건(EntryConditionList 항목 하나가 진입점, 진입점 간 OR, 진입점 안 AND)
    def extract_ProcessFlows(self):
        ProcessFlows = []
        has_condition_type = False
        for flow in self.simulation.SimConnector.Relations.ProcessFlows:
            entry_condition_groups = []
            for entry_condition in flow.EntryConditionList:
                entry_condition_groups.append([self.condition_of_element(condition) for condition in entry_condition.ConditionList])
                has_condition_type |= any(condition.ConditionType for condition in entry_condition.ConditionList)
            ProcessFlows.append({
                'FromProcessCode': flow.FromProcessRef.jump.value,
                'ToProcessCode': flow.ToProcessRef.jump.value,
                'BranchProbability': flow.BranchProbability.value,
                'aas_entry_condition_groups': entry_condition_groups,
            })
        if has_condition_type:
            self.issues.append({'kind': '템플릿에 없는 요소', 'message': 'Simulation ProcessFlows[].EntryConditionList[].ConditionList[].ConditionType: '
                                                                   '읽어서 쓰지만 템플릿 v1.0에 없음'})
        return ProcessFlows

    # ConditionList 항목 → 조건: 종류는 ConditionType(템플릿에 없는 요소), 대상은 ConditionListRef
    #   ProcessCompleted: → Process ProcessCode / ItemAvailable: → Warehouse ItemCodeRef → 품목 CD / ResourceAvailable: → Resource 코드 요소
    def condition_of_element(self, condition_element):
        ConditionType = condition_element.ConditionType.value
        target = condition_element.ConditionListRef.jump
        condition = {'ConditionType': ConditionType}
        if ConditionType == 'ProcessCompleted':
            condition['ProcessCode'] = target.value
        elif ConditionType == 'ItemAvailable':
            condition['ItemCode'] = target.jump.idShort
        elif ConditionType == 'ResourceAvailable':
            condition.update({'ResourceType': target.parent.parent.parent.idShort, 'ResourceCode': target.value})
        else:
            self.issues.append({'kind': '진입 조건', 'message': f'종류를 모르는 조건: {condition_element.id_short_path}'})
        return condition

    # ---------------------------------------------------------------- 진입 조건(Ready Queue 조건): 들어오는 흐름의 AAS 진입점
    def extract_EntryConditions(self, instance):
        incoming_flows = collections.defaultdict(list)
        for flow in instance['ProcessFlows']:
            incoming_flows[flow['ToProcessCode']].append(flow)
        EntryConditions = {}
        for ProcessCode, process in instance['Processes'].items():
            groups, group_keys = [], set()
            for flow in incoming_flows[ProcessCode]:
                if not flow['aas_entry_condition_groups']:
                    self.issues.append({'kind': '진입 조건', 'message': f"{flow['FromProcessCode']} → {ProcessCode}: EntryConditionList 없음"})
                for group in flow['aas_entry_condition_groups']:
                    key = json.dumps(group, sort_keys=True)
                    if key not in group_keys:
                        group_keys.add(key)
                        groups.append([dict(condition) for condition in group])
            if not incoming_flows[ProcessCode]:
                groups = [self.recipe_conditions(process)]
            for group in groups:
                self.set_item_quantities(process, group)
            EntryConditions[ProcessCode] = groups
        return EntryConditions

    def set_item_quantities(self, process, group):
        quantity_by_item = {input_item['ItemCode']: input_item['InputItemQuantity']
                            for recipe in process['Recipes'][:1] for input_item in recipe['InputItems']}
        for condition in group:
            if condition['ConditionType'] == 'ItemAvailable' and 'Quantity' not in condition:
                if condition['ItemCode'] not in quantity_by_item:
                    self.issues.append({'kind': '진입 조건', 'message': f"{process['ProcessCode']}: 레시피에 없는 투입 품목 {condition['ItemCode']}"})
                condition['Quantity'] = quantity_by_item.get(condition['ItemCode'], 1)

    def recipe_conditions(self, process):
        if not process['Recipes']:
            self.issues.append({'kind': '레시피 없음', 'message': process['ProcessCode']})
            return []
        if len(process['Recipes']) > 1:
            self.issues.append({'kind': '레시피', 'message': f"{process['ProcessCode']}: 투입·자원·CycleTime이 다른 레시피 {len(process['Recipes'])}개. "
                                                           f"진입 조건은 첫 레시피 기준"})
        recipe = process['Recipes'][0]
        conditions = [{'ConditionType': 'ItemAvailable', 'ItemCode': input_item['ItemCode'],
                       'Quantity': input_item['InputItemQuantity']}
                      for input_item in recipe['InputItems']]
        for type_key, code_key in (('ResourceGroupType', 'ResourceGroupCode'), ('ResourceUnitType', 'ResourceUnitCode')):
            if recipe[code_key] is not None:
                conditions.append({'ConditionType': 'ResourceAvailable', 'ResourceType': recipe[type_key],
                                   'ResourceCode': recipe[code_key]})
        return conditions

    # ---------------------------------------------------------------- 제품의 공정
    def extract_ProductProcesses(self, instance):
        # 시작 공정 목록에서 연결표(공정 코드 → 바로 이웃 공정 코드 목록)를 따라 연결된 공정 코드 집합을 찾음
        def connected_process_codes(start_process_codes, neighbor_codes_by_process):
            connected = set()
            pending = list(start_process_codes)
            while pending:
                code = pending.pop()
                if code not in connected:
                    connected.add(code)
                    pending += neighbor_codes_by_process[code]
            return connected

        next_process_codes = collections.defaultdict(list)
        previous_process_codes = collections.defaultdict(list)
        for flow in instance['ProcessFlows']:
            next_process_codes[flow['FromProcessCode']].append(flow['ToProcessCode'])
            previous_process_codes[flow['ToProcessCode']].append(flow['FromProcessCode'])
        final_process_codes_by_product, core_process_codes_by_product = {}, {}
        for ProductCode, product in instance['Products'].items():
            bom_item_codes_of_product = bom_item_codes(product['EntryNode'])
            final_process_codes = [code for code, process in instance['Processes'].items()
                                   if any(ProductCode in recipe['OutputItemCodes'] for recipe in process['Recipes'])]
            start_process_codes = []
            for code, process in instance['Processes'].items():
                input_item_codes = {input_item['ItemCode'] for recipe in process['Recipes'] for input_item in recipe['InputItems']}
                if not previous_process_codes[code] and input_item_codes and input_item_codes <= bom_item_codes_of_product:
                    start_process_codes.append(code)
            final_process_codes_by_product[ProductCode] = final_process_codes
            core_process_codes_by_product[ProductCode] = (connected_process_codes(start_process_codes, next_process_codes)
                                                          & connected_process_codes(final_process_codes, previous_process_codes))
        core_count = collections.Counter(code for codes in core_process_codes_by_product.values() for code in codes)
        shared_process_codes = {code for code, count in core_count.items() if count > 1}
        ProductProcesses = {}
        for ProductCode, core_process_codes in core_process_codes_by_product.items():
            previous_without_shared = collections.defaultdict(list)
            for code, previous_codes in previous_process_codes.items():
                if code not in shared_process_codes:
                    previous_without_shared[code] = [previous for previous in previous_codes if previous not in shared_process_codes]
            process_codes = connected_process_codes(core_process_codes - shared_process_codes, previous_without_shared)
            process_codes |= core_process_codes
            final_process_codes = final_process_codes_by_product[ProductCode]
            if not final_process_codes or not core_process_codes:
                self.issues.append({'kind': '제품', 'message': f'{ProductCode}: 마지막 공정 {final_process_codes}, 중심 공정 {len(core_process_codes)}개'})
            ProductProcesses[ProductCode] = {
                'final_process_codes': final_process_codes,
                'start_process_codes': sorted(code for code in process_codes if not previous_process_codes[code]),
                'process_codes': sorted(process_codes),
                'shared_process_codes': sorted(process_codes & shared_process_codes),
            }
        return ProductProcesses

    # ---------------------------------------------------------------- 이벤트: 종류(DistributionUnit)별 동작. 멈춤 시간은 event_duration(모듈이 재정의)
    def extract_Events(self):
        Events = []
        found_non_template_elements = set()
        for event in self.simulation.SimConnector.Relations.Events:
            trigger = event.TriggerDistribution
            if trigger.DistributionUnit:
                found_non_template_elements.add('TriggerDistribution.DistributionUnit')
            if event.HandlingProcessRef:
                found_non_template_elements.add('HandlingProcessRef')
            EventCode = event.EventCode.value
            Events.append({
                'EventCode': EventCode,
                'DistributionType': trigger.DistributionType.value,
                'Parameters': [parameter.DistributionParameter.value for parameter in trigger.Parameters],
                'DistributionUnit': trigger.DistributionUnit.value,
                'TargetProcessCode': event.TargetProcessRef.jump.value,
                'TargetUnitResourceCode': event.TargetUnitResourceRef.jump.value,
                'TargetItemCode': event.TargetItemRef.jump.jump.idShort,
                'HandlingProcessCode': event.HandlingProcessRef.jump.value,
                **self.event_duration(EventCode),
            })
        for event in Events:
            if event['DistributionUnit'] == 'OutputItem' and not event['HandlingProcessCode']:
                self.issues.append({'kind': '이벤트', 'message': f"{event['EventCode']}: 처리 공정 없음"})
        for element_path in sorted(found_non_template_elements):
            self.issues.append({'kind': '템플릿에 없는 요소', 'message': f'Simulation Events[].{element_path}: 읽어서 쓰지만 템플릿 v1.0 Events에 없음'})
        return Events

    def event_duration(self, EventCode):
        return {'Duration': None}

    # ---------------------------------------------------------------- 탄소 경계(MCF 폴더의 MCF Submodel마다): 묶인 공정, 활동량을 쌓는 시간, 탄소 구성요소 줄
    def extract_CarbonBoundaries(self, instance):
        process_code_by_recipe_index = {index: code for code, process in instance['Processes'].items()
                                        for recipe in process['Recipes'] for index in recipe['recipe_indexes']}
        CarbonBoundaries = {}
        for mcf in self.extracted.submodels_with_role('MCF'):
            process_resource = mcf.ManufacturingProcess.ProcessResource
            resource_aas = process_resource.ResourceRef.jump
            recipe_indexes = []
            for mcf_recipe in mcf.ManufacturingProcess.Recipes:
                for output in mcf_recipe.Output:
                    simulation_output_code = output.OutputItemCode.jump
                    if not simulation_output_code:
                        self.issues.append({'kind': 'MCF 레시피', 'message': f'{mcf.id} Output 참조를 따라갈 수 없음'})
                        continue
                    recipe_indexes.append(simulation_output_code.parent.index_in_parent)
            ProcessCodes = sorted({process_code_by_recipe_index[index] for index in recipe_indexes})
            MachineUnitCode = self.machine_unit_code_of_aas(instance, resource_aas)
            CarbonBoundaries[mcf.id] = {
                'mcf_submodel_id': mcf.id,
                'ResourceType': process_resource.ResourceType.value,
                'resource_aas_id': resource_aas.id,
                'MachineUnitCode': MachineUnitCode,
                'recipe_indexes': recipe_indexes,
                'ProcessCodes': ProcessCodes,
                'activity_basis': 'machine_on_time' if MachineUnitCode else 'process_time',
                'carbon_elements': self.carbon_elements(mcf, resource_aas, ProcessCodes),
            }
        covered = {code for boundary in CarbonBoundaries.values() for code in boundary['ProcessCodes']}
        uncovered = sorted(set(instance['Processes']) - covered)
        if uncovered:
            self.issues.append({'kind': '탄소 경계', 'message': f'MCF에 묶이지 않은 공정 {uncovered}'})
        return CarbonBoundaries

    def machine_unit_code_of_aas(self, instance, resource_aas):
        for MachineUnitCode, unit in instance['MachineUnits'].items():
            if unit['machine_aas_id'] == resource_aas.id:
                return MachineUnitCode
        return None

    # 탄소 구성요소
    def carbon_elements(self, mcf, resource_aas, ProcessCodes):
        element_lists = [*mcf.AncillaryInputs, mcf.Residuals.Waste, *mcf.Residuals.Releases]
        carbon_elements = []
        for element_list in element_lists:
            category = element_list.idShort
            for line in element_list:
                activity_rate_by_process_code = {}
                for ProcessCode in ProcessCodes:
                    activity_rate = self.activity_rate(category, resource_aas, ProcessCode)
                    if activity_rate is not None:
                        activity_rate_by_process_code[ProcessCode] = activity_rate
                carbon_elements.append({
                    'category': category,
                    'ClassificationType': line.ClassificationType.value,
                    'AmountUnit': line.AmountUnit.value,
                    'RefEmissionFactor': line.RefEmissionFactor.value,
                    'RefImpactUnitforCalculation': line.RefImpactUnitforCalculation.value,
                    'given_Amount': line.Amount.value,
                    'activity_rate_by_process_code': activity_rate_by_process_code,
                    'amount_path': f'{line.id_short_path}.Amount',
                })
        return carbon_elements

    def activity_rate(self, category, resource_aas, ProcessCode):
        semantic_id = ACTIVITY_DATA_BASIS_SEMANTIC_ID.get(category)
        if semantic_id is not None and resource_aas:
            for element in self.extracted.elements_with_semantic_id(semantic_id):
                if element.submodel in resource_aas.submodels and element.value is not None:
                    return {'rate': element.value, 'rate_unit': element.base_unit or element.unit}
        return CARBON_ACTIVITY_RATE_BY_PROCESS_CODE.get(ProcessCode, {}).get(category)


# ================================================ 시뮬레이션 인스턴스 실행 코드: 아래 정의를 그대로 인스턴스 py 파일에 옮김. 시나리오 모듈은 SimulationModel을 상속해 메서드를 재정의 ================================================
SECONDS_PER_HOUR = 3600.0
SECONDS_PER_DAY = 86400.0
TIME_TOLERANCE = 1e-9
BRANCH_PROBABILITY_TOLERANCE = 1e-9


# ---------------------------------------------------------------- 리소스 요소: 설비 단위, 작업자 그룹
# 설비 단위: 한 번 가동에 동시에 가공하는 수량(CapacityPerCycle)만큼 슬롯. 켜진 시간을 설비 MCF 활동량으로 넘김
class MachineElement:
    def __init__(self, environment, unit, carbon_boundary):
        self.environment = environment
        self.MachineUnitCode = unit['MachineUnitCode']
        self.resource = simpy.Resource(environment, capacity=unit['CapacityPerCycle'])
        self.carbon_boundary = carbon_boundary
        self.use_count_by_process = collections.Counter()
        self.on_since = None
        # ---------------- 생산성 요소: 켜진 시간(h, 하나라도 가공 중인 시간), 가공 횟수
        self.on_hours = 0.0
        self.cycle_count = 0

    def start_use(self, ProcessCode):
        if not +self.use_count_by_process:
            self.on_since = self.environment.now
        self.use_count_by_process[ProcessCode] += 1

    def end_use(self, ProcessCode):
        self.use_count_by_process[ProcessCode] -= 1
        self.cycle_count += 1
        if not +self.use_count_by_process:
            self.add_on_time(ProcessCode)

    def add_on_time(self, ProcessCode):
        hours = (self.environment.now - self.on_since) / SECONDS_PER_HOUR
        self.on_hours += hours
        self.on_since = self.environment.now
        if self.carbon_boundary is not None and self.carbon_boundary.activity_basis == 'machine_on_time':
            self.carbon_boundary.add_operating_time(ProcessCode, hours)

    # 실행이 끝날 때 켜져 있는 설비의 시간을 마저 더함
    def close_on_time(self):
        in_use = +self.use_count_by_process
        if in_use:
            self.add_on_time(next(iter(in_use)))


# 작업자 그룹: 작업자마다 한 공정의 작업을 UnitsPerWorker(공정 값)만큼 동시에 맡음, 공정별 대기 작업
class WorkerGroupElement:
    def __init__(self, environment, group, schedule):
        self.environment = environment
        self.WorkerGroupCode = group['WorkerGroupCode']
        self.schedule = schedule
        self.workers = [{'WorkerUnitCode': code, 'ProcessCode': None, 'job_count': 0, 'busy_since': None, 'busy_hours': 0.0}
                        for code in group['WorkerUnitCodes']]
        self.waiting_jobs_by_process = collections.defaultdict(collections.deque)
        self.wake_event = environment.event()
        self.busy_worker_count = 0
        self.busy_since = None
        # ---------------- 생산성 요소: 그룹 작업 시간(h, 한 명이라도 작업 중인 시간), 작업자별 작업 시간(h, 작업이 하나라도 있는 시간), 작업 수
        self.busy_hours = 0.0
        self.job_count = 0

    def has_waiting_jobs(self):
        return any(self.waiting_jobs_by_process.values())

    # 같은 공정을 맡고 있고 자리가 남은 작업자 → 쉬는 작업자
    def available_worker(self, ProcessCode, UnitsPerWorker):
        for worker in self.workers:
            if worker['job_count'] and worker['ProcessCode'] == ProcessCode and worker['job_count'] < UnitsPerWorker:
                return worker
        for worker in self.workers:
            if not worker['job_count']:
                return worker
        return None

    def start_job(self, worker, ProcessCode):
        if not worker['job_count']:
            worker['ProcessCode'] = ProcessCode
            worker['busy_since'] = self.environment.now
            if not self.busy_worker_count:
                self.busy_since = self.environment.now
            self.busy_worker_count += 1
        worker['job_count'] += 1

    def end_job(self, worker):
        worker['job_count'] -= 1
        self.job_count += 1
        if not worker['job_count']:
            self.close_worker_busy_time(worker)

    def close_worker_busy_time(self, worker):
        worker['busy_hours'] += (self.environment.now - worker['busy_since']) / SECONDS_PER_HOUR
        worker['ProcessCode'] = None
        self.busy_worker_count -= 1
        if not self.busy_worker_count:
            self.busy_hours += (self.environment.now - self.busy_since) / SECONDS_PER_HOUR

    # 실행이 끝날 때 작업 중인 시간을 마저 더함
    def close_busy_time(self):
        for worker in self.workers:
            if worker['job_count']:
                worker['busy_hours'] += (self.environment.now - worker['busy_since']) / SECONDS_PER_HOUR
                worker['busy_since'] = self.environment.now
        if self.busy_worker_count:
            self.busy_hours += (self.environment.now - self.busy_since) / SECONDS_PER_HOUR
            self.busy_since = self.environment.now


# ---------------------------------------------------------------- 탄소 요소: 탄소 구성요소 한 줄, 탄소 경계(MCF 하나)
class CarbonElement:
    def __init__(self, element):
        self.category = element['category']
        self.ClassificationType = element['ClassificationType']
        self.AmountUnit = element['AmountUnit']
        self.RefEmissionFactor = element['RefEmissionFactor'] or 0.0
        self.activity_rate_by_process_code = element['activity_rate_by_process_code']
        self.amount_path = element['amount_path']
        self.is_given_amount = element['given_Amount'] is not None
        self.Amount = element['given_Amount'] or 0.0

    def add_activity(self, ProcessCode, hours):
        activity_rate = self.activity_rate_by_process_code.get(ProcessCode)
        if activity_rate is not None and not self.is_given_amount:
            self.Amount += activity_rate['rate'] * hours

    def ContributionCO2eq(self):
        return self.Amount * self.RefEmissionFactor


# 탄소 경계(MCF 하나)
class CarbonBoundary:
    def __init__(self, boundary):
        self.mcf_submodel_id = boundary['mcf_submodel_id']
        self.activity_basis = boundary['activity_basis']
        self.OperatingTime = 0.0
        self.carbon_elements = [CarbonElement(element) for element in boundary['carbon_elements']]

    def record_process_execution(self, ProcessCode, hours):
        if self.activity_basis == 'process_time':
            self.add_operating_time(ProcessCode, hours)

    def add_operating_time(self, ProcessCode, hours):
        self.OperatingTime += hours
        for carbon_element in self.carbon_elements:
            carbon_element.add_activity(ProcessCode, hours)

    def SumCO2eq(self):
        return sum(carbon_element.ContributionCO2eq() for carbon_element in self.carbon_elements)

    def result(self):
        return {
            'OperatingTime': self.OperatingTime,
            'carbon_elements': [{'category': element.category, 'ClassificationType': element.ClassificationType,
                                 'Amount': element.Amount, 'AmountUnit': element.AmountUnit,
                                 'ContributionCO2eq': element.ContributionCO2eq(), 'amount_path': element.amount_path}
                                for element in self.carbon_elements],
            'SumCO2eq': self.SumCO2eq(),
        }


# ---------------------------------------------------------------- 시뮬레이션 모델: 위 요소를 만들고 제품·작업자·이벤트 SimPy 프로세스를 돌림
class SimulationModel:
    def __init__(self, instance, seed, target_quantity_by_product):
        self.instance = instance
        self.environment = simpy.Environment()
        self.random = random.Random(seed)
        self.event_random = random.Random(f'{seed}-event')
        self.target_quantity_by_product = target_quantity_by_product
        self.stop_event = self.environment.event()
        self.build_elements()
        self.build_routes()

    # ---------------------------------------------------------------- 준비: 요소 만들기, 흐름표·이벤트 대상표
    def build_elements(self):
        instance = self.instance
        self.carbon_boundaries = {key: CarbonBoundary(boundary) for key, boundary in instance['CarbonBoundaries'].items()}
        self.carbon_boundary_by_process = {}
        boundary_by_machine = {}
        for key, boundary in instance['CarbonBoundaries'].items():
            for ProcessCode in boundary['ProcessCodes']:
                self.carbon_boundary_by_process[ProcessCode] = self.carbon_boundaries[key]
            if boundary['MachineUnitCode']:
                boundary_by_machine[boundary['MachineUnitCode']] = self.carbon_boundaries[key]
        self.machines = {code: MachineElement(self.environment, unit, boundary_by_machine.get(code))
                         for code, unit in instance['MachineUnits'].items()}
        self.worker_groups = {code: WorkerGroupElement(self.environment, group, instance['WorkSchedules'][group['WorkScheduleCode']])
                              for code, group in instance['WorkerGroups'].items()}
        self.self_produced_item_codes = self.module_produced_item_codes()
        self.stock = collections.Counter()
        self.stock_event = self.environment.event()
        self.purchased_item_use = collections.Counter()
        self.ready_order_counter = itertools.count()
        # ---------------- 생산성 요소: 제품별 생산량·완료 시각(목표 수량 도달, 한 대마다), 공정별 완료 수, 불량·수리 수
        self.production_quantity_by_product = collections.Counter()
        self.completion_time_by_product = {}
        self.completion_times_by_product = collections.defaultdict(list)
        self.completed_count_by_process = collections.Counter()
        self.defect_count_by_process = collections.Counter()
        self.repair_count_by_product = collections.Counter()
        self.stuck_unit_count = 0

    def build_routes(self):
        self.flows_from = collections.defaultdict(list)
        for flow in self.instance['ProcessFlows']:
            self.flows_from[flow['FromProcessCode']].append(flow)
        self.events_by_kind_and_target = collections.defaultdict(list)
        self.remaining_until_event = {}
        for event in self.instance['Events']:
            for target in {event['TargetProcessCode'], event['TargetUnitResourceCode']} - {None}:
                self.events_by_kind_and_target[(event['DistributionUnit'], target)].append(event)
            self.remaining_until_event[event['EventCode']] = self.sample_event_interval(event)

    # ---------------------------------------------------------------- 품목(진입 조건 ItemAvailable): 자체 생산 품목은 재고에서 꺼냄(모자라면 착수 불가), 구매 품목은 사용 수만 기록
    def item_conditions(self, ProcessCode):
        groups = self.instance['Processes'][ProcessCode]['EntryConditions']
        return [condition for condition in groups[0] if condition['ConditionType'] == 'ItemAvailable'] if groups else []

    def are_input_items_available(self, ProcessCode):
        for condition in self.item_conditions(ProcessCode):
            if condition['ItemCode'] in self.self_produced_item_codes and self.stock[condition['ItemCode']] < condition['Quantity']:
                return False
        return True

    def consume_input_items(self, ProcessCode):
        for condition in self.item_conditions(ProcessCode):
            if condition['ItemCode'] in self.self_produced_item_codes:
                self.stock[condition['ItemCode']] -= condition['Quantity']
            else:
                self.purchased_item_use[condition['ItemCode']] += condition['Quantity']

    def add_stock(self, ItemCode, quantity):
        self.stock[ItemCode] += quantity
        stock_event, self.stock_event = self.stock_event, self.environment.event()
        stock_event.succeed()

    # ---------------------------------------------------------------- 리소스 ① 근무시간: 근무표의 시작~휴식 시작, 휴식 끝~종료 구간. 근무표가 없으면 제한 없음
    def work_windows(self, schedule):
        start, end = schedule['WorkStartTime'], schedule['WorkEndTime']
        if schedule['BreakStartTime'] is None or not schedule['BreakDurationTime']:
            return [(start, end)]
        return [(start, schedule['BreakStartTime']), (schedule['BreakStartTime'] + schedule['BreakDurationTime'], end)]

    def current_window_end(self, schedule):
        if schedule is None:
            return math.inf
        time_of_day = self.environment.now % SECONDS_PER_DAY
        for window_start, window_end in self.work_windows(schedule):
            if window_start - TIME_TOLERANCE <= time_of_day < window_end - TIME_TOLERANCE:
                return self.environment.now + window_end - time_of_day
        return None

    def seconds_until_next_window(self, schedule):
        time_of_day = self.environment.now % SECONDS_PER_DAY
        for window_start, _ in self.work_windows(schedule):
            if window_start > time_of_day + TIME_TOLERANCE:
                return window_start - time_of_day
        return SECONDS_PER_DAY - time_of_day + self.work_windows(schedule)[0][0]

    def wait_for_work_time(self, schedule, duration=0.0):
        while True:
            window_end = self.current_window_end(schedule)
            if window_end is not None and window_end - self.environment.now + TIME_TOLERANCE >= duration:
                return
            yield self.environment.timeout(self.seconds_until_next_window(schedule))

    def schedule_of(self, WorkScheduleCode):
        return self.instance['WorkSchedules'].get(WorkScheduleCode) if WorkScheduleCode else None

    # ---------------------------------------------------------------- 리소스 ② 설비 고르기: 레시피 설비 단위, 설비 그룹이면 대기가 가장 적은 설비
    def machine_for_recipe(self, ProcessCode, recipe):
        if not self.instance['Processes'][ProcessCode]['RequiresMachine']:
            return None
        if recipe['ResourceUnitType'] == 'Machine':
            return self.machines[recipe['ResourceUnitCode']]
        if recipe['ResourceGroupType'] == 'Machine':
            machines = [self.machines[code] for code in self.instance['MachineGroups'][recipe['ResourceGroupCode']]['MachineUnitCodes']]
            return min(machines, key=lambda machine: len(machine.resource.queue) + machine.resource.count)
        return None

    # ---------------------------------------------------------------- 리소스 ③ 작업자 그룹 작업 배정(진입 조건 ResourceAvailable·ItemAvailable)
    def wake_worker_group(self, group):
        if not group.wake_event.triggered:
            group.wake_event.succeed()

    def dispatch_worker_group(self, group):
        while True:
            if not group.has_waiting_jobs():
                group.wake_event = self.environment.event()
                yield group.wake_event
                continue
            yield from self.wait_for_work_time(group.schedule)
            candidate_jobs = self.candidate_jobs(group)
            if not candidate_jobs:
                group.wake_event = self.environment.event()
                waits = [group.wake_event, self.stock_event,
                         self.environment.timeout(self.seconds_until_next_window(group.schedule))]
                yield simpy.AnyOf(self.environment, waits)
                continue
            job = self.select_job(group, candidate_jobs)
            worker = group.available_worker(job['ProcessCode'], self.units_per_worker(job['ProcessCode']))
            group.waiting_jobs_by_process[job['ProcessCode']].remove(job)
            self.consume_input_items(job['ProcessCode'])
            group.start_job(worker, job['ProcessCode'])
            self.environment.process(self.run_worker_job(group, worker, job))

    def units_per_worker(self, ProcessCode):
        return self.instance['Processes'][ProcessCode]['UnitsPerWorker']

    def candidate_jobs(self, group):
        window_end = self.current_window_end(group.schedule)
        if window_end is None:
            return []
        remaining_time = window_end - self.environment.now + TIME_TOLERANCE
        candidates = []
        for ProcessCode, jobs in group.waiting_jobs_by_process.items():
            if not jobs or jobs[0]['recipe']['CycleTime'] > remaining_time:
                continue
            if group.available_worker(ProcessCode, self.units_per_worker(ProcessCode)) is None:
                continue
            if self.are_input_items_available(ProcessCode):
                candidates.append(jobs[0])
        return candidates

    # 강화학습·시나리오가 재정의하는 의사결정 지점: 기본은 먼저 대기에 들어온 작업
    def select_job(self, group, candidate_jobs):
        return min(candidate_jobs, key=lambda job: job['ready_order'])

    def run_worker_job(self, group, worker, job):
        ProcessCode, recipe = job['ProcessCode'], job['recipe']
        machine = self.machine_for_recipe(ProcessCode, recipe)
        machine_request = None
        if machine is not None:
            machine_request = machine.resource.request()
            yield machine_request
            machine.start_use(ProcessCode)
        start_time = self.environment.now
        yield self.environment.timeout(recipe['CycleTime'])
        if machine is not None:
            machine.end_use(ProcessCode)
            machine.resource.release(machine_request)
        group.end_job(worker)
        self.record_process_execution(ProcessCode, self.environment.now - start_time)
        job['finished'].succeed()
        self.wake_worker_group(group)

    # ---------------------------------------------------------------- 시뮬레이션 ① 실행 시작과 종료: 목표 수량만큼 제품 투입, 작업자 그룹 배정, 모듈 프로세스, 시나리오 프로세스
    def start(self):
        for ProductCode, quantity in self.target_quantity_by_product.items():
            for _ in range(quantity):
                self.environment.process(self.produce_unit(ProductCode))
        for group in self.worker_groups.values():
            self.environment.process(self.dispatch_worker_group(group))
        self.start_module_processes()
        self.start_scenario_processes()
        self.environment.process(self.stop_at_run_length())

    # 시나리오 모듈이 SimPy 프로세스를 더 붙이는 자리(작업자 재배치 등)
    def start_scenario_processes(self):
        pass

    def is_target_reached(self):
        for ProductCode, quantity in self.target_quantity_by_product.items():
            if self.production_quantity_by_product[ProductCode] < quantity:
                return False
        return self.is_module_finished()

    def stop_if_target_reached(self):
        if self.is_target_reached() and not self.stop_event.triggered:
            self.stop_event.succeed()

    def stop_at_run_length(self):
        yield self.environment.timeout(self.instance['SimulationConfiguration']['RunLength'])
        if not self.stop_event.triggered:
            self.stop_event.succeed()

    def run(self):
        self.start()
        self.environment.run(until=self.stop_event)
        for machine in self.machines.values():
            machine.close_on_time()
        for group in self.worker_groups.values():
            group.close_busy_time()
        self.close_module_records()
        return self.result()

    # ---------------------------------------------------------------- 시뮬레이션 ② 레시피 실행: 작업자 공정은 작업자 그룹 대기열로, 그 밖은 설비 확보(없으면 시간만)
    def execute_recipe(self, ProcessCode, recipe):
        if self.instance['Processes'][ProcessCode]['RequiresWorker'] and recipe['ResourceGroupType'] == 'Worker':
            finished = self.environment.event()
            group = self.worker_groups[recipe['ResourceGroupCode']]
            group.waiting_jobs_by_process[ProcessCode].append(
                {'ProcessCode': ProcessCode, 'recipe': recipe, 'finished': finished, 'ready_time': self.environment.now,
                 'ready_order': next(self.ready_order_counter)})
            self.wake_worker_group(group)
            yield finished
            return
        yield from self.occupy_machine_and_process(ProcessCode, recipe)

    def occupy_machine_and_process(self, ProcessCode, recipe):
        machine = self.machine_for_recipe(ProcessCode, recipe)
        request = None
        if machine is not None:
            request = machine.resource.request()
            yield request
            machine.start_use(ProcessCode)
        self.consume_input_items(ProcessCode)
        yield self.environment.timeout(recipe['CycleTime'])
        if machine is not None:
            machine.end_use(ProcessCode)
            machine.resource.release(request)
        self.record_process_execution(ProcessCode, recipe['CycleTime'])

    def record_process_execution(self, ProcessCode, duration):
        self.completed_count_by_process[ProcessCode] += 1
        boundary = self.carbon_boundary_by_process.get(ProcessCode)
        if boundary is not None:
            boundary.record_process_execution(ProcessCode, duration / SECONDS_PER_HOUR)

    # ---------------------------------------------------------------- 시뮬레이션 ③ 공정 흐름·진입 조건: 제품 한 대가 진입 조건(선행 공정)을 채운 공정 실행 → 흐름에 따라 다음 공정 → 마지막 공정에서 생산량 기록
    def produce_unit(self, ProductCode):
        product = self.instance['Products'][ProductCode]
        unit = {'ProductCode': ProductCode, 'OutputItemCode': None, 'output_code_by_process': {},
                'completed': set(), 'running': set(), 'arrived_from': collections.defaultdict(set)}
        running_events = []
        while not set(product['final_process_codes']) & unit['completed']:
            for ProcessCode in self.ready_process_codes(unit, product):
                unit['running'].add(ProcessCode)
                running_events.append(self.environment.process(self.run_process_of_unit(unit, ProcessCode)))
            running_events = [event for event in running_events if not event.triggered]
            if not running_events:
                self.stuck_unit_count += 1
                return
            yield simpy.AnyOf(self.environment, running_events)
        self.production_quantity_by_product[ProductCode] += 1
        self.completion_times_by_product[ProductCode].append(self.environment.now)
        if self.production_quantity_by_product[ProductCode] == self.target_quantity_by_product.get(ProductCode):
            self.completion_time_by_product[ProductCode] = self.environment.now
        self.stop_if_target_reached()

    # 진입 조건 OR 묶음 가운데 하나의 선행 공정 완료 조건을 모두 채운 공정. 투입 품목·자원 조건은 작업 배정 때 확인
    def ready_process_codes(self, unit, product):
        ready = []
        for ProcessCode in product['process_codes']:
            if ProcessCode in unit['completed'] or ProcessCode in unit['running']:
                continue
            if ProcessCode not in product['start_process_codes'] and not unit['arrived_from'][ProcessCode]:
                continue
            for group in self.instance['Processes'][ProcessCode]['EntryConditions']:
                if all(self.is_process_condition_met(unit, ProcessCode, condition) for condition in group):
                    ready.append(ProcessCode)
                    break
        return ready

    def is_process_condition_met(self, unit, ProcessCode, condition):
        if condition['ConditionType'] != 'ProcessCompleted':
            return True
        return condition['ProcessCode'] in unit['arrived_from'][ProcessCode]

    def run_process_of_unit(self, unit, ProcessCode):
        recipe = self.instance['Processes'][ProcessCode]['Recipes'][0]
        input_codes = self.input_codes_of_unit(unit, ProcessCode)
        yield from self.execute_recipe(ProcessCode, recipe)
        is_final = ProcessCode in self.instance['Products'][unit['ProductCode']]['final_process_codes']
        OutputItemCode = self.output_item_code(ProcessCode, input_codes, unit['ProductCode'] if is_final else None)
        self.set_unit_output_code(unit, ProcessCode, OutputItemCode)
        self.record_output(ProcessCode, OutputItemCode, recipe['CycleTime'])
        yield from self.handle_defect_events(unit, ProcessCode)
        unit['running'].discard(ProcessCode)
        unit['completed'].add(ProcessCode)
        self.release_next_processes(unit, ProcessCode)

    # 분기: 이 제품의 공정으로 가는 흐름만. 확률 합이 1인 여러 흐름은 하나를 고르고, 그 밖은 흐름마다 확률로
    def release_next_processes(self, unit, ProcessCode):
        product_process_codes = self.instance['Products'][unit['ProductCode']]['process_codes']
        flows = [flow for flow in self.flows_from[ProcessCode] if flow['ToProcessCode'] in product_process_codes]
        probability_sum = sum(flow['BranchProbability'] for flow in flows)
        if len(flows) > 1 and abs(probability_sum - 1.0) < BRANCH_PROBABILITY_TOLERANCE:
            flows = self.random.choices(flows, weights=[flow['BranchProbability'] for flow in flows])
        else:
            flows = [flow for flow in flows if self.random.random() < flow['BranchProbability']]
        for flow in flows:
            unit['arrived_from'][flow['ToProcessCode']].add(ProcessCode)

    # ---------------------------------------------------------------- 시뮬레이션 ③ 산출 품목 코드(템플릿 규칙): 완제품·부품은 ItemCode, 그 밖은 '{ProcessCode}[정렬한 투입 코드를 +로 연결]'
    # 투입 코드 = 레시피 투입 품목 코드만. 앞 공정 중간재는 넣지 않음(11-18 시험). 규칙을 바꿀 때 이 두 메서드를 재정의
    def output_item_code(self, ProcessCode, input_codes, ItemCode=None):
        if ItemCode is not None:
            return ItemCode
        return f"{ProcessCode}[{'+'.join(sorted(input_codes))}]"

    def input_codes_of_unit(self, unit, ProcessCode):
        return [condition['ItemCode'] for condition in self.item_conditions(ProcessCode)]

    def set_unit_output_code(self, unit, ProcessCode, OutputItemCode):
        unit['output_code_by_process'][ProcessCode] = OutputItemCode
        unit['OutputItemCode'] = OutputItemCode

    # ---------------------------------------------------------------- 시뮬레이션 ④ 이벤트: 분포에서 뽑은 횟수(산출 수량·품목 변경 횟수)마다 발생
    def sample_event_interval(self, event):
        mean = event['Parameters'][0]
        if event['DistributionType'] == 'Exponential':
            return self.event_random.expovariate(1.0 / mean)
        return mean

    def is_event_due(self, event):
        self.remaining_until_event[event['EventCode']] -= 1
        if self.remaining_until_event[event['EventCode']] > 0:
            return False
        self.remaining_until_event[event['EventCode']] += self.sample_event_interval(event)
        return True

    # 불량: 대상 공정의 산출 수량 간격마다 → 처리 공정(HandlingProcess)을 거친 뒤 계속. 처리 공정은 ProcessFlows에 없어 단위의 산출 코드는 들어온 중간재 코드를 그대로 둠
    # 처리 공정 MCF에는 처리 공정 레시피 규칙의 산출 코드로 기록
    def handle_defect_events(self, unit, ProcessCode):
        for event in self.events_by_kind_and_target.get(('OutputItem', ProcessCode), []):
            if not self.is_event_due(event):
                continue
            self.defect_count_by_process[ProcessCode] += 1
            HandlingProcessCode = event['HandlingProcessCode']
            handling_recipe = self.instance['Processes'][HandlingProcessCode]['Recipes'][0]
            yield from self.execute_recipe(HandlingProcessCode, handling_recipe)
            self.record_output(HandlingProcessCode, self.output_item_code(HandlingProcessCode, self.input_codes_of_unit(unit, HandlingProcessCode)),
                               handling_recipe['CycleTime'])
            self.repair_count_by_product[unit['ProductCode']] += 1

    # ---------------------------------------------------------------- 결과: 생산성 요소와 탄소 요소
    def result(self):
        return {
            'end_time': self.environment.now,
            'target_reached': self.is_target_reached(),
            'productivity': {
                'production_quantity_by_product': dict(self.production_quantity_by_product),
                'completion_time_by_product': self.completion_time_by_product,
                'stuck_unit_count': self.stuck_unit_count,
                'defect_count_by_process': dict(self.defect_count_by_process),
                'repair_count_by_product': dict(self.repair_count_by_product),
                'worker_group_busy_hours': {code: group.busy_hours for code, group in self.worker_groups.items()},
                'worker_busy_hours': {worker['WorkerUnitCode']: worker['busy_hours']
                                      for group in self.worker_groups.values() for worker in group.workers},
                'worker_group_job_count': {code: group.job_count for code, group in self.worker_groups.items()},
                'machine_on_hours': {code: machine.on_hours for code, machine in self.machines.items()},
                'machine_cycle_count': {code: machine.cycle_count for code, machine in self.machines.items()},
                'completion_times_by_product': dict(self.completion_times_by_product),
            },
            'carbon': {
                'SumCO2eq_total': sum(boundary.SumCO2eq() for boundary in self.carbon_boundaries.values()),
                'boundaries': {key: boundary.result() for key, boundary in self.carbon_boundaries.items()},
            },
        }

    # ---------------------------------------------------------------- 모듈(SMT 라인, 기저부하, MCF 계산 등)이 재정의하는 자리: 공장에서 만들어 재고로 쓰는 품목, 모듈 SimPy 프로세스, 모듈 종료 여부, 실행 끝 기록 마감, 산출물 기록
    # 모듈은 super()를 불러 다른 모듈과 함께 동작
    def module_produced_item_codes(self):
        return set()

    def start_module_processes(self):
        pass

    def is_module_finished(self):
        return True

    def close_module_records(self):
        pass

    # 공정 실행 1회의 산출물(산출 품목 코드, 처리 시간, 산출 수량). 조립 공정·처리 공정(RMA)·SMT 단계가 부름
    def record_output(self, ProcessCode, OutputItemCode, duration, output_quantity=1):
        pass


def load_instance(instance_file_path):
    with open(instance_file_path, encoding='utf-8') as instance_file:
        return json.load(instance_file)


def run_replications(model_class, instance, replications, seed, target_quantity_by_product):
    results = []
    for replication in range(replications):
        model = model_class(instance, seed + replication, target_quantity_by_product)
        results.append(model.run())
    return results


def print_result_summary(results):
    for replication, result in enumerate(results):
        productivity = result['productivity']
        print(f"[{replication}] 종료 {result['end_time']:,.0f} s | 목표 달성 {result['target_reached']} | "
              f"생산량 {productivity['production_quantity_by_product']} | "
              f"탄소배출량 {result['carbon']['SumCO2eq_total']:,.4f} kgCO2eq")


# 시나리오 모듈: main(DEFAULT_MODEL_CLASS를 상속한 클래스)
def main(model_class=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('--instance', default=INSTANCE_FILE_PATH)
    parser.add_argument('--replications', type=int)
    parser.add_argument('--seed', type=int, default=0)
    parser.add_argument('--quantity', type=int, required=True, help='제품별 목표 수량(템플릿에 수요 칸이 없어 실행마다 입력)')
    parser.add_argument('--output', default=os.path.splitext(INSTANCE_FILE_PATH)[0] + '_result.json')
    arguments = parser.parse_args()
    instance = load_instance(arguments.instance)
    replications = arguments.replications or instance['SimulationConfiguration']['Replications']
    target_quantity_by_product = {ProductCode: arguments.quantity for ProductCode in instance['Products']}
    results = run_replications(model_class or DEFAULT_MODEL_CLASS, instance, replications, arguments.seed,
                               target_quantity_by_product)
    print_result_summary(results)
    with open(arguments.output, 'w', encoding='utf-8') as result_file:
        json.dump(results, result_file, ensure_ascii=False, indent=1, default=str)


# ################################################################################################################################
# ================================================ SMT 라인 모듈: SMT 라인에만 쓰는 값·생성 코드·실행 코드를 이 구역에 모음 ================================================
# ################################################################################################################################
# 적용 대상: 라인마다 단계 공정(진행 순서)과 그 단계 설비. 이 공정·설비에만 SMT 라인 코드가 적용됨
SMT_LINES = {
    'Line_1': {
        'ProcessCodes': ['Line_1_Loader', 'Line_1_ScreenPrinter', 'Line_1_SPI', 'Line_1_Mounter',
                         'Line_1_Reflow', 'Line_1_Unloader', 'Line_1_AOI'],
        'MachineUnitCodes': ['Loader_U1', 'ScreenPrinter_U1', 'SPI_U1', 'Mounter_U1', 'Reflow_U1', 'Unloader_U1', 'AOI_U1'],
    },
    'Line_2': {
        'ProcessCodes': ['Line_2_Loader', 'Line_2_ScreenPrinter', 'Line_2_SPI', 'Line_2_Mounter',
                         'Line_2_Reflow', 'Line_2_Unloader', 'Line_2_AOI'],
        'MachineUnitCodes': ['Loader_U2', 'ScreenPrinter_U2', 'SPI_U2', 'Mounter_U2', 'Reflow_U2', 'Unloader_U2', 'AOI_U2'],
    },
}

SMT_PCB_COUNT_PER_ARRAY = 6

# 멈춤 시간(초). (근거 자료 없는 임의값)
SMT_STOP_DURATION_BY_EVENT_CODE = {
    'EV_FILM_CHANGE_Mounter_U1': 300.0,
    'EV_CHIP_REFILL_Mounter_U1': 120.0,
    'EV_FILM_CHANGE_Mounter_U2': 300.0,
    'EV_CHIP_REFILL_Mounter_U2': 120.0,
}


# ---------------------------------------------------------------- SMT 라인 인스턴스 값
class SmtLineGenerator(SimulationGenerator):
    def extract_module_values(self, instance):
        super().extract_module_values(instance)
        instance['SmtLines'] = {}
        for line_code, target in SMT_LINES.items():
            if self.check_smt_line_target(instance, line_code, target):
                instance['SmtLines'][line_code] = self.extract_SmtLine(instance, line_code, target)
        for event in instance['Events']:
            if event['DistributionUnit'] == 'RecipeChange' and event['Duration'] is None:
                self.issues.append({'kind': 'SMT 라인', 'message': f"{event['EventCode']}: 멈춤 시간 없음"})

    # 대상 공정·설비가 AAS에 있고, 단계 레시피의 설비(ResourceUnitRef)와 흐름(ProcessFlows) 순서가 지정과 같은지
    def check_smt_line_target(self, instance, line_code, target):
        missing = [code for code in target['ProcessCodes'] if code not in instance['Processes']]
        missing += [code for code in target['MachineUnitCodes'] if code not in instance['MachineUnits']]
        if missing:
            self.issues.append({'kind': 'SMT 라인', 'message': f'{line_code}: AAS에 없는 대상 {missing}. 이 라인은 만들지 않음'})
            return False
        flows = {(flow['FromProcessCode'], flow['ToProcessCode']) for flow in instance['ProcessFlows']}
        for step_index, (ProcessCode, MachineUnitCode) in enumerate(zip(target['ProcessCodes'], target['MachineUnitCodes'])):
            recipe_machine_codes = {recipe['ResourceUnitCode'] for recipe in instance['Processes'][ProcessCode]['Recipes']}
            if recipe_machine_codes != {MachineUnitCode}:
                self.issues.append({'kind': 'SMT 라인', 'message': f'{line_code}: {ProcessCode} 레시피 설비 {recipe_machine_codes}, 지정 설비 {MachineUnitCode}'})
            if step_index > 0 and (target['ProcessCodes'][step_index - 1], ProcessCode) not in flows:
                self.issues.append({'kind': 'SMT 라인', 'message': f"{line_code}: ProcessFlows에 {target['ProcessCodes'][step_index - 1]} → {ProcessCode} 없음"})
        return True

    # 생산 품목: 마지막 단계 레시피의 산출 품목. 근무시간: 근무표가 하나뿐이면 그 근무표
    def extract_SmtLine(self, instance, line_code, target):
        last_process = instance['Processes'][target['ProcessCodes'][-1]]
        produced_item_codes = sorted({code for recipe in last_process['Recipes'] for code in recipe['OutputItemCodes']})
        WorkScheduleCode = None
        if len(instance['WorkSchedules']) == 1:
            WorkScheduleCode = next(iter(instance['WorkSchedules']))
        else:
            self.issues.append({'kind': 'SMT 라인', 'message': f'{line_code}: 근무표를 정할 수 없어 근무시간 제한 없이 가동'})
        return {
            'ProcessCodes': list(target['ProcessCodes']),
            'MachineUnitCodes': list(target['MachineUnitCodes']),
            'produced_item_codes': produced_item_codes,
            'pcb_count_per_array': SMT_PCB_COUNT_PER_ARRAY,
            'WorkScheduleCode': WorkScheduleCode,
        }

    def event_duration(self, EventCode):
        if EventCode in SMT_STOP_DURATION_BY_EVENT_CODE:
            return {'Duration': SMT_STOP_DURATION_BY_EVENT_CODE[EventCode]}
        return super().event_duration(EventCode)


# ---------------------------------------------------------------- SMT 라인 실행: 필요 PCB 계획 → 품목별 어레이를 근무시간에 투입 → 어레이가 단계 설비를 차례로 점유 → PCB 재고 입고
class SmtLineModel(SimulationModel):
    def build_elements(self):
        super().build_elements()
        self.smt_line_runs = []
        # ---------------- 생산성 요소: 라인·품목별 생산 PCB 수, 라인 완료 시각, 멈춤 이벤트 횟수·시간(h)
        self.produced_pcb_count_by_line_item = collections.Counter()
        self.completion_time_by_line = {}
        self.stop_count_by_event = collections.Counter()
        self.stop_hours_by_event = collections.Counter()

    def module_produced_item_codes(self):
        smt_item_codes = {code for line in self.instance['SmtLines'].values() for code in line['produced_item_codes']}
        return super().module_produced_item_codes() | smt_item_codes

    def start_module_processes(self):
        super().start_module_processes()
        for line_code, plan in self.plan_smt_lines().items():
            self.smt_line_runs.append(self.environment.process(self.run_smt_line(line_code, plan)))

    def is_module_finished(self):
        return super().is_module_finished() and all(line_run.triggered for line_run in self.smt_line_runs)

    # 목표 수량으로 PCB 품목별 필요 수량
    def required_quantity_by_item(self):
        required = collections.Counter()
        for ProductCode, quantity in self.target_quantity_by_product.items():
            for ProcessCode in self.instance['Products'][ProductCode]['process_codes']:
                for condition in self.item_conditions(ProcessCode):
                    if condition['ItemCode'] in self.self_produced_item_codes:
                        required[condition['ItemCode']] += condition['Quantity'] * quantity
        return required

    # 품목을 코드 순으로 그 품목을 만드는 라인에 번갈아 배정(simulation_v2.1 규칙), 어레이 수 = 필요 수량 ÷ 어레이당 PCB 수 올림
    def plan_smt_lines(self):
        lines = self.instance['SmtLines']
        plans = {line_code: [] for line_code in lines}
        for item_index, (ItemCode, quantity) in enumerate(sorted(self.required_quantity_by_item().items())):
            line_codes = sorted(code for code, line in lines.items() if ItemCode in line['produced_item_codes'])
            line_code = line_codes[item_index % len(line_codes)]
            plans[line_code].append({'ItemCode': ItemCode,
                                     'array_count': math.ceil(quantity / lines[line_code]['pcb_count_per_array'])})
        return plans

    def run_smt_line(self, line_code, plan):
        line = self.instance['SmtLines'][line_code]
        schedule = self.schedule_of(line['WorkScheduleCode'])
        for item_index, planned_item in enumerate(plan):
            if item_index > 0:
                yield from self.handle_recipe_change_events(line, schedule)
            yield from self.wait_for_work_time(schedule)
            arrays = [self.environment.process(self.produce_pcb_array(line, planned_item['ItemCode']))
                      for _ in range(planned_item['array_count'])]
            yield simpy.AllOf(self.environment, arrays)
            pcb_count = planned_item['array_count'] * line['pcb_count_per_array']
            self.produced_pcb_count_by_line_item[(line_code, planned_item['ItemCode'])] += pcb_count
            self.add_stock(planned_item['ItemCode'], pcb_count)
        self.completion_time_by_line[line_code] = self.environment.now
        self.environment.process(self.stop_after_smt_line_end())

    def stop_after_smt_line_end(self):
        yield self.environment.timeout(0)
        self.stop_if_target_reached()

    # 어레이 1장이 단계 설비를 차례로 점유: 단계 CycleTime이 근무 구간 안에 끝날 때까지 기다린 뒤(simulation_v2.1 규칙) 다음 설비를 잡고 앞 설비를 놓음
    # 산출 품목 코드는 템플릿 규칙(단계 레시피 투입 품목, 마지막 단계는 PCB 품목 코드)
    def produce_pcb_array(self, line, ItemCode):
        schedule = self.schedule_of(line['WorkScheduleCode'])
        held = None
        for step_index, (ProcessCode, MachineUnitCode) in enumerate(zip(line['ProcessCodes'], line['MachineUnitCodes'])):
            recipe = self.instance['Processes'][ProcessCode]['Recipes'][0]
            input_codes = [condition['ItemCode'] for condition in self.item_conditions(ProcessCode)]
            machine = self.machines[MachineUnitCode]
            yield from self.wait_for_work_time(schedule, recipe['CycleTime'])
            request = machine.resource.request()
            yield request
            if held is not None:
                held['machine'].resource.release(held['request'])
            machine.start_use(ProcessCode)
            yield self.environment.timeout(recipe['CycleTime'])
            machine.end_use(ProcessCode)
            is_last = step_index == len(line['ProcessCodes']) - 1
            OutputItemCode = self.output_item_code(ProcessCode, input_codes, ItemCode if is_last else None)
            self.record_process_execution(ProcessCode, recipe['CycleTime'])
            self.record_output(ProcessCode, OutputItemCode, recipe['CycleTime'], line['pcb_count_per_array'])
            held = {'machine': machine, 'request': request}
        held['machine'].resource.release(held['request'])

    # 품목 변경 멈춤: 라인 생산 품목이 바뀔 때 라인 설비 대상 이벤트의 간격을 세고, 발생하면 근무 구간 안에서 멈춤 시간만큼 다음 품목 착수를 늦춤
    def handle_recipe_change_events(self, line, schedule):
        for MachineUnitCode in line['MachineUnitCodes']:
            for event in self.events_by_kind_and_target.get(('RecipeChange', MachineUnitCode), []):
                if not self.is_event_due(event):
                    continue
                yield from self.wait_for_work_time(schedule, event['Duration'])
                yield self.environment.timeout(event['Duration'])
                self.stop_count_by_event[event['EventCode']] += 1
                self.stop_hours_by_event[event['EventCode']] += event['Duration'] / SECONDS_PER_HOUR

    def result(self):
        result = super().result()
        result['smt_lines'] = {
            'produced_pcb_count_by_line_item': {f'{line}/{item}': count
                                                for (line, item), count in self.produced_pcb_count_by_line_item.items()},
            'completion_time_by_line': self.completion_time_by_line,
            'stop_count_by_event': dict(self.stop_count_by_event),
            'stop_hours_by_event': dict(self.stop_hours_by_event),
        }
        return result


SMT_LINE_RUNTIME_DEFINITIONS = [SmtLineModel]
# ################################################ SMT 라인 모듈 끝 ################################################


# ################################################################################################################################
# ================================================ 기저부하 모듈: 공장 전체 상시 전력(조명·공조 등).  ================================================
# ################################################################################################################################
# 기저부하 전력(kW): auto3_통합/build.py DefaultProcessConsumedPowerKw(이전 Machine_BaseLoad_U1 정격전력 148,221 W)
BASE_LOAD_ELECTRICITY_KW = 148.221
# 기저부하 전력 배출계수(kgCO2eq/kWh): MCF 전력 줄 RefEmissionFactor와 같은 값(Grid electricity)
BASE_LOAD_ELECTRICITY_EMISSION_FACTOR = 0.620873185757848
# 탄소 경계 이름과 활동량 대상 이름(공정 코드 자리에 씀)
BASE_LOAD_CODE = 'BaseLoad'


# ---------------------------------------------------------------- 기저부하 인스턴스 값: 탄소 경계 1개(전력 줄 1개), 근무표
class BaseLoadGenerator(SimulationGenerator):
    def extract_module_values(self, instance):
        super().extract_module_values(instance)
        WorkScheduleCode = None
        if len(instance['WorkSchedules']) == 1:
            WorkScheduleCode = next(iter(instance['WorkSchedules']))
        else:
            self.issues.append({'kind': '기저부하', 'message': '근무표를 정할 수 없어 기저부하를 쌓지 않음'})
        instance['BaseLoad'] = {
            'BoundaryCode': BASE_LOAD_CODE,
            'WorkScheduleCode': WorkScheduleCode,
        }
        instance['CarbonBoundaries'][BASE_LOAD_CODE] = {
            'mcf_submodel_id': None, 'ResourceType': None, 'resource_aas_id': None,
            'MachineUnitCode': None, 'recipe_indexes': [], 'ProcessCodes': [],
            'activity_basis': 'work_time',
            'carbon_elements': [{
                'category': 'Electricity', 'ClassificationType': 'Grid electricity', 'AmountUnit': 'kWh',
                'RefEmissionFactor': BASE_LOAD_ELECTRICITY_EMISSION_FACTOR, 'RefImpactUnitforCalculation': 'kWh',
                'given_Amount': None,
                'activity_rate_by_process_code': {BASE_LOAD_CODE: {'rate': BASE_LOAD_ELECTRICITY_KW, 'rate_unit': 'kW'}},
                'amount_path': None,
            }],
        }


# ---------------------------------------------------------------- 기저부하 실행: 근무 시작~종료(휴식 포함) 동안 기저부하 경계에 시간을 쌓음
class BaseLoadModel(SimulationModel):
    def start_module_processes(self):
        super().start_module_processes()
        base_load = self.instance['BaseLoad']
        self.base_load_boundary = self.carbon_boundaries[base_load['BoundaryCode']]
        self.base_load_schedule = self.schedule_of(base_load['WorkScheduleCode'])
        self.base_load_since = None
        if self.base_load_schedule is not None:
            self.environment.process(self.run_base_load())

    def run_base_load(self):
        WorkStartTime, WorkEndTime = self.base_load_schedule['WorkStartTime'], self.base_load_schedule['WorkEndTime']
        while True:
            time_of_day = self.environment.now % SECONDS_PER_DAY
            if time_of_day < WorkStartTime:
                yield self.environment.timeout(WorkStartTime - time_of_day)
            elif time_of_day < WorkEndTime:
                self.base_load_since = self.environment.now
                yield self.environment.timeout(WorkEndTime - time_of_day)
                self.add_base_load_time()
            else:
                yield self.environment.timeout(SECONDS_PER_DAY - time_of_day + WorkStartTime)

    def add_base_load_time(self):
        hours = (self.environment.now - self.base_load_since) / SECONDS_PER_HOUR
        self.base_load_boundary.add_operating_time(self.instance['BaseLoad']['BoundaryCode'], hours)
        self.base_load_since = None

    def close_module_records(self):
        super().close_module_records()
        if self.base_load_since is not None:
            self.add_base_load_time()


BASE_LOAD_RUNTIME_DEFINITIONS = [BaseLoadModel]
# ################################################ 기저부하 모듈 끝 ################################################


# ################################################################################################################################
# ================================================ MCF 계산 모듈: MCF 경계마다 실행 끝에 pcf_mcf/mcf.py 계산부로 배출량·할당·PCF 계산 ================================================
@dataclass
class Item:
    code: str
    use: dict              # 산출물 1단위당 투입량 {OutputItemCode: 수량}
    ef: float | None       # RefEmissionFactor (원소재)
    pcf_ref: str | None    # PCFEmission이 가리키는 CarbonFootprint id (구매 부품)


@dataclass
class Output:
    code: str
    unit: str
    quantity: float        # OutputItemQuantity
    period: float          # OperatingPeriod


@dataclass
class MCFData:
    boundary_id: str
    basis: str             # AllocationBasis
    items: list
    outputs: list
    ancillary_inputs: list  # [(사용량, 배출계수)]: AncillaryInputs 공통요소 줄 전부
    residuals: list        # [(발생량, 배출계수)]: Residuals 공통요소 줄 전부


@dataclass
class Product:
    code: str
    unit: str
    quantity: float
    factor: float          # AllocatedFactor
    allocated: float       # AllocatedCO2eq
    excluded: list         # 제외된 투입물 코드
    complete: bool
    contributions: list    # [(Tier, ProductCode, 제품 1단위당 kgCO2e)]

    @property
    def pcf(self):
        return self.allocated / self.quantity


@dataclass
class Result:
    input_material: float
    ancillary: float
    residual: float
    amounts: list          # 보조 투입물 줄별 사용량 (Amount에 기록)
    products: list

    @property
    def total(self):
        return self.input_material + self.ancillary + self.residual


def calc_mcf(data, registry, tier):
    """M2~M5. registry: {CarbonFootprint id: UpstreamPCF} (이전 Tier에서 생성했거나 공급사가 제공한 PCF)."""
    # M2 환산계수: {투입물 코드: (계수, 상류 PCF 또는 None)}. 찾지 못한 구매 부품은 포함되지 않음(제외)
    factors = {}
    for it in data.items:
        if it.ef is not None:
            factors[it.code] = (it.ef, None)
        elif it.pcf_ref in registry:
            factors[it.code] = (registry[it.pcf_ref].pcf, registry[it.pcf_ref])

    # M3 배출량
    material = {o.code: sum(it.use.get(o.code, 0.0) * o.quantity * factors[it.code][0]
                            for it in data.items if it.code in factors) for o in data.outputs}
    ancillary = sum(amount * ef for amount, ef in data.ancillary_inputs)
    residual = sum(amount * ef for amount, ef in data.residuals)

    # M4 할당 가중치: 산출물이 하나면 1, 여러 개면 AllocationBasis 기준
    weight = {o.code: 1.0 if len(data.outputs) == 1 else (o.period if data.basis == "OperatingTime" else o.quantity)
              for o in data.outputs}
    total_weight = sum(weight.values())

    products = []
    for o in data.outputs:
        factor = weight[o.code] / total_weight
        allocated = material[o.code] + (ancillary + residual) * factor
        used = [it for it in data.items if it.use.get(o.code, 0.0) > 0]
        linked = [(it, factors[it.code][1]) for it in used if it.code in factors and factors[it.code][1]]

        # M5 Tier별 기여: 이 경계의 배출(제품 1단위당) + 상류 기여 x 투입량
        upstream_part = sum(it.use[o.code] * up.pcf for it, up in linked)
        merged = {(tier, o.code): allocated / o.quantity - upstream_part}
        for it, up in linked:
            for t, code, value in up.contributions:
                merged[(t, code)] = merged.get((t, code), 0.0) + value * it.use[o.code]
        products.append(Product(
            o.code, o.unit, o.quantity, factor, allocated,
            excluded=[it.code for it in used if it.code not in factors],
            complete=all(it.code in factors for it in used) and all(up.complete for _, up in linked),
            contributions=sorted(((t, c, val) for (t, c), val in merged.items()), key=lambda x: (-x[0], x[1])),
        ))
    return Result(sum(material.values()), ancillary, residual, [amount for amount, _ in data.ancillary_inputs], products)


# ---------------------------------------------------------------- MCF 계산 인스턴스 값: MCF Submodel마다 산출물 코드, 투입물, AllocationBasis
class McfGenerator(SimulationGenerator):
    def extract_module_values(self, instance):
        super().extract_module_values(instance)
        instance['MCFCalculations'] = {}
        for mcf in self.extracted.submodels_with_role('MCF'):
            instance['MCFCalculations'][mcf.id] = self.extract_MCFCalculation(mcf)

    # 산출물: Recipes[].Output[].OutputItemCode → Simulation 레시피 OutputItemCode(같은 코드는 하나로)
    # 투입물: Recipes[].InputItemCodeList[]. 품목은 InputItemCode → Warehouse ItemCodeRef → 품목 CD, 중간재는 → 앞 공정 레시피 OutputItemCode
    def extract_MCFCalculation(self, mcf):
        output_codes, items = [], {}
        for mcf_recipe in mcf.ManufacturingProcess.Recipes:
            recipe_output_codes = [output.OutputItemCode.jump.value for output in mcf_recipe.Output]
            output_codes += [code for code in recipe_output_codes if code not in output_codes]
            for input_item in mcf_recipe.InputItemCodeList:
                target = input_item.InputItemCode.jump
                code = target.value if isinstance(target, path_extractor.Property) else target.jump.idShort
                item = items.setdefault(code, {'code': code, 'use': {}, 'ef': input_item.RefEmissionFactor.value,
                                               'pcf_ref': input_item.PCFEmission.jump.id})
                for OutputItemCode in recipe_output_codes:
                    item['use'][OutputItemCode] = input_item.InputItemQuantity.jump.value or 0.0
        AllocationBases = {allocation.AllocationBasis.value for allocation in mcf.MCFEmissions.Allocation}
        if len(AllocationBases) > 1:
            self.issues.append({'kind': 'MCF 할당', 'message': f'{mcf.id}: AllocationBasis가 여럿 {sorted(AllocationBases)}'})
        return {'AllocationBasis': min(AllocationBases, default=None), 'output_codes': output_codes, 'items': list(items.values())}


# ---------------------------------------------------------------- MCF 계산 실행: 산출물별 산출 수량·가동시간(h)을 쌓고 실행 끝에 calc_mcf
class McfModel(SimulationModel):
    def build_elements(self):
        super().build_elements()
        self.OutputItemQuantity_by_mcf = collections.defaultdict(collections.Counter)
        self.OperatingPeriod_by_mcf = collections.defaultdict(collections.Counter)

    def record_output(self, ProcessCode, OutputItemCode, duration, output_quantity=1):
        super().record_output(ProcessCode, OutputItemCode, duration, output_quantity)
        boundary = self.carbon_boundary_by_process.get(ProcessCode)
        if boundary is not None and boundary.mcf_submodel_id in self.instance['MCFCalculations']:
            self.OutputItemQuantity_by_mcf[boundary.mcf_submodel_id][OutputItemCode] += output_quantity
            self.OperatingPeriod_by_mcf[boundary.mcf_submodel_id][OutputItemCode] += duration / SECONDS_PER_HOUR

    # calc_mcf 입력: 실행에서 나온 산출물만(산출 0이면 PCF를 나눌 수 없음), 공통요소 줄은 AncillaryInputs·Residuals 아래 위치로 나눔
    def mcf_data(self, mcf_submodel_id, boundary):
        calculation = self.instance['MCFCalculations'][mcf_submodel_id]
        quantities, periods = self.OutputItemQuantity_by_mcf[mcf_submodel_id], self.OperatingPeriod_by_mcf[mcf_submodel_id]
        outputs = [Output(code, None, quantities[code], periods[code]) for code in calculation['output_codes'] if quantities[code] > 0]
        items = [Item(item['code'], item['use'], item['ef'], item['pcf_ref']) for item in calculation['items']]
        lines_under = lambda container: [(element.Amount, element.RefEmissionFactor) for element in boundary.carbon_elements
                                         if element.amount_path.startswith(container)]
        return MCFData(mcf_submodel_id, calculation['AllocationBasis'], items, outputs,
                       lines_under('AncillaryInputs'), lines_under('Residuals'))

    # registry: 상류 PCF 없음(공급사 PCF·이전 Tier 미연결), tier: 이 공장 한 단계라 1
    def result(self):
        result = super().result()
        for boundary_key, boundary in self.carbon_boundaries.items():
            if boundary.mcf_submodel_id not in self.instance['MCFCalculations']:
                continue
            calculation = self.instance['MCFCalculations'][boundary.mcf_submodel_id]
            quantities = self.OutputItemQuantity_by_mcf[boundary.mcf_submodel_id]
            calculated = calc_mcf(self.mcf_data(boundary.mcf_submodel_id, boundary), {}, 1)
            result['carbon']['boundaries'][boundary_key].update({
                'InputMaterialEmissions': calculated.input_material,
                'AncillaryInputEmissions': calculated.ancillary,
                'ResidualEmissions': calculated.residual,
                'SumCO2eq': calculated.total,
                'AllocationBasis': calculation['AllocationBasis'],
                'Allocation': [{'OutputItemCode': product.code, 'OutputItemQuantity': product.quantity,
                                'OperatingPeriod': self.OperatingPeriod_by_mcf[boundary.mcf_submodel_id][product.code],
                                'AllocatedFactor': product.factor, 'AllocatedCO2eq': product.allocated,
                                'PCF': product.pcf, 'ExcludedInputs': product.excluded}
                               for product in calculated.products],
                'not_produced_outputs': [code for code in calculation['output_codes'] if not quantities[code]],
                'outputs_not_in_mcf': sorted(set(quantities) - set(calculation['output_codes'])),
            })
        result['carbon']['SumCO2eq_total'] = sum(boundary['SumCO2eq'] for boundary in result['carbon']['boundaries'].values())
        return result


MCF_RUNTIME_DEFINITIONS = [Item, Output, MCFData, Product, Result, calc_mcf, McfModel]
# ################################################ MCF 계산 모듈 끝 ################################################


# ================================================ 모듈 조합: 인스턴스에 넣을 모듈을 상속으로 묶음(순서대로 super() 연결) ================================================
class InstanceGenerator(McfGenerator, BaseLoadGenerator, SmtLineGenerator):
    RUNTIME_MODEL_CLASS_NAME = 'InstanceModel'


class InstanceModel(McfModel, BaseLoadModel, SmtLineModel):
    pass


# 인스턴스를 만드는 생성기와 인스턴스 py에 넣을 모듈 실행 코드
GENERATOR_CLASS = InstanceGenerator
MODULE_RUNTIME_DEFINITIONS = SMT_LINE_RUNTIME_DEFINITIONS + BASE_LOAD_RUNTIME_DEFINITIONS + MCF_RUNTIME_DEFINITIONS + [InstanceModel]

INSTANCE_RUNTIME_CONSTANT_NAMES = [
    'SECONDS_PER_HOUR', 'SECONDS_PER_DAY', 'TIME_TOLERANCE', 'BRANCH_PROBABILITY_TOLERANCE',
]
INSTANCE_RUNTIME_DEFINITIONS = [
    MachineElement, WorkerGroupElement, CarbonElement, CarbonBoundary, SimulationModel,
    load_instance, run_replications, print_result_summary, main,
]
INSTANCE_IMPORTS = ['argparse', 'collections', 'itertools', 'json', 'math', 'os', 'random', 'sys', 'simpy']


# ================================================ 인스턴스 파일 쓰기: 값(<이름>.json) + 실행 코드(<이름>.py, 같은 이름의 json을 읽음) ================================================
def write_instance_files(instance, instance_file_path, aas_path, generator_class):
    stem = os.path.splitext(instance_file_path)[0]
    with open(stem + '.json', 'w', encoding='utf-8') as json_file:
        json.dump(instance, json_file, ensure_ascii=False, indent=1, default=str)
    lines = ['# 시뮬레이션 인스턴스 실행 코드: simulation_generator.py가 만든 파일. 값은 같은 이름의 json(INSTANCE_FILE_PATH)',
             f'# AAS 입력: {aas_path}',
             '# 실행: python <이 파일> --quantity 제품별 목표 수량 [--replications N] [--seed S] [--instance 다른 json]',
             '# 시나리오: 이 파일을 import해 DEFAULT_MODEL_CLASS를 상속, 메서드를 재정의한 뒤 main(새 클래스)',
             '']
    lines += [f'import {name}' for name in INSTANCE_IMPORTS]
    lines.append('from dataclasses import dataclass')
    lines += ['', '']
    lines += [f'{name} = {globals()[name]!r}' for name in INSTANCE_RUNTIME_CONSTANT_NAMES]
    lines.append("INSTANCE_FILE_PATH = os.path.splitext(os.path.abspath(__file__))[0] + '.json'")
    lines += ['', '']
    for definition in INSTANCE_RUNTIME_DEFINITIONS + MODULE_RUNTIME_DEFINITIONS:
        lines += [inspect.getsource(definition), '']
    lines += [f'DEFAULT_MODEL_CLASS = {generator_class.RUNTIME_MODEL_CLASS_NAME}', '', '']
    lines += ["if __name__ == '__main__':", '    main()', '']
    with open(stem + '.py', 'w', encoding='utf-8') as instance_file:
        instance_file.write('\n'.join(lines))


def generate(aas_path, instance_file_path, generator_class=GENERATOR_CLASS):
    extracted = path_extractor.extract(aas_path)
    instance = generator_class(extracted, aas_path).generate()
    write_instance_files(instance, instance_file_path, aas_path, generator_class)
    return instance


if __name__ == '__main__':
    argument_parser = argparse.ArgumentParser()
    argument_parser.add_argument('aas_path')
    argument_parser.add_argument('instance_file_path')
    generator_arguments = argument_parser.parse_args()
    generated = generate(generator_arguments.aas_path, generator_arguments.instance_file_path)
    issue_count = collections.Counter(issue['kind'] for issue in generated['issues'])
    print(f"공정 {len(generated['Processes'])} | 흐름 {len(generated['ProcessFlows'])} | "
          f"제품 { {code: len(product['process_codes']) for code, product in generated['Products'].items()} } | "
          f"SMT 라인 {list(generated.get('SmtLines', {}))} | 이벤트 {len(generated['Events'])} | "
          f"탄소 경계 {len(generated['CarbonBoundaries'])} | 확인 필요 {dict(issue_count)}")
