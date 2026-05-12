# -*- coding: utf-8 -*-
"""CPRO RL 재설계 패키지.

흐름::

    path_extractor.load_aas_models  →  AASModel dict
                                       │
                                       Factory  (정적 매핑 + 정규화 분모)
                                       │
                                       KnowledgeGraph  (통합 KG, 5 relation adj)
                                       │
                                       ManufacturingEnv  (SimPy + Dispatcher)
                                       │
                                       ProcessGNN + PPOAgent
                                       │
                                       ExperimentRunner.train()

설계 원칙:
  - AAS 진입은 path_extractor 만.
  - 동적 feat 갱신 + event hook 은 ``sim_env.Dispatcher`` 한 곳.
  - 노드 키 = (model_id, process_code) tuple.
  - 한 (m, pc) 에 시뮬 중 여러 ready unit 가능 → ``ready_units`` FIFO queue.
  - 정규화 분모 (T_REF, E_REF, total_order, total_worker_capacity) 는 cpro_config 에
    식이 명시되고 실제 값은 Factory init 에서 계산.
  - 패딩 / OOV 없음. 다른 공장 적용 시 재학습.
"""
