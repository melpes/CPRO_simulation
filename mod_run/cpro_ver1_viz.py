# -*- coding: utf-8 -*-
"""ver1 공장 물류·작업 흐름 동영상 + 시각화 유틸 (관측용).

- ver1  : 워커 디스패처(_run_job) 경로. produce_unit + 워커 capacity.  → factory_ver1.mp4
A/B/C 각 100개 주문, greedy/학습. (구 ver0/ver0_mod 비교판은 _gantt3 와 함께 legacy.)

시간축: 야간(퇴근 18:00 ~ 출근 08:00)은 영상에서 생략하고 08:00~18:00 만
표현(=하루 중 08~09시 + 근무 + 점심까지 보임). 점심(12~13)은 그대로 표현.
동작/수치 무변경 — CproSimEnv subclass 로 _run_job 만 감싸 이벤트 기록.
make_envs() 는 _capture_and_gantt / _render_trained_det 의 env 진입점이기도 하다.
"""
from __future__ import annotations
import os, importlib, bisect
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.animation import FuncAnimation, FFMpegWriter

import os, sys
_DIR  = os.path.dirname(os.path.abspath(__file__))        # mod_run/ — 결과 저장처
_ROOT = os.path.dirname(_DIR)                             # 패키지 루트 — AAS JSON·root 모듈
sys.path.insert(0, _ROOT)
import path_extractor as pe

# ====== 설정 ======
TARGET_PER_MODEL = {'MODEL_A': 100, 'MODEL_B': 100, 'MODEL_C': 100}
DISP_START   = 28800            # 08:00 — 이 시각부터 표현 (그 전 야간 생략)
SIM_HOUR_TO_SEC = 1.2           # 표현되는 시뮬 1h → 1.2 real-sec (≈현재 effective 재생속도 고정)
FPS          = 15
MAX_FRAMES   = 99999            # 사실상 캡 해제 — 영상 길이 = D(=근무시간 합산)/base_spf 비례
TRANSITION_HOLD_FRAMES = 1
MAX_EVENTS   = 60000            # 100*3 유닛 안전 상한

# ====== AAS 로드 (루트에서) ======
for _f in ['ProvisionOfSimulationModel.json', 'WorkstationWorkerMatchingDataAAS.json',
           'MODEL_A.json', 'MODEL_B.json', 'MODEL_C.json']:
    pe.load(os.path.join(_ROOT, 'aas_data', _f))
PSM = pe.ProvisionofSimulationModelsAAS
SM  = PSM.SimulationModels.SimulationModel
A   = SM.KnowledgeGraph.Action
DP  = SM.DefaultParameters
RW  = SM.RewardWeights

PCB_CATS  = set(PSM.SelfManagedBOM.keys())                 # PCB(SelfManaged) 카테고리(=SMT_PCB)
PCB_MODEL = {e.idShort: aas.submodels['ManufacturingProcess'].model_id
             for aas in pe.ProductAAS
             for e in aas.submodels['HierarchicalStructures']._walk_entities()
             if e.Qualifier.get('Category') in PCB_CATS}   # PCB item_code → 소속 모델


# ====== 이벤트 기록 mixin (process_job 만 감쌈, 동작 무변경) ======
class _Rec:
    def _init_rec(self):
        self.events = []                       # (model, pc, line, t0, t1)
        self.stock_ts = [(0.0, self._stock_totals())]

    def _stock_totals(self):
        # 일반 부품: 카테고리별 합계 / PCB: item_code 별 재고 (모델색용)
        reg, pcb = {}, {}
        for c, items in self.warehouse.inventory.items():
            if c in PCB_CATS:
                for code, it in items.items():
                    pcb[code] = it.present_stock
            else:
                reg[c] = sum(it.present_stock for it in items.values())
        return {'reg': reg, 'pcb': pcb}

    def _line_of(self, pc):
        return next((w for w in self.workers if pc in self.workers[w]['ProcessCode']), '?')

    def _record(self, pc, t0):
        m = self.KnowledgeGraph.nodes[pc].model_id
        self.events.append((m, pc, self._line_of(pc), t0, self.env.now))
        self.stock_ts.append((self.env.now, self._stock_totals()))


def make_envs():
    """ver1 기록용 env 생성 (워커 디스패처 _run_job 경로). wiring 은 cpro_factory 단일 구현."""
    import simulation_ver1 as sv1
    import cpro_factory as cf

    class RecMod(_Rec, sv1.CproSimEnv):             # ver1: _run_job 가 실제 실행 — 여기서 이벤트 기록
        def reset(self):
            super().reset(); self._init_rec()
        def _run_job(self, ws, job, req):
            t0 = self.env.now
            pc = job['pc']
            yield from super()._run_job(ws, job, req)
            self._record(pc, t0)

    env = cf.build_simulation(env_cls=RecMod, target_qty=dict(TARGET_PER_MODEL), MaxEpisodes=1)
    return [('ver1', env, 'run')]


def drive_serial(env):
    obs = env.reset()
    done = False
    while not done and len(env.events) < MAX_EVENTS:
        ready = obs['ready']
        if not ready:
            obs, deadlock = env.skip()
            if deadlock:
                break
            continue
        pc = ready[0]
        ws = next(w for w in env.workers if pc in env.workers[w]['ProcessCode'])
        obs, _, done, _ = env.step((pc, ws))
    return env.events, env.stock_ts


def drive_run(env, agent=None):
    env.run(agent=agent)                            # agent=None=greedy / 학습 정책 = pass agent
    return env.events, env.stock_ts


# ====== 레이아웃: x=라인 컬럼, y=라인 내 공정 순서 ======
def layout(env):
    lines, pos, line_x = list(env.workers), {}, {}
    for xi, ln in enumerate(lines):
        line_x[ln] = xi
        pcs = [p for p in env.workers[ln]['ProcessCode'] if p in env.KnowledgeGraph.nodes]
        n = max(len(pcs), 1)
        for yi, p in enumerate(pcs):
            pos[p] = (xi, 1.0 - (yi + 0.5) / n)
    return lines, line_x, pos


def _disp_segments(makespan, disp_end):
    # [0, makespan] 중 '표현되는' 구간들: 매일 [DISP_START, disp_end].
    segs = []
    day = 0
    while day * 86400 + DISP_START < makespan:
        s = day * 86400 + DISP_START
        e = min(day * 86400 + disp_end, makespan)
        if e > s:
            segs.append((s, e))
        day += 1
    return segs or [(0.0, makespan)]   # 전 구간이 08:00 이전이면 생략 없이 전체


def render(name, env, mode, agent=None):
    events, stock_ts = (drive_run(env, agent) if mode == 'run' else drive_serial(env))
    out = os.path.join(_DIR, f'factory_{name}.mp4')
    if not events:
        print(f'[{name}] 이벤트 0 — 렌더 불가'); return
    makespan = max(e[4] for e in events)
    disp_end = env.WorkEndTime
    segs = _disp_segments(makespan, disp_end)
    D = sum(e - s for s, e in segs) or 1.0
    base_spf = 3600.0 / (SIM_HOUR_TO_SEC * FPS)
    n_frames = min(MAX_FRAMES, int(D / base_spf) + 2)
    spf = D / n_frames                              # 표현 구간 전체를 영상에 담음

    def disp_to_real(dt):                           # 표현시간 → 실제 sim-time
        for s, e in segs:
            ln = e - s
            if dt < ln:
                return s + dt
            dt -= ln
        return segs[-1][1]

    def real_to_frame(t):                           # 실제 sim-time → 프레임 (gap 이면 None)
        disp = 0.0
        for s, e in segs:
            if t >= e:
                disp += e - s
            elif t < s:
                return None
            else:
                return int((disp + (t - s)) / spf)
        return None

    evs = sorted(events, key=lambda e: (e[3], e[4]))
    comp = {}
    for (_m, _pc, _ln, _t0, _t1) in evs:
        comp.setdefault(_pc, []).append(_t1)
    for v in comp.values():
        v.sort()
    transitions = []
    for (m, pc, ln, t0, t1) in evs:
        f = real_to_frame(t0)
        if f is None:
            continue
        for pred in env.KnowledgeGraph._predecessors(pc):
            ts = comp.get(pred)
            if ts and bisect.bisect_right(ts, t0) > 0:
                transitions.append((f, pred, pc, m))

    lines, line_x, pos = layout(env)
    KG = env.KnowledgeGraph
    # 라인별 실시간 전력용: 공정 active 면 RatedPowerKw, 아니면 idle_kw
    # (path_extractor.IdlePowerKw 단일 구현 재사용 — 에너지 모델과 일치).
    idle_kw  = {pc: env.RuntimeVariables.IdlePowerKw(
                    KG.nodes[pc], env.IdleProcessRatedPowerKw, env.IdlePowerRatio)
                for pc in KG.nodes}
    rated_kw = {pc: KG.nodes[pc].RatedPowerKw for pc in KG.nodes}
    line_pcs = {ln: [pc for pc in env.workers[ln]['ProcessCode'] if pc in KG.nodes]
                for ln in lines}
    max_line_pow = max((sum(rated_kw[pc] for pc in pcs)
                        for pcs in line_pcs.values()), default=1.0) or 1.0
    # 공장 전체 전력 총합 시계열 (프레임별 사전계산 — 정적 곡선 + 진행 마커).
    all_pcs  = list(KG.nodes)
    frame_T  = [disp_to_real(fi * spf) for fi in range(n_frames)]
    tot_pow  = []
    for _T in frame_T:
        _act = {pc for (m, pc, ln, t0, t1) in evs if t0 <= _T < t1}
        tot_pow.append(sum(rated_kw[pc] if pc in _act else idle_kw[pc]
                           for pc in all_pcs))
    tot_peak   = max(tot_pow) if tot_pow else 1.0
    idle_floor = sum(idle_kw.values())            # 전 공정 idle (최소 가능 총전력)
    models = list(TARGET_PER_MODEL)
    cmap = {m: c for m, c in zip(models, ['tab:blue', 'tab:orange', 'tab:green'])}
    reg_cats  = list(stock_ts[0][1]['reg'])
    pcb_codes = sorted(stock_ts[0][1]['pcb'],                 # 모델별로 묶여 색 블록
                       key=lambda c: (PCB_MODEL.get(c, ''), c))
    pcb_color = [cmap.get(PCB_MODEL.get(c), 'gray') for c in pcb_codes]
    term_t = {m: sorted(t1 for (mm, pc, ln, t0, t1) in evs   # 모델별 terminal 완료시각
                        if mm == m and pc not in KG.edges) for m in models}
    thru_final = {m: len(term_t[m]) for m in models}
    fig = plt.figure(figsize=(15, 9.5))
    gs  = fig.add_gridspec(4, 2, width_ratios=[3.4, 1],
                           height_ratios=[1, 1, 1, 0.55], hspace=0.42)
    axF = fig.add_subplot(gs[0:3, 0])                         # 공장 (상단 3행 span)
    axS = fig.add_subplot(gs[0, 1])                           # 일반 부품 재고
    axP = fig.add_subplot(gs[1, 1])                           # PCB 재고 (모델색)
    axPow = fig.add_subplot(gs[2, 1])                         # 라인별 실시간 전력(kW)
    axTot = fig.add_subplot(gs[3, :])                         # 공장 전체 전력 총합 시계열
    print(f'[{name}] events={len(events)} makespan={makespan:.0f}s '
          f'frames={n_frames} thru={thru_final} → {out}')

    def stock_at(t):
        cur = stock_ts[0][1]
        for ts, snap in stock_ts:
            if ts <= t:
                cur = snap
            else:
                break
        return cur

    def draw(fi):
        T = disp_to_real(fi * spf)
        axF.clear(); axS.clear(); axP.clear(); axPow.clear(); axTot.clear()
        active = {pc for (m, pc, ln, t0, t1) in evs if t0 <= T < t1}
        for ln, xi in line_x.items():
            axF.axvspan(xi - 0.45, xi + 0.45, color='0.95', zorder=0)
            axF.text(xi, 1.06, ln.replace('WWM_', ''), ha='center', va='bottom',
                     fontsize=7, rotation=20)
        for dp, eds in KG.edges.items():
            if dp not in pos:
                continue
            for ed in eds:
                if ed.ProcessCode in pos:
                    x0, y0 = pos[dp]; x1, y1 = pos[ed.ProcessCode]
                    axF.plot([x0, x1], [y0, y1], color='0.8', lw=0.5, zorder=1)
        for p, (x, y) in pos.items():
            axF.scatter([x], [y], s=120, facecolors='white',
                        edgecolors='0.6', zorder=2)
        for (m, pc, ln, t0, t1) in evs:
            if pc in pos and t0 <= T < t1:
                x, y = pos[pc]
                axF.scatter([x], [y], s=300, facecolors='none',
                            edgecolors=cmap.get(m, 'gray'), linewidths=1.6, zorder=3)
                axF.scatter([x], [y], s=110, color=cmap.get(m, 'gray'),
                            edgecolors='black', linewidths=0.6, zorder=4)
        for hf, pa, pb, mdl in transitions:
            if hf <= fi < hf + TRANSITION_HOLD_FRAMES and pa in pos and pb in pos:
                x0, y0 = pos[pa]; x1, y1 = pos[pb]
                axF.plot([x0, x1], [y0, y1], color=cmap.get(mdl, 'gray'),
                         lw=3.4, alpha=0.95, zorder=2.5, solid_capstyle='round')
        dday, rem = divmod(int(T), 86400)
        hh, rem = divmod(rem, 3600); mm, ss = divmod(rem, 60)
        sod = T % 86400
        lunch = env.break_start_sec <= sod < env.break_end_sec
        onwork = env.WorkStartTime <= sod < env.WorkEndTime and not lunch
        tag = 'LUNCH' if lunch else ('WORK' if onwork else 'OFF ')
        thru = {m: bisect.bisect_right(term_t[m], T) for m in models}
        axF.set_title(f'{name}  D{dday} {hh:02d}:{mm:02d}:{ss:02d} [{tag}]   '
                      + '  '.join(f'{m.split("_")[1]}:{thru[m]}/{TARGET_PER_MODEL[m]}'
                                  for m in models), fontsize=11)
        axF.set_xlim(-0.7, len(lines) - 0.3); axF.set_ylim(-0.05, 1.18)
        axF.axis('off')
        handles = [plt.Line2D([0], [0], marker='o', color='w', label=m,
                              markerfacecolor=cmap[m], markersize=9) for m in models]
        axF.legend(handles=handles, loc='lower left', fontsize=8, ncol=3)
        snap = stock_at(T)
        # 일반 부품: 카테고리별 합계
        rv = [snap['reg'].get(c, 0) for c in reg_cats]
        axS.barh(range(len(reg_cats)), rv,
                 color=['crimson' if v < 0 else 'steelblue' for v in rv])
        axS.set_yticks([])
        axS.axvline(0, color='black', lw=0.6)
        axS.set_title(f'Parts stock / Category ({len(reg_cats)})', fontsize=9)
        # PCB: item_code 별, 모델색
        pv = [snap['pcb'].get(c, 0) for c in pcb_codes]
        axP.barh(range(len(pcb_codes)), pv, color=pcb_color)
        axP.set_yticks([])
        axP.axvline(0, color='black', lw=0.6)
        axP.set_title(f'PCB stock / item — model color ({len(pcb_codes)})', fontsize=9)
        # 라인별 실시간 전력: 각 라인 = Σ(공정 active 면 rated, 아니면 idle_kw).
        # 공정 단위(인스턴스 무관) — active 1개 이상이면 rated 로 본다.
        line_pow = [sum(rated_kw[pc] if pc in active else idle_kw[pc]
                        for pc in line_pcs[ln]) for ln in lines]
        bar_color = ['orangered' if any(pc in active for pc in line_pcs[ln])
                     else 'slategray' for ln in lines]
        axPow.barh(range(len(lines)), line_pow, color=bar_color)
        axPow.set_yticks(range(len(lines)))
        axPow.set_yticklabels([ln.replace('WWM_', '') for ln in lines], fontsize=6)
        axPow.invert_yaxis()
        axPow.set_xlim(0, max_line_pow * 1.05)
        axPow.set_title(f'Line power kW (Σ={sum(line_pow):.0f})', fontsize=9)
        # 공장 전체 전력 총합: 정적 시계열 + 현재 프레임 진행 마커.
        xs = range(n_frames)
        axTot.plot(xs, tot_pow, color='firebrick', lw=1.0)
        axTot.fill_between(xs, tot_pow, color='firebrick', alpha=0.15)
        cur_fi = min(fi, n_frames - 1)
        axTot.axvline(cur_fi, color='black', lw=1.2)
        axTot.scatter([cur_fi], [tot_pow[cur_fi]], s=22, color='black', zorder=3)
        axTot.set_xlim(0, n_frames - 1)
        axTot.set_ylim(0, tot_peak * 1.08)
        nt = min(8, n_frames)
        tk = [round(i * (n_frames - 1) / (nt - 1)) for i in range(nt)] if nt > 1 else [0]
        axTot.set_xticks(tk)
        axTot.set_xticklabels(
            [f'D{int(frame_T[i])//86400} {int(frame_T[i])%86400//3600:02d}h' for i in tk],
            fontsize=7)
        axTot.set_ylabel('kW', fontsize=8)
        axTot.axhline(idle_floor, color='gray', lw=0.8, ls='--', alpha=0.7)
        axTot.set_title(f'Factory total power kW — now {tot_pow[cur_fi]:.0f}  '
                        f'(peak {tot_peak:.0f}, idle floor {idle_floor:.0f})', fontsize=9)
        axTot.grid(True, alpha=0.25)

    ani = FuncAnimation(fig, draw, frames=n_frames, interval=1000 / FPS)
    ani.save(out, writer=FFMpegWriter(fps=FPS, bitrate=2400))
    plt.close(fig)
    print(f'[{name}] 완료: {out}  ({n_frames / FPS:.0f}s, {len(events)} events)')


if __name__ == '__main__':
    for _name, _env, _mode in make_envs():
        render(_name, _env, _mode)
