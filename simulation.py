from __future__ import annotations

import importlib
import inspect
import random
import simpy
import torch

from warehouse import Warehouse, _StockRouter
from knowledge_graph import SHARED_MODEL_ID


EPISODE_DURATION_SEC = 30 * 86400


# ── 시뮬레이션 환경 (SimPy 이산사건 공장) ──
class CproSimEnv:
    def __init__(self, KnowledgeGraph, warehouse, workers,
                 IndependentSequence, DependentSequence, DependentJoin,
                 RewardWeights, ReplenishLeadDay, target_qty, MaxEpisodes,
                 WarehouseManagedBOM, BOMCategory,
                 WorkStartTime, WorkEndTime, break_start_sec, break_end_sec,
                 IdleWorkerThreshold, RuntimeVariables,
                 DefaultProcessConsumedPowerKw, SelfManagedBOM=None,
                 SMTLines=None, SmtArrayPcb=6, DueDay=None,
                 InfiniteStock=False, ScenarioMode='FINITE', MaxEpisodeSec=None,
                 ElectricityTariffBands=None):
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
        self.DefaultProcessConsumedPowerKw = DefaultProcessConsumedPowerKw
        self.RuntimeVariables     = RuntimeVariables
        self.SMTLines             = SMTLines
        self.SmtArrayPcb          = SmtArrayPcb
        self.DueDay               = DueDay
        self.InfiniteStock        = InfiniteStock
        self.ScenarioMode         = ScenarioMode
        self.MaxEpisodeSec        = MaxEpisodeSec
        self.ElectricityTariffBands = ElectricityTariffBands
        self.IdleRewardMode       = 'time'
        self.DueRewardMode        = 'sparse'

    def reset(self):
        self.env                  = simpy.Environment()
        self.CycleCompleted       = False
        self.Throughput           = {model_id: 0 for model_id in self.target_qty}
        self.EpisodeEnergyKwh     = 0.0
        self.SMTEnergyKwh         = 0.0
        self.line_energy          = {}
        self.StockShortageCount   = 0
        self.StockOverflowCount   = 0
        self.IdleViolationCount   = 0
        self.DuePaceDeficit       = 0.0
        self.CompletionSec        = {model_id: None for model_id in self.target_qty}
        self.smt_equip_energy     = {}
        self.completed            = set()
        self.in_progress          = {}
        self.idle_time            = {}
        self.last_active          = {ws: 0.0 for ws in self.workers}
        self.line_idle_time       = {ws: 0.0 for ws in self.workers}
        self.line_idle_viol       = {ws: 0.0 for ws in self.workers}
        self._idle_last_t         = {ws: 0.0 for ws in self.workers}
        self._cont_idle           = {ws: 0.0 for ws in self.workers}
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
        self._stock_violation_norm = max(1.0, sum(len(items) for items in self._counted_warehouse().inventory.values())
                                               * nominal_work_ticks)
        self._idle_violation_norm  = max(1.0, sum(info['worker_count'] for info in self.workers.values())
                                               * nominal_work_ticks)
        self._due_violation_norm   = max(1.0, len(self.target_qty) * nominal_work_ticks)
        smt_plan = getattr(self, 'SmtPlanEffective', None)
        self.MaxEpisodeEnergyKwh = self.RuntimeVariables.MaxEpisodeEnergyKwh(
            self.KnowledgeGraph, self.target_qty, self.workers, work_day_sec,
            self.DefaultProcessConsumedPowerKw,
            horizon_mode=getattr(self, 'W2HorizonMode', 'bottleneck'))
        if smt_plan:
            import smt
            self.MaxEpisodeEnergyKwh += smt.plan_energy_kwh(self, smt_plan)
    
    def _counted_warehouse(self):
        return getattr(self.warehouse, 'main', self.warehouse)

    @property
    def SteadyWIP(self) -> int:
        capacity = sum(i['worker_count'] * i['UnitsPerWorker'] for i in self.workers.values())
        return max(1, capacity // len(self.target_qty))

    # 시간·근무시간 (야간·휴게 처리)
    def _is_work_time(self) -> bool:
        seconds_in_day  = self.env.now % 86400
        return (self.WorkStartTime <= seconds_in_day < self.WorkEndTime and
                not (self.break_start_sec <= seconds_in_day < self.break_end_sec))

    def _off_hours_delta(self) -> float:
        sec_in_day = self.env.now % 86400
        if sec_in_day < self.WorkStartTime:
            return self.WorkStartTime - sec_in_day
        if self.break_start_sec <= sec_in_day < self.break_end_sec:
            return self.break_end_sec - sec_in_day
        return 86400 - sec_in_day + self.WorkStartTime

    def _tariff_weighted_sec(self, t0: float, t1: float) -> float:
        # [t0,t1] 소모 구간을 하루 내 시각으로 접어 요금밴드 비율로 가중한 초.
        # 밴드 미설정(None)이면 그대로 실초 반환. 밴드 밖 시간대는 비율 1.0(보통).
        dt = max(0.0, t1 - t0)
        bands = self.ElectricityTariffBands
        if not bands or dt == 0.0:
            return dt
        s0 = t0 % 86400.0
        s1 = s0 + dt
        weighted = dt
        for start, end, ratio in bands:
            for shift in (0.0, 86400.0):
                overlap = max(0.0, min(s1, end + shift) - max(s0, start + shift))
                weighted += overlap * (ratio - 1.0)
        return weighted

    def _work_elapsed(self, t: float) -> float:
        day = 86400.0
        work_day = (self.WorkEndTime - self.WorkStartTime) - (self.break_end_sec - self.break_start_sec)
        full = int(t // day)
        sec_in_day = t - full * day
        def seg(a, b):
            return max(0.0, min(sec_in_day, b) - a) if sec_in_day > a else 0.0
        partial = seg(self.WorkStartTime, self.break_start_sec) + seg(self.break_end_sec, self.WorkEndTime)
        return full * work_day + partial

    def _flush_idle(self, ws, now: float):
        if self.IdleRewardMode != 'time':
            return
        idle_slots = self.workers[ws]['worker_count'] - self.in_progress.get(ws, 0)
        dt = self._work_elapsed(now) - self._work_elapsed(self._idle_last_t[ws])
        if idle_slots > 0 and dt > 0:
            self.line_idle_time[ws] += idle_slots * dt
            threshold = max(self.IdleWorkerThreshold, 0.0)
            before = max(0.0, self._cont_idle[ws] - threshold)
            self._cont_idle[ws] += dt
            after  = max(0.0, self._cont_idle[ws] - threshold)
            self.line_idle_viol[ws] += idle_slots * (after - before)
        if idle_slots == 0:
            self._cont_idle[ws] = 0.0
        self._idle_last_t[ws] = now

    # 작업 디스패치·실행 (경합점 선택은 _dispatcher에서 agent가)
    def _ready_for(self, model_id, done_set):
        return [pc for pc in self.KnowledgeGraph.ready_queue(
                    self.IndependentSequence, self.DependentSequence,
                    self.DependentJoin, done_set, self.warehouse, self.InfiniteStock)
                if self.KnowledgeGraph.nodes[pc].model_id in (model_id, SHARED_MODEL_ID)]

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
        resource = self.worker_resources[ws]
        while True:
            if not self._pending[ws]:
                self._disp_wake[ws] = self.env.event()
                yield self._disp_wake[ws]
                continue
            if not self._is_work_time():
                yield self.env.timeout(self._off_hours_delta())
                continue
            req = resource.request()
            yield req
            pending = self._pending[ws]
            if not pending:
                resource.release(req)
                continue
            # 당일 퇴근 전에 사이클이 끝나는 작업만 시작 가능 — 못 맞추면 다음 근무 시작까지 보류
            remaining_sec = self.WorkEndTime - self.env.now % 86400
            fitting = [j for j in pending
                       if self.KnowledgeGraph.nodes[j['pc']].CycleTimeSec <= remaining_sec]
            if not fitting:
                resource.release(req)
                self._disp_wake[ws] = self.env.event()
                yield simpy.AnyOf(self.env, [self.env.timeout(self._off_hours_delta()),
                                             self._disp_wake[ws]])
                continue
            distinct_pcs = list(dict.fromkeys(j['pc'] for j in fitting))
            if agent is not None and len(distinct_pcs) >= 2:
                chosen_pc = agent.choose(distinct_pcs, self)
                job = next(j for j in fitting if j['pc'] == chosen_pc)
            else:
                job = fitting[0]
            pending.remove(job)
            self.env.process(self._run_job(ws, job, req))

    def _run_job(self, ws, job, req):
        pc = job['pc']
        node = self.KnowledgeGraph.nodes[pc]
        self._flush_idle(ws, self.env.now)
        self.in_progress[ws] = self.in_progress.get(ws, 0) + 1
        start_sec = self.env.now
        yield self.env.timeout(node.CycleTimeSec)
        self.worker_resources[ws].release(req)
        energy_before = self.EpisodeEnergyKwh
        self.EpisodeEnergyKwh = self.RuntimeVariables.EpisodeEnergyKwh(
            node, self.EpisodeEnergyKwh,
            self._tariff_weighted_sec(start_sec, self.env.now))
        self.line_energy[ws] = self.line_energy.get(ws, 0.0) + (self.EpisodeEnergyKwh - energy_before)
        if node.InputBOM:
            ordered = self.warehouse.consume(node.InputBOM, deduct=not self.InfiniteStock)
            if ordered:
                self.env.process(self.warehouse.replenish(
                    self.env, self.ReplenishLeadDay, ordered, self._wake_stock))
        if node.OutputBOM:
            self.warehouse.produce(node.OutputBOM)
        self._flush_idle(ws, self.env.now)
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
        model_id = node.model_id
        if (model_id in self.CompletionSec and self.CompletionSec[model_id] is None
                and self.Throughput.get(model_id, 0) >= self.target_qty[model_id]):
            self.CompletionSec[model_id] = self.env.now
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

    def _steady_feed(self, model_id, agent, max_sec, hold):
        while self.env.now < max_sec:
            yield from self.produce_unit(model_id, agent)
            self._inflight[model_id] -= 1
            if self._inflight[model_id] >= hold:
                return
            self._inflight[model_id] += 1

    # 에피소드 실행 루프 (피드 + 디스패처 + 30초 감시)
    def run(self, agent=None, max_sec: float = None):
        self.reset()
        if max_sec is None:
            max_sec = float(self.MaxEpisodeSec)
        stop = self.env.event()
        for ws in self.workers:
            self.env.process(self._dispatcher(ws, agent))
        if self.ScenarioMode == 'STEADY':
            hold = self.SteadyWIP
            self._inflight = {m: hold * 2 for m in self.target_qty}
            for model_id in self.target_qty:
                for _ in range(hold * 2):
                    self.env.process(self._steady_feed(model_id, agent, max_sec, hold))
        else:
            for model_id, qty in self.target_qty.items():
                for _ in range(qty):
                    self.env.process(self.produce_unit(model_id, agent))

        def _watch():
            while not stop.triggered:
                yield self.env.timeout(30)
                if self._is_work_time():
                    self.StockShortageCount = self.RuntimeVariables.StockShortageCount(
                        self._counted_warehouse(), self.StockShortageCount)
                    self.StockOverflowCount = self.RuntimeVariables.StockOverflowCount(
                        self._counted_warehouse(), self.StockOverflowCount)
                    if self.IdleRewardMode == 'count':
                        self.IdleViolationCount = self.RuntimeVariables.IdleViolationCount(
                            self.workers, self.in_progress, self.idle_time, self.env.now,
                            self.IdleWorkerThreshold, self.IdleViolationCount)
                        for _ws in self.workers:
                            _idle = self.workers[_ws]['worker_count'] - self.in_progress.get(_ws, 0)
                            if _idle > 0:
                                self.line_idle_time[_ws] += _idle * 30
                    self.DuePaceDeficit = self.RuntimeVariables.DuePaceDeficit(
                        self.Throughput, self.target_qty, self.DueDay, self.env.now,
                        self.DuePaceDeficit)
                target_met = all(self.Throughput[m] >= self.target_qty[m] for m in self.target_qty)
                if ((self.ScenarioMode != 'STEADY' and target_met)
                        or self.env.now >= max_sec):
                    if not stop.triggered:
                        stop.succeed()
                    return
        self.env.process(_watch())
        self.env.run(until=stop)
        for ws in self.workers:
            self._flush_idle(ws, self.env.now)
        return {
            'Throughput'      : dict(self.Throughput),
            'makespan_sec'    : float(self.env.now),
            'EpisodeEnergyKwh': float(self.total_energy_kwh()),
            'ActivePremiumKwh': float(self.EpisodeEnergyKwh),
            'IdleEnergyKwh'   : float(self.baseline_energy_kwh()),
            'SMTEnergyKwh'    : float(self.SMTEnergyKwh),
            'SMTEquipEnergy'  : {line: {eq: float(v) for eq, v in eqs.items()}
                                 for line, eqs in self.smt_equip_energy.items()},
            'CompletionSec'   : {m: (float(t) if t is not None else None)
                                 for m, t in self.CompletionSec.items()},
            'LineEnergy'      : {k: float(v) for k, v in self.line_energy.items()},
            'RewardTerms'     : {k: float(v) for k, v in self.reward_terms().items()},
            'LineIdleTime'    : {k: float(v) / self.workers[k]['worker_count']
                                 for k, v in self.line_idle_time.items()},
            'TotalIdleTime'   : float(sum(self.line_idle_time.values())),
        }

    # 에너지·상태벡터·보상 (W1~W8)
    def baseline_energy_kwh(self) -> float:
        # 기저부하는 출근~퇴근 연속 가동(점심 미차감) — _work_elapsed(점심 차감)와 기준이 다름
        day    = 86400.0
        window = max(0.0, self.WorkEndTime - self.WorkStartTime)
        full   = int(self.env.now // day)
        sec_in_day = self.env.now - full * day
        partial    = min(max(sec_in_day - self.WorkStartTime, 0.0), window)
        weighted_sec = (full * self._tariff_weighted_sec(self.WorkStartTime, self.WorkEndTime)
                        + self._tariff_weighted_sec(self.WorkStartTime, self.WorkStartTime + partial))
        return weighted_sec * self.DefaultProcessConsumedPowerKw / 3600

    def total_energy_kwh(self) -> float:
        return self.baseline_energy_kwh() + self.EpisodeEnergyKwh + self.SMTEnergyKwh

    @property
    def StateDim(self) -> int:
        return len(self.target_qty) + 2 + len(self.workers) + 4

    def StateVector(self) -> torch.Tensor:
        total_target = sum(self.target_qty.values())
        work_day = self.WorkEndTime - self.WorkStartTime - (self.break_end_sec - self.break_start_sec)
        features = []
        for model_id in self.target_qty:
            # 주문 0 인 모델은 진행률 1(이미 충족) — 학습 시엔 target 0 이 없어 동작 불변
            features.append(self.Throughput[model_id] / self.target_qty[model_id]
                            if self.target_qty[model_id] else 1.0)
        features.append(self.env.now / max(work_day * total_target, 1.0))
        features.append(self.total_energy_kwh() / self.MaxEpisodeEnergyKwh)
        for ws, info in self.workers.items():
            features.append(self.in_progress.get(ws, 0) / info['worker_count'])
        stock_short = 0.0
        stock_over  = 0.0
        for category in self._counted_warehouse().inventory.values():
            for stock_item in category.values():
                if stock_item.MinStock > 0:
                    stock_short += max(0, stock_item.MinStock - stock_item.present_stock) / stock_item.MinStock
                if stock_item.MaxStock > 0:
                    stock_over  += max(0, stock_item.present_stock - stock_item.MaxStock) / stock_item.MaxStock
        features.append(stock_short)
        features.append(stock_over)
        idle_norm_sum = 0.0
        for ws in self.workers:
            if self.in_progress.get(ws, 0) == 0:
                idle_norm_sum += (self.env.now - self.last_active[ws]) / max(self.IdleWorkerThreshold, 1.0)
        features.append(idle_norm_sum / len(self.workers))
        due_deficit = 0.0
        for model_id in self.target_qty:
            if not self.target_qty[model_id]:     # 주문 0 인 모델 — 페이스 요구 없음
                continue
            required = min(self.env.now / self.DueDay[model_id], 1.0)
            due_deficit += max(0.0, required - self.Throughput[model_id] / self.target_qty[model_id])
        features.append(due_deficit / len(self.target_qty))
        return torch.tensor(features, dtype=torch.float32)

    def reward_terms(self) -> dict:
        RW = self.RewardWeights
        total_target = sum(self.target_qty.values())
        work_day = self.WorkEndTime - self.WorkStartTime - (self.break_end_sec - self.break_start_sec)
        total_workers = sum(info['worker_count'] for info in self.workers.values())
        if self.IdleRewardMode == 'count':
            w6 = - (self.IdleViolationCount / self._idle_violation_norm) * RW['W6_IdleWorker']
        else:
            idle_avail = max(1.0, total_workers * self._work_elapsed(self.env.now))
            w6 = - (sum(self.line_idle_viol.values()) / idle_avail) * RW['W6_IdleWorker']
        if self.DueRewardMode == 'pace':
            w7 = - (self.DuePaceDeficit / self._due_violation_norm) * RW['W7_DueDate']
        else:
            margin = 0.0
            for model_id in self.target_qty:
                done_t = self.CompletionSec[model_id]
                if done_t is not None:
                    margin += (self.DueDay[model_id] - done_t) / self.DueDay[model_id]
                elif self.env.now > self.DueDay[model_id]:
                    margin += (self.DueDay[model_id] - self.env.now) / self.DueDay[model_id]
            w7 = (margin / len(self.target_qty)) * RW['W7_DueDate']
        return {
            'W5_Throughput':    + (sum(self.Throughput.values()) / total_target)                                * RW['W5_Throughput'],
            'W1_TimeElapsed':   - (self.env.now / (work_day * total_target))                                    * RW['W1_TimeElapsed'],
            'W2_Energy':        - (self.total_energy_kwh() / self.MaxEpisodeEnergyKwh)                          * RW['W2_Energy'],
            'W3_StockOverflow': - (self.StockOverflowCount / self._stock_violation_norm)                        * RW['W3_StockOverflow'],
            'W4_StockShortage': - (self.StockShortageCount / self._stock_violation_norm)                        * RW['W4_StockShortage'],
            'W6_IdleWorker':    w6,
            'W7_DueDate':       w7,
            'W8_Imbalance':     - self._W8_Imbalance()                                                  * RW['W8_Imbalance'],
        }

    def potential(self) -> float:
        for ws in self.workers:
            self._flush_idle(ws, self.env.now)
        return sum(self.reward_terms().values())

    def _W8_Imbalance(self) -> float:
        counts = list(self.Throughput.values())
        done   = sum(counts)
        if done < 1:
            return 0.0
        return (max(counts) - min(counts)) / done

    def episode_reward(self) -> float:
        return self.potential()


# ── 관측 (그래프 임베딩·상태벡터) ──
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
    for DepPrev, edges_from in kg.edges.items():
        for edge in edges_from:
            if DepPrev in node_index and edge.ProcessCode in node_index:
                src.append(node_index[DepPrev]); dst.append(node_index[edge.ProcessCode])
    return torch.tensor([src, dst], dtype=torch.long)

def obs_state_vector(env):
    return env.StateVector()

OBSERVATION_CATALOG = {
    'NodeFeatures':  obs_node_features,
    'GraphTopology': obs_graph_topology,
    'StateVector':   obs_state_vector,
}


# ── PPO 에이전트 (경합점에서 공정 선택 + 학습) ──
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
        state            = env.StateVector() if self.StateDim > 0 else None
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
            node_list      = list(KnowledgeGraph.nodes.keys())
            node_features  = obs_node_features(KnowledgeGraph)
            graph_topology = obs_graph_topology(KnowledgeGraph)
            perm = torch.randperm(n).tolist()
            for s in range(0, n, self.BatchSize):
                mb = perm[s:s + self.BatchSize]
                embeddings = self.GNNEncoder(NodeFeatures=node_features, GraphTopology=graph_topology)
                new_logp, entropy, value_preds = [], [], []
                for i in mb:
                    b          = self.buf[i]
                    ready_emb  = torch.stack([embeddings[node_list.index(pc)] for pc in b['ready']])
                    state      = b['state']
                    dist       = torch.distributions.Categorical(self.Actor(ReadyNodeEmbeddings=ready_emb, StateVector=state))
                    new_logp.append(dist.log_prob(torch.tensor(b['idx'])))
                    entropy.append(dist.entropy())
                    value_preds.append(self.Critic(PooledNodeEmbedding=ready_emb.mean(dim=0, keepdim=True), StateVector=state).squeeze())
                new_logp    = torch.stack(new_logp)
                entropy     = torch.stack(entropy)
                value_preds = torch.stack(value_preds)
                mb_adv      = adv[mb]
                mb_oldlogp  = old_logp[mb]
                mb_returns  = returns[mb]
                ratio       = torch.exp(new_logp - mb_oldlogp)
                actor_loss  = -torch.min(
                                  ratio * mb_adv,
                                  torch.clamp(ratio, 1 - self.ClipEpsilon, 1 + self.ClipEpsilon) * mb_adv
                              ).mean()
                critic_loss = torch.nn.functional.mse_loss(value_preds, mb_returns)
                loss        = actor_loss + self.ValueLossCoef * critic_loss - self.EntropyCoef * entropy.mean()
                self.optimizer.zero_grad()
                loss.backward()
                grad_norm = float(torch.nn.utils.clip_grad_norm_(self.parameters(), 0.5))
                self.optimizer.step()

        with torch.no_grad():
            resid_var  = float((mb_returns - value_preds).var(unbiased=False))
            ret_var    = float(mb_returns.var(unbiased=False))
            clip_frac  = float(((ratio - 1.0).abs() > self.ClipEpsilon).float().mean())
            approx_kl  = float((mb_oldlogp - new_logp).mean())
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

# ── 신경망 조립 (AAS spec → torch 모듈) ──
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
