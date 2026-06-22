# -*- coding: utf-8 -*-
from __future__ import annotations

import random
import simpy
import torch

import carbon
from warehouse import Warehouse, _StockRouter


EPISODE_DURATION_SEC = 30 * 86400

class CproSimEnv:
    def __init__(self, KnowledgeGraph, warehouse, workers,
                 IndependentSequence, DependentSequence, DependentJoin,
                 RewardWeights, ReplenishLeadDay, target_qty, MaxEpisodes,
                 WarehouseManagedBOM, BOMCategory,
                 WorkStartTime, WorkEndTime, break_start_sec, break_end_sec,
                 IdleWorkerThreshold, RuntimeVariables,
                 IdleProcessRatedPowerKw, SelfManagedBOM=None,
                 SMTLines=None, SmtArrayPcb=6, SmtBatchArrays=40, DueDay=None):
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
        self.SelfManagedBOM       = SelfManagedBOM
        self.BOMCategory          = BOMCategory
        self.WorkStartTime        = WorkStartTime
        self.WorkEndTime          = WorkEndTime
        self.break_start_sec      = break_start_sec
        self.break_end_sec        = break_end_sec
        self.IdleWorkerThreshold  = IdleWorkerThreshold
        self.IdleProcessRatedPowerKw       = IdleProcessRatedPowerKw
        self.RuntimeVariables     = RuntimeVariables
        self.SMTLines             = SMTLines
        self.SmtArrayPcb          = SmtArrayPcb
        self.SmtBatchArrays       = SmtBatchArrays
        self.DueDay               = DueDay

    def reset(self):
        self.env                  = simpy.Environment()
        self.CycleCompleted       = False
        self.Throughput           = {model_id: 0 for model_id in self.target_qty}
        self.EpisodeEnergyKwh     = 0.0
        self.SMTEnergyKwh         = 0.0
        self.StockShortageCount   = 0
        self.StockOverflowCount   = 0
        self.IdleViolationCount   = 0
        self.DuePaceDeficit       = 0.0
        self.DuePaceDeficitByModel = {model_id: 0.0 for model_id in self.target_qty}
        self.completed            = set()
        self.in_progress          = {}
        self.idle_time            = {}
        self.last_active          = {ws: 0.0 for ws in self.workers}
        self.warehouse            = Warehouse.build(
                                      self.WarehouseManagedBOM,
                                      self.BOMCategory
                                    )
        if self.SelfManagedBOM:
            self._pcb_warehouse   = Warehouse.build(self.SelfManagedBOM, self.BOMCategory)
            self.warehouse        = _StockRouter(self.warehouse, self._pcb_warehouse)
            import smt
            smt.start(self)
        self.worker_resources     = {
            WorkstationId: simpy.Resource(self.env,
                                          capacity=info['worker_count'] * info['UnitsPerWorker'])
            for WorkstationId, info in self.workers.items()
        }
        self._pending   = {ws: [] for ws in self.workers}
        self._disp_wake = {ws: self.env.event() for ws in self.workers}
        self._stock_wake = self.env.event()
        work_day_sec              = self.WorkEndTime - self.WorkStartTime - (self.break_end_sec - self.break_start_sec)
        nominal_work_ticks        = work_day_sec / 30.0
        self._stock_violation_norm = max(1.0, sum(len(items) for items in self.warehouse.inventory.values())
                                               * nominal_work_ticks)
        self._idle_violation_norm  = max(1.0, sum(info['worker_count'] for info in self.workers.values())
                                               * nominal_work_ticks)
        self._due_violation_norm   = max(1.0, len(self.target_qty) * nominal_work_ticks)
        self.MaxEpisodeEnergyKwh = self.RuntimeVariables.MaxEpisodeEnergyKwh(
            self.KnowledgeGraph, self.target_qty,
            self.IdleProcessRatedPowerKw)
    
    def _is_work_time(self) -> bool:
        seconds_in_day  = self.env.now % 86400
        return (self.WorkStartTime <= seconds_in_day < self.WorkEndTime and
                not (self.break_start_sec <= seconds_in_day < self.break_end_sec))

    def _off_hours_delta(self) -> float:
        sid = self.env.now % 86400
        if sid < self.WorkStartTime:
            return self.WorkStartTime - sid
        if self.break_start_sec <= sid < self.break_end_sec:
            return self.break_end_sec - sid
        return 86400 - sid + self.WorkStartTime

    def process_job(self, ProcessCode, WorkstationId, done_set):
        self.in_progress[WorkstationId] = self.in_progress.get(WorkstationId, 0) + 1
        node = self.KnowledgeGraph.nodes[ProcessCode]
        while not self._is_work_time():
            yield self.env.timeout(self._off_hours_delta())
        with self.worker_resources[WorkstationId].request() as req:
            yield req
            yield self.env.timeout(node.CycleTimeSec)
        self.EpisodeEnergyKwh = self.RuntimeVariables.EpisodeEnergyKwh(
            node, self.EpisodeEnergyKwh, self.IdleProcessRatedPowerKw)
        if node.InputBOM:
            ordered = self.warehouse.consume(node.InputBOM)
            if ordered:
                self.env.process(self.warehouse.replenish(
                    self.env, self.ReplenishLeadDay, ordered))
        if node.OutputBOM:
            self.warehouse.produce(node.OutputBOM)
        done_set.add(ProcessCode)
        self.in_progress[WorkstationId] -= 1
        if self.in_progress[WorkstationId] == 0:
            self.last_active[WorkstationId] = self.env.now
        self.CycleCompleted = self.RuntimeVariables.CycleCompleted(ProcessCode, self.KnowledgeGraph)

    def _ready_for(self, model_id, done_set):
        return [pc for pc in self.KnowledgeGraph.ready_queue(
                    self.IndependentSequence, self.DependentSequence,
                    self.DependentJoin, done_set, self.warehouse)
                if self.KnowledgeGraph.nodes[pc].model_id in (model_id, 'ALL')]

    def _workstation_of(self, ProcessCode):
        return next((ws for ws in self.workers
                     if ProcessCode in self.workers[ws]['ProcessCode']), None)

    def _wake_dispatcher(self, ws):
        ev = self._disp_wake[ws]
        if not ev.triggered:
            ev.succeed()

    def _wake_stock(self):
        ev = self._stock_wake
        self._stock_wake = self.env.event()
        if not ev.triggered:
            ev.succeed()

    def _dispatcher(self, ws, agent):
        res = self.worker_resources[ws]
        while True:
            if not self._pending[ws]:
                self._disp_wake[ws] = self.env.event()
                yield self._disp_wake[ws]
                continue
            if not self._is_work_time():
                yield self.env.timeout(self._off_hours_delta())
                continue
            req = res.request()
            yield req
            pend = self._pending[ws]
            if not pend:
                res.release(req)
                continue
            distinct_pcs = list(dict.fromkeys(j['pc'] for j in pend))
            if agent is not None and len(distinct_pcs) >= 2:
                chosen_pc = agent.choose(distinct_pcs, self)
                job = next(j for j in pend if j['pc'] == chosen_pc)
            else:
                job = pend[0]
            pend.remove(job)
            self.env.process(self._run_job(ws, job, req))

    def _run_job(self, ws, job, req):
        pc = job['pc']
        node = self.KnowledgeGraph.nodes[pc]
        self.in_progress[ws] = self.in_progress.get(ws, 0) + 1
        yield self.env.timeout(node.CycleTimeSec)
        self.worker_resources[ws].release(req)
        self.EpisodeEnergyKwh = self.RuntimeVariables.EpisodeEnergyKwh(
            node, self.EpisodeEnergyKwh, self.IdleProcessRatedPowerKw)
        if node.InputBOM:
            ordered = self.warehouse.consume(node.InputBOM)
            if ordered:
                self.env.process(self.warehouse.replenish(
                    self.env, self.ReplenishLeadDay, ordered, self._wake_stock))
        if node.OutputBOM:
            self.warehouse.produce(node.OutputBOM)
        self.in_progress[ws] -= 1
        if self.in_progress[ws] == 0:
            self.last_active[ws] = self.env.now
        self._wake_dispatcher(ws)

        if node.DepWaitSec:
            yield self.env.timeout(node.DepWaitSec)

        job['done_set'].add(pc)
        job['in_flight'].discard(pc)
        self.CycleCompleted = self.RuntimeVariables.CycleCompleted(pc, self.KnowledgeGraph)
        self.Throughput = self.RuntimeVariables.Throughput(pc, self.KnowledgeGraph, self.Throughput)
        if not job['ev'].triggered:
            job['ev'].succeed()

    def produce_unit(self, model_id, agent=None):
        done_set = set()
        kg = self.KnowledgeGraph
        terminal_pcs = {pc for pc, n in kg.nodes.items()
                        if n.model_id == model_id and pc not in kg.edges}
        in_flight: set = set()
        outstanding: list = []
        while not terminal_pcs.issubset(done_set):
            ready = self._ready_for(model_id, done_set)
            for pc in ready:
                if pc in in_flight or pc in done_set:
                    continue
                node = kg.nodes[pc]
                if node.SamplingRate is not None and random.random() >= node.SamplingRate:
                    done_set.add(pc)
                    continue
                ws = self._workstation_of(pc)
                if ws is None:
                    done_set.add(pc)
                    continue
                in_flight.add(pc)
                ev = self.env.event()
                self._pending[ws].append({'pc': pc, 'done_set': done_set,
                                          'in_flight': in_flight, 'ev': ev})
                outstanding.append(ev)
                self._wake_dispatcher(ws)
            outstanding = [e for e in outstanding if not e.triggered]
            if not outstanding:
                yield self._stock_wake
                continue
            yield simpy.AnyOf(self.env, outstanding)
            outstanding = [e for e in outstanding if not e.triggered]

    def run(self, agent=None, max_sec: float = 60 * 86400):
        self.reset()
        stop = self.env.event()
        for ws in self.workers:
            self.env.process(self._dispatcher(ws, agent))
        for model_id, qty in self.target_qty.items():
            for _ in range(qty):
                self.env.process(self.produce_unit(model_id, agent))

        def _watch():
            while not stop.triggered:
                yield self.env.timeout(30)
                if self._is_work_time():
                    self.StockShortageCount = self.RuntimeVariables.StockShortageCount(
                        self.warehouse, self.StockShortageCount)
                    self.StockOverflowCount = self.RuntimeVariables.StockOverflowCount(
                        self.warehouse, self.StockOverflowCount)
                    self.IdleViolationCount = self.RuntimeVariables.IdleViolationCount(
                        self.workers, self.in_progress, self.idle_time, self.env.now,
                        self.IdleWorkerThreshold, self.IdleViolationCount)
                    self.DuePaceDeficit = self.RuntimeVariables.DuePaceDeficit(
                        self.Throughput, self.target_qty, self.DueDay, self.env.now,
                        self.DuePaceDeficit)
                    self.DuePaceDeficitByModel = self.RuntimeVariables.DuePaceDeficitByModel(
                        self.Throughput, self.target_qty, self.DueDay, self.env.now,
                        self.DuePaceDeficitByModel)
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
            'EpisodeEnergyKwh': float(self.total_energy_kwh()),
            'ActivePremiumKwh': float(self.EpisodeEnergyKwh),
        }

    def total_energy_kwh(self) -> float:
        idle_base = self.RuntimeVariables.IdleBaselineKwh(
            self.KnowledgeGraph, self.env.now,
            self.IdleProcessRatedPowerKw)
        return idle_base + self.EpisodeEnergyKwh + self.SMTEnergyKwh

    @property
    def state_dim(self) -> int:
        return len(self.target_qty) + 2 + len(self.workers) + 4

    def state_vec(self) -> torch.Tensor:
        total_target = sum(self.target_qty.values())
        work_day = self.WorkEndTime - self.WorkStartTime - (self.break_end_sec - self.break_start_sec)
        feats = []
        for model_id in self.target_qty:
            feats.append(self.Throughput[model_id] / self.target_qty[model_id])
        feats.append(self.env.now / max(work_day * total_target, 1.0))
        feats.append(self.EpisodeEnergyKwh / self.MaxEpisodeEnergyKwh)
        for ws, info in self.workers.items():
            feats.append(self.in_progress.get(ws, 0) / info['worker_count'])
        stock_short = 0.0
        stock_over  = 0.0
        for cat in self.warehouse.inventory.values():
            for s in cat.values():
                if s.MinStock > 0:
                    stock_short += max(0, s.MinStock - s.present_stock) / s.MinStock
                if s.MaxStock > 0:
                    stock_over  += max(0, s.present_stock - s.MaxStock) / s.MaxStock
        feats.append(stock_short)
        feats.append(stock_over)
        idle_norm_sum = 0.0
        for ws in self.workers:
            if self.in_progress.get(ws, 0) == 0:
                idle_norm_sum += (self.env.now - self.last_active[ws]) / max(self.IdleWorkerThreshold, 1.0)
        feats.append(idle_norm_sum / len(self.workers))
        due_deficit = 0.0
        for model_id in self.target_qty:
            required = min(self.env.now / self.DueDay[model_id], 1.0)
            due_deficit += max(0.0, required - self.Throughput[model_id] / self.target_qty[model_id])
        feats.append(due_deficit / len(self.target_qty))
        return torch.tensor(feats, dtype=torch.float32)

    def potential(self) -> float:
        RewardWeights = self.RewardWeights
        total_target = sum(self.target_qty.values())
        work_day = self.WorkEndTime - self.WorkStartTime - (self.break_end_sec - self.break_start_sec)
        return (
            + (sum(self.Throughput.values()) / total_target)                                    * RewardWeights['W5_Throughput']
            - (self.env.now / (work_day * total_target))                                        * RewardWeights['W1_TimeElapsed']
            - (carbon.total(self.EpisodeEnergyKwh) / carbon.total(self.MaxEpisodeEnergyKwh))    * RewardWeights['W2_Energy']
            - (self.StockOverflowCount / self._stock_violation_norm)                            * RewardWeights['W3_StockOverflow']
            - (self.StockShortageCount / self._stock_violation_norm)                            * RewardWeights['W4_StockShortage']
            - (self.IdleViolationCount / self._idle_violation_norm)                             * RewardWeights['W6_IdleWorker']
            - (self.DuePaceDeficit / self._due_violation_norm)                                  * RewardWeights['W7_DueDate']
        )

    def episode_reward(self) -> float:
        return self.potential()

def train(env, agent, MaxEpisodes, run_name=None, episode_max_sec=EPISODE_DURATION_SEC):
    import os, time
    from util.rl_logger import RLLogger
    _ROOT = os.path.dirname(os.path.abspath(__file__))

    if run_name is None:
        run_name = 'run_' + time.strftime('%Y-%m-%d_%H-%M-%S')
    _OUT = os.path.join(_ROOT, 'result', 'runs', run_name)
    os.makedirs(_OUT, exist_ok=True)
    print(f'[train] outputs → result/runs/{run_name}/', flush=True)
    logger = RLLogger(os.path.join(_OUT, 'rl_log.jsonl'))
    ckpt   = os.path.join(_OUT, 'agent_mod.pt')

    for episode in range(MaxEpisodes):
        if os.path.exists(os.path.join(_OUT, 'STOP')):
            print(f'[ep {episode}] STOP sentinel — graceful exit', flush=True)
            break
        agent.reset_buffer()
        summary = env.run(agent=agent, max_sec=episode_max_sec)
        R = env.episode_reward()
        decisions = len(agent.buf)
        metrics = agent.learn(R, env.KnowledgeGraph)
        is_best = logger.log_episode(
            episode, R=R, makespan=summary['makespan_sec'],
            energy=summary['EpisodeEnergyKwh'],
            throughput=dict(env.Throughput), target_qty=dict(env.target_qty),
            decisions=decisions, metrics=metrics,
            violations={'stock_shortage': env.StockShortageCount,
                        'stock_overflow': env.StockOverflowCount,
                        'idle_violation': env.IdleViolationCount,
                        'due_pace_deficit': env.DuePaceDeficit,
                        **{f'due_pace/{model_id}': value
                           for model_id, value in env.DuePaceDeficitByModel.items()}})
        if is_best:
            torch.save(agent.state_dict(), ckpt)
        thru = ' '.join(f'{m}:{env.Throughput[m]}/{env.target_qty[m]}' for m in env.target_qty)
        ev = (metrics or {}).get('critic/explained_variance')
        print(f'[ep {episode:>4}] R={R:+.4f} decisions={decisions} '
              f'makespan={summary["makespan_sec"]:.0f} E={summary["EpisodeEnergyKwh"]:.2f} '
              f'thru=[{thru}] ev={ev} {"BEST↑" if is_best else ""}')


def obs_node_features(kg):
    if kg.NodeFeatureAttrs is None:
        raise RuntimeError('KnowledgeGraph.NodeFeatureAttrs 미설정 — ObservationNodeFeatures(AAS) 필요')
    sample  = next(iter(kg.nodes.values()))
    missing = [attr for attr in kg.NodeFeatureAttrs if not hasattr(sample, attr)]
    if missing:
        raise RuntimeError(f'ObservationNodeFeatures 항목이 GraphNode 속성이 아님: {missing}')
    return torch.tensor([[getattr(kg.nodes[pc], attr) for attr in kg.NodeFeatureAttrs]
                         for pc in kg.nodes], dtype=torch.float)

def obs_graph_topology(kg):
    node_index = {pc: i for i, pc in enumerate(kg.nodes)}
    src, dst = [], []
    for DepPrev, GraphEdges in kg.edges.items():
        for GraphEdge in GraphEdges:
            if DepPrev in node_index and GraphEdge.ProcessCode in node_index:
                src.append(node_index[DepPrev]); dst.append(node_index[GraphEdge.ProcessCode])
    return torch.tensor([src, dst], dtype=torch.long)

def obs_state_vector(env):
    return env.state_vec()

OBSERVATION_CATALOG = {
    'NodeFeatures':  obs_node_features,
    'GraphTopology': obs_graph_topology,
    'StateVector':   obs_state_vector,
}


class PPOAgent(torch.nn.Module):
    def __init__(self, *, encoder, actor, critic, StateDim,
                 LearningRate, ClipEpsilon, Gamma, GaeLambda,
                 EntropyCoef, ValueLossCoef, UpdateEpochs, BatchSize, RuntimeVariables):
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
        self.RuntimeVariables = RuntimeVariables
        self.optimizer       = torch.optim.Adam(self.parameters(), lr=LearningRate)

    def reset_buffer(self):
        self.buf = []

    @torch.no_grad()
    def choose(self, ready_pcs, env):
        kg               = env.KnowledgeGraph
        node_list        = list(kg.nodes.keys())
        embeddings       = self.GNNEncoder(NodeFeatures=obs_node_features(kg), GraphTopology=obs_graph_topology(kg))
        ready_emb        = torch.stack([embeddings[node_list.index(pc)] for pc in ready_pcs])
        state            = env.state_vec() if self.StateDim > 0 else None
        dist             = torch.distributions.Categorical(self.Actor(ReadyNodeEmbeddings=ready_emb, StateVector=state))
        idx              = dist.sample() if self.training else dist.probs.argmax()
        value            = self.Critic(PooledNodeEmbedding=ready_emb.mean(dim=0, keepdim=True), StateVector=state).squeeze()
        self.buf.append({'ready': list(ready_pcs), 'idx': int(idx.item()),
                         'logp': dist.log_prob(idx),
                         'value': value,
                         'state': state,
                         'phi': float(env.potential())})
        return ready_pcs[idx.item()]

    def learn(self, episode_return, KnowledgeGraph):
        if not self.buf:
            return None
        n        = len(self.buf)
        values   = torch.stack([b['value'] for b in self.buf])
        old_logp = torch.stack([b['logp']  for b in self.buf])
        phi      = [b['phi'] for b in self.buf]

        rewards = torch.tensor(
            [(phi[i + 1] if i < n - 1 else float(episode_return)) - phi[i]
             for i in range(n)], dtype=torch.float32)

        advantages = torch.zeros(n)
        gae = 0.0
        for t in reversed(range(n)):
            v_next = values[t + 1] if t < n - 1 else 0.0
            delta  = rewards[t] + self.Gamma * v_next - values[t]
            gae    = delta + self.Gamma * self.GaeLambda * gae
            advantages[t] = gae
        returns = advantages + values
        adv     = (advantages - advantages.mean()) / (advantages.std() + 1e-8)
        grad_norm = 0.0
        for _ in range(self.UpdateEpochs):
            new_logp, entropy, value_preds = [], [], []
            node_list      = list(KnowledgeGraph.nodes.keys())
            node_features  = obs_node_features(KnowledgeGraph)
            graph_topology = obs_graph_topology(KnowledgeGraph)
            for b in self.buf:
                embeddings = self.GNNEncoder(NodeFeatures=node_features, GraphTopology=graph_topology)
                ready_emb  = torch.stack([embeddings[node_list.index(pc)] for pc in b['ready']])
                state      = b['state']
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

        with torch.no_grad():
            resid_var  = float((returns - value_preds).var())
            ret_var    = float(returns.var())
            clip_frac  = float(((ratio - 1.0).abs() > self.ClipEpsilon).float().mean())
            approx_kl  = float((old_logp - new_logp).mean())
            return {
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

import importlib, inspect

def import_callable(path: str):
    module, name = path.rsplit('.', 1)
    return getattr(importlib.import_module(module), name)

def op_concat_state(x, state=None):
    if state is None:
        return x
    return torch.cat([x, state.unsqueeze(0).expand(x.size(0), -1)], dim=-1)

def op_squeeze_last(input):
    return input.squeeze(-1)


class GraphModule(torch.nn.Module):
    def __init__(self, spec, source_dims=None):
        super().__init__()
        self.spec = spec
        self.mods = torch.nn.ModuleDict()
        dim = dict(source_dims or {})
        for node in spec:
            operation = node['Operation']
            arguments = dict(node.get('Arguments', {}))
            in_dim    = {param: dim.get(src) for param, src in node['Inputs'].items()}
            callable_ = import_callable(operation)
            if isinstance(callable_, type) and issubclass(callable_, torch.nn.Module):
                params = inspect.signature(callable_).parameters
                if 'in_features' in params and 'in_features' not in arguments:
                    arguments['in_features'] = in_dim['input']
                elif 'in_channels' in params and 'in_channels' not in arguments:
                    arguments['in_channels'] = in_dim['x']
                self.mods[node['id']] = callable_(**arguments)
                out_dim = arguments.get('out_features', arguments.get('out_channels'))
            elif operation.endswith('op_concat_state'):
                out_dim = (in_dim.get('x') or 0) + (in_dim.get('state') or 0)
            else:
                out_dim = next((d for d in in_dim.values() if d is not None), None)
            dim[node['id']] = out_dim

    def forward(self, **sources):
        vals = dict(sources)
        out = None
        for node in self.spec:
            bound = {param: vals[src] for param, src in node['Inputs'].items()}
            if node['id'] in self.mods:
                out = self.mods[node['id']](**bound)
            else:
                out = import_callable(node['Operation'])(**bound, **node.get('Arguments', {}))
            vals[node['id']] = out
        return out
