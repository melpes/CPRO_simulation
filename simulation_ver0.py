@dataclass
class GraphNode:
    ProcessCode  : str      #← ManufacturingProcess.groups.{GroupIdShort}.processes.{ProcessCode}
    GroupIdShort : str      #← ManufacturingProcess.groups.{GroupIdShort}
    model_id     : str      #← ManufacturingProcess.id.split('/')[6]  # 'MODEL_A'
    CycleTimeSec : float    #← ProcessNode.CycleTimeSec.value
    DefectRate   : float    #← ProcessNode.DefectRate.value
    RatedPowerKw : float    #← ProcessNode.RatedPowerKw.value
    InputBOM     : dict     #← ProcessNode.InputBOM

@dataclass
class GraphEdge:
    DepPrev      : str
    ProcessCode  : str
    DepType      : str
# DepPrev=VD7_40,   ProcessCode=VD7_40_1,  DepType=JOIN
# DepPrev=VD7_20_1, ProcessCode=VD7_40_1,  DepType=JOIN
# DepPrev=VD7_10,   ProcessCode=VD7_10_1,  DepType=SEQUENCE

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
    
    def ready_queue(self, IndependentSequence, DependentSequence, DependentJoin,
                    completed: set, warehouse: Warehouse) -> list:
        ready = []

        for ProcessCode in IndependentSequence:
            if self._bom_satisfied(ProcessCode, warehouse):
                ready.append(ProcessCode)

        for ProcessCode in DependentSequence:
            node = self.nodes[ProcessCode]
            if node.DepPrev.value in completed:
                if self._bom_satisfied(ProcessCode, warehouse):
                    ready.append(ProcessCode)

        for ProcessCode in DependentJoin:
            node = self.nodes[ProcessCode]
            if all(dep in completed for dep in node.DepPrev.value.split(';')):
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

def process_job(env, ProcessCode, WorkstationId, KnowledgeGraph, warehouse,
                completed, in_progress, ReplenishLeadDay, EpisodeEnergyKwh):
    in_progress[WorkstationId] = in_progress.get(WorkstationId, 0) + 1
    node = KnowledgeGraph.nodes[ProcessCode]
    yield env.timeout(node.CycleTimeSec)
    EpisodeEnergyKwh[0] += (node.CycleTimeSec * node.RatedPowerKw) / 3600
    if node.InputBOM:
        if warehouse.consume(node.InputBOM):
            env.process(warehouse.replenish(env,ReplenishLeadDay))
    completed.add(ProcessCode)
    in_progress[WorkstationId] -= 1
    if ProcessCode not in KnowledgeGraph.edges:
        completed.clear()

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
        self.HiddenDim = HiddenDim
        self.layers    = torch.nn.ModuleList()
        self.layers.append(torch.nn.Linear(GNNEmbeddingDim, HiddenDim))
        for _ in range(NumLayers - 1):
            self.layers.append(torch.nn.Linear(HiddenDim, HiddenDim))

    def forward(self, x, ActionSpaceDim):
        for i, layer in enumerate(self.layers):
            x = layer(x)
            if i < len(self.layers) - 1:
                x = torch.nn.functional.relu(x)
        x = torch.nn.functional.relu(x)
        logits = torch.nn.Linear(self.HiddenDim, ActionSpaceDim)(x)
        return torch.nn.functional.softmax(logits, dim=-1)
    
class Critic(torch.nn.Module):
    def __init__(self, GNNEmbeddingDim, HiddenDim, NumLayers):
        super().__init__()
        self.HiddenDim    = HiddenDim
        self.layers       = torch.nn.ModuleList()
        self.layers.append(torch.nn.Linear(GNNEmbeddingDim, HiddenDim))
        for _ in range(NumLayers - 1):
            self.layers.append(torch.nn.Linear(HiddenDim, HiddenDim))

    def forward(self, x):
        for i, layer in enumerate(self.layers):
            x = layer(x)
            if i < len(self.layers) - 1:
                x = torch.nn.functional.relu(x)
        x         = torch.nn.functional.relu(x)
        value      = torch.nn.Linear(self.HiddenDim, 1)(x)
        return value
    
class PPOAgent(torch.nn.Module):
    def __init__(self, NodeFeatureDim, HiddenDim, OutputDim, NumLayers,
                 GNNEmbeddingDim, LearningRate, ClipEpsilon, Gamma,
                 GaeLambda, EntropyCoef, ValueLossCoef, UpdateEpochs, BatchSize):
        super().__init__()
        self.GNNEncoder      = GNNEncoder(NodeFeatureDim, HiddenDim, OutputDim, NumLayers)
        self.Actor           = Actor(GNNEmbeddingDim, HiddenDim, NumLayers)
        self.Critic          = Critic(GNNEmbeddingDim, HiddenDim, NumLayers)
        self.ClipEpsilon     = ClipEpsilon
        self.Gamma           = Gamma
        self.GaeLambda       = GaeLambda
        self.EntropyCoef     = EntropyCoef
        self.UpdateEpochs    = UpdateEpochs
        self.BatchSize       = BatchSize
        self.optimizer       = torch.optim.Adam(self.parameters(), lr=LearningRate)

    def select_action(self, observation, KnowledgeGraph):
        data, node_list      = KnowledgeGraph.to_pyg_data()
        embeddings           = self.GNNEncoder(data)
        ready                = observation['ready']
        ActionSpaceDim       = len(ready)

        ready_embeddings     = torch.stack([
            embeddings[node_list.index(ProcessCode)]
            for ProcessCode in ready
        ])

        action_probs         = self.Actor(ready_embeddings.mean(dim=0, keepdim=True), ActionSpaceDim)
        dist                 = torch.distributions.Categorical(action_probs)  #확률 분포에서 action을 샘플링하는 PyTorch 분포 클래스
        action_idx           = dist.sample()
        log_prob             = dist.log_prob(action_idx)   #PPO 학습 시 정책 비율 계산

        ProcessCode          = ready[action_idx.item()]
        WorkstationId        = next(
            ws for ws in KnowledgeGraph.workers
            if ProcessCode in KnowledgeGraph.workers[ws]['ProcessCode']
        )
        return (ProcessCode, WorkstationId), log_prob
    
    def compute_loss(self, observations, actions, log_probs_old, rewards, values): #AAS화 예정
        EpisodeReturns       = [] #Simulation.RuntimeVariables (추가)
        Advantages           = [] #Simulation.RuntimeVariables (추가)
        G                    = 0 #누적 할인 보상 G = reward + Gamma * G
        for reward in reversed(rewards):
            G                = reward + self.Gamma * G
            EpisodeReturns.insert(0, globals)
        Episodereturns       = torch.tensor(Episodereturns, dtype=torch.float)
        Advantages           = Episodereturns - torch.tensor(values, dtype=torch.float)
        Advantages           = (Advantages - Advantages.mean()) / (Advantages.std() + 1e-8)

        log_probs_new        = []
        entropy              = []
        value_preds          = []

        for observation, action in zip(observations, actions):
            data, node_list   = observation['KnowledgeGraph'].to_pyg_data()
            embeddings        = self.GNNEncoder(data)
            ready             = observation['ready']
            ActionSpaceDim    = len(ready)
            ready_embeddings  = torch.stack([
                embeddings[node_list.index(ProcessCode)]
                for ProcessCode in ready
            ])
            action_probs      = self.Actor(ready_embeddings.mean(dim=0, keepdim=True), ActionSpaceDim)
            dist              = torch.distributions.Categorical(action_probs)
            log_probs_new.append(dist.log_prob(torch.tensor(action)))
            entropy.append(dist.entropy())
            value_preds.append(self.Critic(ready_embeddings.mean(dim=0, keepdim=True)))
        
        log_probs_new       = torch.stack(log_probs_new)
        entropy             = torch.stack(entropy)
        value_preds         = torch.stack(value_preds).squeeze()

        ratio               = torch.exp(log_probs_new - log_probs_old)
        actor_loss          = -torch.min(
                                  ratio * advantages,
                                  torch.clamp(ratio, 1 - self.ClipEpsilon, 1 + self.ClipEpsilon) * Advantages
                              ).mean()
        critic_loss         = torch.nn.functional.mse_loss(value_preds, Episodereturns)
        entropy_loss        = entropy.mean()

        loss                = actor_loss + self.ValueLossCoef * critic_loss - self.EntropyCoef * entropy_loss
        return loss
    
    def update(self, observations, actions, log_probs_old, rewards, values):
        log_probs_old = torch.tensor(log_probs_old, dtype=torch.float)
        for _ in range(self.UpdateEpochs):
            indices = torch.randperm(len(observations))  #매 epoch마다 데이터 순서 무작위로 섞음
            for start in range(0, len(observations), self.BatchSize):
                batch_idx         = indices[start : start + self.BatchSize]
                batch_obs         = [observations[i] for i in batch_idx]
                batch_actions     = [actions[i]      for i in batch_idx]
                batch_log_probs   = log_probs_old[batch_idx]
                batch_rewards     = [rewards[i]      for i in batch_idx]
                batch_values      = [values[i]       for i in batch_idx]

                loss  = self.compute_loss(
                    batch_obs,
                    batch_actions,
                    batch_log_probs,
                    batch_rewards,
                    batch_values,
                )
                self.optimizer.zero_grad()
                loss.backward()
                self.optimizer.step()

#========시뮬레이션 환경========-
class CproSimEnv(gym.Env):
    def __init__(self, KnowledgeGraph, warehouse, workers,
                 IndependentSequence, DependentSequence, DependentJoin,
                 RewardWeights, ReplenishLeadDay, target_qty, MaxEpisodes,
                 WarehouseManagedBOM, BOMCategory,
                 WorkStartTime, WorkEndTime, break_start_sec, break_end_sec,
                 IdleWorkerThreshold):
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

    def reset(self):
        self.env                  = simpy.Environment()
        self.completed            = set()
        self.in_progress          = {}
        self.EpisodeEnergyKwh     = [0.0]
        self.Throughput           = 0
        self.StockShortageCount   = 0
        self.StockOverflowCount   = 0
        self.idle_time            = {}
        self.IdleViolationCount   = 0
        self.warehouse            = Warehouse.build(
                                      self.WarehouseManagedBOM,
                                      self.BOMCategory
                                    )
        ready                     = self.KnowledgeGraph.ready_queue(
                                      self.IndependentSequence,
                                      self.DependentSequence,
                                      self.DependentJoin,
                                      self.completed,
                                      self.warehouse
                                    )
        return ready
    
    def _is_work_time(self) -> bool:
        seconds_in_day  = self.env.now % 86400
        return (self.WorkStartTime <= seconds_in_day < self.WorkEndTime and
                not (self.break_start_sec <= seconds_in_day < self.break_end_sec))
    
    def step(self, action):
        ProcessCode, WorkstationId  = action
        self.env.process(
            process_job(
                self.env,
                ProcessCode,
                WorkstationId,
                self.KnowledgeGraph,
                self.warehouse,
                self.completed,
                self.in_progress,
                self.ReplenishLeadDay,
                self.EpisodeEnergyKwh,
            )
        )
        self.env.run(until=self.env.now + self.KnowledgeGraph.nodes[ProcessCode].CycleTimeSec)
        if (ProcessCode in self.KnowledgeGraph.nodes and ProcessCode not in self.KnowledgeGraph.edges):
            self.Throughput += 1

        for Category in self.warehouse.inventory:
            for item in self.warehouse.inventory[Category].values():
                if item.present_stock < item.MinStock:
                    self.StockShortageCount += 1
                if item.present_stock > item.MaxStock:
                    self.StockOverflowCount += 1

        if self._is_work_time():
            for WorkstationId in self.workers:
                idle_slots = (self.workers[WorkstationId]['worker_count'] - 
                              self.in_progress.get(WorkstationId, 0))
                if idle_slots > 0:
                    if WorkstationId not in self.idle_time:
                        self.idle_time[WorkstationId] = self.env.now
                    elif (self.env.now - self.idle_time[WorkstationId]
                          > self.IdleWorkerThreshold):
                        self.IdleViolationCount += idle_slots
                else:
                    self.idle_time.pop(WorkstationId, None)

        work_day_sec = self.WorkEndTime - self.WorkStartTime - (self.break_end_sec - self.break_start_sec)
        step_count = max(self.env.now / (work_day_sec / self.target_qty), 1)

        reward = (
            - (self.env.now / work_day_sec)                         * self.RewardWeights['W1_TimeElapsed']
            - self.EpisodeEnergyKwh[0] / self.MaxEpisodeEnergyKwh   * self.RewardWeights['W2_Energy']
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
        }
        return observation, reward, done, {}

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

        agent.update(observations, actions, log_probs, rewards, values)

if __name__ == '__main__':
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
        MaxEpisodeEnergyKwh  = MaxEpisodeEnergyKwh,
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
    )

    train(env, agent, MaxEpisodes)