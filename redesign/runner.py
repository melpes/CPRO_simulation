# -*- coding: utf-8 -*-
"""실험/학습 루프 — 모든 모듈의 결합 지점.

호출 경로::

    1. path_extractor.load_aas_models(json_dir, model_files) → Dict[str, AASModel]
    2. Factory(models, order, line_to_worker, rated_kw_table, worker_capacity)
    3. KnowledgeGraph(factory)
    4. ManufacturingEnv(factory, kg, agent=None)
    5. ProcessGNN + PPOAgent(gnn, factory, kg, state_dim)
    6. env.agent = agent
    7. for ep in episodes:
           env.reset()
           env.run(until_sec=factory.T_REF)
           r_ep = env.reward(done=True)
           agent.store_reward(r_ep, done=True)
           agent.update()

state_dim 은 ``_compute_state_dim(factory)`` 로 결정 — 패딩 없이 그 공장의
실제 cardinality 에 맞춤. 다른 공장 적용 시 재학습.
"""
from __future__ import annotations

from typing import Dict

import cpro_config as C
from aas import load_aas_models
from factory import Factory
from kg import KnowledgeGraph
from sim_env import ManufacturingEnv
from networks import ProcessGNN, PPOAgent


def _compute_state_dim(factory: Factory) -> int:
    """state_vec 의 정확한 차원 = 1 + K + line_emb + 5 + W.

    networks._build_state_vec 의 concat 순서와 1대1 대응:
      - 진행도            1
      - 모델별 완성률     K = len(factory.order)
      - 호출자 line_emb   C.EMB_DIM_LINE (= 4)
      - 글로벌 5          5
      - 워커 util         W = len(factory.worker_capacity)
    """
    K = len(factory.order)
    W = len(factory.worker_capacity)
    return 1 + K + C.EMB_DIM_LINE + 5 + W


class ExperimentRunner:

    def __init__(self,
                 json_dir: str,
                 model_files: Dict[str, str],
                 wwm_filename: str,
                 sim_filename: str,
                 order:       Dict[str, int],
                 line_to_worker: Dict[str, str],
                 rated_kw_table: Dict[str, float],
                 worker_capacity: Dict[str, int],
                 bom_min_stock:  Dict[str, int] = None,
                 bom_max_stock:  Dict[str, int] = None,
                 sim_node_group_override: Dict[str, str] = None):
        # ── 1. AAS 로딩 (path_extractor 4 진입점 통합) ────────────────
        self.aas_models = load_aas_models(json_dir, model_files, wwm_filename,
                                          sim_filename, sim_node_group_override)

        # ── 2. Factory ─────────────────────────────────────────────────
        self.factory = Factory(
            models          = self.aas_models,
            order           = order,
            line_to_worker  = line_to_worker,
            rated_kw_table  = rated_kw_table,
            worker_capacity = worker_capacity,
            bom_min_stock   = bom_min_stock or {},
            bom_max_stock   = bom_max_stock or {},
        )
        # bom_min/max_stock 미지정 시 cpro_config.MIN_STOCK 으로 임시 채움
        # (AAS HS Category[...].MinStock/MaxStock 미구현 placeholder).
        if not bom_min_stock:
            for item in self.factory.all_bom_items():
                self.factory.bom_min_stock[item] = C.MIN_STOCK
                self.factory.bom_max_stock[item] = C.MIN_STOCK * 4

        # ── 3. KG ──────────────────────────────────────────────────────
        self.kg = KnowledgeGraph(self.factory)

        # ── 4. GNN + PPO ──────────────────────────────────────────────
        self.gnn = ProcessGNN(
            num_pg   = len(self.factory.pg_to_idx),
            num_line = len(self.factory.line_to_idx),
        )
        self.agent = PPOAgent(
            gnn=self.gnn,
            factory=self.factory,
            kg=self.kg,
            state_dim=_compute_state_dim(self.factory),
        )

        # ── 5. SimEnv (agent 주입) ─────────────────────────────────────
        self.env = ManufacturingEnv(self.factory, self.kg, agent=self.agent)

    # ── 학습 entry ────────────────────────────────────────────────────

    def train(self, episodes: int = 100) -> list:
        rewards_log: list = []
        for ep in range(episodes):
            self.env.reset()
            self.env.run(until_sec=self.factory.T_REF)

            # ep 종료 시 마지막 transition 에 terminal reward 부착
            r_terminal = self.env.reward(done=True)
            self.agent.store_reward(r_terminal, done=True)

            ep_r = self.agent.update()
            rewards_log.append(ep_r)
            print(f'[ep {ep:4d}] reward = {ep_r:.4f}')
        return rewards_log


if __name__ == '__main__':
    # 실행 예시 (실제 값은 cpro_config.py 와 호출자가 채움)
    runner = ExperimentRunner(
        json_dir   = '..',
        model_files = {
            'MODEL_A': 'MODEL_A.json',
            'MODEL_B': 'MODEL_B.json',
            'MODEL_C': 'MODEL_C.json',
        },
        wwm_filename = 'WorkstationWorkerMatchingDataAAS.json',
        sim_filename = 'ProvisionOfSimulationModel.json',
        order = {'MODEL_A': 10, 'MODEL_B': 10, 'MODEL_C': 10},
        # 아래 3 dict 는 cpro_config 의 정적 매핑에서 가져오거나 호출 시 명시.
        line_to_worker  = C.WWM_LINE_TO_WORKER,
        rated_kw_table  = C.RATED_POWER_KW,
        worker_capacity = {},   # 실제 사용 시 채워서 전달
    )
    runner.train(episodes=5)
