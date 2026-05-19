# -*- coding: utf-8 -*-
"""라인별 워커 활용률 히트맵 (ver0_mod).

행=워크스테이션(라인), 열=시간bin, 색=활용률(점유 워커수/capacity, 0~1).
시뮬 1 에피소드(greedy)를 돌리며 매 SAMPLE_DT 마다
`worker_resources[ws].count / capacity` 를 샘플. 야간(18:00→08:00)은
영상과 동일하게 생략, 점심(12~13)은 비근무라 자연히 낮은 열(dip)로 보임.

ver0 는 워커 Resource 자체가 없는 직렬 모델이라 제외(활용률 개념이 무의미).
출력: worker_util_ver0_mod.png
"""
from __future__ import annotations
import os, sys, importlib
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

_DIR  = os.path.dirname(os.path.abspath(__file__))        # mod_run/ — 결과 저장처
_ROOT = os.path.dirname(_DIR)                             # 패키지 루트 — AAS JSON·root 모듈
sys.path.insert(0, _ROOT)
import path_extractor as pe

TARGET_PER_MODEL = {'MODEL_A': 100, 'MODEL_B': 100, 'MODEL_C': 100}
SAMPLE_DT  = 300.0              # 5 시뮬-분마다 점유 샘플
DISP_START = 28800             # 08:00 — 이 전(야간) 샘플은 버림 (영상과 동일)

for _f in ['ProvisionOfSimulationModel.json', 'WorkstationWorkerMatchingDataAAS.json',
           'MODEL_A.json', 'MODEL_B.json', 'MODEL_C.json']:
    pe.load(os.path.join(_ROOT, _f))
PSM = pe.ProvisionofSimulationModelsAAS
SM  = PSM.SimulationModels.SimulationModel
A   = SM.KnowledgeGraph.Action
DP  = SM.DefaultParameters
RW  = SM.RewardWeights

svm = importlib.import_module('simulation_ver0_mod')


class UtilEnv(svm.CproSimEnv):
    """reset() 에 점유 샘플러 코루틴을 끼워 활용률 시계열 기록 (동작 무변경)."""
    def reset(self):
        super().reset()
        self.util_ts   = []                        # [(now, {ws: util})]
        self.reason_ts = []                        # [(now, {ws: 사유코드})]  0~4
        self.env.process(self._sample_loop())

    def _line_reason(self, ws, res, work):
        # idle 사유 분해 (샘플 시점 env 상태만으로 — produce_unit 훅 불필요)
        if res.count > 0:
            return 0                                           # ACTIVE (점유중)
        if not work:
            return 1                                           # OFF (근무외/점심)
        kg = self.KnowledgeGraph
        pcs = [pc for pc in self.workers[ws]['ProcessCode'] if pc in kg.nodes]
        served = {kg.nodes[pc].model_id for pc in pcs}
        if served and all(self.Throughput[m] >= self.target_qty[m] for m in served):
            return 4                                           # DONE (담당 모델 생산완료)
        if pcs and all(not kg._bom_satisfied(pc, self.warehouse) for pc in pcs):
            return 2                                           # STOCK (라인 전 공정 재고부족)
        return 3                                                # PREC (선행 미완·해당 유닛 없음)

    def _sample_loop(self):
        while True:
            yield self.env.timeout(SAMPLE_DT)
            work = self._is_work_time()
            self.util_ts.append((self.env.now, {
                ws: res.count / res.capacity
                for ws, res in self.worker_resources.items()}))
            self.reason_ts.append((self.env.now, {
                ws: self._line_reason(ws, res, work)
                for ws, res in self.worker_resources.items()}))


def build():
    KG = svm.KnowledgeGraph.build(
        {mp.model_id: mp for mp in SM.Warehouse.InputBOM.target}, PSM.workers)
    WH = svm.Warehouse.build(PSM.CoManagedBOM, SM.Warehouse.MinStock.target)
    return UtilEnv(
        KnowledgeGraph=KG, warehouse=WH, workers=PSM.workers,
        IndependentSequence=[n.idShort for r in A.IndependentSequence for n in r.target],
        DependentSequence=[n.idShort for r in A.DependentSequence for n in r.target],
        DependentJoin=[n.idShort for r in A.DependentJoin for n in r.target],
        RewardWeights={k: float(RW[k].value) for k in
                       ['W1_TimeElapsed', 'W2_Energy', 'W3_StockOverflow',
                        'W4_StockShortage', 'W5_Throughput', 'W6_IdleWorker']},
        ReplenishLeadDay=int(DP.ReplenishLeadDay.value) * 3600,
        target_qty=dict(TARGET_PER_MODEL), MaxEpisodes=1,
        WarehouseManagedBOM=PSM.CoManagedBOM, BOMCategory=SM.Warehouse.MinStock.target,
        WorkStartTime=DP.WorkStartTime.target.value, WorkEndTime=DP.WorkEndTime.target.value,
        break_start_sec=DP.BreakDurationMin.target.min,
        break_end_sec=DP.BreakDurationMin.target.max,
        IdleWorkerThreshold=int(DP.IdleWorkerThreshold.value),
        RuntimeVariables=SM.RuntimeVariables,
        IdleProcessRatedPowerKw=float(DP.IdleProcessRatedPowerKw.value), IdlePowerRatio=0.10,
        SelfManagedBOM=PSM.SelfManagedBOM)


_R_LABEL = ['ACTIVE', 'OFF', 'STOCK', 'PREC', 'DONE']
_R_COLOR = ['#2ca02c', '#d9d9d9', '#d62728', '#ff7f0e', '#7f7f7f']


def render():
    env = build()
    summary = env.run()                            # greedy
    work_end = env.WorkEndTime
    win = lambda t: DISP_START <= (t % 86400) < work_end   # 표현 윈도우(08~18시)
    samples  = [(t, u) for (t, u) in env.util_ts   if win(t)]
    reasons  = [(t, r) for (t, r) in env.reason_ts if win(t)]
    if not samples:
        print('샘플 0 — 렌더 불가'); return
    lines = list(env.workers)                      # 영상(layout) 라인 컬럼 순서와 동일
    M = np.array([[u.get(ws, 0.0) for (_t, u) in samples] for ws in lines])
    R = np.array([[r.get(ws, 1)   for (_t, r) in reasons] for ws in lines])

    day_of = [int(t // 86400) for (t, _x) in samples]
    ntick = min(12, len(samples))
    idx = np.linspace(0, len(samples) - 1, ntick, dtype=int)
    xlab = [f'D{day_of[i]} {int(samples[i][0] % 86400)//3600:02d}h' for i in idx]

    fig, (axU, axR) = plt.subplots(
        2, 1, figsize=(16, max(7, len(lines) * 0.62)), sharex=True)

    imU = axU.imshow(M, aspect='auto', cmap='viridis', vmin=0, vmax=1,
                     interpolation='nearest')
    axU.set_yticks(range(len(lines)))
    axU.set_yticklabels([ln.replace('WWM_', '') for ln in lines], fontsize=7)
    axU.set_title(f'ver0_mod  per-line worker utilization (active/capacity)   '
                  f'thru={summary["Throughput"]}  makespan={summary["makespan_sec"]:.0f}s'
                  f'   [night omitted, lunch=dip]', fontsize=10)
    fig.colorbar(imU, ax=axU, fraction=0.022, pad=0.01).set_label('utilization', fontsize=8)

    from matplotlib.colors import ListedColormap
    import matplotlib.patches as mpatches
    imR = axR.imshow(R, aspect='auto', cmap=ListedColormap(_R_COLOR),
                     vmin=-0.5, vmax=4.5, interpolation='nearest')
    axR.set_yticks(range(len(lines)))
    axR.set_yticklabels([ln.replace('WWM_', '') for ln in lines], fontsize=7)
    axR.set_title('idle reason   OFF=off-hours/lunch   STOCK=all line procs BOM-blocked   '
                  'PREC=precedence wait / no unit   DONE=served models complete', fontsize=9)
    axR.legend(handles=[mpatches.Patch(color=_R_COLOR[i], label=_R_LABEL[i])
                        for i in range(5)],
               loc='upper center', bbox_to_anchor=(0.5, -0.18),
               ncol=5, fontsize=8, frameon=False)
    for ax in (axU, axR):
        for i in range(1, len(day_of)):
            if day_of[i] != day_of[i - 1]:
                ax.axvline(i - 0.5, color='white', lw=0.8, ls='--', alpha=0.6)
    axR.set_xticks(idx)
    axR.set_xticklabels(xlab, fontsize=7, rotation=30)

    fig.tight_layout()
    out = os.path.join(_DIR, 'worker_util_ver0_mod.png')
    fig.savefig(out, dpi=130)
    plt.close(fig)
    frac = {_R_LABEL[i]: round(float((R == i).mean()), 3) for i in range(5)}
    print(f'완료: {out}  (lines={len(lines)}, samples={len(samples)}, '
          f'mean_util={M.mean():.3f})  사유비중={frac}')


if __name__ == '__main__':
    render()
