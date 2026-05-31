# -*- coding: utf-8 -*-
"""events.jsonl → 워커 슬롯별 Gantt 재생성.
- 색: 연두 계열 3톤 (밝게).
- y라벨: 라인당 1개로 통합(슬롯 행은 유지).
- x축: 비근무시간(밤 18~9, 점심 12~13) 제거 후 D1, D2... 라벨링.
- 제목: makespan + 총 idle worker-h + busy% 동시 표기.
- cycle (워커 점유) = 진색만 표시. DepWait (워커 비점유) 는 렌더링하지 않음 (정책 — 2026-05-28).
- events.jsonl 스키마: {model, pc, line, t0, t_cycle, t_total} (구 스키마 t1 도 fallback 지원).
sim 재실행 없음.

호출:
  python _redraw_gantt_slots.py                       # 기본 current_render_05-25
  python _redraw_gantt_slots.py <runs_dir_name>       # 지정 runs 폴더 (예: dep_wait_05-27)
"""
import os, json, sys
import matplotlib; matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches

_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _DIR); sys.path.insert(0, os.path.dirname(_DIR))
import path_extractor as pe
import cpro_ver1_viz  # noqa: F401  (AAS load)
import simulation_ver1 as svm
PSM = pe.ProvisionofSimulationModelsAAS
SM  = PSM.SimulationModels.SimulationModel
WORKERS = PSM.workers
EXCLUDE = ('WWM_RMALine',)                              # RMA 는 아직 활동 X — 표시 제거. OQC 는 포함 (5% 샘플링).
LINES = [ln for ln in WORKERS if ln not in EXCLUDE]

# 모델별 terminal ProcessCode (KG 에서 outgoing edge 없는 노드 = 단위 완성 시점)
_MPs = {mp.model_id: mp for mp in SM.Warehouse.InputBOM.target}
_SHARED = {name: g for name, g in SM.KnowledgeGraph.Node.value.items() if name in ('ProcessOQC',)}
_KG  = svm.KnowledgeGraph.build(_MPs, PSM.workers, _SHARED)
_has_succ = set(_KG.edges.keys())
TERM_PER_MODEL = {}
for _pc, _n in _KG.nodes.items():
    if _pc not in _has_succ:
        TERM_PER_MODEL.setdefault(_n.model_id, set()).add(_pc)
# 연두 계열 밝은 톤 (LightLime / Lime / Forest)
COLOR = {'MODEL_A': '#C7EBA8',    # pale 연두
         'MODEL_B': '#7AC74F',    # bright 연두
         'MODEL_C': '#2E8B3F'}    # rich 연두

# argv 로 runs 폴더 받기 — 기본은 기존 current_render_05-25
_RUN_NAME = sys.argv[1] if len(sys.argv) > 1 else 'current_render_05-25'
OUT = os.path.join(_DIR, 'result', 'runs', _RUN_NAME)

# 근무시간 상수 — env 와 동일(AAS DefaultParameters 의 값)
WS_S = 32400      # 09:00
WS_E = 64800      # 18:00
LB   = 43200      # 12:00
LE   = 46800      # 13:00
DAY  = 86400
WORK_PER_DAY = (WS_E - WS_S) - (LE - LB)        # 8h = 28800s


def t_to_disp(t):
    """sim sec → display sec (비근무시간 제거 압축)."""
    day = int(t // DAY); in_day = t - day * DAY
    if in_day < WS_S:    d = 0
    elif in_day < LB:    d = in_day - WS_S
    elif in_day < LE:    d = LB - WS_S
    elif in_day < WS_E:  d = (in_day - LE) + (LB - WS_S)
    else:                d = WORK_PER_DAY
    return day * WORK_PER_DAY + d


def assign_slots(events, n_workers, units_per_worker=1):
    """slot 배정 — 슬롯 = 워커(n_workers). 워커 1명이 동시에 units_per_worker 개까지 처리.
    AGING(units_per_worker=10): 1워커가 여러 챔버를 병렬 모니터링 → 칸 수는 워커수만 (6),
    한 칸에 동시 여러 job 이 겹칠 수 있고 그건 "그 워커가 busy" 로만 본다 (1개든 10개든 동일).
    events = [(model, t0, t_cycle, t_total)]"""
    events = sorted(events, key=lambda e: e[1])
    slot_active = [[] for _ in range(n_workers)]   # 슬롯별 진행중 job 의 t_cycle 끝시간 리스트
    out = []
    for (m, t0, t_cyc, t_tot) in events:
        for i in range(n_workers):                  # t0 이전 끝난 job 정리
            slot_active[i] = [e for e in slot_active[i] if e > t0]
        free = [i for i in range(n_workers) if len(slot_active[i]) < units_per_worker]
        if free:
            idx = min(free, key=lambda i: len(slot_active[i]))   # 가장 한가한 워커
            actual_t0 = t0
        else:                                       # 전 워커가 units_per_worker 만큼 꽉 — 가장 빨리 한 자리 비는 워커
            idx = min(range(n_workers), key=lambda i: min(slot_active[i]))
            actual_t0 = max(t0, min(slot_active[idx]))
            slot_active[idx] = [e for e in slot_active[idx] if e > actual_t0]
        slot_active[idx].append(t_cyc)
        out.append((idx, m, actual_t0, t_cyc, t_tot))
    return out


def render(label, events_path, out_png, xmax_disp_h=None):
    rows = [json.loads(l) for l in open(events_path, encoding='utf-8')]
    by_line = {ln: [] for ln in LINES}
    for r in rows:
        if r['line'] in by_line:
            t_cyc = r.get('t_cycle', r.get('t1'))                # 구 스키마 fallback
            t_tot = r.get('t_total', r.get('t1'))
            by_line[r['line']].append((r['model'], r['t0'], t_cyc, t_tot))

    # 칸 수 = 워커수만. 1워커가 동시에 UnitsPerWorker 개 처리해도 "그 워커 busy" 로만 본다 (AGING 6칸).
    caps = {ln: WORKERS[ln]['worker_count'] for ln in LINES}
    assigned = {ln: assign_slots(by_line[ln], caps[ln], WORKERS[ln]['UnitsPerWorker']) for ln in LINES}
    total_rows = sum(caps.values())
    y_of = {}; y = 0; line_centers = {}; line_sep = []
    for ln in LINES:
        line_sep.append(y)
        slot_ys = []
        for k in range(caps[ln]):
            y_of[(ln, k)] = y; slot_ys.append(y); y += 1
        line_centers[ln] = (slot_ys[0] + slot_ys[-1]) / 2

    fig, (ax, ax_b) = plt.subplots(
        2, 1, figsize=(18, max(8, total_rows * 0.16) + 2.2),
        gridspec_kw={'height_ratios': [max(8, total_rows * 0.16), 2.0]},
        sharex=True)
    own_ms_sec = max((r.get('t_total', r.get('t1')) for r in rows), default=1)
    own_ms_h   = own_ms_sec / 3600
    own_disp_h = t_to_disp(own_ms_sec) / 3600
    xmax = xmax_disp_h if xmax_disp_h is not None else own_disp_h * 1.02

    # bar: t_to_disp 적용한 display 좌표(시간단위)
    # DepWait 구간(워커 비점유)은 렌더링하지 않는다 (정책 — 2026-05-28). cycle(워커 점유)만 표시.
    # assigned 는 위에서 이미 계산 (slot 배정 → 행 수 산정).
    # cycle 구간 (워커 점유) 진색. 같은 슬롯(워커)에 여러 job 겹쳐도 색 동일 = busy.
    for ln in LINES:
        for (slot, m, t0_a, t_cyc, t_tot) in assigned[ln]:
            d0 = t_to_disp(t0_a); d_cyc = t_to_disp(t_cyc)
            ax.broken_barh([(d0 / 3600, (d_cyc - d0) / 3600)],
                           (y_of[(ln, slot)] - 0.42, 0.84),
                           facecolors=COLOR.get(m, '#888'), linewidth=0)
    # used = 슬롯(워커) busy 시간 union (겹친 job 중복 제거). 1워커가 10제품 봐도 busy 시간은 union.
    used_disp_sec = 0.0
    for ln in LINES:
        per_slot = {}
        for (slot, m, t0_a, t_cyc, t_tot) in assigned[ln]:
            per_slot.setdefault(slot, []).append((t_to_disp(t0_a), t_to_disp(t_cyc)))
        for intervals in per_slot.values():
            intervals.sort()
            merged_end = -1.0
            for s, e in intervals:
                s = max(s, merged_end)
                if e > s:
                    used_disp_sec += (e - s)
                    merged_end = max(merged_end, e)

    # 라인 경계
    for sep in line_sep[1:]:
        ax.axhline(sep - 0.5, color='0.85', lw=0.6)
    # 일 경계(작업일 단위, 8h 마다) + 점심 시각 표시(4h 마다 = 점심 끝지점)
    ndays = int(xmax * 3600 / WORK_PER_DAY) + 1
    for d in range(ndays + 1):
        ax.axvline(d * 8, color='0.85', lw=0.7)
    # 본 run makespan 점선
    ax.axvline(own_disp_h, color='#444', lw=1.2, ls='--', alpha=0.7)

    # x축: 라벨 2 work-h 마다 (D1 / +2h / +4h / +6h / D2 / ...), minor tick 0.5h
    major = [t for t in range(0, int(xmax) + 1, 2)]
    def _lab(t):
        day, hr = divmod(t, 8)
        return f'D{day+1}' if hr == 0 else f'+{hr}h'
    ax.set_xticks(major); ax.set_xticklabels([_lab(t) for t in major], fontsize=9)
    minor = [i * 0.5 for i in range(int(xmax / 0.5) + 1) if (i * 0.5) % 2 != 0]
    ax.set_xticks(minor, minor=True)
    ax.tick_params(axis='x', which='major', length=7)
    ax.tick_params(axis='x', which='minor', length=3)

    # y축 라벨: 라인당 1개 (슬롯 행은 유지, 라벨만 통합)
    ax.set_yticks([line_centers[ln] for ln in LINES])
    ax.set_yticklabels([ln.replace('WWM_', '').replace('Line', '') for ln in LINES],
                       fontsize=10)
    ax.tick_params(axis='y', length=0)

    ax.set_ylim(-0.5, total_rows - 0.5)
    ax.invert_yaxis()
    ax.set_xlim(0, xmax)
    ax.set_xlabel('')                                              # 군더더기 제거

    # idle 계산: total worker work-hours during 본 run makespan
    avail_disp_sec = t_to_disp(own_ms_sec) * total_rows           # 슬롯 = 워커 수
    used_h  = used_disp_sec / 3600
    idle_h  = avail_disp_sec / 3600 - used_h

    ax.set_title(f'{label}   makespan={own_ms_h:.1f}h   idle={idle_h:.0f} worker·h',
                 fontsize=12)

    ax.text(own_disp_h / xmax, 1.005, f'↓ makespan',
            transform=ax.transAxes, fontsize=9, color='#444', va='bottom', ha='center')
    ax.legend(handles=[mpatches.Patch(color=c, label=m) for m, c in COLOR.items()],
              loc='upper right', ncol=3, fontsize=9, frameon=False)

    # ====== 하단 subplot: 모델별 누적 완성 수량 (terminal PC 의 t_total 카운트) ======
    completions = {m: [] for m in TERM_PER_MODEL}
    for r in rows:
        if r['pc'] in TERM_PER_MODEL.get(r['model'], set()):
            t_done = r.get('t_total', r.get('t1'))              # 새 스키마 우선
            completions[r['model']].append(t_to_disp(t_done) / 3600)
    for m, ts in completions.items():
        ts.sort()
        if not ts: continue
        xs = [0] + ts + [xmax]
        ys = [0] + list(range(1, len(ts) + 1)) + [len(ts)]
        ax_b.step(xs, ys, where='post', label=f'{m} ({len(ts)})',
                  color=COLOR[m], lw=1.6)
    ax_b.axvline(own_disp_h, color='#444', lw=1.0, ls='--', alpha=0.6)
    for d in range(ndays + 1):
        ax_b.axvline(d * 8, color='0.85', lw=0.7)
    ax_b.set_xlim(0, xmax)
    ax_b.set_ylim(0, max(len(ts) for ts in completions.values()) * 1.05)
    ax_b.set_ylabel('cumulative\ncompleted', fontsize=10)
    ax_b.legend(loc='lower right', fontsize=9, frameon=False)
    ax_b.grid(axis='y', alpha=0.3)

    fig.subplots_adjust(left=0.06, right=0.985, top=0.945, bottom=0.06, hspace=0.04)
    fig.savefig(out_png, dpi=130); plt.close(fig)
    print(f'  saved {out_png}  (used={used_h:.0f}h idle={idle_h:.0f}h, '
          f'completed={ {m: len(ts) for m, ts in completions.items()} })')


if __name__ == '__main__':
    LABELS = ('greedy', 'trained_det')
    print(f'대상 폴더: {OUT}')
    xmax = 0.0
    for label in LABELS:
        ev_p = os.path.join(OUT, f'events_{label}.jsonl')
        if os.path.exists(ev_p):
            ms = max((json.loads(l).get('t_total', json.loads(l).get('t1', 0))
                      for l in open(ev_p, encoding='utf-8')), default=0)
            xmax = max(xmax, t_to_disp(ms) / 3600)
    xmax *= 1.02
    print(f'공통 x-축(work-h): 0 ~ {xmax:.1f}h')
    for label in LABELS:
        ev_p = os.path.join(OUT, f'events_{label}.jsonl')
        if os.path.exists(ev_p):
            render(label, ev_p, os.path.join(OUT, f'gantt_{label}.png'), xmax_disp_h=xmax)
        else:
            print(f'  skip {label}: {ev_p} 없음')
