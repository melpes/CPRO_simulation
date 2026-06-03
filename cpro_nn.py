# -*- coding: utf-8 -*-
"""ver1 RL 신경망·해석기 (③ 분할). import_callable/GraphModule(AAS 계산그래프 해석) + op primitive + PPOAgent."""
from __future__ import annotations

import torch

from cpro_observe import obs_node_features, obs_graph_topology


class PPOAgent(torch.nn.Module):
    def __init__(self, *, encoder, actor, critic, StateDim,
                 LearningRate, ClipEpsilon, Gamma, GaeLambda,
                 EntropyCoef, ValueLossCoef, UpdateEpochs, BatchSize, RuntimeVariables):
        # 아키텍처(encoder/actor/critic)는 해석기(cf.build_agent)가 GraphModule 로 빌드해 주입.
        # AAS ModelArchitecture.Network 가 조립을 기술하고 코드 팔레트가 빌더를 보유 — 여기선 받기만.
        # submodule 속성명(GNNEncoder/Actor/Critic)은 state_dict 호환 위해 고정.
        super().__init__()
        self.StateDim        = StateDim
        self.GNNEncoder      = encoder
        self.Actor           = actor
        self.Critic          = critic
        self.ClipEpsilon     = ClipEpsilon
        self.Gamma           = Gamma
        self.GaeLambda       = GaeLambda
        self.EntropyCoef     = EntropyCoef
        self.ValueLossCoef   = ValueLossCoef
        self.UpdateEpochs    = UpdateEpochs
        self.BatchSize       = BatchSize
        self.RuntimeVariables = RuntimeVariables  #← path_extractor RuntimeVariables (AAS 명시 연산)
        self.optimizer       = torch.optim.Adam(self.parameters(), lr=LearningRate)

    def reset_buffer(self):
        self.buf = []   # 결정점마다 {ready, idx, logp, value}

    @torch.no_grad()        # rollout 은 무-grad (표준 PPO). grad 는 learn() 이 forward 재실행하며 계산.
    def choose(self, ready_pcs, env):
        # produce_unit 의 결정점 콜백. 학습(training)→샘플, 평가(eval)→argmax(결정론).
        # ready_pcs 는 distinct 공정 코드 리스트(디스패처가 중복 압축해 전달) — 큐 깊이가 아니라
        # 공정 타입 위 분포를 학습. 저장값은 전부 스칼라/snapshot 텐서라 grad 불요. buf 는 학습·평가 양쪽 다.
        kg               = env.KnowledgeGraph
        node_list        = list(kg.nodes.keys())
        embeddings       = self.GNNEncoder(NodeFeatures=obs_node_features(kg), GraphTopology=obs_graph_topology(kg))
        ready_emb        = torch.stack([embeddings[node_list.index(pc)] for pc in ready_pcs])
        state            = env.state_vec() if self.StateDim > 0 else None    # 결정점 동적 관측
        dist             = torch.distributions.Categorical(self.Actor(ReadyNodeEmbeddings=ready_emb, StateVector=state))
        idx              = dist.sample() if self.training else dist.probs.argmax()
        value            = self.Critic(PooledNodeEmbedding=ready_emb.mean(dim=0, keepdim=True), StateVector=state).squeeze()
        self.buf.append({'ready': list(ready_pcs), 'idx': int(idx.item()),
                         'logp': dist.log_prob(idx),                          # no_grad 컨텍스트 — grad_fn 없음
                         'value': value,
                         'state': state,                                      # 결정점 상태 snapshot
                         'phi': float(env.potential())})       # 결정점 Φ(s_t) — per-step 보상용
        return ready_pcs[idx.item()]

    def learn(self, episode_return, KnowledgeGraph):
        # 에피소드 종료 후 1회 PPO-clip 업데이트. terminal 스칼라 보상을 전 결정이
        # 공유 (critic baseline 으로 advantage). 보상 시점/형태는 튜닝 대상.
        # 반환: rl_logger_spec 진단 dict (마지막 epoch 기준). buf 비면 None.
        if not self.buf:
            return None
        n        = len(self.buf)
        values   = torch.stack([b['value'] for b in self.buf])      # 결정점 V(s_t) (detach)
        old_logp = torch.stack([b['logp']  for b in self.buf])
        phi      = [b['phi'] for b in self.buf]

        # per-step 보상 r_t = Φ(s_{t+1})−Φ(s_t). 마지막은 Φ(terminal)=episode_return.
        # telescoping → Σr ≈ R − Φ(s_0) (potential-based shaping; 최적정책 불변).
        rewards = torch.tensor(
            [(phi[i + 1] if i < n - 1 else float(episode_return)) - phi[i]
             for i in range(n)], dtype=torch.float32)

        # GAE (γ=self.Gamma, λ=self.GaeLambda — 기존 선언됐으나 미사용이던 것 복원). 터미널 V=0.
        advantages = torch.zeros(n)
        gae = 0.0
        for t in reversed(range(n)):
            v_next = values[t + 1] if t < n - 1 else 0.0
            delta  = rewards[t] + self.Gamma * v_next - values[t]
            gae    = delta + self.Gamma * self.GaeLambda * gae
            advantages[t] = gae
        returns = advantages + values                               # critic 타깃 (분산>0)
        adv     = (advantages - advantages.mean()) / (advantages.std() + 1e-8)
        grad_norm = 0.0
        for _ in range(self.UpdateEpochs):
            new_logp, entropy, value_preds = [], [], []
            node_list      = list(KnowledgeGraph.nodes.keys())
            node_features  = obs_node_features(KnowledgeGraph)         # 에폭당 1회 (그래프 고정)
            graph_topology = obs_graph_topology(KnowledgeGraph)
            for b in self.buf:
                embeddings = self.GNNEncoder(NodeFeatures=node_features, GraphTopology=graph_topology)
                ready_emb  = torch.stack([embeddings[node_list.index(pc)] for pc in b['ready']])
                state      = b['state']                                          # 결정점 시점 snapshot 재사용
                dist       = torch.distributions.Categorical(self.Actor(ReadyNodeEmbeddings=ready_emb, StateVector=state))
                new_logp.append(dist.log_prob(torch.tensor(b['idx'])))
                entropy.append(dist.entropy())
                value_preds.append(self.Critic(PooledNodeEmbedding=ready_emb.mean(dim=0, keepdim=True), StateVector=state).squeeze())
            new_logp    = torch.stack(new_logp)
            entropy     = torch.stack(entropy)
            value_preds = torch.stack(value_preds)
            ratio       = torch.exp(new_logp - old_logp)
            actor_loss  = -torch.min(
                              ratio * adv,
                              torch.clamp(ratio, 1 - self.ClipEpsilon, 1 + self.ClipEpsilon) * adv
                          ).mean()
            critic_loss = torch.nn.functional.mse_loss(value_preds, returns)
            loss        = actor_loss + self.ValueLossCoef * critic_loss - self.EntropyCoef * entropy.mean()
            self.optimizer.zero_grad()
            loss.backward()
            grad_norm = float(torch.nn.utils.clip_grad_norm_(self.parameters(), 0.5))
            self.optimizer.step()

        # ---- rl_logger_spec 진단 (마지막 epoch tensor 기준) ----
        with torch.no_grad():
            resid_var  = float((returns - value_preds).var())
            ret_var    = float(returns.var())                          # 스칼라 보상이면 0 (무신호 진단 핵심)
            clip_frac  = float(((ratio - 1.0).abs() > self.ClipEpsilon).float().mean())
            approx_kl  = float((old_logp - new_logp).mean())
            return {
                # 스칼라 보상 → ret_var≈0 이면 ev 정의 불가(=학습 무신호 진단)
                'critic/explained_variance': (float('nan') if ret_var < 1e-9
                                              else 1.0 - resid_var / ret_var),
                'critic/value_loss'        : float(critic_loss),
                'critic/v_mean'            : float(value_preds.mean()),
                'critic/v_max'             : float(value_preds.max()),
                'critic/returns_var'       : ret_var,
                'stability/approx_kl'      : approx_kl,
                'stability/clip_fraction'  : clip_frac,
                'stability/grad_norm'      : grad_norm,
                'stability/learning_rate'  : float(self.optimizer.param_groups[0]['lr']),
                'exploration/entropy'      : float(entropy.mean()),
                'actor/loss'               : float(actor_loss),
            }

#========RL 계산그래프 해석기 (코드 = import + wire, 아키텍처 = AAS)========
# AAS ModelArchitecture 의 계산그래프(op 노드: Op=import 경로 / Args=생성자 인자 / In=named 입력)를
# 제네릭하게 조립한다. 코드는 아키텍처를 '표현'하지 않는다 — importlib 로 실제 클래스/함수를 가져와
# named 텐서로 wiring 할 뿐. (공정 노드 생성과 동일: 구조는 AAS, 코드는 해석.)
# 새 모델/레이어 = AAS 에 Op 경로만 — 코드 무수정(import 가능한 무엇이든).
import importlib, inspect

def import_callable(path: str):
    """'torch_geometric.nn.GCNConv' → 클래스/함수 객체. AAS Op 가 가리키는 실제 라이브러리/primitive."""
    module, name = path.rsplit('.', 1)
    return getattr(importlib.import_module(module), name)

# 태스크 primitive (라이브러리 레이어가 아닌 RL 태스크 op — AAS Op 가 경로로 참조). 최소 코드.
def op_concat_state(x, state=None):
    """노드 임베딩 x 에 state 벡터를 행 broadcast 해 concat. state=None(StateDim=0) 이면 x 그대로."""
    if state is None:
        return x
    return torch.cat([x, state.unsqueeze(0).expand(x.size(0), -1)], dim=-1)

def op_squeeze_last(input):
    return input.squeeze(-1)


class GraphModule(torch.nn.Module):
    """계산그래프 spec 으로 net 조립. spec=[{'id','Op','Args','In'}], In={forward param: source}.
    source = 다른 노드 id 또는 외부 입력 이름(예 obs.x/edge_index/ready_emb/pooled_emb/state).
    파라미터 보유 모듈만 등록·학습; 함수(relu/softmax/primitive)는 매 forward 호출(Args 는 호출 인자).
    Linear in_features 처럼 런타임 의존 차원은 wiring 으로 resolve — source_dims(외부 입력 차원)로 추론.
    코드는 아키텍처를 표현하지 않는다 (import + wire + 최소 dim 추론)."""
    def __init__(self, spec, source_dims=None):
        super().__init__()
        self.spec = spec
        self.mods = torch.nn.ModuleDict()
        dim = dict(source_dims or {})                                  # node id/입력 → 출력 feature dim
        for node in spec:
            operation = node['Operation']
            arguments = dict(node.get('Arguments', {}))
            in_dim    = {param: dim.get(src) for param, src in node['Inputs'].items()}
            callable_ = import_callable(operation)
            if isinstance(callable_, type) and issubclass(callable_, torch.nn.Module):
                params = inspect.signature(callable_).parameters       # 생성자 시그니처로 일반 resolve (특정 레이어 하드코딩 X)
                if 'in_features' in params and 'in_features' not in arguments:
                    arguments['in_features'] = in_dim['input']         # Linear 류 (forward 'input')
                elif 'in_channels' in params and 'in_channels' not in arguments:
                    arguments['in_channels'] = in_dim['x']             # graph conv 류 (forward 'x') — GCN/SAGE/GAT/... 임의 교체
                self.mods[node['id']] = callable_(**arguments)
                out_dim = arguments.get('out_features', arguments.get('out_channels'))
            elif operation.endswith('op_concat_state'):
                out_dim = (in_dim.get('x') or 0) + (in_dim.get('state') or 0)   # 입력 노드 차원 합 (state=StateVector source)
            else:                                                      # relu/softmax/squeeze 등 passthrough
                out_dim = next((d for d in in_dim.values() if d is not None), None)
            dim[node['id']] = out_dim

    def forward(self, **sources):
        vals = dict(sources)
        out = None
        for node in self.spec:
            bound = {param: vals[src] for param, src in node['Inputs'].items()}
            if node['id'] in self.mods:
                out = self.mods[node['id']](**bound)                   # 모듈: Arguments 는 생성 때 소비
            else:
                out = import_callable(node['Operation'])(**bound, **node.get('Arguments', {}))   # 함수: Arguments 를 호출 인자로
            vals[node['id']] = out
        return out
