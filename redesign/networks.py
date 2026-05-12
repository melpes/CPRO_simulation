# -*- coding: utf-8 -*-
"""GNN + PPO 네트워크.

GNN
---
R-GCN 2-layer, 5 relation (fwd_join, fwd_seq, bwd_join, bwd_seq, self).
입력 H = [정적 scalar 5 + pg_emb 4 + line_emb 4 + 동적 4] = 17-d.
출력:
  - node_scores (N,) — actor logit
  - graph_embed (16,) — critic context

PPO
---
- act(): GNN forward → mask + softmax + sample → (action_idx, log_pi, V, ...)
- store(): rollout buffer 에 transition 저장 (H snapshot 보존)
- update(): GAE + clipped surrogate + value MSE

경로 패턴(참고)::

    pg_ids   = kg.pg_ids()
    line_ids = kg.line_ids()
    H_static = kg.build_H_static_scalar()        # (N, 5)
    H_dyn    = kg.build_H_dynamic()              # (N, 4)
    H = concat([H_static, pg_emb(pg_ids), line_emb(line_ids), H_dyn], -1)  # (N, 17)
"""
from __future__ import annotations

from typing import Dict, List, Optional, Tuple

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F

import cpro_config as C
from kg import KnowledgeGraph, NUM_RELATIONS, R_FWD_JOIN, R_FWD_SEQ, R_BWD_JOIN, R_BWD_SEQ, R_SELF
from factory import Factory


# ── R-GCN ────────────────────────────────────────────────────────────────


class RelGCNLayer(nn.Module):
    """Relation-aware GCN layer.

    H_next = ReLU( Σ_r  Â_r @ H @ W_r  + bias )
    """

    def __init__(self, in_dim: int, out_dim: int, num_rel: int = NUM_RELATIONS):
        super().__init__()
        self.W = nn.ModuleList([
            nn.Linear(in_dim, out_dim, bias=False) for _ in range(num_rel)
        ])
        self.bias = nn.Parameter(torch.zeros(out_dim))

    def forward(self, H: torch.Tensor, adj_norm_list: List[torch.Tensor]) -> torch.Tensor:
        out = 0
        for r, A_n in enumerate(adj_norm_list):
            out = out + self.W[r](A_n @ H)
        return F.relu(out + self.bias)


class ProcessGNN(nn.Module):
    """2-layer R-GCN + embedding (pg, line) + score head.

    forward / graph_embed 둘 다 (node_scores, H2) 를 반환하도록 통합.
    """

    def __init__(self,
                 num_pg: int,
                 num_line: int,
                 num_static_scalar: int = 5,
                 num_dynamic: int = 4,
                 emb_pg: int = C.EMB_DIM_PG,
                 emb_line: int = C.EMB_DIM_LINE,
                 hidden: int = C.GNN_HIDDEN,
                 out_dim: int = C.GNN_OUT_DIM):
        super().__init__()
        in_dim = num_static_scalar + emb_pg + emb_line + num_dynamic
        assert in_dim == C.GNN_IN_DIM, f'in_dim {in_dim} != GNN_IN_DIM {C.GNN_IN_DIM}'

        self.pg_emb   = nn.Embedding(num_pg, emb_pg)
        self.line_emb = nn.Embedding(num_line, emb_line)

        self.layer1 = RelGCNLayer(in_dim, hidden)
        self.layer2 = RelGCNLayer(hidden, out_dim)
        self.score  = nn.Linear(out_dim, 1)

    def build_H(self,
                H_static: torch.Tensor,
                H_dynamic: torch.Tensor,
                pg_ids: torch.Tensor,
                line_ids: torch.Tensor) -> torch.Tensor:
        return torch.cat([
            H_static,
            self.pg_emb(pg_ids),
            self.line_emb(line_ids),
            H_dynamic,
        ], dim=-1)

    def forward(self,
                H: torch.Tensor,
                adj_norm_list: List[torch.Tensor]
                ) -> Tuple[torch.Tensor, torch.Tensor]:
        H1 = self.layer1(H,  adj_norm_list)
        H2 = self.layer2(H1, adj_norm_list)
        node_scores = self.score(H2).squeeze(-1)
        graph_embed = H2.mean(dim=0)
        return node_scores, graph_embed

    @staticmethod
    def row_normalize(adj: torch.Tensor) -> torch.Tensor:
        deg = adj.sum(dim=1, keepdim=True).clamp(min=1e-6)
        return adj / deg


# ── PPO ──────────────────────────────────────────────────────────────────


class PPOAgent(nn.Module):
    """Critic encoder + heads + rollout buffer + update.

    Critic 입력 = concat(state_vec, graph_embed).
    Actor logit = GNN 의 node_scores (마스킹 후 softmax).
    """

    def __init__(self,
                 gnn: ProcessGNN,
                 factory: Factory,
                 kg: KnowledgeGraph,
                 state_dim: int):
        super().__init__()
        self.gnn = gnn
        self.factory = factory
        self.kg = kg
        self.state_dim = state_dim

        in_dim = state_dim + C.GNN_OUT_DIM
        self.encoder = nn.Sequential(
            nn.Linear(in_dim, C.CRITIC_HIDDEN_1), nn.ReLU(),
            nn.Linear(C.CRITIC_HIDDEN_1, C.CRITIC_HIDDEN_2), nn.ReLU(),
        )
        self.critic_head = nn.Linear(C.CRITIC_HIDDEN_2, 1)

        self.optimizer = torch.optim.Adam(self.parameters(), lr=C.PPO_LR)
        self.buf: List[dict] = []
        self.ep_rewards: List[float] = []

        # adj 5종 정규화 텐서 — KG 가 정적이라 한 번만 계산
        self._adj_norm = [
            ProcessGNN.row_normalize(torch.tensor(A, dtype=torch.float32))
            for A in kg.adj_relations
        ]

    # ── 한 step 의 입력 빌드 ──────────────────────────────────────────

    def _build_H_tensors(self) -> Tuple[torch.Tensor, torch.Tensor]:
        H_static  = torch.tensor(self.kg.build_H_static_scalar(), dtype=torch.float32)
        H_dynamic = torch.tensor(self.kg.build_H_dynamic(),       dtype=torch.float32)
        pg_ids    = torch.tensor(self.kg.pg_ids(),                dtype=torch.long)
        line_ids  = torch.tensor(self.kg.line_ids(),              dtype=torch.long)
        return self.gnn.build_H(H_static, H_dynamic, pg_ids, line_ids), H_static

    # ── action 선택 ──────────────────────────────────────────────────

    def act(self,
            env,                     # ManufacturingEnv (state_vec build 용)
            mask_np: np.ndarray,
            caller_line_id: str) -> Optional[int]:
        H, _ = self._build_H_tensors()
        state_vec = self._build_state_vec(env, caller_line_id)

        with torch.no_grad():
            node_scores, graph_embed = self.gnn(H, self._adj_norm)
            mask_t = torch.tensor(mask_np, dtype=torch.bool)
            scores = node_scores.masked_fill(~mask_t, float('-inf'))
            probs = torch.softmax(scores, dim=0)
            dist  = torch.distributions.Categorical(probs=probs, validate_args=False)
            action = dist.sample()
            log_pi = dist.log_prob(action)

            x = torch.cat([state_vec.unsqueeze(0), graph_embed.unsqueeze(0)], dim=-1)
            v = self.critic_head(self.encoder(x)).squeeze().item()

        # buffer 에 transition 저장 (H snapshot 통째 보존)
        self.buf.append({
            'state_vec':   state_vec.detach().numpy(),
            'H_snapshot':  H.detach().numpy(),
            'mask':        mask_np.copy(),
            'action':      int(action.item()),
            'log_pi_old':  float(log_pi.item()),
            'V':           float(v),
            'caller_line': caller_line_id,
            'reward':      0.0,    # store_reward 로 채움
            'done':        False,
        })
        return int(action.item())

    def store_reward(self, r: float, done: bool) -> None:
        if not self.buf:
            return
        self.buf[-1]['reward'] = float(r)
        self.buf[-1]['done']   = bool(done)

    # ── state_vec 빌드 ───────────────────────────────────────────────

    def _build_state_vec(self, env, caller_line_id: str) -> torch.Tensor:
        """state_vec = [진행도 1 + 모델별 완성률 K + line_emb(caller) 4
                      + 글로벌 5 + 워커 util W]"""
        factory = self.factory

        # 진행도
        now = float(env.simpy_env.now)
        progress_t = now / max(factory.T_REF, 1.0)

        # 모델별 완성률
        completion = []
        for model_id, qty in factory.order.items():
            done_n = sum(
                1 for s in env.units.values()
                if s.model_id == model_id
                and len(s.done) == len(factory.models[model_id].process_codes()))
            completion.append(done_n / max(qty, 1))

        # 호출자 line_emb (GNN 의 embedding 공유)
        line_idx = factory.line_to_idx[caller_line_id]
        caller_vec = self.gnn.line_emb(torch.tensor(line_idx)).detach().numpy()

        # 글로벌 5
        total_order = max(factory.total_order, 1)
        global5 = [
            env.warehouse.violations_count / total_order,
            env.wip.violations_count       / total_order,
            env.energy.total_kwh           / max(now + 1, 1),
            env.idle.idle_seconds          / max(now + 1, 1),
            0.0,    # smt_broken_ratio placeholder
        ]

        # 워커 util W
        worker_util = [
            1.0 - r.count / max(r.capacity, 1)
            for r in env.worker_resources.values()
        ]

        vec = np.concatenate([
            np.asarray([progress_t], dtype=np.float32),
            np.asarray(completion,   dtype=np.float32),
            caller_vec.astype(np.float32),
            np.asarray(global5,      dtype=np.float32),
            np.asarray(worker_util,  dtype=np.float32),
        ])
        return torch.tensor(vec, dtype=torch.float32)

    # ── PPO update (GAE + clip + value MSE) ──────────────────────────

    def update(self) -> float:
        if len(self.buf) < 2:
            self.buf.clear()
            return 0.0

        rewards = [e['reward'] for e in self.buf]
        values  = [e['V']      for e in self.buf]
        ep_r    = float(sum(rewards))
        self.ep_rewards.append(ep_r)

        # GAE
        advs = [0.0] * len(rewards)
        gae = 0.0
        for i in reversed(range(len(rewards) - 1)):
            delta = rewards[i] + C.PPO_GAMMA * values[i+1] - values[i]
            gae   = delta + C.PPO_GAMMA * C.PPO_LAMBDA * gae
            advs[i] = gae
        advs_t = torch.tensor(advs, dtype=torch.float32)
        if advs_t.std() > 1e-8:
            advs_t = (advs_t - advs_t.mean()) / (advs_t.std() + 1e-8)
        returns = [a + v for a, v in zip(advs, values)]

        for _ in range(C.PPO_EPOCHS):
            for i in range(len(self.buf) - 1):
                e = self.buf[i]
                H = torch.tensor(e['H_snapshot'], dtype=torch.float32)
                node_scores, graph_embed = self.gnn(H, self._adj_norm)
                mask_t = torch.tensor(e['mask'], dtype=torch.bool)
                scores = node_scores.masked_fill(~mask_t, float('-inf'))
                probs  = torch.softmax(scores, dim=0)
                dist   = torch.distributions.Categorical(probs=probs, validate_args=False)
                new_lp = dist.log_prob(torch.tensor(e['action']))
                ratio  = torch.exp(new_lp - torch.tensor(e['log_pi_old']))

                s_t = torch.tensor(e['state_vec'], dtype=torch.float32).unsqueeze(0)
                x   = torch.cat([s_t, graph_embed.unsqueeze(0)], dim=-1)
                v_new = self.critic_head(self.encoder(x)).squeeze()

                adv = advs_t[i]
                loss_p = -torch.min(
                    ratio * adv,
                    torch.clamp(ratio, 1 - C.PPO_CLIP_EPS, 1 + C.PPO_CLIP_EPS) * adv)
                loss_v = F.mse_loss(v_new, torch.tensor(returns[i], dtype=torch.float32))

                # entropy bonus
                ent = dist.entropy()
                loss = loss_p + C.PPO_C_VALUE * loss_v - C.PPO_C_ENT * ent

                self.optimizer.zero_grad()
                loss.backward()
                nn.utils.clip_grad_norm_(self.parameters(), 0.5)
                self.optimizer.step()

        self.buf.clear()
        return ep_r
