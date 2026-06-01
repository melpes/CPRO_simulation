# -*- coding: utf-8 -*-
"""전량완료 평가 — greedy vs 학습 agent(결정론) 캡처 + 간트.

사용자 평가 기준 = 전량작업(300 unit 전부 완성)까지. 3일 horizon 으로 학습한 agent 를
argmax(결정론)로 돌려 greedy 와 makespan·유휴·에너지·재고 비교 + 라인×시간 간트 2장.
(검증: greedy 134.0h vs trained 113.0h, 유휴 −13%, 에너지 −8% — 2026-06-01)

_capture_oqc 의 RecEnv·make_env·AAS load 재사용. 체크포인트는 인자 또는 기본값(최근 학습).
출력: mod_run/result/runs/{MMDDHHMM}_eval_compare/
"""
import os, sys, json, time, subprocess
import torch

_DIR  = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_DIR)
sys.path.insert(0, _DIR); sys.path.insert(0, _ROOT)

import _capture_oqc as cap        # AAS load + RecEnv + make_env + GNN/TC 상수
import simulation_ver1 as sv

SM, GNN, TC = cap.SM, cap.GNN, cap.TC

RUN_NAME = time.strftime('%m%d%H%M') + '_eval_compare'
OUT      = os.path.join(_DIR, 'result', 'runs', RUN_NAME)
# 학습 체크포인트 (3일 horizon 60ep, StateDim=18). 인자로 override 가능.
CKPT     = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
               _DIR, 'result', 'runs', '06011244_reward_effect', 'agent_mod.pt')
MAX_SEC  = 60 * 86400            # 전량완료까지 (target 도달 시 종료, 60일 cap)
os.makedirs(OUT, exist_ok=True)


def build_trained_agent(state_dim):
    ag = sv.PPOAgent(
        NodeFeatureDim=int(GNN.NodeFeatureDim.value), HiddenDim=int(GNN.HiddenDim.value),
        OutputDim=int(GNN.OutputDim.value), NumLayers=int(GNN.NumLayers.value),
        GNNEmbeddingDim=int(GNN.OutputDim.value),
        LearningRate=float(TC.LearningRate.value), ClipEpsilon=float(TC.ClipEpsilon.value),
        Gamma=float(TC.Gamma.value), GaeLambda=float(TC.GaeLambda.value),
        EntropyCoef=float(TC.EntropyCoef.value), ValueLossCoef=float(TC.ValueLossCoef.value),
        UpdateEpochs=TC.UpdateEpochs.value, BatchSize=int(TC.BatchSize.value),
        RuntimeVariables=SM.RuntimeVariables, StateDim=state_dim)
    ag.load_state_dict(torch.load(CKPT))
    ag.eval(); ag.reset_buffer()
    return ag


def capture(label, agent):
    print(f'[{time.strftime("%H:%M:%S")}] {label} 전량완료 sim 시작...', flush=True)
    env = cap.make_env(seed=42)
    t0  = time.time()
    summary = env.run(agent=agent, max_sec=MAX_SEC)
    dt  = time.time() - t0
    ev  = env.events
    print(f'[{time.strftime("%H:%M:%S")}] {label} 완료 dt={dt:.1f}s events={len(ev)} '
          f'makespan={summary["makespan_sec"]:.0f}s ({summary["makespan_sec"]/3600:.1f}h) '
          f'thru={summary["Throughput"]} idle={env.IdleViolationCount} '
          f'energy={summary["EpisodeEnergyKwh"]:.0f}', flush=True)
    with open(os.path.join(OUT, f'events_{label}.jsonl'), 'w', encoding='utf-8') as fp:
        for (m, pc, ln, t0_, t_cyc, t_tot) in ev:
            fp.write(json.dumps({'model': m, 'pc': pc, 'line': ln, 't0': float(t0_),
                                 't_cycle': float(t_cyc), 't_total': float(t_tot)}) + '\n')
    return summary, env


def main():
    print(f'대상 폴더: {OUT}\nCKPT: {CKPT}', flush=True)
    s_g, env_g = capture('greedy', None)
    state_dim  = cap.make_env(seed=42).state_dim
    ag         = build_trained_agent(state_dim)
    s_t, env_t = capture('trained_det', ag)

    smr = [f'# 전량완료 평가 greedy vs trained(결정론)  /  {RUN_NAME}', '',
           f'학습: 3일 horizon 60ep (`{os.path.relpath(CKPT, _DIR)}`). 평가: 300 unit 전량완료.', '',
           '| 정책 | makespan | 유휴 | 에너지 | 재고부족 |', '|---|---:|---:|---:|---:|']
    for label, s, e in [('greedy', s_g, env_g), ('trained_det', s_t, env_t)]:
        smr.append(f'| {label} | {s["makespan_sec"]/3600:.1f}h | {e.IdleViolationCount} | '
                   f'{s["EpisodeEnergyKwh"]:.0f} | {e.StockShortageCount} |')
    smr += ['', '## 산출물', '- `events_*.jsonl`, `gantt_*.png` (공통 x축 → makespan 차이 시각화)']
    with open(os.path.join(OUT, 'summary.md'), 'w', encoding='utf-8') as fp:
        fp.write('\n'.join(smr) + '\n')

    print(f'\n[{time.strftime("%H:%M:%S")}] 간트 렌더링...', flush=True)
    r = subprocess.run([sys.executable, os.path.join(_DIR, '_redraw_gantt_slots.py'), RUN_NAME],
                       capture_output=True, text=True, encoding='utf-8')
    print(r.stdout, flush=True)
    if r.returncode != 0:
        print('GANTT STDERR:', r.stderr, flush=True)
    print('\n=== summary ===\n' + '\n'.join(smr))


if __name__ == '__main__':
    main()
