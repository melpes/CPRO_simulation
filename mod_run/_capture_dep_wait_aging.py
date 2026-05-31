# -*- coding: utf-8 -*-
"""DepWaitSec AGING 일반화 도입 효과 측정 (BT5_42 본드 24h + VD7_100/BT5_100/NVD_110 AGING 3h).

이전 시점 (dep_wait_05-27) 은 BT5_42 본드 경화 24h 만 DepWaitSec 으로 적용.
본 시점 (dep_wait_aging_05-27) 은 AAS json (VD7_100/BT5_100/NVD_110) 에
`AgingTestDurationSec=10800` (3h) SME 추가 + path_extractor `_positions` 한 줄
확장으로 AGING 도 DepWaitSec 으로 통합 — 시뮬 코드 무변경.

비교:
  baseline (dep_wait_05-27, BT5_42 24h만): greedy 131.35h / trained_det 107.67h
  현재  (dep_wait_aging_05-27, +AGING 3h × 3): ??? / ???

출력: mod_run/result/runs/dep_wait_aging_05-27/
"""
import os, sys, json, time
import torch

_DIR  = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_DIR)
sys.path.insert(0, _DIR); sys.path.insert(0, _ROOT)

import path_extractor as pe
import simulation_ver1 as sv

for _f in ['ProvisionOfSimulationModel.json', 'WorkstationWorkerMatchingDataAAS.json',
           'MODEL_A.json', 'MODEL_B.json', 'MODEL_C.json']:
    pe.load(os.path.join(_ROOT, 'aas_data', _f))
PSM = pe.ProvisionofSimulationModelsAAS
SM  = PSM.SimulationModels.SimulationModel
A   = SM.KnowledgeGraph.Action
DP  = SM.DefaultParameters
RW  = SM.RewardWeights
GNN = SM.ModelArchitecture.GNN
TC  = SM.ModelArchitecture.PPO.TrainingConfig

OUT  = os.path.join(_DIR, 'result', 'runs', 'dep_wait_aging_05-27')
CKPT = os.path.join(_DIR, 'result', 'runs', 'current_render_05-25', 'agent_used_StateDim0.pt')
os.makedirs(OUT, exist_ok=True)

TARGET = {'MODEL_A': 100, 'MODEL_B': 100, 'MODEL_C': 100}

# baseline = dep_wait_05-27 (BT5_42 본드 24h 만 적용)
BASELINE = {
    'greedy':      {'makespan_sec': 472860, 'makespan_h': 131.35},
    'trained_det': {'makespan_sec': 387630, 'makespan_h': 107.67},
}


class RecEnv(sv.CproSimEnv):
    """_run_job 을 감싸 (model, pc, line, t0, t_cycle, t_total) 이벤트 기록."""
    def reset(self):
        super().reset()
        self.events = []

    def _line_of(self, pc):
        return next((w for w in self.workers if pc in self.workers[w]['ProcessCode']), '?')

    def _run_job(self, ws, job, req):
        t0 = self.env.now
        pc = job['pc']
        node = self.KnowledgeGraph.nodes[pc]
        yield from super()._run_job(ws, job, req)
        t_cycle = t0 + node.CycleTimeSec
        t_total = self.env.now
        self.events.append((node.model_id, pc, self._line_of(pc), t0, t_cycle, t_total))


def make_env():
    MPs = {mp.model_id: mp for mp in SM.Warehouse.InputBOM.target}
    KG  = sv.KnowledgeGraph.build(MPs, PSM.workers)
    WH  = sv.Warehouse.build(PSM.CoManagedBOM, SM.Warehouse.MinStock.target)
    rw  = {k: float(RW[k].value) for k in
           ['W1_TimeElapsed', 'W2_Energy', 'W3_StockOverflow',
            'W4_StockShortage', 'W5_Throughput', 'W6_IdleWorker']}
    return RecEnv(
        KnowledgeGraph=KG, warehouse=WH, workers=PSM.workers,
        IndependentSequence=[n.idShort for r in A.IndependentSequence for n in r.target],
        DependentSequence=[n.idShort for r in A.DependentSequence for n in r.target],
        DependentJoin=[n.idShort for r in A.DependentJoin for n in r.target],
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


def build_agent_StateDim0():
    ag = sv.PPOAgent(
        NodeFeatureDim=int(GNN.NodeFeatureDim.value), HiddenDim=int(GNN.HiddenDim.value),
        OutputDim=int(GNN.OutputDim.value), NumLayers=int(GNN.NumLayers.value),
        GNNEmbeddingDim=int(GNN.OutputDim.value),
        LearningRate=float(TC.LearningRate.value), ClipEpsilon=float(TC.ClipEpsilon.value),
        Gamma=float(TC.Gamma.value), GaeLambda=float(TC.GaeLambda.value),
        EntropyCoef=float(TC.EntropyCoef.value), ValueLossCoef=float(TC.ValueLossCoef.value),
        UpdateEpochs=TC.UpdateEpochs.value, BatchSize=int(TC.BatchSize.value),
        RuntimeVariables=SM.RuntimeVariables, StateDim=0)
    ag.load_state_dict(torch.load(CKPT))
    ag.eval(); ag.reset_buffer()
    return ag


def capture(label, agent):
    print(f'[{time.strftime("%H:%M:%S")}] {label} sim 시작 (DepWaitSec AGING 적용)...', flush=True)
    env = make_env()
    t0  = time.time()
    summary = env.run(agent=agent, max_sec=360 * 86400)
    dt  = time.time() - t0
    ev  = env.events
    print(f'[{time.strftime("%H:%M:%S")}] {label} 완료 dt={dt:.1f}s events={len(ev)} '
          f'makespan={summary["makespan_sec"]:.0f}s ({summary["makespan_sec"]/3600:.1f}h) '
          f'thru={summary["Throughput"]}', flush=True)
    p = os.path.join(OUT, f'events_{label}.jsonl')
    with open(p, 'w', encoding='utf-8') as fp:
        for (m, pc, ln, t0_, t_cyc, t_tot) in ev:
            fp.write(json.dumps({'model': m, 'pc': pc, 'line': ln,
                                 't0': float(t0_),
                                 't_cycle': float(t_cyc),
                                 't_total': float(t_tot)}) + '\n')
    return ev, summary, env


def main():
    runs = {}
    ev_g, s_g, env_g = capture('greedy', None)
    runs['greedy'] = (ev_g, s_g, env_g)
    ag = build_agent_StateDim0()
    ev_t, s_t, env_t = capture('trained_det', ag)
    runs['trained_det'] = (ev_t, s_t, env_t)

    smr = ['# DepWaitSec AGING 일반화 효과 (qty=100/100/100)', '',
           f'적용: BT5_42 본드 경화 24h + VD7_100/BT5_100/NVD_110 AGING 3h.',
           f'AAS json 의 idShort=`AgingTestDurationSec`, value=10800 (3h) — path_extractor `DepWaitSec` 으로 통합 추출.',
           f'시뮬 코드 무변경 — `_run_job` 의 `if node.DepWaitSec:` 분기가 자동으로 모든 DepWaitSec 노드 처리.',
           '',
           '## makespan 비교',
           '',
           '| 정책 | baseline (BT5_42 24h만) | 현재 (+AGING 3h×3) | Δ | Δ% |',
           '|---|---:|---:|---:|---:|']
    for label in ('greedy', 'trained_det'):
        ms_new = runs[label][1]['makespan_sec']
        ms_base = BASELINE[label]['makespan_sec']
        smr.append(f'| {label} | {ms_base/3600:.2f}h ({ms_base}s) | '
                   f'{ms_new/3600:.2f}h ({ms_new:.0f}s) | '
                   f'{(ms_new-ms_base)/3600:+.2f}h | {(ms_new/ms_base - 1)*100:+.2f}% |')
    smr += ['',
            '## throughput 검증',
            '']
    for label in ('greedy', 'trained_det'):
        smr.append(f'- {label}: {dict(runs[label][1]["Throughput"])}')
    smr += ['',
            '## 산출물',
            '- `events_greedy.jsonl`, `events_trained_det.jsonl` — per-job timeline',
            '',
            f'baseline 출처: `mod_run/result/runs/dep_wait_05-27/summary.md`',
            f'가중치: `current_render_05-25/agent_used_StateDim0.pt` (StateDim=0)',
           ]
    with open(os.path.join(OUT, 'summary.md'), 'w', encoding='utf-8') as fp:
        fp.write('\n'.join(smr) + '\n')

    print('\n=== summary ===')
    print('\n'.join(smr))


if __name__ == '__main__':
    main()
