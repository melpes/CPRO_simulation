# -*- coding: utf-8 -*-
"""추론 진입점 — 학습된 정책(.pt)을 시뮬레이터에 실행해 KPI + 워커 스케줄을 낸다.

"모델" = .pt(가중치) + 시뮬레이터 엔진 + AAS(구조). 정책은 경합점(워커가 비고 후보공정 ≥2)에서
"어느 공정 먼저"만 고르고, makespan·throughput·에너지·납기·스케줄 자체는 시뮬레이터가 만든다.

호출:
    python run_trained.py --in scenario.json --out result.json [--ckpt X.pt] [--aas-dir aas_data] [--seed 42]

scenario.json:
    {"po": {"MODEL_A": {"qty": 6, "due_day": 22}, ...},
     "overrides": {"ReplenishLeadDay": 3, "IdleWorkerThreshold": 1800, "seed": 42}}

라이브러리:
    model  = TrainedModel(checkpoint="agent_mod.pt", aas_dir="aas_data")
    result = model.run(po={...}, overrides={...})   # → {"kpi": {...}, "schedule": [...]}

제약: .pt 는 학습된 모델 set(3종) 전용. qty/due 변경 OK, 모델 추가/삭제 시 StateDim 이 바뀌어 재학습 필요.
"""
from __future__ import annotations
import os, sys, json, argparse, random

sys.dont_write_bytecode = True


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


def _schedule_env_cls():
    import simulation as sim
    import export

    class _ScheduleEnv(sim.CproSimEnv):
        """추론 계측 env(배포 전용). 시뮬 본체 무수정: 스케줄 이벤트 기록 + warehouse 기록 프록시
        설치 + SMT 설비 가동 훅. export.build_payload 가 이 기록들로 산출물을 가공한다."""
        def reset(self):
            super().reset()
            self.events = []
            self.smt_events = []
            self.smt_op_time = {}
            init = getattr(self, '_init_stock', None)
            if init:
                for cat, val in init.items():
                    if cat in self.warehouse.inventory:
                        for item in self.warehouse.inventory[cat].values():
                            item.present_stock = float(val)
            self.warehouse = export.RecordingWarehouse(self.warehouse, lambda: self.env.now)

        def _run_job(self, ws, job, req):
            t0   = self.env.now
            node = self.KnowledgeGraph.nodes[job['pc']]
            yield from super()._run_job(ws, job, req)
            self.events.append({'workstation'  : ws,
                                'model'        : node.model_id,
                                'process_code' : job['pc'],
                                'start_sec'    : float(t0),
                                'end_sec'      : float(t0 + node.CycleTimeSec),
                                'unit_id'      : id(job['done_set'])})

        def smt_record(self, line_id, equipment, code, t_end, array_cycle, array_energy):
            """smt.py 훅: 한 array 처리 직후 호출. array 는 설비들을 직렬로 통과(array_cycle=Σcycle)
            → 설비별 [start,end] 구간·가동시간·전력으로 분해."""
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
    """학습된 정책을 1회 로드해두고, PO/수치만 바꿔 반복 실행하는 추론 모델."""

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

    def run(self, po: dict = None, overrides: dict = None, seed: int = 42) -> dict:
        import torch
        import carbon
        overrides = dict(overrides or {})
        seed      = int(overrides.pop('seed', seed))

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

        unknown_ov = set(overrides) - ALLOWED_OVERRIDES
        if unknown_ov:
            raise ValueError(f"unknown override keys {sorted(unknown_ov)}; allowed: {sorted(ALLOWED_OVERRIDES)}")

        random.seed(seed)
        torch.manual_seed(seed)

        env = self._build.build_simulation(
            env_cls    = self._schedule_env,
            target_qty = target_qty,
            due_day    = due_day or None,
            MaxEpisodes= 1,
        )
        if 'ReplenishLeadDay' in overrides:
            env.ReplenishLeadDay   = int(overrides['ReplenishLeadDay']) * 86400
        if 'IdleWorkerThreshold' in overrides:
            env.IdleWorkerThreshold = int(overrides['IdleWorkerThreshold'])
        if 'WorkStartTime' in overrides:
            env.WorkStartTime = float(overrides['WorkStartTime']) * 3600
        if 'WorkEndTime' in overrides:
            env.WorkEndTime   = float(overrides['WorkEndTime']) * 3600
        if 'BreakStart' in overrides or 'BreakDuration' in overrides:
            bs  = (float(overrides['BreakStart']) * 3600 if 'BreakStart' in overrides
                   else env.break_start_sec)
            dur = (float(overrides['BreakDuration']) * 60 if 'BreakDuration' in overrides
                   else env.break_end_sec - env.break_start_sec)
            env.break_start_sec = bs
            env.break_end_sec   = bs + dur
        if 'DefaultProcessConsumedPowerKw' in overrides:
            env.DefaultProcessConsumedPowerKw = float(overrides['DefaultProcessConsumedPowerKw'])
        if 'initial_state' in overrides:
            init = overrides['initial_state'] or {}
            env._init_stock = dict(init.get('initial_stock') or {})
        if 'ScenarioMode' in overrides:
            mode = str(overrides['ScenarioMode']).upper()
            if mode not in ('FINITE', 'STEADY'):
                raise ValueError(f"ScenarioMode must be FINITE|STEADY, got {overrides['ScenarioMode']!r}")
            env.ScenarioMode = mode
        if 'MaxEpisodeSec' in overrides:
            env.MaxEpisodeSec = int(overrides['MaxEpisodeSec'])
        if 'InfiniteStock' in overrides:
            env.InfiniteStock = bool(overrides['InfiniteStock'])

        summary = env.run(agent=self.agent)

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
            'feasibility'      : bool(all(throughput[m] >= target[m] for m in target)),
            'energy_kwh'       : energy_kwh,
            'active_premium_kwh': summary['ActivePremiumKwh'],
            'carbon_kgco2e'    : carbon.total(energy_kwh),
            'due_day'          : {m: env.DueDay[m] / 86400.0 for m in target},
            'due_pace_deficit' : env.DuePaceDeficit,
            'due_pace_by_model': dict(env.DuePaceDeficitByModel),
            'violations'       : {
                'stock_shortage': env.StockShortageCount,
                'stock_overflow': env.StockOverflowCount,
                'idle_violation': env.IdleViolationCount,
            },
            'seed'             : seed,
        }
        import export
        payload = export.build_payload(env, summary)
        prod, carb = payload['productivity'], payload['carbon']
        kpi['actual_due_day'] = prod['kpi'].get('actual_due_day')
        kpi['idle_power_kwh'] = carb['kpi'].get('idle_power_kwh')
        prod.pop('kpi', None)
        carb.pop('kpi', None)
        return {'kpi': kpi, 'schedule': env.events,
                'productivity': prod, 'carbon': carb,
                'meta': payload['meta']}


def main(argv=None):
    p = argparse.ArgumentParser(description='학습된 CPRO 정책으로 PO/수치를 바꿔 KPI+스케줄을 추론')
    p.add_argument('--in',  dest='in_path',  required=True, help='시나리오 JSON ({po?, overrides?})')
    p.add_argument('--out', dest='out_path', required=True, help='결과 JSON ({kpi, schedule})')
    p.add_argument('--ckpt',    dest='ckpt',    default=CKPT_DEFAULT,    help='체크포인트 .pt (동결 번들 기본=동봉)')
    p.add_argument('--aas-dir', dest='aas_dir', default=AAS_DIR_DEFAULT, help='AAS 디렉토리')
    p.add_argument('--seed',    type=int,       default=42)
    a = p.parse_args(argv)

    with open(a.in_path, encoding='utf-8') as f:
        scenario = json.load(f)

    model  = TrainedModel(checkpoint=a.ckpt, aas_dir=a.aas_dir)
    result = model.run(po=scenario.get('po'), overrides=scenario.get('overrides'), seed=a.seed)

    out_dir = os.path.dirname(os.path.abspath(a.out_path))
    os.makedirs(out_dir, exist_ok=True)
    with open(a.out_path, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    kpi = result['kpi']
    print(f"[run_trained] makespan={kpi['makespan_days']:.2f}d "
          f"throughput_ratio={kpi['throughput_ratio']:.3f} feasible={kpi['feasibility']} "
          f"energy={kpi['energy_kwh']:.1f}kWh schedule_events={len(result['schedule'])} → {a.out_path}")


if __name__ == '__main__':
    main()
