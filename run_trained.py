from __future__ import annotations
import os, sys, json, argparse, random

sys.dont_write_bytecode = True

AGING_WORKSTATION = 'WWM_AgingLine'
SEMI_WORKSTATION  = 'WWM_SemiAssemblyLine'


def _resource_root() -> str:
    return getattr(sys, '_MEIPASS', None) or os.path.dirname(os.path.abspath(__file__))


def _resource_path(*parts) -> str:
    return os.path.join(_resource_root(), *parts)


AAS_DIR_DEFAULT = _resource_path('aas_data')
CKPT_DEFAULT    = _resource_path('agent_mod.pt')

ALLOWED_OVERRIDES = {'ReplenishLeadDay', 'IdleWorkerThreshold',
                     'WorkStartTime', 'WorkEndTime', 'BreakStart', 'BreakDuration',
                     'DefaultProcessConsumedPowerKw', 'initial_state',
                     'ScenarioMode', 'MaxEpisodeSec', 'InfiniteStock'}


# ==================================================================================
# 공용 엔진 — 모든 시나리오 공통. AAS·정책 1회 로드 후 PO/수치만 바꿔 시뮬을 구동한다.
# 시나리오 구역(아래 4개)은 이 엔진을 호출만 하며, 시나리오별 로직/출력만 담는다.
# ==================================================================================
def _schedule_env_cls():
    import simulation as sim
    import export

    class _ScheduleEnv(sim.CproSimEnv):
        def reset(self):
            super().reset()
            self.events = []
            self.smt_events = []
            self.smt_op_time = {}
            self._unit_seq  = {}   # id(done_set) -> 결정적 순번
            self._unit_keep = []   # done_set 참조 보관 — GC 후 id 재사용 방지
            initial_stock = getattr(self, '_init_stock', None)
            if initial_stock:
                for category, value in initial_stock.items():
                    if category in self.warehouse.inventory:
                        for item in self.warehouse.inventory[category].values():
                            item.present_stock = float(value)
            self.warehouse = export.RecordingWarehouse(self.warehouse, lambda: self.env.now)

        def _unit_id(self, done_set):
            """유닛의 결정적 식별자. done_set 객체가 유닛의 정체이나 id()는 메모리 주소라
            실행마다 달라짐 → 최초 등장 순서로 순번을 부여(같은 시드면 순서도 동일)."""
            key = id(done_set)
            seq = self._unit_seq.get(key)
            if seq is None:
                seq = len(self._unit_seq)
                self._unit_seq[key] = seq
                self._unit_keep.append(done_set)
            return seq

        def _run_job(self, ws, job, req):
            start_sec = self.env.now
            node = self.KnowledgeGraph.nodes[job['pc']]
            unit_id = self._unit_id(job['done_set'])
            yield from super()._run_job(ws, job, req)
            self.events.append({'workstation'  : ws,
                                'model'        : node.model_id,
                                'process_code' : job['pc'],
                                'start_sec'    : float(start_sec),
                                'end_sec'      : float(start_sec + node.CycleTimeSec),
                                'unit_id'      : unit_id})

        def smt_record(self, line_id, equipment, code, t_end, array_cycle, array_energy):
            cursor = float(t_end) - float(array_cycle)
            line_op = self.smt_op_time.setdefault(line_id, {})
            for name, cycle, power in equipment:
                start, end = cursor, cursor + cycle
                line_op[name] = line_op.get(name, 0.0) + float(cycle)
                self.smt_events.append({'equipment': name, 'line': line_id, 'pcb_code': code,
                                        'start_sec': start, 'end_sec': end,
                                        'power_kw': float(power),
                                        'energy_kwh': float(power) * float(cycle) / 3600.0})
                cursor = end

    return _ScheduleEnv


class TrainedModel:

    def __init__(self, checkpoint: str, aas_dir: str = None):
        import build
        from path_extractor import ProvisionofSimulationModelsAAS as _PSM
        self.aas_dir = aas_dir or AAS_DIR_DEFAULT
        if not _PSM.submodels:
            build.load_aas(self.aas_dir, files=build.TRAINING_AAS_FILES)
        self._build       = build
        self._schedule_env = _schedule_env_cls()
        base_env          = build.build_simulation()
        self.default_target = dict(base_env.target_qty)
        self.model_set      = set(base_env.target_qty)
        self.agent          = build.build_agent(base_env, checkpoint=checkpoint)
        self._orig_workers  = {ws: (info['worker_count'], info.get('UnitsPerWorker', 1))
                               for ws, info in base_env.workers.items()}

    def _restore_workers(self):
        workers = self._build.build_simulation().workers
        for ws, (worker_count, units_per_worker) in self._orig_workers.items():
            workers[ws]['worker_count']   = worker_count
            workers[ws]['UnitsPerWorker'] = units_per_worker

    def _resolve_po(self, po: dict):
        target_qty = dict(self.default_target)
        due_day    = {}
        if po:
            unknown = set(po) - self.model_set
            if unknown:
                raise ValueError(
                    f"po references unknown models {sorted(unknown)}; trained model set is "
                    f"{sorted(self.model_set)}. StateDim 고정 — 모델 추가/삭제는 재학습 필요.")
            for model_id, spec in po.items():
                if 'qty' in spec:
                    target_qty[model_id] = int(spec['qty'])
                if 'due_day' in spec:
                    due_day[model_id] = int(spec['due_day'])
        return target_qty, due_day

    def _apply_overrides(self, env, overrides: dict):
        unknown = set(overrides) - ALLOWED_OVERRIDES
        if unknown:
            raise ValueError(f"unknown override keys {sorted(unknown)}; allowed: {sorted(ALLOWED_OVERRIDES)}")
        if 'ReplenishLeadDay' in overrides:
            env.ReplenishLeadDay    = int(overrides['ReplenishLeadDay']) * 86400
        if 'IdleWorkerThreshold' in overrides:
            env.IdleWorkerThreshold = int(overrides['IdleWorkerThreshold'])
        if 'WorkStartTime' in overrides:
            env.WorkStartTime = float(overrides['WorkStartTime']) * 3600
        if 'WorkEndTime' in overrides:
            env.WorkEndTime   = float(overrides['WorkEndTime']) * 3600
        if 'BreakStart' in overrides or 'BreakDuration' in overrides:
            break_start = (float(overrides['BreakStart']) * 3600 if 'BreakStart' in overrides
                           else env.break_start_sec)
            duration    = (float(overrides['BreakDuration']) * 60 if 'BreakDuration' in overrides
                           else env.break_end_sec - env.break_start_sec)
            env.break_start_sec = break_start
            env.break_end_sec   = break_start + duration
        if 'DefaultProcessConsumedPowerKw' in overrides:
            env.DefaultProcessConsumedPowerKw = float(overrides['DefaultProcessConsumedPowerKw'])
        if 'initial_state' in overrides:
            initial_state = overrides['initial_state'] or {}
            env._init_stock = dict(initial_state.get('initial_stock') or {})
        if 'ScenarioMode' in overrides:
            mode = str(overrides['ScenarioMode']).upper()
            if mode not in ('FINITE', 'STEADY'):
                raise ValueError(f"ScenarioMode must be FINITE|STEADY, got {overrides['ScenarioMode']!r}")
            env.ScenarioMode = mode
        if 'MaxEpisodeSec' in overrides:
            env.MaxEpisodeSec = int(overrides['MaxEpisodeSec'])
        if 'InfiniteStock' in overrides:
            env.InfiniteStock = bool(overrides['InfiniteStock'])

    def simulate(self, *, target_qty, due_day, overrides, seed,
                 env_wrap=None, aging_units_per_worker=None):
        import torch
        random.seed(seed)
        torch.manual_seed(seed)
        self._restore_workers()

        env_cls = self._schedule_env
        if env_wrap is not None:
            env_cls = env_wrap(env_cls)
        env = self._build.build_simulation(
            env_cls    = env_cls,
            target_qty = target_qty,
            due_day    = due_day or None,
            MaxEpisodes= 1,
        )
        if aging_units_per_worker is not None:
            env.workers[AGING_WORKSTATION]['UnitsPerWorker'] = int(aging_units_per_worker)
        self._apply_overrides(env, dict(overrides or {}))
        summary = env.run(agent=self.agent)
        return env, summary

    def full_result(self, env, summary, seed: int) -> dict:
        import carbon, export
        target       = dict(env.target_qty)
        throughput   = dict(env.Throughput)
        total_target = sum(target.values()) or 1
        energy_kwh   = summary['EpisodeEnergyKwh']
        kpi = {
            'makespan_sec'     : summary['makespan_sec'],
            'makespan_days'    : summary['makespan_sec'] / 86400.0,
            'target_qty'       : target,
            'throughput'       : throughput,
            'throughput_ratio' : sum(throughput.values()) / total_target,
            'target_met'       : bool(all(throughput[m] >= target[m] for m in target)),
            'energy_kwh'       : energy_kwh,
            'active_premium_kwh': summary['ActivePremiumKwh'],
            'carbon_kgco2e'    : carbon.TotalEmission(energy_kwh),
            'due_day'          : {m: env.DueDay[m] / 86400.0 for m in target},
            'due_pace_deficit' : env.DuePaceDeficit,
            'violations'       : {
                'stock_shortage': env.StockShortageCount,
                'stock_overflow': env.StockOverflowCount,
                'idle_violation': env.IdleViolationCount,
            },
            'seed'             : seed,
        }
        payload = export.build_payload(env, summary)
        productivity, carbon_section = payload['productivity'], payload['carbon']
        kpi['actual_due_day'] = productivity['kpi'].get('actual_due_day')
        kpi['idle_power_kwh'] = carbon_section['kpi'].get('idle_power_kwh')
        productivity.pop('kpi', None)
        carbon_section.pop('kpi', None)
        return {'kpi': kpi, 'schedule': env.events,
                'productivity': productivity, 'carbon': carbon_section,
                'meta': payload['meta']}

    @staticmethod
    def point_kpi(env, summary) -> dict:
        target     = dict(env.target_qty)
        throughput = dict(env.Throughput)
        total_power_kwh     = float(summary['EpisodeEnergyKwh'])
        idle_power_kwh      = float(summary['IdleEnergyKwh'])
        assembly_active_kwh = float(summary['ActivePremiumKwh'])
        smt_power_kwh       = float(summary['SMTEnergyKwh'])
        return {
            'target_qty'    : target,
            'total_qty'     : sum(target.values()),
            'throughput'    : throughput,
            'target_met'    : bool(all(throughput[m] >= target[m] for m in target)),
            'makespan_sec'  : summary['makespan_sec'],
            'makespan_days' : summary['makespan_sec'] / 86400.0,
            'total_power_kwh': total_power_kwh,
            'process_work_time_sec': _process_work_time(env),
            'energy_breakdown'     : {
                'total_power_kwh'    : total_power_kwh,
                'idle_power_kwh'     : idle_power_kwh,
                'assembly_active_kwh': assembly_active_kwh,
                'smt_power_kwh'      : smt_power_kwh,
                'line_power_kwh'     : {k: float(v) for k, v in summary.get('LineEnergy', {}).items()},
                'makespan_sec'       : summary['makespan_sec'],
            },
        }

def artifacts(env, summary, sample_sec: int = None) -> dict:
    import export
    payload = export.build_payload(env, summary,
                                   **({'sample_sec': int(sample_sec)} if sample_sec else {}))
    prod, carb, meta = payload['productivity'], payload['carbon'], payload['meta']

    target     = dict(env.target_qty)
    throughput = dict(env.Throughput)
    metric = {
        'makespan_sec'   : summary['makespan_sec'],
        'makespan_days'  : summary['makespan_sec'] / 86400.0,
        'order_quantity' : target,
        'total_qty'      : sum(target.values()),
        'throughput'     : throughput,
        'target_met'     : bool(all(throughput[m] >= target[m] for m in target)),
        'due_day'        : prod['kpi'].get('due_day'),
        'actual_due_day' : prod['kpi'].get('actual_due_day'),
        'due_improvement': _due_improvement(env, summary),
        'power_kwh'      : {'total'          : float(summary['EpisodeEnergyKwh']),
                            'idle'           : float(summary['IdleEnergyKwh']),
                            'assembly_active': float(summary['ActivePremiumKwh']),
                            'smt'            : float(summary['SMTEnergyKwh'])},
        'carbon_kgco2e'  : carb['kpi'].get('total_carbon_kgco2e'),
        'scenario_mode'  : meta.get('scenario_mode'),
    }
    history = {
        'process'  : prod['events']['schedule'],
        'equipment': prod['events']['equipment'],
        'warehouse': prod['events']['warehouse'],
    }
    timeseries = {
        'sample_sec': prod['timeseries']['sample_sec'],
        't_sec'     : prod['timeseries']['t_sec'],
        'features'  : {
            'work_elapsed_h'                : prod['timeseries']['work_elapsed_h'],
            'cumulative_completed'          : prod['timeseries']['cumulative_completed'],
            'cumulative_completed_by_model' : prod['timeseries']['cumulative_completed_by_model'],
            'completion_ratio'              : prod['timeseries']['completion_ratio'],
            'wip'                           : prod['timeseries']['wip'],
            'wip_by_model'                  : prod['timeseries']['wip_by_model'],
            'active_workers'                : prod['timeseries']['active_workers'],
            'line_active_workers'           : prod['timeseries']['line_active_workers'],
            'line_worker_idle_h'            : prod['timeseries']['line_worker_idle_h'],
            'line_occupancy'                : prod['timeseries']['line_occupancy'],
            'instant_power_kw'              : carb['timeseries']['instant_power_kw'],
            'instant_power_base_kw'         : carb['timeseries']['instant_power_base_kw'],
            'instant_power_assembly_kw'     : carb['timeseries']['instant_power_assembly_kw'],
            'instant_power_smt_kw'          : carb['timeseries']['instant_power_smt_kw'],
            'energy_kwh_by_source'          : carb['timeseries']['energy_kwh_by_source'],
            'smt_equipment_kwh'             : carb['timeseries']['smt_equipment_kwh'],
            'cumulative_energy_kwh'         : carb['timeseries']['cumulative_energy_kwh'],
        },
    }
    per_kind_summary = {
        'process'     : _process_work_time(env),
        'process_slot': _process_slot_work_time(env),
        'line'        : {
            'power_kwh'    : {k: float(v) for k, v in summary.get('LineEnergy', {}).items()},
            'idle_time_sec': {k: float(v) for k, v in summary.get('LineIdleTime', {}).items()},
        },
        'equipment'   : prod['by_entity']['equipment'],
        'worker'      : prod['by_entity']['workers'],
        'item'        : prod['by_entity']['warehouse_by_item'],
    }
    return {'metric': metric, 'history': history,
            'timeseries': timeseries, 'summary': per_kind_summary}


# ---------- 시나리오 공용 산출 헬퍼 ----------
def _process_work_time(env):
    work_time = {}
    for event in getattr(env, 'events', []):
        process_code = event['process_code']
        work_time[process_code] = work_time.get(process_code, 0.0) + (event['end_sec'] - event['start_sec'])
    return work_time


def _process_slot_work_time(env):
    by_process = {}
    for event in getattr(env, 'events', []):
        by_process.setdefault(event['process_code'], []).append((event['start_sec'], event['end_sec']))
    slot_work_time = {}
    for process_code, intervals in by_process.items():
        intervals.sort()
        slot_free, slot_busy = [], []
        for start, end in intervals:
            placed = False
            for i in range(len(slot_free)):
                if slot_free[i] <= start + 1e-9:
                    slot_free[i] = end
                    slot_busy[i] += end - start
                    placed = True
                    break
            if not placed:
                slot_free.append(end)
                slot_busy.append(end - start)
        slot_work_time[process_code] = [round(x, 1) for x in slot_busy]
    return slot_work_time


def _due_improvement(env, summary):
    per_model = {}
    for m in env.target_qty:
        due_day       = env.DueDay[m]
        completed_sec = summary.get('CompletionSec', {}).get(m)
        per_model[m] = ((due_day - completed_sec) / due_day) if (completed_sec is not None and due_day) else None
    values = [v for v in per_model.values() if v is not None]
    overall = min(values) if (values and len(values) == len(per_model)) else None
    return {'per_model': per_model, 'overall': overall}


def _pareto_min(points, keys, eps=1e-6):
    front = []
    for p in points:
        dominated = any(q is not p
                        and all(q[k] <= p[k] + eps for k in keys)
                        and any(q[k] <  p[k] - eps for k in keys)
                        for q in points)
        if not dominated:
            front.append(p)
    return front


def _percent(x):
    return 'n/a' if x is None else f'{x * 100:.1f}%'


# ==================================================================================
# 시나리오 1 · 무한생산 (infinite)
#   입력  {"points": [ {"MODEL_A": {"qty": N}, ... }, ... ], "overrides": {...}}
#   가동  각 생산 수량을 학습정책으로 완주 → 전력량 곡선(탄소 산정용 kWh 분해는 energy_breakdown).
#   출력  생산량↑ 시 전력량 증가분(energy_increase_per_added_unit, 평균기울기) 최소 지점을 최적해로.
# ==================================================================================
def scenario_infinite(model: TrainedModel, scenario_input: dict, seed: int):
    overrides = dict(scenario_input.get('overrides') or {})
    seed      = int(overrides.pop('seed', seed))
    points    = scenario_input.get('points')
    if not points:
        raise ValueError("infinite 시나리오는 points(생산 수량 후보 리스트)가 필요합니다.")

    curve = []
    for po in points:
        target_qty, due_day = model._resolve_po(po)
        env, summary = model.simulate(target_qty=target_qty, due_day=due_day,
                                      overrides=overrides, seed=seed)
        point = model.point_kpi(env, summary)
        point['energy_per_unit'] = point['total_power_kwh'] / max(1, point['total_qty'])
        curve.append(point)

    curve.sort(key=lambda p: p['total_qty'])
    baseline = curve[0]
    for i, point in enumerate(curve):
        if i == 0:
            point['energy_increase_per_added_unit'] = None
        else:
            qty_increase    = point['total_qty'] - baseline['total_qty']
            energy_increase = point['total_power_kwh'] - baseline['total_power_kwh']
            point['energy_increase_per_added_unit'] = (energy_increase / qty_increase) if qty_increase else None

    scored  = [p for p in curve if p.get('energy_increase_per_added_unit') is not None]
    optimum = min(scored, key=lambda p: p['energy_increase_per_added_unit']) if scored else curve[0]
    # MCF 모듈에 보낼 데이터: [데이터] 수량별 총전력·생산량·총시간  |  [요구사항] MCF 저감효과
    mcf_payload = {
        'data': [{'production_qty': p['total_qty'],
                  'total_power_kwh': p['total_power_kwh'],
                  'total_time_sec': p['makespan_sec']} for p in curve],
        'request': '수량별 단위 생산당 탄소를 산정해 단위당 탄소가 최소인 생산량 도출',
    }
    result  = {'scenario': 'infinite', 'seed': seed,
               'objective': '생산량 증가 시 전력량 증가분(energy_increase_per_added_unit, kWh/unit 평균기울기) 최소',
               'curve': curve, 'optimum': optimum, 'mcf_payload': mcf_payload}
    summary_line = (f"[infinite] points={len(curve)} optimum total_qty={optimum['total_qty']} "
                    f"energy_increase/added_unit={optimum.get('energy_increase_per_added_unit')}")
    return result, summary_line


# ==================================================================================
# 시나리오 2 · 생산계획(고정수량 공정 스케줄링) (schedule)
#   입력  {"po": {"MODEL_A": {"qty": 6, "due_day": 22}, ...}, "overrides": {...}}
#   가동  고정 수량을 학습정책으로 완주.
#   출력  최적해 정의 = 입력 납기 대비 개선율(due_improvement).
#         + 공정코드별 총 작업시간 + 워커 스케줄 + 탄소 산정용 kWh 분해(energy_breakdown).
# ==================================================================================
def scenario_schedule(model: TrainedModel, scenario_input: dict, seed: int):
    overrides = dict(scenario_input.get('overrides') or {})
    seed      = int(overrides.pop('seed', seed))
    target_qty, due_day = model._resolve_po(scenario_input.get('po'))
    env, summary = model.simulate(target_qty=target_qty, due_day=due_day,
                                  overrides=overrides, seed=seed)
    result = model.full_result(env, summary, seed)
    result['energy_breakdown']            = model.point_kpi(env, summary)['energy_breakdown']
    result['due_improvement']      = _due_improvement(env, summary)
    result['process_work_time_sec'] = _process_work_time(env)
    # MCF 모듈에 보낼 데이터: [데이터] 공정·슬롯별 작업시간·생산량·총시간  |  [요구사항] MCF 저감효과
    result['mcf_payload'] = {
        'data': {
            'production_qty': sum(env.target_qty.values()),
            'total_time_sec': summary['makespan_sec'],
            'process_slot_work_time_sec': _process_slot_work_time(env),
        },
        'request': '납기 대비 시간 절약(입력 납기 − 실제 완료)에 의한 탄소 배출 저감량 산정',
    }
    kpi = result['kpi']
    summary_line = (f"[schedule] makespan={kpi['makespan_days']:.2f}d "
                    f"due_impr={_percent(result['due_improvement']['overall'])} target_met={kpi['target_met']} "
                    f"total_power_kwh={result['energy_breakdown']['total_power_kwh']:.1f} "
                    f"schedule_events={len(result['schedule'])}")
    return result, summary_line


# ==================================================================================
# 시나리오 2-1 · 생산계획 + SEMI 재배치 (realloc)
#   시나리오 2와 동일 세팅에서 재배치만 추가.
#   입력  {"po": {...},
#          "realloc": {"src": "WWM_SemiAssemblyLine",
#                      "moves": {"WWM_SetAssemblyLine": 2}, "idle_trigger_sec": 600},
#          "overrides": {...}}
#   가동  SEMI가 idle_trigger_sec 연속 완전유휴이면 고정 이동안을 1회 적용(전용 래퍼).
#   출력  최적해 정의 2개 = ⑴ 입력 납기 대비 개선율, ⑵ 재배치 개선율(2번 makespan 대비).
# ==================================================================================
def _realloc_env_wrap(base_cls, realloc: dict):
    src     = realloc.get('src', SEMI_WORKSTATION)
    moves   = dict(realloc.get('moves', {}))
    trigger = float(realloc.get('idle_trigger_sec', 600))
    tick    = float(realloc.get('tick_sec', 30))

    class _ReallocEnv(base_cls):
        def reset(self):
            super().reset()
            self.realloc_fired_sec = None
            self._realloc_done     = False
            self._realloc_src_jobs = 0
            self.env.process(self._realloc_monitor())

        def _run_job(self, ws, job, req):
            yield from super()._run_job(ws, job, req)
            if ws == src:
                self._realloc_src_jobs += 1

        def _realloc_monitor(self):
            idle_accumulated = 0.0
            while not self._realloc_done:
                yield self.env.timeout(tick)
                if not self._is_work_time():
                    continue
                fully_idle = (self._realloc_src_jobs > 0
                              and self.in_progress.get(src, 0) == 0
                              and not self._pending[src])
                idle_accumulated = idle_accumulated + tick if fully_idle else 0.0
                if idle_accumulated >= trigger:
                    self._apply_realloc()

        def _apply_realloc(self):
            now = self.env.now
            for ws in [src, *moves]:
                self._flush_idle(ws, now)
            for ws, count in moves.items():
                self.workers[ws]['worker_count'] += count
                resource = self.worker_resources[ws]
                resource._capacity += count * self.workers[ws].get('UnitsPerWorker', 1)
                resource._trigger_put(None)
                self._wake_dispatcher(ws)
            moved = sum(moves.values())
            self.workers[src]['worker_count'] -= moved
            self.worker_resources[src]._capacity -= moved * self.workers[src].get('UnitsPerWorker', 1)
            self._realloc_done     = True
            self.realloc_fired_sec = now

    return _ReallocEnv


def scenario_realloc(model: TrainedModel, scenario_input: dict, seed: int):
    overrides = dict(scenario_input.get('overrides') or {})
    seed      = int(overrides.pop('seed', seed))
    realloc   = scenario_input.get('realloc')
    if not realloc or not realloc.get('moves'):
        raise ValueError("2-1(재배치) 시나리오는 realloc.moves(고정 이동안)가 필요합니다.")
    target_qty, due_day = model._resolve_po(scenario_input.get('po'))

    # 시나리오 2 기준선(재배치 없음) — 재배치 개선율의 분모
    baseline_env, baseline_summary = model.simulate(target_qty=target_qty, due_day=due_day,
                                                    overrides=overrides, seed=seed)
    baseline = model.point_kpi(baseline_env, baseline_summary)
    baseline['due_improvement'] = _due_improvement(baseline_env, baseline_summary)

    # 재배치 적용 run
    realloc_env, realloc_summary = model.simulate(
        target_qty=target_qty, due_day=due_day, overrides=overrides, seed=seed,
        env_wrap=lambda cls: _realloc_env_wrap(cls, realloc))
    realloc_kpi = model.point_kpi(realloc_env, realloc_summary)
    realloc_kpi['due_improvement']   = _due_improvement(realloc_env, realloc_summary)
    realloc_kpi['realloc_fired_sec'] = getattr(realloc_env, 'realloc_fired_sec', None)
    realloc_kpi['workers_final']     = {ws: info['worker_count'] for ws, info in realloc_env.workers.items()}

    base_makespan = baseline['makespan_sec']
    realloc_improvement = ((base_makespan - realloc_kpi['makespan_sec']) / base_makespan) if base_makespan else None
    optimum = {
        'due_improvement'    : realloc_kpi['due_improvement']['overall'],   # ⑴ 입력 납기 대비 개선율(재배치 run)
        'realloc_improvement': realloc_improvement,                         # ⑵ 재배치 개선율(2번 makespan 대비)
    }
    # MCF 모듈에 보낼 데이터: [데이터] 재배치 정보 + 공정·슬롯별 작업시간(고정배치/재배치)  |  [요구사항] MCF 저감효과 2종
    mcf_payload = {
        'data': {
            'production_qty': realloc_kpi['total_qty'],
            'fixed': {  # 고정배치(재배치 없음)
                'total_time_sec': baseline['makespan_sec'],
                'process_slot_work_time_sec': _process_slot_work_time(baseline_env),
            },
            'realloc': {  # 재배치 적용
                'total_time_sec': realloc_kpi['makespan_sec'],
                'realloc_info': realloc_kpi['workers_final'],
                'realloc_fired_sec': realloc_kpi['realloc_fired_sec'],
                'process_slot_work_time_sec': _process_slot_work_time(realloc_env),
            },
        },
        'request': '⑴ 납기 대비 + ⑵ 고정배치 대비 시간 절약에 의한 탄소 배출 저감량(2종) 산정',
    }
    result = {'scenario': 'realloc(2-1)', 'seed': seed,
              'objective': '⑴ 입력 납기 대비 개선율 + ⑵ 재배치 개선율(2번 makespan 대비)',
              'optimum': optimum,
              'realloc': {'config': realloc, **realloc_kpi},
              'baseline': baseline,
              'schedule': realloc_env.events,
              'mcf_payload': mcf_payload}
    summary_line = (f"[realloc/2-1] due_impr={_percent(optimum['due_improvement'])} "
                    f"realloc_impr={_percent(realloc_improvement)} fired={realloc_kpi['realloc_fired_sec']}")
    return result, summary_line


# ==================================================================================
# 시나리오 4 · 핵심공정(에이징) 설비수량 최적화 (aging)
#   입력  {"po": {...},
#          "points": [ {"poe_switches": 6, "units_per_switch": 8,
#                        "units_per_worker": 45, "worker_count": 6}, ... ],
#          "overrides": {...}}
#   가동  각 후보의 동시 가동수 = min(PoE스위치×스위치당, 작업자수×작업자당)로 에이징 슬롯을 바꿔 완주.
#         (PoE/작업자 분해는 현재 표현만 — 물리 모델은 단일 슬롯 손잡이로 적용.)
#   출력  생산시간–전력 trade-off 파레토(완주 가능 중 비지배해) + 에이징 유닛별 진행 이벤트.
# ==================================================================================
def scenario_aging(model: TrainedModel, scenario_input: dict, seed: int):
    overrides = dict(scenario_input.get('overrides') or {})
    seed      = int(overrides.pop('seed', seed))
    points    = scenario_input.get('points')
    if not points:
        raise ValueError("핵심공정 시나리오는 points(PoE/작업자 설비 후보 리스트)가 필요합니다.")
    target_qty, due_day = model._resolve_po(scenario_input.get('po'))
    aging_worker_count = model._orig_workers[AGING_WORKSTATION][0]

    curve = []
    for spec in points:
        poe_switches     = int(spec.get('poe_switches', 0))
        units_per_switch = int(spec.get('units_per_switch', 0))
        units_per_worker = int(spec.get('units_per_worker', 0))
        worker_count     = int(spec.get('worker_count', aging_worker_count))
        equipment_slots  = poe_switches * units_per_switch
        labor_slots      = worker_count * units_per_worker
        candidates = [x for x in (equipment_slots, labor_slots) if x > 0]
        concurrent_aging_slots = min(candidates) if candidates else aging_worker_count
        aging_units_per_worker = max(1, round(concurrent_aging_slots / aging_worker_count))

        env, summary = model.simulate(target_qty=target_qty, due_day=due_day,
                                      overrides=overrides, seed=seed,
                                      aging_units_per_worker=aging_units_per_worker)
        point = model.point_kpi(env, summary)
        point['poe_switches']           = poe_switches
        point['units_per_switch']       = units_per_switch
        point['units_per_worker']       = units_per_worker
        point['equipment_slots']        = equipment_slots
        point['labor_slots']            = labor_slots
        point['concurrent_aging_slots'] = concurrent_aging_slots
        aging_events = [{'unit_id': event['unit_id'], 'process_code': event['process_code'],
                         'start_sec': event['start_sec'], 'end_sec': event['end_sec']}
                        for event in env.events if event['workstation'] == AGING_WORKSTATION]
        point['aging_event_count'] = len(aging_events)
        point['_evt'] = aging_events
        curve.append(point)

    curve.sort(key=lambda p: p['concurrent_aging_slots'])
    target_met_points = [p for p in curve if p['target_met']]
    pool     = target_met_points or curve
    pareto   = _pareto_min(pool, ['makespan_sec', 'total_power_kwh'])
    pareto.sort(key=lambda p: p['makespan_sec'])
    # MCF 모듈에 보낼 데이터: [데이터] 설비변수 + 에이징 타임라인(파레토 안들)  |  [요구사항] MCF 최소배출 구성
    mcf_payload = {
        'data': [{'poe_switches': p['poe_switches'],
                  'units_per_switch': p['units_per_switch'],
                  'units_per_worker': p['units_per_worker'],
                  'concurrent_aging_slots': p['concurrent_aging_slots'],
                  'production_qty': p['total_qty'],
                  'total_time_sec': p['makespan_sec'],
                  'total_power_kwh': p['total_power_kwh'],
                  'aging_timeline': p['_evt']} for p in pareto],
        'request': '설비구성별 탄소를 산정해 생산시간–탄소 파레토 위 최소 배출 구성 도출',
    }
    for p in curve:
        p.pop('_evt', None)
    result = {'scenario': 'core_equipment', 'seed': seed,
              'objective': '생산시간–전력 trade-off 파레토(완주 가능 중 비지배해)',
              'aging_worker_count': aging_worker_count,
              'curve': curve, 'pareto': pareto, 'mcf_payload': mcf_payload}
    summary_line = (f"[core_equipment] points={len(curve)} target_met={len(target_met_points)} "
                    f"pareto={len(pareto)}")
    return result, summary_line


# ==================================================================================
# 진입점 — 시나리오 선택 후 입력 JSON을 읽어 해당 구역을 가동, 결과 JSON을 쓴다.
# ==================================================================================
SCENARIOS = {
    'infinite': scenario_infinite,
    'schedule': scenario_schedule,
    'realloc' : scenario_realloc,
    'aging'   : scenario_aging,
}


def main(argv=None):
    parser = argparse.ArgumentParser(description='학습된 CPRO 정책으로 시나리오별 결과/최적해를 추론')
    parser.add_argument('--in',  dest='in_path',  required=True)
    parser.add_argument('--out', dest='out_path', required=True)
    parser.add_argument('--ckpt',    dest='ckpt',    default=CKPT_DEFAULT)
    parser.add_argument('--aas-dir', dest='aas_dir', default=AAS_DIR_DEFAULT)
    parser.add_argument('--seed',    type=int,       default=42)
    args = parser.parse_args(argv)

    with open(args.in_path, encoding='utf-8') as f:
        scenario_input = json.load(f)

    scenario = scenario_input.get('scenario')
    if scenario not in SCENARIOS:
        raise SystemExit(f"입력 JSON의 'scenario'는 {sorted(SCENARIOS)} 중 하나여야 합니다: {scenario!r}")

    model = TrainedModel(checkpoint=args.ckpt, aas_dir=args.aas_dir)
    result, summary_line = SCENARIOS[scenario](model, scenario_input, args.seed)

    out_dir = os.path.dirname(os.path.abspath(args.out_path))
    os.makedirs(out_dir, exist_ok=True)
    with open(args.out_path, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f"{summary_line} -> {args.out_path}")


if __name__ == '__main__':
    main()
