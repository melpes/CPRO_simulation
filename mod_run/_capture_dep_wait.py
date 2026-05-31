# -*- coding: utf-8 -*-
"""DepWaitSec (BT5_42 본드 경화 24h) 도입 효과 측정.

simulation_ver1.py 의 _run_job 이 cycle 직후 워커 release 후 추가 DepWaitSec timeout
하도록 수정됨 (2026-05-27). 본 스크립트는 ver1 환경을 직접 빌드해 greedy / trained
두 정책으로 qty=100/100/100 풀생산한 뒤 events 캡처·gantt PNG·util 표 작성.

비교 베이스라인: mod_run/result/runs/current_render_05-25/metadata.json
  greedy=467,701s (129.9h) / trained_det=388,015s (107.8h)

출력: mod_run/result/runs/dep_wait_05-27/
  - events_{label}.jsonl   (사후 분석용 timeline)
  - gantt_{label}.png      (라인×시간 간트차트)
  - util_table.md          (per-line utilization 비교)
  - summary.md             (baseline 대비 makespan 증가량)
"""
import os, sys, json, time
import torch

_DIR  = os.path.dirname(os.path.abspath(__file__))            # mod_run/
_ROOT = os.path.dirname(_DIR)                                  # 패키지 루트
sys.path.insert(0, _DIR); sys.path.insert(0, _ROOT)

import path_extractor as pe
import simulation_ver1 as sv

# === AAS 로드 ===
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

OUT  = os.path.join(_DIR, 'result', 'runs', 'dep_wait_05-27')
CKPT = os.path.join(_DIR, 'result', 'runs', 'current_render_05-25', 'agent_used_StateDim0.pt')
os.makedirs(OUT, exist_ok=True)

TARGET = {'MODEL_A': 100, 'MODEL_B': 100, 'MODEL_C': 100}

# baseline (current_render_05-25 — DepWaitSec 미적용 시점)
BASELINE = {
    'greedy':      {'makespan_sec': 467701, 'makespan_h': 129.92},
    'trained_det': {'makespan_sec': 388015, 'makespan_h': 107.78},
}


class RecEnv(sv.CproSimEnv):
    """_run_job 을 감싸 (model, pc, line, t0, t_cycle, t_total) 이벤트 기록.
    동작 무변경 — 단순 wrap.
      t_cycle = t0 + CycleTimeSec (워커 release 시점)
      t_total = 전체 종료 시점 (DepWait 포함)
    util 은 [t0, t_cycle] 만 카운트, gantt 는 cycle 진색 + DepWait 옅게."""
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
        # cycle 종료 시점 = t0 + CycleTimeSec (env.timeout(CycleTimeSec) 은 야간 점프 없이 흐름)
        t_cycle = t0 + node.CycleTimeSec
        t_total = self.env.now
        self.events.append((node.model_id, pc, self._line_of(pc), t0, t_cycle, t_total))


def make_env():
    """ver1 환경 빌드 (DepWaitSec 반영 — KnowledgeGraph.build 가 자동 추출)."""
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
    print(f'[{time.strftime("%H:%M:%S")}] {label} sim 시작 (DepWaitSec 적용)...', flush=True)
    env = make_env()
    t0  = time.time()
    summary = env.run(agent=agent, max_sec=360 * 86400)         # ★ 360일 한도 (greedy 진짜 완료 측정)
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


def gantt(events_by_label, env, out_path):
    """라인×시간 간트차트.
    cycle 구간 (워커 점유) = 진한 색 / DepWait 구간 (워커 비점유) = 같은 색 alpha=0.3 옅게."""
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    import matplotlib.patches as mpatches
    color = {'MODEL_A': '#2a6cb0', 'MODEL_B': '#b04a4a', 'MODEL_C': '#3aa8a8'}
    lines = list(env.workers)
    for label, ev in events_by_label.items():
        fig, ax = plt.subplots(figsize=(16, 0.4 * len(lines) + 2))
        y_of = {ln: i for i, ln in enumerate(lines)}
        for (m, pc, ln, t0, t_cyc, t_tot) in ev:
            if ln not in y_of: continue
            ax.broken_barh([(t0 / 3600, (t_cyc - t0) / 3600)],         # cycle (워커 점유)
                           (y_of[ln] - 0.4, 0.8),
                           facecolors=color.get(m, '#888'), linewidth=0)
            if t_tot > t_cyc:                                          # DepWait (워커 비점유)
                ax.broken_barh([(t_cyc / 3600, (t_tot - t_cyc) / 3600)],
                               (y_of[ln] - 0.4, 0.8),
                               facecolors=color.get(m, '#888'), linewidth=0, alpha=0.3)
        ax.set_yticks(range(len(lines)))
        ax.set_yticklabels([ln.replace('WWM_', '').replace('Line', '') for ln in lines], fontsize=8)
        ax.invert_yaxis()
        ax.set_xlabel('sim time (h)')
        ms = max(t_tot for *_, t_tot in ev) / 3600 if ev else 1
        ax.set_xlim(0, ms * 1.02)
        baseline_h = BASELINE.get(label, {}).get('makespan_h', None)
        title = f'Gantt — {label} (DepWaitSec ON, cycle=진색 / DepWait=옅게)  events={len(ev)}  makespan={ms:.1f}h'
        if baseline_h:
            title += f'  | baseline {baseline_h:.1f}h → Δ {ms - baseline_h:+.1f}h ({(ms/baseline_h - 1)*100:+.1f}%)'
        ax.set_title(title, fontsize=10)
        ax.legend(handles=[mpatches.Patch(color=c, label=m) for m, c in color.items()],
                  loc='upper right', ncol=3, fontsize=9, frameon=False)
        for d in range(int(ms / 24) + 1):
            ax.axvline(d * 24, color='0.85', lw=0.5)
        fig.tight_layout()
        p = os.path.join(out_path, f'gantt_{label}.png')
        fig.savefig(p, dpi=130); plt.close(fig)
        print(f'  → {p}')


def per_line_util(ev, env, ms):
    """워커 점유 시간 (cycle 구간 [t0, t_cycle]) 만 카운트 — DepWait 제외."""
    WS_S, WS_E = env.WorkStartTime, env.WorkEndTime
    LB, LE = env.break_start_sec, env.break_end_sec
    DAY = 86400
    def overlap(a, b):
        tot = 0.0
        d0, d1 = int(a // DAY), int(b // DAY)
        for d in range(d0, d1 + 1):
            ws = max(a, d * DAY + WS_S); we = min(b, d * DAY + WS_E)
            if we <= ws: continue
            la = max(ws, d * DAY + LB); lb = min(we, d * DAY + LE)
            tot += (we - ws) - max(0.0, lb - la)
        return tot
    avail_makespan = overlap(0, ms)
    used = {ln: 0.0 for ln in env.workers}
    for (m, pc, ln, t0, t_cyc, t_tot) in ev:
        if ln in used: used[ln] += overlap(t0, t_cyc)               # ★ DepWait 제외
    rows = []
    for ln in used:
        cap = env.workers[ln]['worker_count']
        avail = avail_makespan * cap
        rows.append((ln, cap, used[ln], avail, used[ln] / avail if avail else 0))
    return rows


def main():
    runs = {}
    # greedy
    ev_g, s_g, env_g = capture('greedy', None)
    runs['greedy'] = (ev_g, s_g, env_g)
    # trained (det)
    ag = build_agent_StateDim0()
    ev_t, s_t, env_t = capture('trained_det', ag)
    runs['trained_det'] = (ev_t, s_t, env_t)

    gantt({lbl: tup[0] for lbl, tup in runs.items()}, env_g, OUT)

    # util 표
    rows_by_label = {}
    for lbl, (ev, s, env) in runs.items():
        rows_by_label[lbl] = {r[0]: r for r in per_line_util(ev, env, s['makespan_sec'])}
    out = ['| line | cap | util(greedy) | util(trained_det) | Δ |',
           '|---|---:|---:|---:|---:|']
    tot_gu = tot_gv = tot_tu = tot_tv = 0
    for ln in sorted(rows_by_label['greedy']):
        _, cap, ug_u, ug_v, ug = rows_by_label['greedy'][ln]
        _, _, ut_u, ut_v, ut = rows_by_label['trained_det'][ln]
        tot_gu += ug_u; tot_gv += ug_v; tot_tu += ut_u; tot_tv += ut_v
        out.append(f'| {ln} | {cap} | {ug*100:.1f}% | {ut*100:.1f}% | {(ut-ug)*100:+.1f}%pt |')
    out.append(f'| **TOTAL** | {sum(env_g.workers[ln]["worker_count"] for ln in env_g.workers)} | '
               f'**{tot_gu/tot_gv*100:.1f}%** | **{tot_tu/tot_tv*100:.1f}%** | '
               f'**{(tot_tu/tot_tv - tot_gu/tot_gv)*100:+.1f}%pt** |')
    util_md = '\n'.join(out)
    with open(os.path.join(OUT, 'util_table.md'), 'w', encoding='utf-8') as fp:
        fp.write('# per-line util — dep_wait_05-27 (DepWaitSec ON)\n\n' + util_md + '\n')

    # summary.md
    smr = ['# DepWaitSec 도입 효과 요약 (qty=100/100/100)', '',
           f'대상: BT5_42 본드 경화 `CuringTimeSec=86400s` (24h) — `simulation_ver1._run_job` 에서 done 마킹을 cycle 후 24h 지연.',
           '',
           '## makespan 비교',
           '',
           '| 정책 | baseline (DepWait OFF) | 현재 (DepWait ON) | Δ | Δ% |',
           '|---|---:|---:|---:|---:|']
    for label in ('greedy', 'trained_det'):
        ms_new = runs[label][1]['makespan_sec']
        ms_base = BASELINE[label]['makespan_sec']
        smr.append(f'| {label} | {ms_base/3600:.2f}h ({ms_base}s) | '
                   f'{ms_new/3600:.2f}h ({ms_new:.0f}s) | '
                   f'{(ms_new-ms_base)/3600:+.2f}h | {(ms_new/ms_base - 1)*100:+.2f}% |')
    smr += ['',
            '## throughput 검증 (둘 다 목표 100/100/100 도달 예상)',
            '']
    for label in ('greedy', 'trained_det'):
        smr.append(f'- {label}: {dict(runs[label][1]["Throughput"])}')
    smr += ['',
            '## 산출물',
            '- `events_greedy.jsonl`, `events_trained_det.jsonl` — per-job timeline',
            '- `gantt_greedy.png`, `gantt_trained_det.png` — 라인×시간 간트차트',
            '- `util_table.md` — per-line utilization 비교',
            '',
            f'baseline 출처: `mod_run/result/runs/current_render_05-25/metadata.json`',
            f'가중치: `current_render_05-25/agent_used_StateDim0.pt` (StateDim=0)',
           ]
    with open(os.path.join(OUT, 'summary.md'), 'w', encoding='utf-8') as fp:
        fp.write('\n'.join(smr) + '\n')

    print('\n=== summary ===')
    print('\n'.join(smr))


if __name__ == '__main__':
    main()
