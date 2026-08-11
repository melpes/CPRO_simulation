# -*- coding: utf-8 -*-
# 시뮬레이션 구동부 — 모든 시나리오 공통.
#   AAS 를 입력 계약으로 삼는다: API 요청값을 AAS 의 해당 위치에 쓰고, 그 AAS 로 시뮬을 빌드·구동한다.
#   시나리오 실행부(scenario.py)는 이 구동부를 호출만 한다.
from __future__ import annotations

import copy
import os
import random
import sys

sys.dont_write_bytecode = True

AGING_WORKSTATION = 'WWM_AgingLine'
SEMI_WORKSTATION  = 'WWM_SemiAssemblyLine'

# SMT 라인을 이루는 설비 — 외부 명세는 이 7개를 'SMT' 하나로 묶어 호출한다.
SMT_EQUIPMENT = ('LoaderProcess', 'ScreenPrinterProcess', 'SPIProcess', 'MounterProcess',
                 'AOIProcess', 'ReflowProcess', 'UnloaderProcess')


def _resource_root() -> str:
    return getattr(sys, '_MEIPASS', None) or os.path.dirname(os.path.abspath(__file__))


AAS_DIR_DEFAULT = os.path.join(_resource_root(), 'aas_data')
CKPT_DEFAULT    = os.path.join(_resource_root(), 'agent_mod.pt')

# AAS 에 직접 반영되는 override (DefaultParameters / SimulationConfig 의 Property)
AAS_OVERRIDES = {
    'ReplenishLeadDay'             : 'DefaultParameters',
    'IdleWorkerThreshold'          : 'DefaultParameters',
    'DefaultProcessConsumedPowerKw': 'DefaultParameters',
    'InfiniteStock'                : 'DefaultParameters',
    'ScenarioMode'                 : 'SimulationConfig',
    'MaxEpisodeSec'                : 'SimulationConfig',
}
# AAS 에 자리가 없어 env 에 직접 반영하는 override
ENV_OVERRIDES = {'WorkStartTime', 'WorkEndTime', 'BreakStart', 'BreakDuration', 'initial_state'}
ALLOWED_OVERRIDES = set(AAS_OVERRIDES) | ENV_OVERRIDES | {'seed'}


# ==================================================================================
# 계측 env — 시뮬 본체 무수정. 공정 이력·SMT 설비 가동·창고 기록을 남긴다.
# ==================================================================================
def _instrumented_env_cls():
    import simulation as sim
    import export

    class _InstrumentedEnv(sim.CproSimEnv):
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
            self.events.append({'workstation' : ws,
                                'model'       : node.model_id,
                                'process_code': job['pc'],
                                'start_sec'   : float(start_sec),
                                'end_sec'     : float(start_sec + node.CycleTimeSec),
                                'unit_id'     : unit_id})

        def smt_record(self, line_id, equipment, code, t_end, array_cycle, array_energy):
            # 설비가 실제로 켜져 있는 시간. smt.py 와 같은 규칙(파이프라인이면 병목 주기로 제한):
            #   첫 어레이(플러시) → array_cycle 이 커서 on_sec = cycle,  이후 → on_sec = base_cycle 로 제한.
            window_start = float(t_end) - float(array_cycle)
            on_secs = [min(float(cycle), float(array_cycle)) for _, cycle, _ in equipment]
            sequential = sum(on_secs) <= float(array_cycle) + 1e-9      # 플러시: 설비가 차례로 가동
            line_op = self.smt_op_time.setdefault(line_id, {})
            cursor = window_start
            for (name, _cycle, power), on_sec in zip(equipment, on_secs):
                if sequential:
                    start, end = cursor, cursor + on_sec
                    cursor = end
                else:
                    start, end = window_start, window_start + on_sec    # 파이프라인: 동시 가동
                line_op[name] = line_op.get(name, 0.0) + on_sec
                self.smt_events.append({'equipment': name, 'line': line_id, 'pcb_code': code,
                                        'start_sec': start, 'end_sec': end,
                                        'power_kw': float(power),
                                        'energy_kwh': float(power) * on_sec / 3600.0})

    return _InstrumentedEnv


# ==================================================================================
# 산출물 헬퍼
# ==================================================================================
def process_work_time(env) -> dict:
    """공정코드별 총 작업시간(초)."""
    total = {}
    for event in getattr(env, 'events', []):
        code = event['process_code']
        total[code] = total.get(code, 0.0) + (event['end_sec'] - event['start_sec'])
    return total


def process_slot_work_time(env) -> dict:
    """공정을 동시 처리 슬롯으로 분해한 작업시간(초). 리스트 길이 = 그 공정의 최대 동시 처리 수."""
    by_code = {}
    for event in getattr(env, 'events', []):
        by_code.setdefault(event['process_code'], []).append((event['start_sec'], event['end_sec']))
    result = {}
    for code, intervals in by_code.items():
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
        result[code] = [round(x, 1) for x in slot_busy]
    return result


def due_improvement(env, summary) -> dict:
    """납기 대비 개선율 = (납기 − 실제 완료) / 납기. 모델별 + 전체(최악 모델)."""
    per_model = {}
    for model_id in env.target_qty:
        due = env.DueDay[model_id]
        completed = summary.get('CompletionSec', {}).get(model_id)
        per_model[model_id] = ((due - completed) / due) if (completed is not None and due) else None
    values = [v for v in per_model.values() if v is not None]
    overall = min(values) if (values and len(values) == len(per_model)) else None
    return {'per_model': per_model, 'overall': overall}


def percent(x) -> str:
    return 'n/a' if x is None else f'{x * 100:.1f}%'


def line_summary(env, summary, productivity) -> dict:
    """라인별 집계 — 순수 작업시간(유휴 제외)·작업자당 평균 유휴시간·전력.
    'ALL' 은 전 라인 합계."""
    by_worker  = productivity['by_entity']['workers']
    line_power = {k: float(v) for k, v in summary.get('LineEnergy', {}).items()}
    smt_kwh    = float(summary.get('SMTEnergyKwh') or 0.0)

    lines = {}
    for ws, info in by_worker.items():
        worker_count = info['worker_count'] or 1
        lines[ws] = {
            'worker_count'            : info['worker_count'],
            'operating_sec'           : info['operating_sec'],          # 순수 작업시간(유휴 제외)
            'operating_ratio'         : info['operating_ratio'],
            'idle_sec'                : info['idle_sec'],               # 작업자·시간 총합 기준 유휴
            'idle_sec_per_worker'     : round(info['idle_sec'] / worker_count, 1),
            'power_kwh'               : round(line_power.get(ws, 0.0), 4),
            'processed_quantity'      : info['processed_quantity'],
        }
    lines['SMT'] = {'power_kwh': round(smt_kwh, 4),
                    'operating_sec': round(sum(
                        sec for line in getattr(env, 'smt_op_time', {}).values()
                        for sec in line.values()), 1)}
    lines['ALL'] = {
        'worker_count' : sum(v.get('worker_count') or 0 for v in by_worker.values()),
        'operating_sec': round(sum(v['operating_sec'] for v in by_worker.values()), 1),
        'idle_sec'     : round(sum(v['idle_sec'] for v in by_worker.values()), 1),
        'power_kwh'    : round(float(summary.get('EpisodeEnergyKwh') or 0.0), 4),
    }
    return lines


def equipment_summary(env, productivity) -> dict:
    """설비별 가동시간 + SMT 7설비 묶음 합계."""
    by_line = productivity['by_entity']['equipment_op_time']
    merged = {}
    for line_ops in by_line.values():
        for name, sec in line_ops.items():
            merged[name] = merged.get(name, 0.0) + float(sec)
    return {
        'by_line'     : by_line,
        'by_equipment': {k: round(v, 1) for k, v in merged.items()},
        'SMT'         : round(sum(merged.get(name, 0.0) for name in SMT_EQUIPMENT), 1),
    }


# ---------- 최적해 후보(candidate) — 데이터 의미 4분류 ----------
#   metric     : 스칼라 집계 (총 생산시간·수량·완주·전력·납기)
#   history    : 공정·설비 수행 이력
#   timeseries : 시간별 추이 (일정 간격)
#   summary    : 항목별 집계 (공정·라인·설비·작업자·품목)
def candidate_artifacts(env, summary) -> dict:
    import export
    payload = export.build_payload(env, summary)
    productivity, carbon_section, meta = payload['productivity'], payload['carbon'], payload['meta']

    target     = dict(env.target_qty)
    throughput = dict(env.Throughput)

    metric = {
        'makespan_sec'   : summary['makespan_sec'],
        'makespan_days'  : summary['makespan_sec'] / 86400.0,
        'order_quantity' : target,
        'total_qty'      : sum(target.values()),
        'throughput'     : throughput,
        'target_met'     : bool(all(throughput[m] >= target[m] for m in target)),
        'due_day'        : productivity['kpi'].get('due_day'),
        'actual_due_day' : productivity['kpi'].get('actual_due_day'),
        'due_improvement': due_improvement(env, summary),
        'power_kwh'      : {'total'          : float(summary['EpisodeEnergyKwh']),
                            'idle'           : float(summary['IdleEnergyKwh']),
                            'assembly_active': float(summary['ActivePremiumKwh']),
                            'smt'            : float(summary['SMTEnergyKwh'])},
        'scenario_mode'  : meta.get('scenario_mode'),
    }
    history = {
        'process'  : productivity['events']['schedule'],
        'equipment': productivity['events']['equipment'],
        'warehouse': productivity['events']['warehouse'],
    }
    timeseries = {
        'sample_sec': productivity['timeseries']['sample_sec'],
        't_sec'     : productivity['timeseries']['t_sec'],
        'features'  : {
            'cumulative_completed' : productivity['timeseries']['cumulative_completed'],
            'completion_ratio'     : productivity['timeseries']['completion_ratio'],
            'wip'                  : productivity['timeseries']['wip'],
            'active_workers'       : productivity['timeseries']['active_workers'],
            'line_active_workers'  : productivity['timeseries']['line_active_workers'],
            'line_idle_sec_per_worker': productivity['timeseries']['line_idle_sec_per_worker'],
            'instant_power_kw'     : carbon_section['timeseries']['instant_power_kw'],
            'cumulative_energy_kwh': carbon_section['timeseries']['cumulative_energy_kwh'],
            'idle_energy_kwh'      : carbon_section['timeseries']['idle_energy_kwh'],
            'smt_energy_kwh'       : carbon_section['timeseries']['smt_energy_kwh'],
            'line_energy_kwh'      : carbon_section['timeseries']['line_energy_kwh'],
        },
    }
    summary_by_entity = {
        'process'     : process_work_time(env),
        'process_slot': process_slot_work_time(env),
        'line'        : line_summary(env, summary, productivity),
        'equipment'   : equipment_summary(env, productivity),
        'worker'      : productivity['by_entity']['workers'],
        'item'        : productivity['by_entity']['warehouse_by_item'],
    }
    return {'metric': metric, 'history': history,
            'timeseries': timeseries, 'summary': summary_by_entity}


def make_candidate(env, summary, candidate_id: int, condition: dict) -> dict:
    """최적해 후보 — 한 조건으로 돌린 시뮬 1회."""
    artifacts = candidate_artifacts(env, summary)
    return {
        'candidate_id': candidate_id,
        'condition'   : condition,
        'flags'       : {'target_met': artifacts['metric']['target_met'], 'is_optimum': False},
        **artifacts,
    }


# ==================================================================================
# 구동부 — AAS 가 입력 계약. 요청값을 AAS 에 쓰고 그 AAS 로 시뮬을 빌드·구동한다.
# ==================================================================================
class TrainedModel:

    def __init__(self, checkpoint: str = None, aas_dir: str = None):
        import build
        from path_extractor import ProvisionofSimulationModelsAAS as PSM
        self.aas_dir = aas_dir or AAS_DIR_DEFAULT
        if not PSM.submodels:
            build.load_aas(self.aas_dir, files=build.TRAINING_AAS_FILES)
        self._build = build
        self._env_cls = _instrumented_env_cls()

        base_env = build.build_simulation()
        self.model_set = set(base_env.target_qty)
        self.default_order_quantity = dict(base_env.target_qty)
        self.agent = build.build_agent(base_env, checkpoint=checkpoint or CKPT_DEFAULT)

        self._aas_defaults = self._snapshot_aas()

    # ---------- AAS 접근 ----------
    @staticmethod
    def _simulation_model():
        from path_extractor import ProvisionofSimulationModelsAAS as PSM
        return PSM.SimulationModels.SimulationModel

    @staticmethod
    def _workstation(ws_id: str):
        from path_extractor import _aas_registry
        return (_aas_registry['AssemblyByWorker']
                .submodels['WorkstationWorkerMatchingData']
                .value['GeneralWorkstationData']
                .value['WorkstationInformation']
                .value[ws_id])

    def _realloc_scope(self):
        action = self._simulation_model().KnowledgeGraph.Action
        worker_realloc = action.value.get('WorkerReallocation')
        return worker_realloc if worker_realloc is not None else None

    def _snapshot_aas(self) -> dict:
        """요청이 덮어쓰는 AAS 값의 원본. 매 실행 전 여기로 되돌려 이전 요청이 새지 않게 한다."""
        sm = self._simulation_model()
        snapshot = {
            'purchase_order': {model_id: (order.value, order.Qualifier['DueDay'])
                               for model_id, order in sm.value['PurchaseOrder'].value.items()},
            'parameters': {},
            'aging': {},
            'realloc': {},
        }
        for key, section in AAS_OVERRIDES.items():
            container = sm.value[section].value
            if key in container:
                snapshot['parameters'][key] = container[key].value

        aging = self._workstation(AGING_WORKSTATION)
        for key in ('SwitchCount', 'PortCount', 'UnitsPerWorker'):
            if key in aging.value:
                snapshot['aging'][key] = aging.value[key].value

        worker_realloc = self._realloc_scope()
        if worker_realloc is not None:
            snapshot['realloc']['IdleThreshold'] = worker_realloc.value['ReallocationIdleThresholdSec'].value
            moves = {}
            for src_id, src_list in worker_realloc.value['ReallocationScope'].value.items():
                for target in src_list:
                    line = self._target_line(target)
                    moves[(src_id, line)] = self._move_count(target).value
            snapshot['realloc']['moves'] = moves
        return copy.deepcopy(snapshot)

    @staticmethod
    def _target_line(target_smc) -> str:
        ref = target_smc.value['TargetLine']
        return ref.value[0].rstrip('/').rsplit('/', 3)[-3]

    @staticmethod
    def _move_count(target_smc):
        return target_smc.value['MoveWorkerCount']

    def reset_aas(self) -> None:
        sm = self._simulation_model()
        defaults = self._aas_defaults

        purchase_order = sm.value['PurchaseOrder'].value
        for model_id, (qty, due_day) in defaults['purchase_order'].items():
            purchase_order[model_id].value = qty
            purchase_order[model_id].Qualifier['DueDay'] = due_day

        for key, value in defaults['parameters'].items():
            sm.value[AAS_OVERRIDES[key]].value[key].value = value

        aging = self._workstation(AGING_WORKSTATION)
        for key, value in defaults['aging'].items():
            aging.value[key].value = value

        worker_realloc = self._realloc_scope()
        if worker_realloc is not None and defaults['realloc']:
            worker_realloc.value['ReallocationIdleThresholdSec'].value = defaults['realloc']['IdleThreshold']
            for src_id, src_list in worker_realloc.value['ReallocationScope'].value.items():
                for target in src_list:
                    line = self._target_line(target)
                    self._move_count(target).value = defaults['realloc']['moves'][(src_id, line)]

    # ---------- 요청 → AAS 반영 ----------
    def apply_purchase_order(self, order: dict) -> None:
        """{'MODEL_A': {'qty':100,'due_day':22}, ...} → AAS SimulationModel.PurchaseOrder"""
        if not order:
            return
        unknown = sorted(set(order) - self.model_set)
        if unknown:
            raise ValueError(f'학습된 모델셋에 없는 모델: {unknown} (가능: {sorted(self.model_set)}). '
                             f'StateDim 고정 — 모델 추가/삭제는 재학습 필요.')
        purchase_order = self._simulation_model().value['PurchaseOrder'].value
        for model_id, spec in order.items():
            if 'qty' in spec:
                purchase_order[model_id].value = int(spec['qty'])
            if 'due_day' in spec:
                purchase_order[model_id].Qualifier['DueDay'] = int(spec['due_day'])

    def apply_overrides(self, overrides: dict) -> dict:
        """AAS 에 자리가 있는 것은 AAS 에 쓰고, 없는 것(근무시간·초기재고)만 돌려준다."""
        overrides = dict(overrides or {})
        overrides.pop('seed', None)
        unknown = sorted(set(overrides) - ALLOWED_OVERRIDES)
        if unknown:
            raise ValueError(f'허용되지 않은 override 키: {unknown} '
                             f'(허용: {sorted(ALLOWED_OVERRIDES)})')
        sm = self._simulation_model()
        for key, section in AAS_OVERRIDES.items():
            if key in overrides:
                sm.value[section].value[key].value = overrides.pop(key)
        return overrides                                  # env 에 직접 반영할 나머지

    def apply_aging_equipment(self, switch_count=None, port_count=None, units_per_worker=None) -> None:
        aging = self._workstation(AGING_WORKSTATION)
        for key, value in (('SwitchCount', switch_count), ('PortCount', port_count),
                           ('UnitsPerWorker', units_per_worker)):
            if value is not None:
                aging.value[key].value = int(value)

    def apply_realloc(self, source: str, moves: dict, idle_trigger_sec=None) -> None:
        """{'WWM_SetAssemblyLine': 2} → AAS ReallocationScope 의 해당 타겟 MoveWorkerCount"""
        worker_realloc = self._realloc_scope()
        if worker_realloc is None:
            raise ValueError('AAS 에 WorkerReallocation 이 없습니다.')
        if idle_trigger_sec is not None:
            worker_realloc.value['ReallocationIdleThresholdSec'].value = int(idle_trigger_sec)

        scope = worker_realloc.value['ReallocationScope'].value
        if source not in scope:
            raise ValueError(f'재배치 소스 라인이 AAS 스코프에 없습니다: {source} (가능: {sorted(scope)})')
        allowed = {self._target_line(t): t for t in scope[source]}
        unknown = sorted(set(moves) - set(allowed))
        if unknown:
            raise ValueError(f'AAS 스코프가 허용하지 않는 타겟: {unknown} (가능: {sorted(allowed)})')
        for line, count in moves.items():
            self._move_count(allowed[line]).value = int(count)

    def realloc_plan(self, source: str) -> dict:
        """AAS 에 현재 설정된 이동안 — 시뮬 래퍼가 이걸 읽어 실행한다."""
        worker_realloc = self._realloc_scope()
        scope = worker_realloc.value['ReallocationScope'].value
        moves = {}
        for target in scope[source]:
            count = int(self._move_count(target).value)
            if count > 0:
                moves[self._target_line(target)] = count
        return {'src': source,
                'moves': moves,
                'idle_trigger_sec': float(worker_realloc.value['ReallocationIdleThresholdSec'].value)}

    def aging_equipment(self) -> dict:
        aging = self._workstation(AGING_WORKSTATION)
        worker_count     = len(aging.WorkstationConfigurationRecords)
        switch_count     = int(aging.value['SwitchCount'].value)
        port_count       = int(aging.value['PortCount'].value)
        units_per_worker = int(aging.value['UnitsPerWorker'].value)
        equipment_slots  = switch_count * port_count
        labor_slots      = worker_count * units_per_worker
        return {'switch_count': switch_count, 'port_count': port_count,
                'units_per_worker': units_per_worker, 'worker_count': worker_count,
                'equipment_slots': equipment_slots, 'labor_slots': labor_slots,
                'concurrent_operation_count': min(equipment_slots, labor_slots)}

    def purchase_order(self) -> dict:
        sm = self._simulation_model()
        return {model_id: {'qty': int(order.value), 'due_day': int(order.Qualifier['DueDay'])}
                for model_id, order in sm.value['PurchaseOrder'].value.items()}

    # ---------- 구동 ----------
    def simulate(self, seed: int, env_overrides: dict = None, env_wrap=None):
        """AAS 에 반영된 값 그대로 시뮬을 빌드·구동한다."""
        import torch
        random.seed(seed)
        torch.manual_seed(seed)
        self.agent.reset_buffer()

        env_cls = self._env_cls if env_wrap is None else env_wrap(self._env_cls)
        env = self._build.build_simulation(env_cls=env_cls, MaxEpisodes=1)

        for key, value in (env_overrides or {}).items():   # AAS 에 자리가 없는 것만
            if key == 'WorkStartTime':
                env.WorkStartTime = float(value) * 3600
            elif key == 'WorkEndTime':
                env.WorkEndTime = float(value) * 3600
            elif key in ('BreakStart', 'BreakDuration'):
                start = (float(env_overrides['BreakStart']) * 3600
                         if 'BreakStart' in env_overrides else env.break_start_sec)
                duration = (float(env_overrides['BreakDuration']) * 60
                            if 'BreakDuration' in env_overrides
                            else env.break_end_sec - env.break_start_sec)
                env.break_start_sec = start
                env.break_end_sec = start + duration
            elif key == 'initial_state':
                env._init_stock = dict((value or {}).get('initial_stock') or {})

        summary = env.run(agent=self.agent)
        return env, summary

    def prepare(self, request: dict) -> dict:
        """모든 시나리오 공통 전처리 — AAS 를 원본으로 되돌리고 요청을 AAS 에 반영."""
        self.reset_aas()
        self.apply_purchase_order(request.get('po'))
        return self.apply_overrides(request.get('overrides'))


# ==================================================================================
# 단독 실행 진입점 — 각 시나리오 실행부가 이걸 __main__ 으로 쓴다.
#   python scenario.py --in scenario.json --out result.json
# ==================================================================================
def cli(module, argv=None) -> None:
    import argparse
    import json

    parser = argparse.ArgumentParser(
        description=f'{module.NAME} 시나리오 — {module.OBJECTIVE}')
    parser.add_argument('--in',  dest='in_path',  required=True, help='입력 JSON')
    parser.add_argument('--out', dest='out_path', required=True, help='결과 JSON')
    parser.add_argument('--ckpt',    default=CKPT_DEFAULT,    help='학습된 정책 .pt')
    parser.add_argument('--aas-dir', dest='aas_dir', default=AAS_DIR_DEFAULT, help='AAS 폴더')
    parser.add_argument('--seed',    type=int, default=42)
    args = parser.parse_args(argv)

    with open(args.in_path, encoding='utf-8') as fp:
        raw = json.load(fp)
    request = module.Request.model_validate(raw).model_dump(exclude_none=True)   # 스키마 검증

    model = TrainedModel(checkpoint=args.ckpt, aas_dir=args.aas_dir)
    result, summary_line = module.run(model, request, args.seed)

    out_dir = os.path.dirname(os.path.abspath(args.out_path))
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    with open(args.out_path, 'w', encoding='utf-8') as fp:
        json.dump(result, fp, ensure_ascii=False, indent=2)

    print(f'{summary_line} -> {args.out_path}')
