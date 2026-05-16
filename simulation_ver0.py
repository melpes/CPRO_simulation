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

    def select_action(self, observation, KnowledgeGraph):
        data, node_list      = KnowledgeGraph.to_pyg_data()
        embeddings           = self.GNNEncoder(data)
        ready                = observation['ready']

        ready_embeddings     = torch.stack([
            embeddings[node_list.index(ProcessCode)]
            for ProcessCode in ready
        ])

        action_probs         = self.Actor(ready_embeddings)
        dist                 = torch.distributions.Categorical(action_probs)  #확률 분포에서 action을 샘플링하는 PyTorch 분포 클래스
        action_idx           = dist.sample()
        log_prob             = dist.log_prob(action_idx)   #PPO 학습 시 정책 비율 계산

        ProcessCode          = ready[action_idx.item()]
        WorkstationId        = next(
            ws for ws in KnowledgeGraph.workers
            if ProcessCode in KnowledgeGraph.workers[ws]['ProcessCode']
        )
        return (ProcessCode, WorkstationId), log_prob
    
    def compute_loss(self, observations, actions, log_probs_old, Advantages, EpisodeReturns): #AAS화 예정
        log_probs_new        = []
        entropy              = []
        value_preds          = []

        for observation, action in zip(observations, actions):
            data, node_list   = observation['KnowledgeGraph'].to_pyg_data()
            embeddings        = self.GNNEncoder(data)
            ready             = observation['ready']
            ready_embeddings  = torch.stack([
                embeddings[node_list.index(ProcessCode)]
                for ProcessCode in ready
            ])
            action_probs      = self.Actor(ready_embeddings)
            dist              = torch.distributions.Categorical(action_probs)
            action_idx        = ready.index(action[0])   # 저장 action=(ProcessCode,WS) → 샘플 당시 ready 내 위치 복원
            log_probs_new.append(dist.log_prob(torch.tensor(action_idx)))
            entropy.append(dist.entropy())
            value_preds.append(self.Critic(ready_embeddings.mean(dim=0, keepdim=True)))
        
        log_probs_new       = torch.stack(log_probs_new)
        entropy             = torch.stack(entropy)
        value_preds         = torch.stack(value_preds).squeeze()

        ratio               = torch.exp(log_probs_new - log_probs_old)
        actor_loss          = -torch.min(
                                  ratio * Advantages,
                                  torch.clamp(ratio, 1 - self.ClipEpsilon, 1 + self.ClipEpsilon) * Advantages
                              ).mean()
        critic_loss         = torch.nn.functional.mse_loss(value_preds, EpisodeReturns)
        entropy_loss        = entropy.mean()

        loss                = actor_loss + self.ValueLossCoef * critic_loss - self.EntropyCoef * entropy_loss
        return loss
    
    def update(self, observations, actions, log_probs_old, rewards, values):
        log_probs_old        = torch.tensor(log_probs_old, dtype=torch.float)
        returns_list         = self.RuntimeVariables.EpisodeReturns(rewards, self.Gamma)
        Advantages           = torch.tensor(
                                   self.RuntimeVariables.Advantages(returns_list, values),
                                   dtype=torch.float)                  # rollout 1회 정규화
        EpisodeReturns       = torch.tensor(returns_list, dtype=torch.float)
        for _ in range(self.UpdateEpochs):
            indices = torch.randperm(len(observations))  #매 epoch마다 데이터 순서 무작위로 섞음
            for start in range(0, len(observations), self.BatchSize):
                batch_idx         = indices[start : start + self.BatchSize]
                batch_obs         = [observations[i] for i in batch_idx]
                batch_actions     = [actions[i]      for i in batch_idx]
                batch_log_probs   = log_probs_old[batch_idx]
                batch_adv         = Advantages[batch_idx]
                batch_ret         = EpisodeReturns[batch_idx]

                loss  = self.compute_loss(
                    batch_obs,
                    batch_actions,
                    batch_log_probs,
                    batch_adv,
                    batch_ret,
                )
                self.optimizer.zero_grad()
                loss.backward()
                torch.nn.utils.clip_grad_norm_(self.parameters(), 0.5)
                self.optimizer.step()

#========시뮬레이션 환경========-
class CproSimEnv:
    def __init__(self, KnowledgeGraph, warehouse, workers,
                 IndependentSequence, DependentSequence, DependentJoin,
                 RewardWeights, ReplenishLeadDay, target_qty, MaxEpisodes,
                 WarehouseManagedBOM, BOMCategory,
                 WorkStartTime, WorkEndTime, break_start_sec, break_end_sec,
                 IdleWorkerThreshold, RuntimeVariables):
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
        self.WarehouseManagedBOM  = WarehouseManagedBOM
        self.BOMCategory          = BOMCategory
        self.WorkStartTime        = WorkStartTime
        self.WorkEndTime          = WorkEndTime
        self.break_start_sec      = break_start_sec  # int(min.split(':')[0]) * 3600 + int(min.split(':')[1]) * 60
        self.break_end_sec        = break_end_sec    # int(max.split(':')[0]) * 3600 + int(max.split(':')[1]) * 60
        self.IdleWorkerThreshold  = IdleWorkerThreshold
        self.RuntimeVariables     = RuntimeVariables  #← path_extractor RuntimeVariables (AAS 명시 연산)

    def reset(self):
        self.env                  = simpy.Environment()
        #========RuntimeVariables (← SimulationModel.RuntimeVariables)========
        # AAS 에 value=None 으로 정의만 있는 동적 상태. 연산은 self.RuntimeVariables
        # (path_extractor) 가 단일 구현. 여기선 에피소드 초기값만 둔다.
        self.CycleCompleted       = False   #← .CycleCompleted
        self.Throughput           = 0       #← .Throughput
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
        self.MaxEpisodeEnergyKwh  = self.RuntimeVariables.MaxEpisodeEnergyKwh(self.KnowledgeGraph)
        #← .MaxEpisodeEnergyKwh = Σ(CycleTimeSec·RatedPowerKw)/3600 over all GraphNode (W2_Energy 분모)
        ready                     = self.KnowledgeGraph.ready_queue(
                                      self.IndependentSequence,
                                      self.DependentSequence,
                                      self.DependentJoin,
                                      self.completed,
                                      self.warehouse
                                    )
        return {'ready': ready, 'KnowledgeGraph': self.KnowledgeGraph}
    
    def _is_work_time(self) -> bool:
        seconds_in_day  = self.env.now % 86400
        return (self.WorkStartTime <= seconds_in_day < self.WorkEndTime and
                not (self.break_start_sec <= seconds_in_day < self.break_end_sec))

    def process_job(self, ProcessCode, WorkstationId):
        # step() 에서만 env.process 로 스케줄되는 simpy 코루틴. yield 가 있어
        # 별도 제너레이터로 남고, CproSimEnv 가 simpy 보유 컨트롤러라 메서드.
        self.in_progress[WorkstationId] = self.in_progress.get(WorkstationId, 0) + 1
        node = self.KnowledgeGraph.nodes[ProcessCode]
        yield self.env.timeout(node.CycleTimeSec)
        self.EpisodeEnergyKwh = self.RuntimeVariables.EpisodeEnergyKwh(node, self.EpisodeEnergyKwh)
        if node.InputBOM:
            if self.warehouse.consume(node.InputBOM):
                self.env.process(self.warehouse.replenish(self.env, self.ReplenishLeadDay))
        self.completed.add(ProcessCode)
        self.in_progress[WorkstationId] -= 1
        self.CycleCompleted = self.RuntimeVariables.CycleCompleted(ProcessCode, self.KnowledgeGraph)
        if self.CycleCompleted:                      # terminal 노드 완료 → completed 리셋
            self.completed.clear()

    def step(self, action):
        ProcessCode, WorkstationId  = action
        self.env.process(self.process_job(ProcessCode, WorkstationId))
        self.env.run(until=self.env.now + self.KnowledgeGraph.nodes[ProcessCode].CycleTimeSec)

        rv = self.RuntimeVariables
        self.Throughput         = rv.Throughput(ProcessCode, self.KnowledgeGraph, self.Throughput)
        self.StockShortageCount = rv.StockShortageCount(self.warehouse, self.StockShortageCount)
        self.StockOverflowCount = rv.StockOverflowCount(self.warehouse, self.StockOverflowCount)
        if self._is_work_time():
            self.IdleViolationCount = rv.IdleViolationCount(
                self.workers, self.in_progress, self.idle_time,
                self.env.now, self.IdleWorkerThreshold, self.IdleViolationCount,
            )

        work_day_sec = self.WorkEndTime - self.WorkStartTime - (self.break_end_sec - self.break_start_sec)
        step_count = max(self.env.now / (work_day_sec / self.target_qty), 1)

        reward = (
            - (self.env.now / work_day_sec)                         * self.RewardWeights['W1_TimeElapsed']
            - self.EpisodeEnergyKwh / self.MaxEpisodeEnergyKwh      * self.RewardWeights['W2_Energy']
            - self.StockOverflowCount  / step_count                 * self.RewardWeights['W3_StockOverflow']
            - self.StockShortageCount  / step_count                 * self.RewardWeights['W4_StockShortage']
            + (self.Throughput / self.target_qty)                   * self.RewardWeights['W5_Throughput']
            - self.IdleViolationCount  / step_count                 * self.RewardWeights['W6_IdleWorker']
        )

        done = self.Throughput >= self.target_qty
        observation = {
            'ready'          : self.KnowledgeGraph.ready_queue(
                                  self.IndependentSequence,
                                  self.DependentSequence,
                                  self.DependentJoin,
                                  self.completed,
                                  self.warehouse
                              ),
            'in_progress'    : self.in_progress,
            'inventory'      : {
                                 Category: {
                                     item_code: item.present_stock
                                     for item_code, item in items.items()
                                 }
                                 for Category, items in self.warehouse.inventory.items()
                              },
            'Throughput'    : self.Throughput,
            'KnowledgeGraph' : self.KnowledgeGraph,
        }
        return observation, reward, done, {}

    def skip(self):
        # ready 빔(재고/선행공정 대기) 처리: 행동 없이 다음 simpy 이벤트
        # (진행 공정 완료·재고 보충)까지 진행시켜 ready 가 다시 차길 기다린다.
        # 대기할 이벤트가 전혀 없으면(real deadlock) deadlock=True.
        while self.env.peek() != float('inf'):
            self.env.step()
            ready = self.KnowledgeGraph.ready_queue(
                self.IndependentSequence,
                self.DependentSequence,
                self.DependentJoin,
                self.completed,
                self.warehouse,
            )
            if ready:
                return {'ready': ready, 'KnowledgeGraph': self.KnowledgeGraph}, False
        return {'ready': [], 'KnowledgeGraph': self.KnowledgeGraph}, True

def train(env, agent, MaxEpisodes):
    for episode in range(MaxEpisodes):
        observation          = env.reset()
        observations         = []
        actions              = []
        log_probs            = []
        rewards              = []
        values               = []
        done                 = False

        while not done:
            if not observation['ready']:
                # ready 빔 = 재고/선행공정 대기. 다음 이벤트(공정 완료·재고 보충)
                # 까지 진행 후 이 스텝 스킵. 대기할 이벤트가 전혀 없을 때만 종료.
                observation, deadlock = env.skip()
                if deadlock:
                    break
                continue
            action, log_prob  = agent.select_action(observation, env.KnowledgeGraph)
            data, node_list   = env.KnowledgeGraph.to_pyg_data()
            embeddings        = agent.GNNEncoder(data)
            ready             = observation['ready']
            ready_embeddings  = torch.stack([
                embeddings[node_list.index(ProcessCode)]
                for ProcessCode in ready
            ])
            value             = agent.Critic(ready_embeddings.mean(dim=0, keepdim=True))

            observations.append(observation)
            actions.append(action)
            log_probs.append(log_prob.item())
            values.append(value.item())

            observation, reward, done, _ = env.step(action)
            rewards.append(reward)

        if rewards:
            agent.update(observations, actions, log_probs, rewards, values)
            # rl_logger_spec: [F] train/rollout_reward_mean + sanity/episode_length, [E] task/primary_metric
            print(f'[ep {episode:>4}] return={sum(rewards):+.3f} len={len(rewards):>4} '
                  f'thru={env.Throughput}/{env.target_qty} done={done}')
        else:
            print(f'[ep {episode:>4}] rollout 0 — 행동 가능 시점 없이 종료 (deadlock)')

if __name__ == '__main__':
    import os
    import path_extractor
    from path_extractor import ProvisionofSimulationModelsAAS

    _DIR = os.path.dirname(os.path.abspath(__file__))
    for _f in ['ProvisionOfSimulationModel.json', 'WorkstationWorkerMatchingDataAAS.json',
               'MODEL_A.json', 'MODEL_B.json', 'MODEL_C.json']:
        path_extractor.load(os.path.join(_DIR, _f))

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
    WarehouseManagedBOM  = PSM.WarehouseManagedBOM                                        #← ProductAAS HS
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

    target_qty = int(input('목표 생산 수량을 입력하세요: '))

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