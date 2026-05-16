# -*- coding: utf-8 -*-
"""GNN + PPO 네트워크.

agent.act 호출 시 만나는 순서:

    1. kg.build_H_static_scalar()                              # (N, 5)
    2. kg.build_H_dynamic(completed, warehouse, wip_tracker)   # (N, 4)
    3. kg.GroupIdShort_ids(factory)                            # (N,) int
    4. kg.WorkstationId_ids(factory)                           # (N,) int
    5. GroupIdShort_embedding / WorkstationId_embedding lookup → H (N, 17)
    6. R-GCN 2-layer forward → node_scores (N,), graph_embed (16,)
    7. node_scores 를 ready_mask 로 마스킹 → softmax → Categorical.sample()
    8. critic encoder(state_vec || graph_embed) → V(s)
"""
from dataclasses import dataclass, field
from typing import Dict, List, Tuple

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F

import cpro_config as C
from kg import KnowledgeGraph, NUM_RELATIONS
from factory import Factory


# ── R-GCN layer ──────────────────────────────────────────────────────────

class RelationalGCNLayer(nn.Module):
    """H_next = ReLU( Σ_r  Â_r @ H @ W_r + bias )"""

    def __init__(self, in_dim: int, out_dim: int, num_relations: int = NUM_RELATIONS):
        super().__init__()
        self.W = nn.ModuleList([
            nn.Linear(in_dim, out_dim, bias=False) for _ in range(num_relations)
        ])
        self.bias = nn.Parameter(torch.zeros(out_dim))

    def forward(self, H: torch.Tensor, adj_normalized_list: List[torch.Tensor]) -> torch.Tensor:
        out = 0
        for r, A_n in enumerate(adj_normalized_list):
            out = out + self.W[r](A_n @ H)
        return F.relu(out + self.bias)


#========ProcessGNN========

class ProcessGNN(nn.Module):
    """2-layer R-GCN + (GroupIdShort, WorkstationId) embedding + score head."""

    def __init__(self,
                 num_GroupIdShort: int,
                 num_WorkstationId: int,
                 num_static_scalar: int = 5,
                 num_dynamic: int = 4,
                 GroupIdShort_embedding_dim:  int = C.GROUPIDSHORT_EMBEDDING_DIM,
                 WorkstationId_embedding_dim: int = C.WORKSTATIONID_EMBEDDING_DIM,
                 hidden:                      int = C.GNN_HIDDEN,
                 out_dim:                     int = C.GNN_OUT_DIM):
        super().__init__()
        in_dim = (num_static_scalar + GroupIdShort_embedding_dim
                + WorkstationId_embedding_dim + num_dynamic)
        assert in_dim == C.GNN_IN_DIM, f'in_dim {in_dim} != GNN_IN_DIM {C.GNN_IN_DIM}'

        self.GroupIdShort_embedding  = nn.Embedding(num_GroupIdShort,  GroupIdShort_embedding_dim)
        self.WorkstationId_embedding = nn.Embedding(num_WorkstationId, WorkstationId_embedding_dim)

        self.layer1 = RelationalGCNLayer(in_dim, hidden)
        self.layer2 = RelationalGCNLayer(hidden, out_dim)
        self.score  = nn.Linear(out_dim, 1)

    def build_H(self,
                H_static:           torch.Tensor,
                H_dynamic:          torch.Tensor,
                GroupIdShort_ids:   torch.Tensor,
                WorkstationId_ids:  torch.Tensor) -> torch.Tensor:
        return torch.cat([
            H_static,
            self.GroupIdShort_embedding(GroupIdShort_ids),
            self.WorkstationId_embedding(WorkstationId_ids),
            H_dynamic,
        ], dim=-1)

    def forward(self,
                H: torch.Tensor,
                adj_normalized_list: List[torch.Tensor]
                ) -> Tuple[torch.Tensor, torch.Tensor]:
        H1 = self.layer1(H,  adj_normalized_list)
        H2 = self.layer2(H1, adj_normalized_list)
        node_scores = self.score(H2).squeeze(-1)
        graph_embed = H2.mean(dim=0)
        return node_scores, graph_embed

    @staticmethod
    def row_normalize(adj: torch.Tensor) -> torch.Tensor:
        deg = adj.sum(dim=1, keepdim=True).clamp(min=1e-6)
        return adj / deg


#========PPOAgent========

@dataclass
class Transition:
    state_vec  : np.ndarray
    H_snapshot : np.ndarray
    mask       : np.ndarray
    action     : int
    log_pi_old : float
    value      : float
    reward     : float = 0.0
    done       : bool  = False


class PPOAgent(nn.Module):
    """Critic encoder + heads + rollout buffer + update.

    state_vec = [progress_t 1 + 모델별 완성률 K + 워커 util W + energy_norm 1]
    Actor logit  = GNN node_scores (ready_mask masked)
    """

    def __init__(self, gnn: ProcessGNN, factory: Factory, kg: KnowledgeGraph, state_dim: int):
        super().__init__()
        self.gnn       = gnn
        self.factory   = factory
        self.kg        = kg
        self.state_dim = state_dim

        in_dim = state_dim + C.GNN_OUT_DIM
        self.encoder = nn.Sequential(
            nn.Linear(in_dim,             C.CRITIC_HIDDEN_1), nn.ReLU(),
            nn.Linear(C.CRITIC_HIDDEN_1,  C.CRITIC_HIDDEN_2), nn.ReLU(),
        )
        self.critic_head = nn.Linear(C.CRITIC_HIDDEN_2, 1)

        self.optimizer = torch.optim.Adam(self.parameters(), lr=C.PPO_LR)
        self.buf: List[Transition] = []
        # delta reward state (매 episode 시작 시 reset_episode 호출 필요)
        self._prev_t    = 0.0
        self._prev_kwh  = 0.0
        self._prev_done = 0

        # KG 가 정적이므로 5종 정규화 인접행렬을 한 번만 캐시
        self.adj_normalized_list = [
            ProcessGNN.row_normalize(torch.tensor(A, dtype=torch.float32))
            for A in kg.adj_relations
        ]
        self.GroupIdShort_ids  = torch.tensor(kg.GroupIdShort_ids(factory),  dtype=torch.long)
        self.WorkstationId_ids = torch.tensor(kg.WorkstationId_ids(factory), dtype=torch.long)

    # ── 한 step 의 입력 빌드 ──────────────────────────────────────────

    def build_H_tensor(self, env, done_set) -> torch.Tensor:
        H_static  = torch.tensor(self.kg.build_H_static_scalar(),                  dtype=torch.float32)
        H_dynamic = torch.tensor(
            self.kg.build_H_dynamic(done_set, env.warehouse),                      dtype=torch.float32)
        return self.gnn.build_H(H_static, H_dynamic, self.GroupIdShort_ids, self.WorkstationId_ids)

    def build_state_vec(self, env) -> torch.Tensor:
        """state_vec = [progress_t 1 + 모델별 Throughput 비율 K + 워커 util W + energy_norm 1].

        mod 일치 — env.EpisodeEnergyKwh[0] / env._throughput_counter[0] / env.worker_resources.
        """
        now         = float(env.env.now)
        progress_t  = now / max(self.factory.total_work_seconds, 1.0)
        energy_norm = env.EpisodeEnergyKwh[0] / max(self.factory.total_expected_kwh, 1.0)

        global_throughput = env._throughput_counter[0]
        target_total      = max(env.target_qty, 1)
        completion_rates  = [global_throughput / target_total] * len(env.TARGET_QTY)

        worker_util = [
            1.0 - res.count / max(res.capacity, 1)
            for res in env.worker_resources.values()
        ]

        vec = np.concatenate([
            np.asarray([progress_t],     dtype=np.float32),
            np.asarray(completion_rates, dtype=np.float32),
            np.asarray(worker_util,      dtype=np.float32),
            np.asarray([energy_norm],    dtype=np.float32),
        ])
        return torch.tensor(vec, dtype=torch.float32)

    # ── action 선택 (produce_unit 내부 callback) ─────────────────────

    def _delta_reward(self, env) -> float:
        """mod 의 누적 state 만 읽어 delta reward 계산 (mod 에 reward() 메서드 없음)."""
        dt_wall = env.env.now                   - self._prev_t
        d_kwh   = env.EpisodeEnergyKwh[0]       - self._prev_kwh
        d_done  = env._throughput_counter[0]    - self._prev_done

        W = env.RewardWeights
        r_time = -dt_wall / max(self.factory.total_work_seconds, 1.0)
        r_kwh  = -d_kwh   / max(self.factory.total_expected_kwh, 1.0)
        r_done =  d_done  / max(self.factory.total_target_qty,   1)

        reward = (W.get('W1_TimeElapsed', 0.2) * r_time
                + W.get('W2_Energy',      0.2) * r_kwh
                + W.get('W5_Throughput',  0.25) * r_done)

        self._prev_t    = env.env.now
        self._prev_kwh  = env.EpisodeEnergyKwh[0]
        self._prev_done = env._throughput_counter[0]
        return reward

    def choose(self, ready_pcs, model_id, done_set, env) -> str:
        """produce_unit 안에서 호출. ready_pcs 중 한 PC 선택 → ProcessCode 반환."""
        # 직전 transition reward 갱신
        if self.buf:
            self.buf[-1].reward = float(self._delta_reward(env))

        H         = self.build_H_tensor(env, done_set)
        state_vec = self.build_state_vec(env)
        ready_mask = np.array([(pc in ready_pcs) for pc in self.kg.ProcessCodes], dtype=bool)

        with torch.no_grad():
            node_scores, graph_embed = self.gnn(H, self.adj_normalized_list)
            mask_t = torch.tensor(ready_mask, dtype=torch.bool)
            scores = node_scores.masked_fill(~mask_t, float('-inf'))
            probs  = torch.softmax(scores, dim=0)
            dist   = torch.distributions.Categorical(probs=probs, validate_args=False)
            action = dist.sample()
            log_pi = dist.log_prob(action)

            x = torch.cat([state_vec.unsqueeze(0), graph_embed.unsqueeze(0)], dim=-1)
            v = self.critic_head(self.encoder(x)).squeeze().item()

        self.buf.append(Transition(
            state_vec  = state_vec.detach().numpy(),
            H_snapshot = H.detach().numpy(),
            mask       = ready_mask.copy(),
            action     = int(action.item()),
            log_pi_old = float(log_pi.item()),
            value      = float(v),
        ))
        action_idx = int(action.item())
        chosen_pc  = self.kg.ProcessCodes[action_idx]
        # mask 실패 (이론상 안 일어남) 시 첫 ready 로 fallback
        if chosen_pc not in ready_pcs:
            chosen_pc = ready_pcs[0]
        return chosen_pc

    def finalize_episode(self, env) -> None:
        """episode 끝에 마지막 transition 의 reward 갱신 + done 표시."""
        if self.buf:
            self.buf[-1].reward = float(self._delta_reward(env))
            self.buf[-1].done   = True

    def reset_episode(self) -> None:
        """새 episode 시작 시 delta 기준점 초기화."""
        self._prev_t    = 0.0
        self._prev_kwh  = 0.0
        self._prev_done = 0

    # ── PPO update (GAE + clip + value MSE + entropy) ────────────────

    def update(self) -> float:
        if len(self.buf) < 2:
            self.buf.clear()
            return 0.0

        rewards = [t.reward for t in self.buf]
        values  = [t.value  for t in self.buf]
        ep_r    = float(sum(rewards))

        advantages = [0.0] * len(rewards)
        gae        = 0.0
        for i in reversed(range(len(rewards) - 1)):
            delta         = rewards[i] + C.PPO_GAMMA * values[i + 1] - values[i]
            gae           = delta + C.PPO_GAMMA * C.PPO_LAMBDA * gae
            advantages[i] = gae
        advantages_t = torch.tensor(advantages, dtype=torch.float32)
        if advantages_t.std() > 1e-8:
            advantages_t = (advantages_t - advantages_t.mean()) / (advantages_t.std() + 1e-8)
        returns = [a + v for a, v in zip(advantages, values)]

        for _ in range(C.PPO_EPOCHS):
            for i in range(len(self.buf) - 1):
                t   = self.buf[i]
                H   = torch.tensor(t.H_snapshot, dtype=torch.float32)
                node_scores, graph_embed = self.gnn(H, self.adj_normalized_list)
                mask_t = torch.tensor(t.mask, dtype=torch.bool)
                scores = node_scores.masked_fill(~mask_t, float('-inf'))
                probs  = torch.softmax(scores, dim=0)
                dist   = torch.distributions.Categorical(probs=probs, validate_args=False)
                new_lp = dist.log_prob(torch.tensor(t.action))
                ratio  = torch.exp(new_lp - torch.tensor(t.log_pi_old))

                s_t   = torch.tensor(t.state_vec, dtype=torch.float32).unsqueeze(0)
                x     = torch.cat([s_t, graph_embed.unsqueeze(0)], dim=-1)
                v_new = self.critic_head(self.encoder(x)).squeeze()

                adv    = advantages_t[i]
                loss_p = -torch.min(
                    ratio * adv,
                    torch.clamp(ratio, 1 - C.PPO_CLIP_EPS, 1 + C.PPO_CLIP_EPS) * adv)
                loss_v = F.mse_loss(v_new, torch.tensor(returns[i], dtype=torch.float32))
                entropy = dist.entropy()
                loss    = loss_p + C.PPO_C_VALUE * loss_v - C.PPO_C_ENT * entropy

                self.optimizer.zero_grad()
                loss.backward()
                nn.utils.clip_grad_norm_(self.parameters(), 0.5)
                self.optimizer.step()

        self.buf.clear()
        return ep_r
