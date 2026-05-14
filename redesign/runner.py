# -*- coding: utf-8 -*-
"""실험 진입점 — PSM 단일 진입으로 모든 변수 로드 → KG / Warehouse / CproSimEnv 구성.

AAS 접근 규칙
    `from aas_architecture import ProvisionofSimulationModelsAAS` 만 사용.
    JSON 등록은 모듈 함수 `aas_architecture.load(json_path)` 로 일괄 처리.
    이후 모든 변수는 PSM 의 submodel 트리 / @property 에서 꺼낸다.

경로 패턴(참고)::

    PSM                     = ProvisionofSimulationModelsAAS
    PSM.SimulationModels.SimulationModel.Action.{IndependentSequence|DependentSequence|DependentJoin}
    PSM.SimulationModels.SimulationModel.Warehouse.{InputBOM|MinStock|MaxStock|OrderRatio}
    PSM.SimulationModels.SimulationModel.DefaultParameters.{WorkStartTime|WorkEndTime|BreakDurationMin}
    PSM.workers                                         # WWM registry walk
    PSM.WarehouseManagedBOM                             # ProductAAS HS walk
"""
import os
import sys

_PKG_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PKG_DIR not in sys.path:
    sys.path.append(_PKG_DIR)

import path_extractor
from path_extractor import ProvisionofSimulationModelsAAS

import cpro_config as C
from kg import KnowledgeGraph
from sim_env import Warehouse, CproSimEnv


#========AAS JSON 로딩========
JSON_FILES = [
    'ProvisionOfSimulationModel.json',
    'WorkstationWorkerMatchingDataAAS.json',
    'MODEL_A.json',
    'MODEL_B.json',
    'MODEL_C.json',
]

def load_all_aas(json_dir: str = _PKG_DIR) -> None:
    for filename in JSON_FILES:
        path_extractor.load(os.path.join(json_dir, filename))


#========PSM 단일 진입점으로 변수 추출========
def build_env() -> CproSimEnv:
    PSM                       = ProvisionofSimulationModelsAAS
    SimulationModel           = PSM.SimulationModels.SimulationModel
    Action                    = SimulationModel.Action
    PSM_Warehouse             = SimulationModel.Warehouse
    DefaultParameters         = SimulationModel.DefaultParameters

    # ── KG 입력
    ManufacturingProcesses    = {mp.model_id: mp for mp in PSM_Warehouse.InputBOM.target}
    workers                   = PSM.workers
    kg                        = KnowledgeGraph.build(ManufacturingProcesses, workers)

    # ── Warehouse 입력
    WarehouseManagedBOM       = PSM.WarehouseManagedBOM
    BOMCategory               = PSM_Warehouse.MinStock.target
    warehouse                 = Warehouse.build(WarehouseManagedBOM, BOMCategory)

    # ── PSM Action (각 ref.target = List[ProcessNode] → idShort 평탄화)
    IndependentSequence       = [node.idShort for ref in Action.IndependentSequence.values() for node in ref.target]
    DependentSequence         = [node.idShort for ref in Action.DependentSequence.values()   for node in ref.target]
    DependentJoin             = [node.idShort for ref in Action.DependentJoin.values()       for node in ref.target]

    # ── PSM DefaultParameters (xs:time → 자정 기준 초)
    WorkStartTime             = DefaultParameters.WorkStartTime.target.value
    WorkEndTime               = DefaultParameters.WorkEndTime.target.value
    BreakDurationMin          = DefaultParameters.BreakDurationMin.target.value

    # ── 비 AAS 정책 상수 (cpro_config)
    RewardWeights             = {
        'STOCK_SHORT' : C.REWARD_W_STOCK_SHORT,
        'STOCK_OVER'  : C.REWARD_W_STOCK_OVER,
        'DONE'        : C.REWARD_W_DONE,
        'IDLE'        : C.REWARD_W_IDLE,
        'MAKESPAN'    : C.REWARD_W_MAKESPAN,
        'KWH'         : C.REWARD_W_KWH,
        'SUCCESS'     : C.REWARD_W_SUCCESS,
    }
    ReplenishLeadDay          = C.REPLENISH_LEAD_TIME_SEC
    target_qty                = sum(C.TARGET_QTY.values()) if hasattr(C, 'TARGET_QTY') else 0
    MaxEpisodes               = C.MAX_DAYS

    return CproSimEnv(
        KnowledgeGraph        = kg,
        warehouse             = warehouse,
        workers               = workers,
        IndependentSequence   = IndependentSequence,
        DependentSequence     = DependentSequence,
        DependentJoin         = DependentJoin,
        RewardWeights         = RewardWeights,
        ReplenishLeadDay      = ReplenishLeadDay,
        target_qty            = target_qty,
        MaxEpisodes           = MaxEpisodes,
        WarehouseManagedBOM   = WarehouseManagedBOM,
        BOMCategory           = BOMCategory,
        WorkStartTime         = WorkStartTime,
        WorkEndTIme           = WorkEndTime,
        break_start_sec       = WorkStartTime + (WorkEndTime - WorkStartTime) // 2,
        break_end_sec         = WorkStartTime + (WorkEndTime - WorkStartTime) // 2 + BreakDurationMin * 60,
    )


if __name__ == '__main__':
    load_all_aas()
    env  = build_env()
    ready = env.reset()
    print(f'[ready_queue] {len(ready)} processes ready at t=0')
