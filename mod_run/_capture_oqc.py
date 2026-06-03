# -*- coding: utf-8 -*-
"""OQC SamplingRate 통합 시뮬 + events 저장 + 간트차트 자동 렌더.

baseline (dep_wait_aging_05-27, BT5_42 24h + AGING 3h×3): greedy 134.35h / trained_det 110.67h
현재 (OQC 추가, SamplingRate=0.05): greedy / trained_det — 5% 분기로 OQC 600s × 평균 15 unit / 4명

출력: mod_run/result/runs/{MMDDHHMM}_oqc_validation/
"""
import os, sys, json, time, random
import subprocess
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

# 현재 시각 기반 폴더명 (MMDDHHMM)
RUN_NAME = time.strftime('%m%d%H%M') + '_aging_cycle'
OUT  = os.path.join(_DIR, 'result', 'runs', RUN_NAME)
CKPT = os.path.join(_DIR, 'result', 'runs', '05261016_current_render_05-25', 'agent_used_StateDim0.pt')
os.makedirs(OUT, exist_ok=True)

TARGET = {'MODEL_A': 100, 'MODEL_B': 100, 'MODEL_C': 100}

# baseline = 05281038_oqc_validation (OQC 추가, AGING 은 아직 DepWait 3h 시절)
BASELINE = {
    'greedy':      {'makespan_sec': 483660, 'makespan_h': 134.35},
    'trained_det': {'makespan_sec': 398430, 'makespan_h': 110.67},
}


class RecEnv(sv.CproSimEnv):
    """_run_job 을 감싸 (model, pc, line, t0, t_cycle, t_total) 이벤트 기록."""
    def reset(self):
        super().reset()
        self.events = []
        self.oqc_actual = 0   # OQC 실제 워커 큐 진입 (5% 분기 검증)

    def _line_of(self, pc):
        return next((w for w in self.workers if pc in self.workers[w]['ProcessCode']), '?')

    def _run_job(self, ws, job, req):
        t0 = self.env.now
        pc = job['pc']
        node = self.KnowledgeGraph.nodes[pc]
        if pc == 'OQC':
            self.oqc_actual += 1
        yield from super()._run_job(ws, job, req)
        t_cycle = t0 + node.CycleTimeSec
        t_total = self.env.now
        self.events.append((node.model_id, pc, self._line_of(pc), t0, t_cycle, t_total))


def make_env(seed=42):
    import cpro_factory as cf                       # wiring 단일 구현 — env_cls 로 RecEnv 주입
    random.seed(seed)
    return cf.build_simulation(env_cls=RecEnv, target_qty=dict(TARGET), MaxEpisodes=1)


def build_agent_StateDim0():
    import cpro_factory as cf                       # StateDim=0 구 체크포인트 로드 (결정형 평가)
    return cf.build_agent(StateDim=0, checkpoint=CKPT)


def capture(label, agent, max_sec):
    print(f'[{time.strftime("%H:%M:%S")}] {label} sim 시작 '
          f'(OQC SamplingRate=0.05, max_sec={max_sec}s={max_sec/3600:.1f}h)...', flush=True)
    env = make_env(seed=42)
    t0  = time.time()
    summary = env.run(agent=agent, max_sec=max_sec)
    dt  = time.time() - t0
    ev  = env.events
    print(f'[{time.strftime("%H:%M:%S")}] {label} 완료 dt={dt:.1f}s events={len(ev)} '
          f'makespan={summary["makespan_sec"]:.0f}s ({summary["makespan_sec"]/3600:.1f}h) '
          f'thru={summary["Throughput"]} OQC actual={env.oqc_actual}', flush=True)
    p = os.path.join(OUT, f'events_{label}.jsonl')
    with open(p, 'w', encoding='utf-8') as fp:
        for (m, pc, ln, t0_, t_cyc, t_tot) in ev:
            fp.write(json.dumps({'model': m, 'pc': pc, 'line': ln,
                                 't0': float(t0_),
                                 't_cycle': float(t_cyc),
                                 't_total': float(t_tot)}) + '\n')
    return ev, summary, env


def main():
    # 평가 horizon 선택: (1) 1일 (86400s) — 1일당 throughput 비교
    #                   (2) 전체 — target_qty 도달까지 (60일 기본 timeout)
    mode = input('평가 horizon (1=1일 86400s, 2=전체 target_qty 도달까지, 기본=2): ').strip()
    if mode == '1':
        max_sec = 86400
        horizon_tag = '1day'
    else:
        max_sec = 60 * 86400
        horizon_tag = 'full'
    print(f'[main] horizon={horizon_tag} max_sec={max_sec}s ({max_sec/3600:.1f}h)', flush=True)

    runs = {}
    ev_g, s_g, env_g = capture('greedy', None, max_sec)
    runs['greedy'] = (ev_g, s_g, env_g)
    ag = build_agent_StateDim0()
    ev_t, s_t, env_t = capture('trained_det', ag, max_sec)
    runs['trained_det'] = (ev_t, s_t, env_t)

    # summary.md
    smr = [f'# AGING 모델 변경 효과 (qty=100/100/100)  /  {RUN_NAME}', '',
           '변경: AGING(VD7_100/BT5_100/NVD_110) 을 DepWait(3h 워커 비점유) → CycleTimeSec=10800(3h 워커 점유) 으로.',
           '- WWM_AgingLine 에 UnitsPerWorker=10 추가 → capacity = 6명 × 10 = 60 (동시 60제품 AGING).',
           '- 1작업자가 여러 챔버를 병렬 모니터링하는 현실 반영 (기존 암묵적 1제품/워커 → 10).',
           '- DepWaitSec 은 이제 BT5_42 본드 경화(24h) 단독.',
           '',
           '## makespan 비교',
           '',
           '| 정책 | baseline (OQC, AGING DepWait) | 현재 (AGING cycle+cap60) | Δ | Δ% |',
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
        smr.append(f'- {label}: {dict(runs[label][1]["Throughput"])}, OQC actual={runs[label][2].oqc_actual}')
    smr += ['',
            '## 산출물',
            '- `events_greedy.jsonl`, `events_trained_det.jsonl` — per-job timeline (OQC 포함)',
            '- `gantt_greedy.png`, `gantt_trained_det.png` — 라인×시간 간트차트 (WWM_OqcLine 슬롯 포함)',
            '',
            f'baseline 출처: `mod_run/result/runs/05271819_dep_wait_aging_05-27/summary.md`',
            f'가중치: `05261016_current_render_05-25/agent_used_StateDim0.pt` (StateDim=0)',
           ]
    with open(os.path.join(OUT, 'summary.md'), 'w', encoding='utf-8') as fp:
        fp.write('\n'.join(smr) + '\n')

    # 간트차트 자동 렌더
    print(f'\n[{time.strftime("%H:%M:%S")}] 간트차트 렌더링 (WWM_OqcLine 포함)...', flush=True)
    r = subprocess.run([sys.executable, os.path.join(_DIR, '_redraw_gantt_slots.py'), RUN_NAME],
                       capture_output=True, text=True, encoding='utf-8')
    print(r.stdout, flush=True)
    if r.returncode != 0:
        print('GANTT STDERR:', r.stderr, flush=True)

    print('\n=== summary ===')
    print('\n'.join(smr))


if __name__ == '__main__':
    main()
