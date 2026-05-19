# -*- coding: utf-8 -*-
"""ver0_mod(학습 best) 단일 Gantt — 퇴근시간(비근무) 제거, 점심은 표현.

x축 = 근무시간만 이어붙임(매일 [WorkStart, WorkEnd]). 퇴근~출근 구간은
완전히 제거(빈 공간 없음). 점심(12~13시)은 근무창 안의 자연 dip 로 그대로 보임.
y축 = 라인별 개별 워커 슬롯(58, 영상/히트맵과 동일 순서), 색 = 모델.
agent_mod.pt(학습 中 best 가중치) 로 1 eval 기록. 출력: gantt_mod.png
"""
import os
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import torch

import _gantt3 as g                                       # _kwargs/_agent/rec_mod/_slots/MODEL_COLOR 재사용
import path_extractor as pe

DP = pe.ProvisionofSimulationModelsAAS.SimulationModels.SimulationModel.DefaultParameters
WS = int(DP.WorkStartTime.target.value)                   # 32400 (09:00)
WE = int(DP.WorkEndTime.target.value)                     # 64800 (18:00)
LB = int(DP.BreakDurationMin.target.min)                  # 43200 (12:00)
LE = int(DP.BreakDurationMin.target.max)                  # 46800 (13:00)
DAY = 86400


def _segments(makespan):
    # 근무창만: 매일 [WS, WE]. makespan 까지, 실제 이벤트 없는 날은 자동 제외(빈칸).
    segs, d = [], 0
    while d * DAY + WS < makespan + 1:
        s, e = d * DAY + WS, min(d * DAY + WE, makespan)
        if e > s:
            segs.append((d, s, e))
        d += 1
    return segs


def _mapper(segs):
    # 실제시각 → 압축표시시각 (초). 비근무 구간은 길이 0 으로 접힘.
    base, off = [], 0.0
    for _d, s, e in segs:
        base.append((s, e, off))
        off += e - s
    total = off

    def disp(t):
        for s, e, o in base:
            if t < s:
                return o
            if t <= e:
                return o + (t - s)
        return total
    return disp, total


def render():
    _, kw = g._kwargs(True)
    svm = __import__('simulation_ver0_mod')
    agent = g._agent(svm)
    agent.load_state_dict(torch.load(os.path.join(g.DIR, 'agent_mod.pt')))
    env = g.rec_mod(kw, agent)                             # best 가중치로 1 eval

    workers = pe.ProvisionofSimulationModelsAAS.workers
    lines = list(workers)
    cap = {ln: workers[ln]['worker_count'] for ln in lines}
    nrow = sum(cap.values())
    y_of, ylab, sep, y = {}, [], [], 0
    for ln in lines:
        sep.append(y)
        for k in range(cap[ln]):
            y_of[(ln, k)] = y
            ylab.append(f'{ln.replace("WWM_","").replace("Line","")} #{k+1}')
            y += 1

    makespan = max((e[4] for e in env.events), default=1.0)
    segs = _segments(makespan)
    disp, total = _mapper(segs)
    H = 3600.0

    fig, ax = plt.subplots(figsize=(16, max(8, nrow * 0.16)))
    for ln in lines:
        for sl, m, t0, t1 in g._slots(env.events, ln, cap[ln], env.KnowledgeGraph):
            for _d, s, e in segs:                          # 근무창별로 잘라 매핑
                a, b = max(t0, s), min(t1, e)
                if b <= a:
                    continue
                x0, x1 = disp(a) / H, disp(b) / H
                ax.broken_barh([(x0, max(x1 - x0, 0.01))],
                               (y_of[(ln, sl)] - 0.42, 0.84),
                               facecolors=g.MODEL_COLOR.get(m, '#888'), linewidth=0)

    # 근무일 경계 실선 + 점심 음영 + x 라벨(실제 D/시각)
    xticks, xlab = [], []
    for _d, s, e in segs:
        d = _d
        x_s, x_e = disp(s) / H, disp(e) / H
        ax.axvline(x_s, color='0.55', lw=1.0)
        for hh in range(WS // 3600, WE // 3600 + 1, 3):
            tt = d * DAY + hh * 3600
            if s <= tt <= e:
                xticks.append(disp(tt) / H); xlab.append(f'D{d} {hh:02d}h')
        ax.axvspan(disp(d * DAY + LB) / H, disp(d * DAY + LE) / H,
                   color='0.92', zorder=0)                  # 점심 dip 음영
    ax.axvline(total / H, color='0.55', lw=1.0)

    for syi in sep[1:]:
        ax.axhline(syi - 0.5, color='0.85', lw=0.6)
    ax.set_ylim(-0.5, nrow - 0.5)
    ax.set_yticks(range(nrow))
    ax.set_yticklabels(ylab, fontsize=6)
    ax.invert_yaxis()
    ax.set_xlim(0, total / H)
    ax.set_xticks(xticks)
    ax.set_xticklabels(xlab, fontsize=7, rotation=30)
    ax.set_xlabel('working hours only  (off-hours removed, lunch=grey dip)', fontsize=10)
    ax.legend(handles=[mpatches.Patch(color=c, label=m)
                       for m, c in g.MODEL_COLOR.items()],
              loc='upper right', ncol=3, fontsize=9, frameon=False)
    ms = makespan / H
    ax.set_title(f'ver0_mod (PPO-trained best)  thru={dict(env.Throughput)}  '
                 f'makespan={ms:.1f}h (real)  events={len(env.events)}', fontsize=11)
    fig.tight_layout()
    out = os.path.join(g.DIR, 'gantt_mod.png')
    fig.savefig(out, dpi=140)
    plt.close(fig)
    print(f'완료: {out}  rows={nrow} segs={len(segs)} '
          f'thru={dict(env.Throughput)} makespan={ms:.1f}h')


if __name__ == '__main__':
    render()
