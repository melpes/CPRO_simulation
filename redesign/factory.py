# -*- coding: utf-8 -*-
"""정규화 분모 + 식별자 idx 매핑.

KG / workers / WorkSchedule / 주문량을 받아 reward / state_vec 계산에
쓰이는 스칼라 4종과 (ProcessGroup, Workstation) → idx 매핑을 한 번에 산출.

흐름::

    runner.build_env()
        ├─ KnowledgeGraph.build(...)
        ├─ workers = PSM.workers
        ├─ schedule = WorkSchedule(...)
        └─ Factory.build(kg, workers, schedule, target_qty, MAX_DAYS)
                ↓
            CproSimEnv 에 주입 → step 안에서 reward 계산
"""
from dataclasses import dataclass, field
from typing import Dict

from kg import KnowledgeGraph


@dataclass
class Factory:
    total_work_seconds                 : float    #← MAX_DAYS * (work_end - work_start - break_duration). reward 시간 페널티 분모.
    total_expected_kwh                 : float    #← Σ CycleTimeSec * RatedPowerKw * total_target_qty / 3600. reward 에너지 페널티 분모.
    total_target_qty                   : int      #← sum(TARGET_QTY.values()). 전체 unit 수.
    total_pc_progressions              : int      #← Σ_m TARGET_QTY[m] * PCs_per_model[m]. reward dense 완성 보상 분모 (한 unit 의 모든 PC 진행 합).
    total_worker_capacity              : int      #← sum(info['worker_count'] for info in workers.values()). reward idle 페널티 분모.
    GroupIdShort_to_embedding_index    : Dict[str, int] = field(default_factory=dict)   #← GNN.GroupIdShort_embedding lookup row {GroupIdShort  : 0..N-1}
    WorkstationId_to_embedding_index   : Dict[str, int] = field(default_factory=dict)   #← GNN.WorkstationId_embedding lookup row {WorkstationId : 0..N-1}

    @classmethod
    def build(cls, kg: KnowledgeGraph, workers: dict,
              WorkStartTime: int, WorkEndTime: int, break_start_sec: int, break_end_sec: int,
              TARGET_QTY: Dict[str, int], MAX_DAYS: int) -> 'Factory':
        work_sec_per_day      = (WorkEndTime - WorkStartTime
                              - (break_end_sec - break_start_sec))
        total_work_seconds    = float(MAX_DAYS * work_sec_per_day)

        total_target_qty      = sum(TARGET_QTY.values())

        PCs_per_model         = {}
        for node in kg.nodes.values():
            PCs_per_model[node.model_id] = PCs_per_model.get(node.model_id, 0) + 1
        total_pc_progressions = sum(
            TARGET_QTY.get(model_id, 0) * pc_count
            for model_id, pc_count in PCs_per_model.items()
        )

        expected_kwh_per_unit = sum(
            node.CycleTimeSec * node.RatedPowerKw / 3600
            for node in kg.nodes.values()
        )
        total_expected_kwh    = max(expected_kwh_per_unit * total_target_qty, 1.0)

        total_worker_capacity = sum(info['worker_count'] for info in workers.values())

        GroupIdShorts         = []
        for node in kg.nodes.values():
            if node.GroupIdShort not in GroupIdShorts:
                GroupIdShorts.append(node.GroupIdShort)
        WorkstationIds        = list(workers.keys())

        return cls(
            total_work_seconds               = total_work_seconds,
            total_expected_kwh               = total_expected_kwh,
            total_target_qty                 = total_target_qty,
            total_pc_progressions            = total_pc_progressions,
            total_worker_capacity            = total_worker_capacity,
            GroupIdShort_to_embedding_index  = {GroupIdShort:  i for i, GroupIdShort  in enumerate(GroupIdShorts)},
            WorkstationId_to_embedding_index = {WorkstationId: i for i, WorkstationId in enumerate(WorkstationIds)},
        )
