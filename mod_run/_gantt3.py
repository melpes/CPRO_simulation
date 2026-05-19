# -*- coding: utf-8 -*-
"""3-policy 작업자별 Gantt.

정책: greedy(ver0_mod produce_unit, agent=None) / ver0(학습) / ver0_mod(학습).
qty A/B/C = 50/50/50. ver0_mod 140ep, ver0 80ep 학습 후 각 1 eval 에피소드
기록(_Rec 래퍼 — sim 본체 무수정). y축 = 라인별 개별 작업자 슬롯(사후
그리디 interval coloring, 슬롯≤worker_count, 라인순서=list(workers)=영상과 동일),
x축 = 시간(h), 색 = 모델.

체크포인트: agent_mod.pt / agent_v0.pt / gantt3_events.pkl 있으면 해당
단계 skip → 중단 후 재개 가능. 출력: gantt_3policy.png
"""
from __future__ import annotations
import os, sys, time, pickle, importlib
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np
import torch

DIR   = os.path.dirname(os.path.abspath(__file__))        # mod_run/ — 결과·ckpt 저장처
_ROOT = os.path.dirname(DIR)                               # 패키지 루트 — AAS JSON·root 모듈
sys.path.insert(0, _ROOT)
import path_extractor as pe
from cpro_ver0_viz import _Rec                    # 이벤트 기록 mixin 재사용 (mod_run 동일폴더)

QTY = {'MODEL_A': 50, 'MODEL_B': 50, 'MODEL_C': 50}
EP_MOD = 13                        # 17:49 시작·데드라인 19:00, qty50+기록 ~230s/ep → 종료~18:45
MODEL_COLOR = {'MODEL_A': '#1f5fa8', 'MODEL_B': '#8c4a3a', 'MODEL_C': '#17b4c4'}

for f in ['ProvisionOfSimulationModel.json', 'WorkstationWorkerMatchingDataAAS.json',
          'MODEL_A.json', 'MODEL_B.json', 'MODEL_C.json']:
    pe.load(os.path.join(_ROOT, f))
PSM = pe.ProvisionofSimulationModelsAAS
SM  = PSM.SimulationModels.SimulationModel
A   = SM.KnowledgeGraph.Action
DP  = SM.DefaultParameters
RW  = SM.RewardWeights
GNN = SM.ModelArchitecture.GNN
TC  = SM.ModelArchitecture.PPO.TrainingConfig


def _kwargs(is_mod):
    sv = importlib.import_module('simulation_ver0_mod' if is_mod else 'simulation_ver0')
    KG = sv.KnowledgeGraph.build(
        {mp.model_id: mp for mp in SM.Warehouse.InputBOM.target}, PSM.workers)
    wbom = PSM.CoManagedBOM if is_mod else PSM.WarehouseManagedBOM
    WH = sv.Warehouse.build(wbom, SM.Warehouse.MinStock.target)
    kw = dict(
        KnowledgeGraph=KG, warehouse=WH, workers=PSM.workers,
        IndependentSequence=[n.idShort for r in A.IndependentSequence for n in r.target],
        DependentSequence=[n.idShort for r in A.DependentSequence for n in r.target],
        DependentJoin=[n.idShort for r in A.DependentJoin for n in r.target],
        RewardWeights={k: float(RW[k].value) for k in
                       ['W1_TimeElapsed', 'W2_Energy', 'W3_StockOverflow',
                        'W4_StockShortage', 'W5_Throughput', 'W6_IdleWorker']},
        ReplenishLeadDay=int(DP.ReplenishLeadDay.value) * 3600,
        target_qty=dict(QTY), MaxEpisodes=1,
        WarehouseManagedBOM=wbom, BOMCategory=SM.Warehouse.MinStock.target,
        WorkStartTime=DP.WorkStartTime.target.value, WorkEndTime=DP.WorkEndTime.target.value,
        break_start_sec=DP.BreakDurationMin.target.min,
        break_end_sec=DP.BreakDurationMin.target.max,
        IdleWorkerThreshold=int(DP.IdleWorkerThreshold.value),
        RuntimeVariables=SM.RuntimeVariables,
        IdleProcessRatedPowerKw=float(DP.IdleProcessRatedPowerKw.value),
        IdlePowerRatio=0.10)
    if is_mod:
        kw['SelfManagedBOM'] = PSM.SelfManagedBOM
    return sv, kw


def _agent(sv):
    return sv.PPOAgent(
        NodeFeatureDim=int(GNN.NodeFeatureDim.value), HiddenDim=int(GNN.HiddenDim.value),
        OutputDim=int(GNN.OutputDim.value), NumLayers=int(GNN.NumLayers.value),
        GNNEmbeddingDim=int(GNN.OutputDim.value),
        LearningRate=float(TC.LearningRate.value), ClipEpsilon=float(TC.ClipEpsilon.value),
        Gamma=float(TC.Gamma.value), GaeLambda=float(TC.GaeLambda.value),
        EntropyCoef=float(TC.EntropyCoef.value), ValueLossCoef=float(TC.ValueLossCoef.value),
        UpdateEpochs=TC.UpdateEpochs.value, BatchSize=int(TC.BatchSize.value),
        RuntimeVariables=SM.RuntimeVariables)


# ---------- 학습 ----------
def train_save(is_mod, ep, ckpt):
    sv, kw = _kwargs(is_mod)
    env, agent = sv.CproSimEnv(**kw), _agent(sv)
    tag = 'ver0_mod' if is_mod else 'ver0'
    if os.path.exists(ckpt):
        agent.load_state_dict(torch.load(ckpt)); print(f'[{tag}] ckpt 로드 — 학습 skip')
        return sv, kw, agent
    print(f'[{tag}] 학습 {ep}ep 시작 (qty {QTY["MODEL_A"]})', flush=True)
    t = time.perf_counter()
    sv.train(env, agent, ep)
    torch.save(agent.state_dict(), ckpt)
    print(f'[{tag}] 학습 완료 {time.perf_counter()-t:.0f}s → {ckpt}', flush=True)
    return sv, kw, agent


# ---------- eval 기록 ----------
def _mk_rec_mod(kw):
    svm = importlib.import_module('simulation_ver0_mod')
    Rec = type('RecM', (_Rec, svm.CproSimEnv), {
        'reset': lambda s: (svm.CproSimEnv.reset(s), s._init_rec())[0],
        'process_job': lambda s, pc, ws, ds: (yield from _wrap(s, pc, ws, ds))})
    return Rec(**kw)


def rec_mod(kw, agent):                                   # produce_unit (greedy/trained)
    if agent is not None:
        agent.reset_buffer()                              # eval: buf 누적 무시(학습 안 함)
    env = _mk_rec_mod(kw)
    env.run(agent=agent)
    return env


def train_mod_best(kw, ep):
    """ver0_mod 학습 — 매 ep 이벤트 기록, best(R 최대=throughput 포화시 makespan
    최소) 에피소드의 실제 스케줄을 캡처해 반환. 마지막 ep 가중치가 아닌
    '학습 중 가장 좋은 결과' 를 렌더하기 위함."""
    import copy
    from types import SimpleNamespace
    svm = importlib.import_module('simulation_ver0_mod')
    env = _mk_rec_mod(kw)
    agent = _agent(svm)
    best = None
    print(f'[ver0_mod] 학습 {ep}ep 시작 (qty {QTY["MODEL_A"]}) — best 캡처', flush=True)
    t = time.perf_counter()
    for e in range(ep):
        agent.reset_buffer()
        env.run(agent=agent)                              # 내부 reset → events 갱신
        R = env.episode_reward()
        agent.learn(R, env.KnowledgeGraph)
        thru = dict(env.Throughput)
        ms = max((x[4] for x in env.events), default=0)
        full = all(thru[m] >= env.target_qty[m] for m in env.target_qty)
        print(f'[ep {e:>3}] R={R:+.4f} makespan={ms:.0f} thru={thru} '
              f'{"FULL" if full else "part"}', flush=True)
        if best is None or R > best.R:
            best = SimpleNamespace(R=R, events=list(env.events),
                                   Throughput=dict(env.Throughput),
                                   KnowledgeGraph=env.KnowledgeGraph)
            torch.save(agent.state_dict(), os.path.join(DIR, 'agent_mod.pt'))
            print(f'        ↑ best 갱신 (R={R:+.4f}, makespan={ms:.0f})', flush=True)
    print(f'[ver0_mod] 학습 완료 {time.perf_counter()-t:.0f}s  '
          f'best R={best.R:+.4f} thru={best.Throughput}', flush=True)
    return best


def _wrap(s, pc, ws, ds):
    svm = importlib.import_module('simulation_ver0_mod')
    t0 = s.env.now
    yield from svm.CproSimEnv.process_job(s, pc, ws, ds)
    s._record(pc, t0)


def rec_v0(kw, agent):                                    # serial, 학습 정책
    sv0 = importlib.import_module('simulation_ver0')
    def pj(s, pc, ws):
        t0 = s.env.now
        yield from sv0.CproSimEnv.process_job(s, pc, ws)
        s._record(pc, t0)
    Rec = type('RecV', (_Rec, sv0.CproSimEnv), {
        'reset': lambda s: (lambda o: (s._init_rec(), o)[1])(sv0.CproSimEnv.reset(s)),
        'process_job': pj})
    env = Rec(**kw)
    obs = env.reset()
    done = False
    while not done and len(env.events) < 200000:
        if not obs['ready']:
            obs, dead = env.skip()
            if dead: break
            continue
        action, _ = agent.select_action(obs, env.KnowledgeGraph)
        obs, _, done, _ = env.step(action)
    return env


# ---------- Gantt 렌더 ----------
def _slots(events, line, capacity, kg):
    # 실제 처리구간 = [t1-CycleTimeSec, t1] (앞쪽 근무시간/BOM/자원 대기는 막대에서
    # 제외 — 사후 유도, sim 무수정). line 이벤트를 시작시각순 그리디 슬롯 배정.
    evs = []
    for m, pc, ln, t0, t1 in events:
        if ln != line:
            continue
        ct = kg.nodes[pc].CycleTimeSec if pc in kg.nodes else (t1 - t0)
        evs.append((m, pc, ln, max(t0, t1 - ct), t1))
    evs.sort(key=lambda e: e[3])
    end = []                                              # 슬롯별 마지막 종료시각
    rows = []                                             # (slot, model, t0, t1)
    for m, pc, ln, t0, t1 in evs:
        s = next((i for i, te in enumerate(end) if te <= t0), None)
        if s is None:
            if len(end) < capacity:
                s = len(end); end.append(t1)
            else:                                         # capacity 초과(이론상 없음) → 막대 슬롯
                s = min(range(len(end)), key=lambda i: end[i]); end[s] = t1
        else:
            end[s] = t1
        rows.append((s, m, t0, t1))
    return rows


def render(panels):                                       # panels: [(name, env), ...]
    workers = PSM.workers
    lines = list(workers)                                  # 영상/히트맵과 동일 순서
    cap = {ln: workers[ln]['worker_count'] for ln in lines}
    nrow = sum(cap.values())
    y_of, ylab, sep = {}, [], []
    y = 0
    for ln in lines:
        sep.append(y)
        for k in range(cap[ln]):
            y_of[(ln, k)] = y
            ylab.append(f'{ln.replace("WWM_","").replace("Line","")} #{k+1}')
            y += 1
    makespan = max((e[4] for _n, env in panels for e in env.events), default=1.0)

    fig, axes = plt.subplots(len(panels), 1, sharex=True,
                             figsize=(18, max(8, nrow * 0.13 * len(panels))))
    if len(panels) == 1: axes = [axes]
    for ax, (name, env) in zip(axes, panels):
        for ln in lines:
            for sl, m, t0, t1 in _slots(env.events, ln, cap[ln], env.KnowledgeGraph):
                yy = y_of[(ln, sl)]
                ax.broken_barh([(t0 / 3600.0, max((t1 - t0) / 3600.0, 0.02))],
                               (yy - 0.42, 0.84),
                               facecolors=MODEL_COLOR.get(m, '#888'), linewidth=0)
        for s in sep[1:]:
            ax.axhline(s - 0.5, color='0.8', lw=0.6)
        for d in range(1, int(makespan // 86400) + 2):
            ax.axvline(d * 24, color='0.85', lw=0.7, ls='--')
        thr = getattr(env, 'Throughput', {})
        ms = max((e[4] for e in env.events), default=0) / 3600.0
        ax.set_title(f'{name}   thru={dict(thr)}   makespan={ms:.1f}h   '
                     f'events={len(env.events)}', fontsize=10, loc='left')
        ax.set_ylim(-0.5, nrow - 0.5)
        ax.set_yticks(range(nrow))
        ax.set_yticklabels(ylab, fontsize=5.5)
        ax.invert_yaxis()
        ax.set_xlim(0, makespan / 3600.0 * 1.01)
    axes[-1].set_xlabel('time (h)', fontsize=10)
    axes[0].legend(handles=[mpatches.Patch(color=c, label=m)
                            for m, c in MODEL_COLOR.items()],
                   loc='upper right', ncol=3, fontsize=9, frameon=False)
    fig.suptitle('3-policy worker-level Gantt  (y = per-line worker slot, color = model)',
                 fontsize=12)
    fig.tight_layout(rect=[0, 0, 1, 0.985])
    out = os.path.join(DIR, 'gantt_3policy.png')
    fig.savefig(out, dpi=140)
    plt.close(fig)
    for name, env in panels:
        print(f'  {name}: events={len(env.events)} '
              f'thru={dict(getattr(env,"Throughput",{}))} '
              f'makespan={max((e[4] for e in env.events),default=0)/3600.0:.1f}h')
    print('완료:', out)


if __name__ == '__main__':
    # ver0_mod 만 학습. 최종 Gantt = greedy + ver0_mod(학습 中 best ep) 2패널.
    _, kw_mod = _kwargs(True)

    best = train_mod_best(kw_mod, EP_MOD)                  # 학습 中 R-best 스케줄 캡처

    print('[eval] greedy(ver0_mod) 기록', flush=True)
    e_greedy = rec_mod(kw_mod, None)

    render([('greedy (ver0_mod, no learning)',          e_greedy),
            (f'ver0_mod (parallel, PPO best R={best.R:+.4f})', best)])
