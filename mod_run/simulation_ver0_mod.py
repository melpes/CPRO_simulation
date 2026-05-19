# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict

import simpy
import torch
from torch_geometric.nn import GCNConv
from torch_geometric.data import Data


@dataclass
class GraphNode:
    ProcessCode  : str      #← ManufacturingProcess.groups.{GroupIdShort}.processes.{ProcessCode}
    GroupIdShort : str      #← ManufacturingProcess.groups.{GroupIdShort}
    model_id     : str      #← ManufacturingProcess.id.split('/')[6]  # 'MODEL_A'
    CycleTimeSec : float    #← ProcessNode.CycleTimeSec.value
    DefectRate   : float    #← ProcessNode.DefectRate.value
    RatedPowerKw : float    #← ProcessNode.RatedPowerKw.value
    InputBOM     : dict     #← ProcessNode.InputBOM
# DepPrev/DepType 는 노드에 캐싱하지 않는다. 의존 관계의 단일 표현은 edges
# (이전 공정 → 다음 공정 + type). 이전 공정이 필요하면 _predecessors 로 검색.

@dataclass
class GraphEdge:
    ProcessCode  : str      #← ProcessNode.{ProcessCode}            (다음 공정)
    DepType      : str      #← ProcessNode.DepType.value   ('SEQUENCE' | 'JOIN')
# edges 의 dict 키가 이전 공정. 키(이전 공정) → [GraphEdge(다음 공정, type)]
# VD7_40   → [GraphEdge(VD7_40_1, JOIN)]
# VD7_20_1 → [GraphEdge(VD7_40_1, JOIN)]
# VD7_10   → [GraphEdge(VD7_10_1, SEQUENCE)]

@dataclass
class KnowledgeGraph:
    nodes        : dict #{ProcessCode: GraphNode}
    edges        : dict #{DepPrev: [GraphEdge, ...]}
    workers      : dict #{WorkstationId: {'worker_count': int, 'ProcessCode': [...]}}
#        'WWM_FwInputLine': {
#        'worker_count': 2,
#        'ProcessCode' : ['VD7_10', 'VD7_10_1', 'VD7_10_2', 'VD7_10_3',
#                         'BT5_10', 'BT5_11', ...]

    @classmethod
    def build(cls, ManufacturingProcesses, workers) -> 'KnowledgeGraph':
        nodes = {}
        edges = {}
        for model_id, mp in ManufacturingProcesses.items():
            for GroupIdShort, processes in mp.groups.items():
                for ProcessCode, ProcessNode in processes.items():
                    nodes[ProcessCode]   = GraphNode(
                        ProcessCode      = ProcessCode,
                        GroupIdShort     = GroupIdShort,
                        model_id         = model_id,
                        CycleTimeSec     = ProcessNode.CycleTimeSec.value,
                        DefectRate       = ProcessNode.DefectRate.value,
                        RatedPowerKw     = ProcessNode.RatedPowerKw.value,
                        InputBOM         = ProcessNode.InputBOM,
                    )
                    for DepPrev in ProcessNode.DepPrev.value.split(';'):
                        DepPrev    = DepPrev.strip()
                        if not DepPrev:
                            continue
                        if DepPrev not in edges:
                            edges[DepPrev] = []
                        edges[DepPrev].append(GraphEdge(
                            ProcessCode   = ProcessCode,
                            DepType       = ProcessNode.DepType.value,
                        ))
        return cls(nodes, edges, workers)
    
    def _bom_satisfied(self, ProcessCode: str, warehouse: Warehouse) -> bool:
        node = self.nodes[ProcessCode]
        if not node.InputBOM:
            return True
        return all(
            warehouse.inventory[Category][item_code].present_stock >= ProcessConsumedBOM
            for item_code, ProcessConsumedBOM in node.InputBOM.items()
            for Category in warehouse.inventory
            if item_code in warehouse.inventory[Category]
        )
    
    def _predecessors(self, ProcessCode: str) -> list:
        # edges(이전 공정 → 다음 공정) 역방향 검색으로 이전 공정 목록 복원.
        return [
            DepPrev
            for DepPrev, GraphEdges in self.edges.items()
            for GraphEdge in GraphEdges
            if GraphEdge.ProcessCode == ProcessCode
        ]

    def ready_queue(self, IndependentSequence, DependentSequence, DependentJoin,
                    completed: set, warehouse: Warehouse) -> list:
        ready = []

        for ProcessCode in IndependentSequence:
            if ProcessCode in completed:
                continue
            if self._bom_satisfied(ProcessCode, warehouse):
                ready.append(ProcessCode)

        for ProcessCode in DependentSequence:
            if ProcessCode in completed:
                continue
            DepPrev_list = self._predecessors(ProcessCode)
            if any(d in completed for d in DepPrev_list):
                if self._bom_satisfied(ProcessCode, warehouse):
                    ready.append(ProcessCode)

        for ProcessCode in DependentJoin:
            if ProcessCode in completed:
                continue
            DepPrev_list = self._predecessors(ProcessCode)
            if all(d in completed for d in DepPrev_list):
                if self._bom_satisfied(ProcessCode, warehouse):
                    ready.append(ProcessCode)

        return ready
    
    def to_pyg_data(self):
        node_list     = list(self.nodes.keys())
        node_index    = {ProcessCode: i for i, ProcessCode in enumerate(node_list)}

        x = torch.tensor([
            [
                self.nodes[ProcessCode].CycleTimeSec,
                self.nodes[ProcessCode].DefectRate,
                self.nodes[ProcessCode].RatedPowerKw,
            ]
            for ProcessCode in node_list
        ], dtype=torch.float)
        edge_src = []
        edge_dst = []
        for DepPrev, GraphEdges in self.edges.items():
            for GraphEdge in GraphEdges:
                if (DepPrev in node_index and 
                    GraphEdge.ProcessCode in node_index):
                    edge_src.append(node_index[DepPrev])
                    edge_dst.append(node_index[GraphEdge.ProcessCode])
                    
        edge_index  = torch.tensor([edge_src, edge_dst], dtype=torch.long)
        
        return Data (x=x, edge_index=edge_index), node_list
    
@dataclass
class StockItem:
    present_stock      : float
    MinStock           : float
    MaxStock           : float
    OrderRatio         : float

@dataclass
class Warehouse:
    inventory   : Dict[str, Dict[str, StockItem]] #{Category : {item_code  : StockItem}}
    
    @classmethod
    def build(cls, WarehouseManagedBOM, BOMCategory) -> 'Warehouse':
        inventory = {}
        for Category, items in WarehouseManagedBOM.items():
            inventory[Category] = {}
            for item_code in items:
                inventory[Category][item_code] = StockItem(
                    present_stock   = BOMCategory[Category].MinStock,
                    MinStock        = BOMCategory[Category].MinStock,
                    MaxStock        = BOMCategory[Category].MaxStock,
                    OrderRatio      = BOMCategory[Category].OrderRatio,
                )
        return cls(inventory)
    
    def consume(self, ProcessConsumedBOM: dict) -> bool:
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
    
    def replenish(self, env, ReplenishLeadDay) -> None:
        yield env.timeout(ReplenishLeadDay)
        for Category in self.inventory:
            for item in self.inventory[Category].values():
                if item.present_stock <= item.MinStock * item.OrderRatio:
                    item.present_stock += item.MaxStock * item.OrderRatio


class _StockRouter:
    """메인(CoManaged) + PCB(SelfManaged) 두 Warehouse 인스턴스를 묶어
    Warehouse 와 동일한 인터페이스(inventory / consume / replenish)로 노출.
    Warehouse·StockItem 구조는 무변경 — item_code 소속으로만 라우팅."""
    def __init__(self, main: Warehouse, pcb: Warehouse):
        self.main = main
        self.pcb  = pcb
        self._pcb_items = {code
                           for items in pcb.inventory.values()
                           for code in items}

    @property
    def inventory(self):                                  # _bom_satisfied 읽기용 (병합 뷰)
        return {**self.main.inventory, **self.pcb.inventory}

    def consume(self, ProcessConsumedBOM: dict) -> bool:
        main_bom, pcb_bom = {}, {}
        for code, qty in ProcessConsumedBOM.items():
            (pcb_bom if code in self._pcb_items else main_bom)[code] = qty
        reorder = self.main.consume(main_bom) if main_bom else False
        if pcb_bom:
            self.pcb.consume(pcb_bom)                      # PCB 보충은 cpro_pcb 코루틴 담당
        return reorder

    def replenish(self, env, ReplenishLeadDay):           # 메인만 (PCB 는 일정증가 별도)
        return self.main.replenish(env, ReplenishLeadDay)


class GNNEncoder(torch.nn.Module):
    def __init__(self, NodeFeatureDim, HiddenDim, OutputDim, NumLayers):
        super().__init__()
        self.layers  = torch.nn.ModuleList()
        self.layers.append(GCNConv(NodeFeatureDim, HiddenDim))
        for _ in range(NumLayers - 2):
            self.layers.append(GCNConv(HiddenDim, HiddenDim))
        self.layers.append(GCNConv(HiddenDim, OutputDim))

    def forward(self, data):
        x          =  data.x
        edge_index =  data.edge_index
        for i, layer in enumerate(self.layers):
            x = layer(x, edge_index)
            if i < len(self.layers) - 1:           #마지막 출력 OutputDim embedding 벡터는 활성화 함수 없이 PPO로 넘겨야 함
                x  =  torch.nn.functional.relu(x)
        return x                                   #(node 수 x OutputDim) 크기의 노드 embedding 행렬
    
class Actor(torch.nn.Module):
    def __init__(self, GNNEmbeddingDim, HiddenDim, NumLayers):
        super().__init__()
        self.layers     = torch.nn.ModuleList()
        self.layers.append(torch.nn.Linear(GNNEmbeddingDim, HiddenDim))
        for _ in range(NumLayers - 1):
            self.layers.append(torch.nn.Linear(HiddenDim, HiddenDim))
        self.score_head = torch.nn.Linear(HiddenDim, 1)

    def forward(self, x):                       # x: (N_ready, GNNEmbeddingDim)
        for i, layer in enumerate(self.layers):
            x = layer(x)
            if i < len(self.layers) - 1:
                x = torch.nn.functional.relu(x)
        x = torch.nn.functional.relu(x)
        logits = self.score_head(x).squeeze(-1)             # (N_ready,)
        return torch.nn.functional.softmax(logits, dim=-1)  # ready 위 분포
    
class Critic(torch.nn.Module):
    def __init__(self, GNNEmbeddingDim, HiddenDim, NumLayers):
        super().__init__()
        self.layers       = torch.nn.ModuleList()
        self.layers.append(torch.nn.Linear(GNNEmbeddingDim, HiddenDim))
        for _ in range(NumLayers - 1):
            self.layers.append(torch.nn.Linear(HiddenDim, HiddenDim))
        self.value_head   = torch.nn.Linear(HiddenDim, 1)

    def forward(self, x):
        for i, layer in enumerate(self.layers):
            x = layer(x)
            if i < len(self.layers) - 1:
                x = torch.nn.functional.relu(x)
        x         = torch.nn.functional.relu(x)
        value      = self.value_head(x)
        return value
    
class PPOAgent(torch.nn.Module):
    def __init__(self, NodeFeatureDim, HiddenDim, OutputDim, NumLayers,
                 GNNEmbeddingDim, LearningRate, ClipEpsilon, Gamma,
                 GaeLambda, EntropyCoef, ValueLossCoef, UpdateEpochs, BatchSize,
                 RuntimeVariables):
        super().__init__()
        self.GNNEncoder      = GNNEncoder(NodeFeatureDim, HiddenDim, OutputDim, NumLayers)
        self.Actor           = Actor(GNNEmbeddingDim, HiddenDim, NumLayers)
        self.Critic          = Critic(GNNEmbeddingDim, HiddenDim, NumLayers)
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

    def choose(self, ready_pcs, env):
        # produce_unit 의 결정점 콜백. ready_pcs 위에서 행동 샘플 + rollout 기록.
        data, node_list  = env.KnowledgeGraph.to_pyg_data()
        embeddings       = self.GNNEncoder(data)
        ready_emb        = torch.stack([embeddings[node_list.index(pc)] for pc in ready_pcs])
        dist             = torch.distributions.Categorical(self.Actor(ready_emb))
        idx              = dist.sample()
        value            = self.Critic(ready_emb.mean(dim=0, keepdim=True)).squeeze()
        self.buf.append({'ready': list(ready_pcs), 'idx': int(idx.item()),
                         'logp': dist.log_prob(idx).detach(),
                         'value': value.detach(),
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
            data, node_list = KnowledgeGraph.to_pyg_data()
            for b in self.buf:
                embeddings = self.GNNEncoder(data)
                ready_emb  = torch.stack([embeddings[node_list.index(pc)] for pc in b['ready']])
                dist       = torch.distributions.Categorical(self.Actor(ready_emb))
                new_logp.append(dist.log_prob(torch.tensor(b['idx'])))
                entropy.append(dist.entropy())
                value_preds.append(self.Critic(ready_emb.mean(dim=0, keepdim=True)).squeeze())
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

#========시뮬레이션 환경========-
class CproSimEnv:
    def __init__(self, KnowledgeGraph, warehouse, workers,
                 IndependentSequence, DependentSequence, DependentJoin,
                 RewardWeights, ReplenishLeadDay, target_qty, MaxEpisodes,
                 WarehouseManagedBOM, BOMCategory,
                 WorkStartTime, WorkEndTime, break_start_sec, break_end_sec,
                 IdleWorkerThreshold, RuntimeVariables,
                 IdleProcessRatedPowerKw, IdlePowerRatio=0.10, SelfManagedBOM=None):
        self.KnowledgeGraph       = KnowledgeGraph
        self.warehouse            = warehouse
        self.workers              = workers
        self.IndependentSequence  = IndependentSequence
        self.DependentSequence    = DependentSequence
        self.DependentJoin        = DependentJoin
        self.RewardWeights        = RewardWeights
        self.ReplenishLeadDay     = ReplenishLeadDay
        self.target_qty           = target_qty
        self.MaxEpisodes          = MaxEpisodes
        self.WarehouseManagedBOM  = WarehouseManagedBOM   # CoManaged (PCB 제외)
        self.SelfManagedBOM       = SelfManagedBOM         # PCB 등 — 별도 창고. None 이면 PCB 분리 안 함
        self.BOMCategory          = BOMCategory
        self.WorkStartTime        = WorkStartTime
        self.WorkEndTime          = WorkEndTime
        self.break_start_sec      = break_start_sec  # int(min.split(':')[0]) * 3600 + int(min.split(':')[1]) * 60
        self.break_end_sec        = break_end_sec    # int(max.split(':')[0]) * 3600 + int(max.split(':')[1]) * 60
        self.IdleWorkerThreshold  = IdleWorkerThreshold
        self.IdleProcessRatedPowerKw = IdleProcessRatedPowerKw  #← DefaultParameters.IdleProcessRatedPowerKw
        self.IdlePowerRatio       = IdlePowerRatio    # AAS 미반영 정책상수(=0.10) — 호출부 주입
        self.RuntimeVariables     = RuntimeVariables  #← path_extractor RuntimeVariables (AAS 명시 연산)

    def reset(self):
        self.env                  = simpy.Environment()
        #========RuntimeVariables (← SimulationModel.RuntimeVariables)========
        # AAS 에 value=None 으로 정의만 있는 동적 상태. 연산은 self.RuntimeVariables
        # (path_extractor) 가 단일 구현. 여기선 에피소드 초기값만 둔다.
        self.CycleCompleted       = False   #← .CycleCompleted
        self.Throughput           = {model_id: 0 for model_id in self.target_qty}  #← .Throughput (모델별)
        self.EpisodeEnergyKwh     = 0.0     #← .EpisodeEnergyKwh
        self.StockShortageCount   = 0       #← .StockShortageCount
        self.StockOverflowCount   = 0       #← .StockOverflowCount
        self.IdleViolationCount   = 0       #← .IdleViolationCount
        #----generic 헬퍼 (AAS 외 — 순수 코드용)----
        self.completed            = set()
        self.in_progress          = {}
        self.idle_time            = {}
        self.warehouse            = Warehouse.build(
                                      self.WarehouseManagedBOM,
                                      self.BOMCategory
                                    )
        if self.SelfManagedBOM:                          # PCB(SelfManaged) 별도 창고
            import cpro_pcb
            self._pcb_warehouse   = Warehouse.build(self.SelfManagedBOM, self.BOMCategory)
            self.warehouse        = _StockRouter(self.warehouse, self._pcb_warehouse)
            self.env.process(cpro_pcb.pcb_supply(self.env, self._pcb_warehouse))
        self.worker_resources     = {                       # 워커 capacity (라인별 동시 작업 한도)
            WorkstationId: simpy.Resource(self.env, capacity=info['worker_count'])
            for WorkstationId, info in self.workers.items()
        }
        # MaxEpisodeEnergyKwh 는 idle baseline(now 의존)으로 바뀌어 reset 캐싱 불가
        # → episode_reward() 에서 self.env.now 로 계산.
    
    def _is_work_time(self) -> bool:                    # ver0 원본 그대로 (무변경)
        seconds_in_day  = self.env.now % 86400
        return (self.WorkStartTime <= seconds_in_day < self.WorkEndTime and
                not (self.break_start_sec <= seconds_in_day < self.break_end_sec))

    def process_job(self, ProcessCode, WorkstationId, done_set):
        # ver0 process_job 원본 본문 유지. 최소 수정만:
        #   (1) 파라미터 done_set 추가  (2) 근무시간 대기  (3) 워커 Resource 점유
        #   (4) self.completed → done_set, 전역 clear() 제거
        self.in_progress[WorkstationId] = self.in_progress.get(WorkstationId, 0) + 1
        node = self.KnowledgeGraph.nodes[ProcessCode]
        while not self._is_work_time():                              # (2) 비근무면 재개까지 정확 점프
            sid = self.env.now % 86400
            if sid < self.WorkStartTime:
                d = self.WorkStartTime - sid
            elif self.break_start_sec <= sid < self.break_end_sec:
                d = self.break_end_sec - sid
            else:
                d = 86400 - sid + self.WorkStartTime
            yield self.env.timeout(d)
        with self.worker_resources[WorkstationId].request() as req:  # (3) 워커 capacity
            yield req
            yield self.env.timeout(node.CycleTimeSec)
        self.EpisodeEnergyKwh = self.RuntimeVariables.EpisodeEnergyKwh(
            node, self.EpisodeEnergyKwh, self.IdleProcessRatedPowerKw, self.IdlePowerRatio)
        if node.InputBOM:
            if self.warehouse.consume(node.InputBOM):
                self.env.process(self.warehouse.replenish(self.env, self.ReplenishLeadDay))
        done_set.add(ProcessCode)                                    # (4) self.completed → done_set
        self.in_progress[WorkstationId] -= 1
        self.CycleCompleted = self.RuntimeVariables.CycleCompleted(ProcessCode, self.KnowledgeGraph)
        # (4) terminal 시 self.completed.clear() 제거 — 유닛-local done_set 이라 불필요/유해

    def _ready_for(self, model_id, done_set):
        return [pc for pc in self.KnowledgeGraph.ready_queue(        # ver0 ready_queue 원본
                    self.IndependentSequence, self.DependentSequence,
                    self.DependentJoin, done_set, self.warehouse)    # completed ← done_set
                if self.KnowledgeGraph.nodes[pc].model_id == model_id]

    def _workstation_of(self, ProcessCode):
        return next((ws for ws in self.workers
                     if ProcessCode in self.workers[ws]['ProcessCode']), None)

    def _do_process(self, ProcessCode, WorkstationId, done_set, in_flight):
        yield self.env.process(self.process_job(ProcessCode, WorkstationId, done_set))
        in_flight.discard(ProcessCode)
        self.Throughput = self.RuntimeVariables.Throughput(          # terminal 이면 모델 +1
            ProcessCode, self.KnowledgeGraph, self.Throughput)

    def produce_unit(self, model_id, agent=None):
        # 주문 1개 = 코루틴 1개. 유닛별 done_set 으로 ver0 ready_queue 호출(교차오염 X).
        done_set = set()
        kg = self.KnowledgeGraph
        terminal_pcs = {pc for pc, n in kg.nodes.items()
                        if n.model_id == model_id} - set(kg.edges.keys())

        if agent is not None:
            # PPO 결정점 경로 — 기존 단일선택 유지(학습 contract 보존). 병렬화는 greedy 만.
            while not terminal_pcs.issubset(done_set):
                ready = self._ready_for(model_id, done_set)
                if not ready:
                    yield self.env.timeout(60)
                    continue
                ProcessCode   = agent.choose(ready, self)
                WorkstationId = self._workstation_of(ProcessCode)
                if WorkstationId is None:
                    done_set.add(ProcessCode)
                    continue
                yield self.env.process(
                    self.process_job(ProcessCode, WorkstationId, done_set))
                self.Throughput = self.RuntimeVariables.Throughput(
                    ProcessCode, kg, self.Throughput)
            return

        # greedy: 한 유닛 내에서 '선후·BOM 충족된 ready 공정' 을 모두 동시 디스패치.
        # 직렬화는 produce_unit 구현 인공물이었을 뿐 — 도메인 제약(ready_queue)·
        # 워커 Resource·근무시간만 진짜 게이트. 같은 모델 다른 유닛 병렬은 그대로.
        in_flight: set = set()
        active: list = []
        while not terminal_pcs.issubset(done_set):
            for pc in self._ready_for(model_id, done_set):
                if pc in in_flight:
                    continue
                ws = self._workstation_of(pc)
                if ws is None:
                    done_set.add(pc)
                    continue
                in_flight.add(pc)
                active.append(self.env.process(
                    self._do_process(pc, ws, done_set, in_flight)))
            active = [p for p in active if p.is_alive]
            if not active:
                yield self.env.timeout(60)                           # 재고/선행 대기
                continue
            yield simpy.AnyOf(self.env, active)                      # 하나라도 끝나면 재평가
            active = [p for p in active if p.is_alive]

    def run(self, agent=None, max_sec: float = 60 * 86400):
        # 주문수량만큼 produce_unit 을 동시에 띄우고 한 번 진행. agent=None → greedy.
        self.reset()
        stop = self.env.event()
        for model_id, qty in self.target_qty.items():
            for _ in range(qty):
                self.env.process(self.produce_unit(model_id, agent))

        def _watch():
            while not stop.triggered:
                yield self.env.timeout(30)
                if (all(self.Throughput[m] >= self.target_qty[m] for m in self.target_qty)
                        or self.env.now >= max_sec):
                    if not stop.triggered:
                        stop.succeed()
                    return
        self.env.process(_watch())
        self.env.run(until=stop)
        return {
            'Throughput'      : dict(self.Throughput),
            'makespan_sec'    : float(self.env.now),
            'EpisodeEnergyKwh': float(self.EpisodeEnergyKwh),
        }

    def potential(self) -> float:
        # 현재 상태의 목적함수 값 Φ(s). 임의 시점(결정점/종료)에서 호출 가능.
        # per-step 보상 r_t = Φ(s_{t+1})−Φ(s_t) 의 telescoping → 종료 시 episode_reward 와 일치.
        # 구조상 per-step 누적이 없어 W3/W4/W6(재고·유휴)은 생략 — 후속 reward 재설계.
        w = self.RewardWeights
        total_target = sum(self.target_qty.values())
        work_day = self.WorkEndTime - self.WorkStartTime - (self.break_end_sec - self.break_start_sec)
        maxE = self.RuntimeVariables.MaxEpisodeEnergyKwh(            # now 의존(idle baseline)
            self.KnowledgeGraph, self.env.now,
            self.IdleProcessRatedPowerKw, self.IdlePowerRatio)
        maxE = max(maxE, 1e-6)                                       # 초기 decision div0 가드
        return (
            + (sum(self.Throughput.values()) / total_target)        * w['W5_Throughput']
            - (self.env.now / (work_day * total_target))            * w['W1_TimeElapsed']
            - (self.EpisodeEnergyKwh / maxE)                        * w['W2_Energy']
        )

    def episode_reward(self) -> float:
        # 종료 시 스칼라 보상 = Φ(terminal). learn() 의 마지막 결정 보상 기준값.
        return self.potential()

def train(env, agent, MaxEpisodes):
    # 에피소드 = produce_unit 구조 1회(env.run(agent)). 결정점마다 agent.choose 가
    # rollout 기록 → 종료 후 episode_reward 로 1회 PPO learn. (직렬 step/skip 없음)
    # 매 ep rl_logger_spec 항목 JSONL 기록 + best R 갱신 시에만 agent_mod.pt 저장.
    import os
    from rl_logger import RLLogger

    _OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'result')
    os.makedirs(_OUT, exist_ok=True)                                   # mod_run/result/
    logger = RLLogger(os.path.join(_OUT, 'rl_log.jsonl'))
    ckpt   = os.path.join(_OUT, 'agent_mod.pt')

    for episode in range(MaxEpisodes):
        if os.path.exists(os.path.join(_OUT, 'STOP')):                 # 협조적 중단(외부 신호)
            print(f'[ep {episode}] STOP sentinel — graceful exit', flush=True)
            break
        agent.reset_buffer()
        summary = env.run(agent=agent)
        R = env.episode_reward()
        decisions = len(agent.buf)
        metrics = agent.learn(R, env.KnowledgeGraph)                   # 진단 dict (B/C/D)
        is_best = logger.log_episode(
            episode, R=R, makespan=summary['makespan_sec'],
            energy=summary['EpisodeEnergyKwh'],
            throughput=dict(env.Throughput), target_qty=dict(env.target_qty),
            decisions=decisions, metrics=metrics)
        if is_best:
            torch.save(agent.state_dict(), ckpt)                       # best 갱신 시에만, 덮어쓰기
        thru = ' '.join(f'{m}:{env.Throughput[m]}/{env.target_qty[m]}' for m in env.target_qty)
        ev = (metrics or {}).get('critic/explained_variance')
        print(f'[ep {episode:>4}] R={R:+.4f} decisions={decisions} '
              f'makespan={summary["makespan_sec"]:.0f} E={summary["EpisodeEnergyKwh"]:.2f} '
              f'thru=[{thru}] ev={ev} {"BEST↑" if is_best else ""}')

if __name__ == '__main__':
    import os, sys

    _DIR  = os.path.dirname(os.path.abspath(__file__))                 # mod_run/ — 결과 저장처
    _ROOT = os.path.dirname(_DIR)                                      # 패키지 루트 — AAS JSON · path_extractor
    sys.path.insert(0, _ROOT)
    import path_extractor
    from path_extractor import ProvisionofSimulationModelsAAS

    for _f in ['ProvisionOfSimulationModel.json', 'WorkstationWorkerMatchingDataAAS.json',
               'MODEL_A.json', 'MODEL_B.json', 'MODEL_C.json']:
        path_extractor.load(os.path.join(_ROOT, _f))

    PSM                  = ProvisionofSimulationModelsAAS
    SimulationModel      = PSM.SimulationModels.SimulationModel
    Action               = SimulationModel.KnowledgeGraph.Action
    PSM_Warehouse        = SimulationModel.Warehouse
    DefaultParameters    = SimulationModel.DefaultParameters
    RewardWeightsSME     = SimulationModel.RewardWeights
    GNN_arch             = SimulationModel.ModelArchitecture.GNN
    PPO_arch             = SimulationModel.ModelArchitecture.PPO
    TrainingConfig       = PPO_arch.TrainingConfig

    ManufacturingProcesses = {mp.model_id: mp for mp in PSM_Warehouse.InputBOM.target}  #← Warehouse.InputBOM
    workers              = PSM.workers                                                   #← WWM
    WarehouseManagedBOM  = PSM.CoManagedBOM                                               #← ProductAAS HS (PCB 제외)
    SelfManagedBOM       = PSM.SelfManagedBOM                                             #← PCB(SMT_PCB) 별도 창고
    BOMCategory          = PSM_Warehouse.MinStock.target                                  #← Warehouse.MinStock

    IndependentSequence  = [node.idShort for ref in Action.IndependentSequence for node in ref.target]
    DependentSequence    = [node.idShort for ref in Action.DependentSequence   for node in ref.target]
    DependentJoin        = [node.idShort for ref in Action.DependentJoin       for node in ref.target]

    RewardWeights        = {
        'W1_TimeElapsed'   : float(RewardWeightsSME.W1_TimeElapsed.value),
        'W2_Energy'        : float(RewardWeightsSME.W2_Energy.value),
        'W3_StockOverflow' : float(RewardWeightsSME.W3_StockOverflow.value),
        'W4_StockShortage' : float(RewardWeightsSME.W4_StockShortage.value),
        'W5_Throughput'    : float(RewardWeightsSME.W5_Throughput.value),
        'W6_IdleWorker'    : float(RewardWeightsSME.W6_IdleWorker.value),
    }
    ReplenishLeadDay     = int(DefaultParameters.ReplenishLeadDay.value) * 3600           #← DefaultParameters
    IdleWorkerThreshold  = int(DefaultParameters.IdleWorkerThreshold.value)
    WorkStartTime        = DefaultParameters.WorkStartTime.target.value
    WorkEndTime          = DefaultParameters.WorkEndTime.target.value
    break_start_sec      = DefaultParameters.BreakDurationMin.target.min
    break_end_sec        = DefaultParameters.BreakDurationMin.target.max
    MaxEpisodes          = int(SimulationModel.SimulationConfig.MaxEpisodes.value)
    RuntimeVariables     = SimulationModel.RuntimeVariables                               #← SimulationModel.RuntimeVariables (AAS 명시 연산 단일 구현처)

    NodeFeatureDim       = int(GNN_arch.NodeFeatureDim.value)                             #← ModelArchitecture.GNN
    HiddenDim            = int(GNN_arch.HiddenDim.value)
    OutputDim            = int(GNN_arch.OutputDim.value)
    NumLayers            = int(GNN_arch.NumLayers.value)
    GNNEmbeddingDim      = OutputDim                                                      #← PPO.Actor.GNNEmbeddingDim → OutputDim
    LearningRate         = float(TrainingConfig.LearningRate.value)                       #← ModelArchitecture.PPO.TrainingConfig
    ClipEpsilon          = float(TrainingConfig.ClipEpsilon.value)
    Gamma                = float(TrainingConfig.Gamma.value)
    GaeLambda            = float(TrainingConfig.GaeLambda.value)
    EntropyCoef          = float(TrainingConfig.EntropyCoef.value)
    ValueLossCoef        = float(TrainingConfig.ValueLossCoef.value)
    UpdateEpochs         = TrainingConfig.UpdateEpochs.value
    BatchSize            = int(TrainingConfig.BatchSize.value)

    target_qty = {
        model_id: int(input(f'{model_id} 목표 생산 수량을 입력하세요: '))
        for model_id in ManufacturingProcesses
    }

    KnowledgeGraph  = KnowledgeGraph.build(ManufacturingProcesses, workers)
    warehouse       = Warehouse.build(WarehouseManagedBOM, BOMCategory)

    env = CproSimEnv(
        KnowledgeGraph       = KnowledgeGraph,
        warehouse            = warehouse,
        workers              = workers,
        IndependentSequence  = IndependentSequence,
        DependentSequence    = DependentSequence,
        DependentJoin        = DependentJoin,
        RewardWeights        = RewardWeights,
        ReplenishLeadDay     = ReplenishLeadDay,
        target_qty           = target_qty,
        MaxEpisodes          = MaxEpisodes,
        WarehouseManagedBOM  = WarehouseManagedBOM,
        BOMCategory          = BOMCategory,
        WorkStartTime        = WorkStartTime,
        WorkEndTime          = WorkEndTime,
        break_start_sec      = break_start_sec,
        break_end_sec        = break_end_sec,
        IdleWorkerThreshold  = IdleWorkerThreshold,
        RuntimeVariables     = RuntimeVariables,
        IdleProcessRatedPowerKw = float(DefaultParameters.IdleProcessRatedPowerKw.value),
        IdlePowerRatio       = 0.10,
        SelfManagedBOM       = SelfManagedBOM,
    )

    agent = PPOAgent(
        NodeFeatureDim  = NodeFeatureDim,
        HiddenDim       = HiddenDim,
        OutputDim       = OutputDim,
        NumLayers       = NumLayers,
        GNNEmbeddingDim = GNNEmbeddingDim,
        LearningRate    = LearningRate,
        ClipEpsilon     = ClipEpsilon,
        Gamma           = Gamma,
        GaeLambda       = GaeLambda,
        EntropyCoef     = EntropyCoef,
        ValueLossCoef   = ValueLossCoef,
        UpdateEpochs    = UpdateEpochs,
        BatchSize       = BatchSize,
        RuntimeVariables = RuntimeVariables,
    )

    train(env, agent, MaxEpisodes)