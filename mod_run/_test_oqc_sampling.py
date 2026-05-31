# -*- coding: utf-8 -*-
"""OQC SamplingRate 5% 확률 분기 동작 검증.

목표 — 100/100/100 unit 시뮬에서 OQC 실제 거친 unit 수가 통계적으로 5% ± 표준편차
       내인지, PACK 첫 노드의 SEQUENCE any-prev 동작이 막힘 없이 진행되는지 확인.

산출:
- OQC cycle 실제 진입 카운트 (모델별)
- random.seed 고정으로 결정론 재현
- 통계: 5% × 300 = 15 ± √(300*0.05*0.95) ≈ 15 ± 3.8
"""
import os, sys, json, time, random

_DIR  = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_DIR)
sys.path.insert(0, _DIR); sys.path.insert(0, _ROOT)

import path_extractor as pe
import simulation_ver1 as sv

for f in ['ProvisionOfSimulationModel.json', 'WorkstationWorkerMatchingDataAAS.json',
          'MODEL_A.json', 'MODEL_B.json', 'MODEL_C.json']:
    pe.load(os.path.join(_ROOT, 'aas_data', f))

PSM = pe.ProvisionofSimulationModelsAAS
SM  = PSM.SimulationModels.SimulationModel
A   = SM.KnowledgeGraph.Action
DP  = SM.DefaultParameters
RW  = SM.RewardWeights

OUT = os.path.join(_DIR, 'result', 'runs', 'oqc_sampling_test')
os.makedirs(OUT, exist_ok=True)

TARGET = {'MODEL_A': 100, 'MODEL_B': 100, 'MODEL_C': 100}


class RecEnv(sv.CproSimEnv):
    """OQC 진입 / skip 이벤트 기록."""
    def reset(self):
        super().reset()
        self.oqc_cycle_count = {m: 0 for m in self.target_qty}     # OQC 실제 워커 큐 진입
        self.oqc_skip_count  = {m: 0 for m in self.target_qty}     # OQC random skip

    def _run_job(self, ws, job, req):
        pc = job['pc']
        node = self.KnowledgeGraph.nodes[pc]
        # _run_job 진입 = 워커 큐를 거쳐 실제 cycle 시작. OQC 이 여기 들어오면 5% 의 한 unit.
        if pc == 'OQC':
            # OQC 는 model_id='ALL' 이라 어느 unit 의 호출인지는 done_set 으로 추적 불가
            # 대신 done_set 길이 (이전 노드 수) 로 추정 — 간이.
            self.oqc_cycle_count.setdefault('_total', 0)
            self.oqc_cycle_count['_total'] += 1
        yield from super()._run_job(ws, job, req)

    def produce_unit(self, model_id, agent=None):
        # produce_unit 의 fan-out 단계에서 random skip 호출 가로채려고 wrap.
        # 단순: super 그대로 호출. 카운팅은 _run_job 에서.
        yield from super().produce_unit(model_id, agent)


def make_env(seed=42):
    random.seed(seed)
    MPs = {mp.model_id: mp for mp in SM.Warehouse.InputBOM.target}
    shared = {name: g for name, g in SM.KnowledgeGraph.Node.value.items() if name in ('ProcessOQC',)}
    KG  = sv.KnowledgeGraph.build(MPs, PSM.workers, shared)
    WH  = sv.Warehouse.build(PSM.CoManagedBOM, SM.Warehouse.MinStock.target)
    rw  = {k: float(RW[k].value) for k in
           ['W1_TimeElapsed', 'W2_Energy', 'W3_StockOverflow',
            'W4_StockShortage', 'W5_Throughput', 'W6_IdleWorker']}
    return RecEnv(
        KnowledgeGraph=KG, warehouse=WH, workers=PSM.workers,
        IndependentSequence=[n.idShort for r in A.IndependentSequence for n in r.target if n is not None],
        DependentSequence=[n.idShort for r in A.DependentSequence for n in r.target if n is not None],
        DependentJoin=[n.idShort for r in A.DependentJoin for n in r.target if n is not None],
        RewardWeights=rw,
        ReplenishLeadDay=int(DP.ReplenishLeadDay.value) * 3600,
        target_qty=dict(TARGET), MaxEpisodes=1,
        WarehouseManagedBOM=PSM.CoManagedBOM,
        BOMCategory=SM.Warehouse.MinStock.target,
        WorkStartTime=DP.WorkStartTime.target.value,
        WorkEndTime=DP.WorkEndTime.target.value,
        break_start_sec=DP.BreakDurationMin.target.min,
        break_end_sec=DP.BreakDurationMin.target.max,
        IdleWorkerThreshold=int(DP.IdleWorkerThreshold.value),
        RuntimeVariables=SM.RuntimeVariables,
        IdleProcessRatedPowerKw=float(DP.IdleProcessRatedPowerKw.value),
        IdlePowerRatio=0.10,
        SelfManagedBOM=PSM.SelfManagedBOM,
    )


def main():
    seeds = [42, 100, 1000]
    results = []
    for seed in seeds:
        print(f'\n[seed={seed}] greedy sim 시작...', flush=True)
        env = make_env(seed)
        t0 = time.time()
        summary = env.run(agent=None, max_sec=360 * 86400)
        dt = time.time() - t0
        total_unit = sum(TARGET.values())
        oqc_actual = env.oqc_cycle_count.get('_total', 0)
        expected = total_unit * 0.05
        results.append({
            'seed': seed,
            'oqc_actual': oqc_actual,
            'oqc_expected': expected,
            'makespan_h': summary['makespan_sec'] / 3600,
            'throughput': dict(summary['Throughput']),
            'dt_s': dt,
        })
        print(f'[seed={seed}] dt={dt:.1f}s makespan={summary["makespan_sec"]/3600:.1f}h '
              f'thru={summary["Throughput"]} OQC actual={oqc_actual} expected={expected:.1f}',
              flush=True)

    # 통계
    lines = ['# OQC SamplingRate (=0.05) 분기 검증', '']
    lines.append(f'target unit 총합: {sum(TARGET.values())}')
    lines.append(f'기대값: 300 × 0.05 = 15 (Binom σ ≈ 3.8)')
    lines.append('')
    lines.append('| seed | OQC 실제 | 기대 | makespan(h) | throughput |')
    lines.append('|---|---:|---:|---:|---|')
    for r in results:
        lines.append(f'| {r["seed"]} | {r["oqc_actual"]} | {r["oqc_expected"]:.0f} | '
                     f'{r["makespan_h"]:.1f} | {r["throughput"]} |')

    open(os.path.join(OUT, 'result.md'), 'w', encoding='utf-8').write('\n'.join(lines) + '\n')
    print('\n=== 결과 ===')
    print('\n'.join(lines))


if __name__ == '__main__':
    main()
