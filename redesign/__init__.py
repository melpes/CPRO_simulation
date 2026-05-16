# -*- coding: utf-8 -*-
"""CPRO 시뮬레이션 + RL 재설계 패키지.

흐름 (위에서 아래로 읽는 순서)::

    path_extractor.load(*.json)
        │  ← AAS 4종 (PSM / WWM / HS / MP) 모두 PSM 한 진입점으로 노출
        ▼
    ProvisionofSimulationModelsAAS (PSM)
        │  ← PSM.SimulationModels.SimulationModel.{Action, Warehouse, DefaultParameters}
        │    PSM.workers / PSM.WarehouseManagedBOM
        ▼
    runner.build_env()
        │
        ├─ KnowledgeGraph.build(ManufacturingProcesses, workers)   # kg.py
        ├─ Warehouse.build(WarehouseManagedBOM, BOMCategory)       # sim_env.py
        └─ CproSimEnv(KG, Warehouse, Sequences, DefaultParameters) # sim_env.py
               │
               ├─ env.reset()              → ready (List[ProcessCode])
               └─ env.step((pc, ws_id))    → process_job(env, ...)
                                                ├─ env.timeout(CycleTimeSec)
                                                ├─ warehouse.consume(InputBOM)
                                                └─ warehouse.replenish()  (부족 시)

설계 원칙 (CLAUDE.md '## redesign / ver0 코딩 스타일' 참조):
  - AAS 진입은 path_extractor 만. PSM 트리에서 모든 변수 추출.
  - 도메인 dataclass (KG, Warehouse) 는 simpy 의존 없음. 재사용 가능.
  - 모든 외부 입력은 runner.build_env() 한 곳에서 결합.
  - 가독성 + 코드 흐름 순서가 최우선.
"""
