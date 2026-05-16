# -*- coding: utf-8 -*-
"""simulation_ver0.py 가 요구하는 모든 변수를 PSM 경유로 세팅 + KG/Warehouse 통합 동작 확인."""
from dataclasses import dataclass
from typing import Dict
from path_extractor import ProvisionofSimulationModelsAAS, load


# region AAS 로드
for f in ['ProvisionOfSimulationModel.json', 'WorkstationWorkerMatchingDataAAS.json',
          'MODEL_A.json', 'MODEL_B.json', 'MODEL_C.json']:
    load(f)
# endregion


# region 시뮬 입력 변수 (전부 PSM 경유)
psm = ProvisionofSimulationModelsAAS
SM = psm.SimulationModels.SimulationModel
dp = SM.DefaultParameters

ManufacturingProcesses = {mp.model_id: mp for mp in SM.Warehouse.InputBOM.target}
workers                = psm.workers
WarehouseManagedBOM    = psm.WarehouseManagedBOM
BOMCategory            = SM.Warehouse.MinStock.target            # BOMCategory SMC (target of any of MinStock/MaxStock/OrderRatio ref)

IndependentSequence    = [n.idShort for ref in SM.Action.IndependentSequence for n in ref]
DependentSequence      = [n.idShort for ref in SM.Action.DependentSequence   for n in ref]
DependentJoin          = [n.idShort for ref in SM.Action.DependentJoin       for n in ref]

WorkStartTime          = dp.WorkStartTime.target.value           # sec
WorkEndTime            = dp.WorkEndTime.target.value             # sec
break_start_sec        = dp.BreakDurationMin.target.min          # sec
break_end_sec          = dp.BreakDurationMin.target.max          # sec
ReplenishLeadDay       = dp.ReplenishLeadDay.value
MaxEpisodes            = SM.SimulationConfig.MaxEpisodes.value
RewardWeights          = {c.idShort: c.value for c in SM.RewardWeights.values()}
# endregion


# region simulation_ver0.py 의 KG (DepPrev/DepType 은 GraphEdge — 의존성 reverse index)
@dataclass
class GraphNode:
    ProcessCode  : str
    GroupIdShort : str
    model_id     : str
    CycleTimeSec : float
    DefectRate   : float
    RatedPowerKw : float
    InputBOM     : object

@dataclass
class GraphEdge:
    DepPrev      : str
    ProcessCode  : str
    DepType      : str

@dataclass
class KnowledgeGraph:
    nodes   : dict
    edges   : dict
    workers : dict

    @classmethod
    def build(cls, ManufacturingProcesses, workers) -> 'KnowledgeGraph':
        nodes, edges = {}, {}
        for model_id, mp in ManufacturingProcesses.items():
            for GroupIdShort, processes in mp.groups.items():
                for ProcessCode, ProcessNode in processes.items():
                    nodes[ProcessCode] = GraphNode(
                        ProcessCode  = ProcessCode,
                        GroupIdShort = GroupIdShort,
                        model_id     = model_id,
                        CycleTimeSec = ProcessNode.CycleTimeSec.value,
                        DefectRate   = ProcessNode.DefectRate.value,
                        RatedPowerKw = ProcessNode.RatedPowerKw.value,
                        InputBOM     = ProcessNode.InputBOM,
                    )
                    for DepPrev in ProcessNode.DepPrev.value.split(';'):
                        DepPrev = DepPrev.strip()
                        if not DepPrev:
                            continue
                        edges.setdefault(DepPrev, []).append(GraphEdge(
                            DepPrev     = DepPrev,
                            ProcessCode = ProcessCode,
                            DepType     = ProcessNode.DepType.value,
                        ))
        return cls(nodes, edges, workers)

    def __post_init__(self):
        self._deps_of = {}
        for dep_prev, edge_list in self.edges.items():
            for edge in edge_list:
                self._deps_of.setdefault(edge.ProcessCode, []).append(dep_prev)

    def _bom_satisfied(self, ProcessCode, warehouse) -> bool:
        node = self.nodes[ProcessCode]
        if not node.InputBOM:
            return True
        return all(
            warehouse.inventory[Category][item_code].present_stock >= ProcessConsumedBOM
            for item_code, ProcessConsumedBOM in node.InputBOM.items()
            for Category in warehouse.inventory
            if item_code in warehouse.inventory[Category]
        )

    def ready_queue(self, IndependentSequence, DependentSequence, DependentJoin,
                    completed: set, warehouse) -> list:
        ready = []
        for ProcessCode in IndependentSequence:
            if self._bom_satisfied(ProcessCode, warehouse):
                ready.append(ProcessCode)
        for ProcessCode in DependentSequence + DependentJoin:
            deps = self._deps_of.get(ProcessCode, [])
            if all(dep in completed for dep in deps):
                if self._bom_satisfied(ProcessCode, warehouse):
                    ready.append(ProcessCode)
        return ready
# endregion


# region simulation_ver0.py 의 Warehouse
@dataclass
class StockItem:
    present_stock : float
    MinStock      : float
    MaxStock      : float
    OrderRatio    : float

@dataclass
class Warehouse:
    inventory : Dict[str, Dict[str, StockItem]]

    @classmethod
    def build(cls, WarehouseManagedBOM, BOMCategory) -> 'Warehouse':
        inventory = {}
        for Category, items in WarehouseManagedBOM.items():
            inventory[Category] = {}
            for item_code in items:
                inventory[Category][item_code] = StockItem(
                    present_stock = BOMCategory[Category].MinStock,
                    MinStock      = BOMCategory[Category].MinStock,
                    MaxStock      = BOMCategory[Category].MaxStock,
                    OrderRatio    = BOMCategory[Category].OrderRatio,
                )
        return cls(inventory)

    def consume(self, ProcessConsumedBOM) -> bool:
        for item_code, Quantity in ProcessConsumedBOM.items():
            for Category in self.inventory:
                if item_code in self.inventory[Category]:
                    self.inventory[Category][item_code].present_stock -= Quantity
                    break
        return any(
            item.present_stock <= item.MinStock * item.OrderRatio
            for Category in self.inventory
            for item in self.inventory[Category].values()
        )
# endregion


# region 실행 — 통합 동작 확인
print('=' * 60)
print('변수 셋업 확인')
print('=' * 60)
print(f'ManufacturingProcesses : {list(ManufacturingProcesses.keys())}')
print(f'workers                : {len(workers)} workstations')
print(f'WarehouseManagedBOM    : {len(WarehouseManagedBOM)} categories, '
      f'{sum(len(v) for v in WarehouseManagedBOM.values())} items')
print(f'BOMCategory            : {len(BOMCategory)} entries')
print(f'IndependentSequence    : {len(IndependentSequence)}')
print(f'DependentSequence      : {len(DependentSequence)}')
print(f'DependentJoin          : {len(DependentJoin)}')
print(f'WorkStartTime / End    : {WorkStartTime} / {WorkEndTime} sec')
print(f'break range            : {break_start_sec} ~ {break_end_sec} sec')
print(f'ReplenishLeadDay       : {ReplenishLeadDay}')
print(f'MaxEpisodes            : {MaxEpisodes}')
print(f'RewardWeights          : {RewardWeights}')

print()
print('=' * 60)
print('KG.build + Warehouse.build')
print('=' * 60)
kg = KnowledgeGraph.build(ManufacturingProcesses, workers)
warehouse = Warehouse.build(WarehouseManagedBOM, BOMCategory)
print(f'KG nodes        : {len(kg.nodes)}')
print(f'KG edges        : {len(kg.edges)} (선행 키 개수)')
print(f'KG _deps_of     : {len(kg._deps_of)} (후행 키 개수)')
total_stock_items = sum(len(items) for items in warehouse.inventory.values())
print(f'Warehouse items : {total_stock_items} (= {len(warehouse.inventory)} categories)')

print()
print('=' * 60)
print('ready_queue 시나리오')
print('=' * 60)
ready_initial = kg.ready_queue(IndependentSequence, DependentSequence, DependentJoin,
                                completed=set(), warehouse=warehouse)
print(f'Initial ready (completed=∅):  {len(ready_initial)} 개')
print(f'  first 5: {ready_initial[:5]}')

completed = {'VD7_10'}
ready_after = kg.ready_queue(IndependentSequence, DependentSequence, DependentJoin,
                              completed=completed, warehouse=warehouse)
newly_ready = sorted(set(ready_after) - set(ready_initial))
print(f'\nAfter completing {completed}: {len(ready_after)} 개')
print(f'  newly ready: {newly_ready}')

print()
print('=' * 60)
print('Warehouse.consume 시나리오 (VD7_10 의 InputBOM 소비)')
print('=' * 60)
vd7_10 = kg.nodes['VD7_10']
if vd7_10.InputBOM:
    print(f'VD7_10 InputBOM items: {dict(vd7_10.InputBOM.items())}')
    # 소비 전 stock
    sample_item = next(iter(vd7_10.InputBOM.keys()))
    for cat in warehouse.inventory:
        if sample_item in warehouse.inventory[cat]:
            before = warehouse.inventory[cat][sample_item].present_stock
            need_replenish = warehouse.consume(dict(vd7_10.InputBOM.items()))
            after = warehouse.inventory[cat][sample_item].present_stock
            print(f'  {sample_item}: {before} → {after} (replenish needed: {need_replenish})')
            break
else:
    print('  VD7_10 has no InputBOM')

print()
print('✓ 전체 셋업 + KG/Warehouse 통합 동작 OK')
# endregion
