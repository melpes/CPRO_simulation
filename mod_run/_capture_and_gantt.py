# -*- coding: utf-8 -*-
"""sim-only(영상X) 재실행으로 events 캡처 → events.jsonl + gantt PNG + per-line util.
mp4 없이 빠르게(~5-10분/each at qty100). 결과 → result/runs/current_render_05-25/.
"""
import os, sys, json, time, shutil, torch
_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _DIR); sys.path.insert(0, os.path.dirname(_DIR))
import simulation_ver1 as svm
import cpro_ver1_viz as viz                                # AAS load + RecMod(ver1) 정의 가져옴
import path_extractor as pe
PSM = pe.ProvisionofSimulationModelsAAS
SM  = PSM.SimulationModels.SimulationModel
GNN = SM.ModelArchitecture.GNN; TC = SM.ModelArchitecture.PPO.TrainingConfig

OUT = os.path.join(_DIR, 'result', 'runs', 'current_render_05-25')
os.makedirs(OUT, exist_ok=True)


def build_agent_StateDim0(ckpt):
    ag = svm.PPOAgent(
        NodeFeatureDim=int(GNN.NodeFeatureDim.value), HiddenDim=int(GNN.HiddenDim.value),
        OutputDim=int(GNN.OutputDim.value), NumLayers=int(GNN.NumLayers.value),
        GNNEmbeddingDim=int(GNN.OutputDim.value),
        LearningRate=float(TC.LearningRate.value), ClipEpsilon=float(TC.ClipEpsilon.value),
        Gamma=float(TC.Gamma.value), GaeLambda=float(TC.GaeLambda.value),
        EntropyCoef=float(TC.EntropyCoef.value), ValueLossCoef=float(TC.ValueLossCoef.value),
        UpdateEpochs=TC.UpdateEpochs.value, BatchSize=int(TC.BatchSize.value),
        RuntimeVariables=SM.RuntimeVariables, StateDim=0)
    ag.load_state_dict(torch.load(ckpt)); ag.eval(); ag.reset_buffer()
    return ag


def capture(label, agent):
    print(f'[{time.strftime("%H:%M:%S")}] {label} sim 시작...')
    envs = viz.make_envs()
    _, env, _ = next(e for e in envs if e[0] == 'ver1')
    t0 = time.time()
    s = env.run(agent=agent)
    dt = time.time() - t0
    ev = env.events
    print(f'[{time.strftime("%H:%M:%S")}] {label} 완료 dt={dt:.1f}s events={len(ev)} '
          f'makespan={s["makespan_sec"]:.0f}s thru={s["Throughput"]}')
    # events.jsonl
    p = os.path.join(OUT, f'events_{label}.jsonl')
    with open(p, 'w', encoding='utf-8') as fp:
        for (m, pc, ln, t0_, t1_) in ev:
            fp.write(json.dumps({'model': m, 'pc': pc, 'line': ln,
                                 't0': float(t0_), 't1': float(t1_)}) + '\n')
    return ev, s, env


def gantt(events_by_label, env, out_path):
    """라인×시간 Gantt: 행=workstation(=라인), 색=모델, 바=공정 실행구간.
    events_by_label = {label: events_list}. 동일 plot 에 색만 라벨 구분 안 하고,
    각 label 별 PNG 따로."""
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    import matplotlib.patches as mpatches
    color = {'MODEL_A': '#2a6cb0', 'MODEL_B': '#b04a4a', 'MODEL_C': '#3aa8a8'}
    lines = list(env.workers)
    for label, ev in events_by_label.items():
        fig, ax = plt.subplots(figsize=(16, 0.4 * len(lines) + 2))
        y_of = {ln: i for i, ln in enumerate(lines)}
        for (m, pc, ln, t0, t1) in ev:
            if ln not in y_of: continue
            ax.broken_barh([(t0 / 3600, (t1 - t0) / 3600)],
                           (y_of[ln] - 0.4, 0.8),
                           facecolors=color.get(m, '#888'), linewidth=0)
        ax.set_yticks(range(len(lines)))
        ax.set_yticklabels([ln.replace('WWM_', '').replace('Line', '') for ln in lines], fontsize=8)
        ax.invert_yaxis()
        ax.set_xlabel('sim time (h)')
        ms = max(t1 for *_, t1 in ev) / 3600 if ev else 1
        ax.set_xlim(0, ms * 1.02)
        ax.set_title(f'Gantt — {label}  events={len(ev)}  makespan={ms:.1f}h', fontsize=11)
        ax.legend(handles=[mpatches.Patch(color=c, label=m) for m, c in color.items()],
                  loc='upper right', ncol=3, fontsize=9, frameon=False)
        for d in range(int(ms / 24) + 1):                                # 일 경계
            ax.axvline(d * 24, color='0.85', lw=0.5)
        fig.tight_layout()
        p = os.path.join(out_path, f'gantt_{label}.png')
        fig.savefig(p, dpi=130); plt.close(fig)
        print(f'  → {p}')


def per_line_util(label, ev, env, ms):
    WS_S, WS_E = env.WorkStartTime, env.WorkEndTime
    LB, LE = env.break_start_sec, env.break_end_sec
    DAY = 86400
    work_per_day = (WS_E - WS_S) - (LE - LB)
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
    for (m, pc, ln, t0, t1) in ev:
        if ln in used: used[ln] += overlap(t0, t1)
    rows = []
    for ln in used:
        cap = env.workers[ln]['worker_count']
        avail = avail_makespan * cap
        rows.append((ln, cap, used[ln], avail, used[ln] / avail if avail else 0))
    return rows


def main():
    src = os.path.join(_DIR, 'result', 'runs',
                       'b2_horizon_60ep_orig_05-19_StateDim0', 'agent_horizon_qty100_baseline.pt')
    runs = {}
    # greedy
    ev_g, s_g, env_g = capture('greedy', None)
    runs['greedy'] = (ev_g, s_g, env_g)
    # trained (det, StateDim=0)
    ag = build_agent_StateDim0(src)
    ev_t, s_t, env_t = capture('trained_det', ag)
    runs['trained_det'] = (ev_t, s_t, env_t)

    # Gantt PNG per label
    gantt({lbl: tup[0] for lbl, tup in runs.items()}, env_g, OUT)

    # per-line util 표 (두 정책 동시)
    rg = per_line_util('greedy', *runs['greedy'][:1], runs['greedy'][2], runs['greedy'][1]['makespan_sec'])
    rt = per_line_util('trained_det', *runs['trained_det'][:1], runs['trained_det'][2], runs['trained_det'][1]['makespan_sec'])
    rd = {r[0]: r for r in rg}
    out = ['| line | cap | util(greedy) | util(trained_det) | Δ |',
           '|---|---:|---:|---:|---:|']
    tot_gu = tot_gv = tot_tu = tot_tv = 0
    for (ln, cap, u_t, v_t, ut) in sorted(rt):
        _, _, u_g, v_g, ug = rd[ln]
        tot_gu += u_g; tot_gv += v_g; tot_tu += u_t; tot_tv += v_t
        out.append(f'| {ln} | {cap} | {ug*100:.1f}% | {ut*100:.1f}% | {(ut-ug)*100:+.1f}%pt |')
    out.append(f'| **TOTAL** | {sum(env_g.workers[ln]["worker_count"] for ln in env_g.workers)} | '
               f'**{tot_gu/tot_gv*100:.1f}%** | **{tot_tu/tot_tv*100:.1f}%** | '
               f'**{(tot_tu/tot_tv - tot_gu/tot_gv)*100:+.1f}%pt** |')
    util_md = '\n'.join(out)
    with open(os.path.join(OUT, 'util_table.md'), 'w', encoding='utf-8') as fp:
        fp.write('# per-line util — current_render_05-25\n\n' + util_md + '\n')
    print('util_table.md 저장')
    print(util_md)


if __name__ == '__main__':
    main()
