# -*- coding: utf-8 -*-
from __future__ import annotations
import os, sys, json, bisect
from typing import Dict, List, Optional, Tuple
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.animation import FuncAnimation, FFMpegWriter

_DIR  = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_DIR)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
import path_extractor as pe
import knowledge_graph as kg_mod


#========AAS 로드========
for _file in ['ProvisionOfSimulationModel.json', 'WorkstationWorkerMatchingDataAAS.json',
              'MODEL_A.json', 'MODEL_B.json', 'MODEL_C.json']:
    pe.load(os.path.join(_ROOT, 'aas_data', _file))
PSM     = pe.ProvisionofSimulationModelsAAS
SM      = PSM.SimulationModels.SimulationModel
WORKERS = PSM.workers
DEFAULT_TARGET = {model_id: quantity                                  #← SimulationModel/PurchaseOrder
                  for model_id, (quantity, DueDay, RegisteredDay) in SM.PurchaseOrder.items()}
PCB_CATS  = set(PSM.SelfManagedBOM.keys())
PCB_MODEL = {entity.idShort: aas.submodels['ManufacturingProcess'].model_id
             for aas in pe.ProductAAS
             for entity in aas.submodels['HierarchicalStructures']._walk_entities()
             if entity.Qualifier.get('Category') in PCB_CATS}


#========영상 렌더 설정========
DISP_START             = 28800
SIM_HOUR_TO_SEC        = 1.2
FPS                    = 15
MAX_FRAMES             = 99999
TRANSITION_HOLD_FRAMES = 1
MAX_EVENTS             = 60000


#========간트 렌더 설정========
EXCLUDE      = ('WWM_RMALine',)
LINES        = [ln for ln in WORKERS if ln not in EXCLUDE]
WS_S, WS_E   = 32400, 64800
LB,   LE     = 43200, 46800
DAY          = 86400
WORK_PER_DAY = (WS_E - WS_S) - (LE - LB)
GANTT_COLOR  = {'MODEL_A': '#C7EBA8', 'MODEL_B': '#7AC74F', 'MODEL_C': '#2E8B3F'}

_MPs    = {mp.model_id: mp for mp in SM.Warehouse.InputBOM.target}
_SHARED = {name: group for name, group in SM.KnowledgeGraph.Node.value.items()
           if name in ('ProcessOQC',)}
_KG       = kg_mod.KnowledgeGraph.build(_MPs, PSM.workers, _SHARED)
_has_succ = set(_KG.edges.keys())
TERM_PER_MODEL: Dict[str, set] = {}
for _pc, _node in _KG.nodes.items():
    if _pc not in _has_succ:
        TERM_PER_MODEL.setdefault(_node.model_id, set()).add(_pc)


#========기록 env (영상·간트 공용 RecEnv: model,pc,line,t0,t_cycle,t_total + stock_ts)========
def _recording_env(target_qty: Optional[Dict[str, int]] = None, seed: int = 42, **policy):
    import random
    import simulation as sv
    import build as cf
    random.seed(seed)

    class RecEnv(sv.CproSimEnv):
        def reset(self):
            super().reset()
            self.events   = []
            self.stock_ts = [(0.0, self._stock_totals())]
            self.oqc_actual = 0

        def _stock_totals(self):
            reg, pcb = {}, {}
            for category, items in self.warehouse.inventory.items():
                if category in PCB_CATS:
                    for code, item in items.items():
                        pcb[code] = item.present_stock
                else:
                    reg[category] = sum(item.present_stock for item in items.values())
            return {'reg': reg, 'pcb': pcb}

        def _line_of(self, pc):
            return next((w for w in self.workers if pc in self.workers[w]['ProcessCode']), '?')

        def _run_job(self, ws, job, req):
            t0   = self.env.now
            pc   = job['pc']
            node = self.KnowledgeGraph.nodes[pc]
            if pc == 'OQC':
                self.oqc_actual += 1
            yield from super()._run_job(ws, job, req)
            t_cycle = t0 + node.CycleTimeSec
            self.events.append((node.model_id, pc, self._line_of(pc), t0, t_cycle, self.env.now))
            self.stock_ts.append((self.env.now, self._stock_totals()))

    target = dict(target_qty) if target_qty is not None else dict(DEFAULT_TARGET)
    return cf.build_simulation(env_cls=RecEnv, target_qty=target, MaxEpisodes=1, **policy)


def drive_serial(env):
    obs  = env.reset()
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
    env.run(agent=agent)
    return env.events, env.stock_ts


#========영상 렌더 (factory animation → mp4)========
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
    segs = []
    day = 0
    while day * 86400 + DISP_START < makespan:
        s = day * 86400 + DISP_START
        e = min(day * 86400 + disp_end, makespan)
        if e > s:
            segs.append((s, e))
        day += 1
    return segs or [(0.0, makespan)]


def render_video(name: str, env, mode: str, agent=None, out_dir: Optional[str] = None) -> Optional[str]:
    events, stock_ts = (drive_run(env, agent) if mode == 'run' else drive_serial(env))
    out_dir = out_dir or os.path.join(_ROOT, 'result', 'viz')
    os.makedirs(out_dir, exist_ok=True)
    out = os.path.join(out_dir, f'factory_{name}.mp4')
    if not events:
        print(f'[{name}] 이벤트 0 — 렌더 불가'); return None
    makespan = max(e[5] for e in events)
    disp_end = env.WorkEndTime
    segs = _disp_segments(makespan, disp_end)
    D = sum(e - s for s, e in segs) or 1.0
    base_spf = 3600.0 / (SIM_HOUR_TO_SEC * FPS)
    n_frames = min(MAX_FRAMES, int(D / base_spf) + 2)
    spf = D / n_frames

    def disp_to_real(dt):
        for s, e in segs:
            ln = e - s
            if dt < ln:
                return s + dt
            dt -= ln
        return segs[-1][1]

    def real_to_frame(t):
        disp = 0.0
        for s, e in segs:
            if t >= e:
                disp += e - s
            elif t < s:
                return None
            else:
                return int((disp + (t - s)) / spf)
        return None

    evs = sorted(events, key=lambda e: (e[3], e[5]))
    comp = {}
    for (_m, _pc, _ln, _t0, _tc, _t1) in evs:
        comp.setdefault(_pc, []).append(_t1)
    for v in comp.values():
        v.sort()
    transitions = []
    for (m, pc, ln, t0, _tc, t1) in evs:
        f = real_to_frame(t0)
        if f is None:
            continue
        for pred in env.KnowledgeGraph._predecessors(pc):
            ts = comp.get(pred)
            if ts and bisect.bisect_right(ts, t0) > 0:
                transitions.append((f, pred, pc, m))

    lines, line_x, pos = layout(env)
    KG = env.KnowledgeGraph
    idle_kw  = {pc: env.RuntimeVariables.IdlePowerKw(
                    KG.nodes[pc], env.IdleProcessRatedPowerKw)
                for pc in KG.nodes}
    rated_kw = {pc: KG.nodes[pc].RatedPowerKw for pc in KG.nodes}
    line_pcs = {ln: [pc for pc in env.workers[ln]['ProcessCode'] if pc in KG.nodes]
                for ln in lines}
    max_line_pow = max((sum(rated_kw[pc] for pc in pcs)
                        for pcs in line_pcs.values()), default=1.0) or 1.0
    all_pcs  = list(KG.nodes)
    frame_T  = [disp_to_real(fi * spf) for fi in range(n_frames)]
    tot_pow  = []
    for _T in frame_T:
        _act = {pc for (m, pc, ln, t0, _tc, t1) in evs if t0 <= _T < t1}
        tot_pow.append(sum(rated_kw[pc] if pc in _act else idle_kw[pc]
                           for pc in all_pcs))
    tot_peak   = max(tot_pow) if tot_pow else 1.0
    idle_floor = sum(idle_kw.values())
    models = list(env.target_qty)
    cmap = {m: c for m, c in zip(models, ['tab:blue', 'tab:orange', 'tab:green'])}
    reg_cats  = list(stock_ts[0][1]['reg'])
    pcb_codes = sorted(stock_ts[0][1]['pcb'],
                       key=lambda c: (PCB_MODEL.get(c, ''), c))
    pcb_color = [cmap.get(PCB_MODEL.get(c), 'gray') for c in pcb_codes]
    term_t = {m: sorted(t1 for (mm, pc, ln, t0, _tc, t1) in evs
                        if mm == m and pc not in KG.edges) for m in models}
    fig = plt.figure(figsize=(15, 9.5))
    gs  = fig.add_gridspec(4, 2, width_ratios=[3.4, 1],
                           height_ratios=[1, 1, 1, 0.55], hspace=0.42)
    axF = fig.add_subplot(gs[0:3, 0])
    axS = fig.add_subplot(gs[0, 1])
    axP = fig.add_subplot(gs[1, 1])
    axPow = fig.add_subplot(gs[2, 1])
    axTot = fig.add_subplot(gs[3, :])
    print(f'[{name}] events={len(events)} makespan={makespan:.0f}s '
          f'frames={n_frames} → {out}')

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
        active = {pc for (m, pc, ln, t0, _tc, t1) in evs if t0 <= T < t1}
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
        for (m, pc, ln, t0, _tc, t1) in evs:
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
                      + '  '.join(f'{m.split("_")[1]}:{thru[m]}/{env.target_qty[m]}'
                                  for m in models), fontsize=11)
        axF.set_xlim(-0.7, len(lines) - 0.3); axF.set_ylim(-0.05, 1.18)
        axF.axis('off')
        handles = [plt.Line2D([0], [0], marker='o', color='w', label=m,
                              markerfacecolor=cmap[m], markersize=9) for m in models]
        axF.legend(handles=handles, loc='lower left', fontsize=8, ncol=3)
        snap = stock_at(T)
        rv = [snap['reg'].get(c, 0) for c in reg_cats]
        axS.barh(range(len(reg_cats)), rv,
                 color=['crimson' if v < 0 else 'steelblue' for v in rv])
        axS.set_yticks([])
        axS.axvline(0, color='black', lw=0.6)
        axS.set_title(f'Parts stock / Category ({len(reg_cats)})', fontsize=9)
        pv = [snap['pcb'].get(c, 0) for c in pcb_codes]
        axP.barh(range(len(pcb_codes)), pv, color=pcb_color)
        axP.set_yticks([])
        axP.axvline(0, color='black', lw=0.6)
        axP.set_title(f'PCB stock / item — model color ({len(pcb_codes)})', fontsize=9)
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
    return out


#========간트 렌더 (events.jsonl → png)========
def t_to_disp(t):
    day = int(t // DAY); in_day = t - day * DAY
    if in_day < WS_S:    d = 0
    elif in_day < LB:    d = in_day - WS_S
    elif in_day < LE:    d = LB - WS_S
    elif in_day < WS_E:  d = (in_day - LE) + (LB - WS_S)
    else:                d = WORK_PER_DAY
    return day * WORK_PER_DAY + d


def assign_slots(events, n_workers, units_per_worker=1):
    events = sorted(events, key=lambda e: e[1])
    slot_active = [[] for _ in range(n_workers)]
    out = []
    for (m, t0, t_cyc, t_tot) in events:
        for i in range(n_workers):
            slot_active[i] = [e for e in slot_active[i] if e > t0]
        free = [i for i in range(n_workers) if len(slot_active[i]) < units_per_worker]
        if free:
            idx = min(free, key=lambda i: len(slot_active[i]))
            actual_t0 = t0
        else:
            idx = min(range(n_workers), key=lambda i: min(slot_active[i]))
            actual_t0 = max(t0, min(slot_active[idx]))
            slot_active[idx] = [e for e in slot_active[idx] if e > actual_t0]
        slot_active[idx].append(t_cyc)
        out.append((idx, m, actual_t0, t_cyc, t_tot))
    return out


def render_gantt(label: str, events_path: str, out_png: str, xmax_disp_h: Optional[float] = None) -> str:
    rows = [json.loads(l) for l in open(events_path, encoding='utf-8')]
    by_line = {ln: [] for ln in LINES}
    for r in rows:
        if r['line'] in by_line:
            t_cyc = r.get('t_cycle', r.get('t1'))
            t_tot = r.get('t_total', r.get('t1'))
            by_line[r['line']].append((r['model'], r['t0'], t_cyc, t_tot))

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

    for ln in LINES:
        for (slot, m, t0_a, t_cyc, t_tot) in assigned[ln]:
            d0 = t_to_disp(t0_a); d_cyc = t_to_disp(t_cyc)
            ax.broken_barh([(d0 / 3600, (d_cyc - d0) / 3600)],
                           (y_of[(ln, slot)] - 0.42, 0.84),
                           facecolors=GANTT_COLOR.get(m, '#888'), linewidth=0)
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

    for sep in line_sep[1:]:
        ax.axhline(sep - 0.5, color='0.85', lw=0.6)
    ndays = int(xmax * 3600 / WORK_PER_DAY) + 1
    for d in range(ndays + 1):
        ax.axvline(d * 8, color='0.85', lw=0.7)
    ax.axvline(own_disp_h, color='#444', lw=1.2, ls='--', alpha=0.7)

    major = [t for t in range(0, int(xmax) + 1, 2)]
    def _lab(t):
        day, hr = divmod(t, 8)
        return f'D{day+1}' if hr == 0 else f'+{hr}h'
    ax.set_xticks(major); ax.set_xticklabels([_lab(t) for t in major], fontsize=9)
    minor = [i * 0.5 for i in range(int(xmax / 0.5) + 1) if (i * 0.5) % 2 != 0]
    ax.set_xticks(minor, minor=True)
    ax.tick_params(axis='x', which='major', length=7)
    ax.tick_params(axis='x', which='minor', length=3)

    ax.set_yticks([line_centers[ln] for ln in LINES])
    ax.set_yticklabels([ln.replace('WWM_', '').replace('Line', '') for ln in LINES],
                       fontsize=10)
    ax.tick_params(axis='y', length=0)

    ax.set_ylim(-0.5, total_rows - 0.5)
    ax.invert_yaxis()
    ax.set_xlim(0, xmax)
    ax.set_xlabel('')

    avail_disp_sec = t_to_disp(own_ms_sec) * total_rows
    used_h  = used_disp_sec / 3600
    idle_h  = avail_disp_sec / 3600 - used_h

    ax.set_title(f'{label}   makespan={own_ms_h:.1f}h   idle={idle_h:.0f} worker·h',
                 fontsize=12)

    ax.text(own_disp_h / xmax, 1.005, f'↓ makespan',
            transform=ax.transAxes, fontsize=9, color='#444', va='bottom', ha='center')
    ax.legend(handles=[mpatches.Patch(color=c, label=m) for m, c in GANTT_COLOR.items()],
              loc='upper right', ncol=3, fontsize=9, frameon=False)

    completions = {m: [] for m in TERM_PER_MODEL}
    for r in rows:
        if r['pc'] in TERM_PER_MODEL.get(r['model'], set()):
            t_done = r.get('t_total', r.get('t1'))
            completions[r['model']].append(t_to_disp(t_done) / 3600)
    for m, ts in completions.items():
        ts.sort()
        if not ts: continue
        xs = [0] + ts + [xmax]
        ys = [0] + list(range(1, len(ts) + 1)) + [len(ts)]
        ax_b.step(xs, ys, where='post', label=f'{m} ({len(ts)})',
                  color=GANTT_COLOR[m], lw=1.6)
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
    return out_png


#========고수준 라이브러리========
def render_greedy(target_qty: Optional[Dict[str, int]] = None,
                  out_dir: Optional[str] = None, name: str = 'greedy') -> Optional[str]:
    env = _recording_env(target_qty)
    return render_video(name, env, 'run', agent=None, out_dir=out_dir)


def render_trained(checkpoint: str, StateDim: int = 0,
                   target_qty: Optional[Dict[str, int]] = None,
                   out_dir: Optional[str] = None, name: str = 'trained_det') -> Optional[str]:
    import build as cf
    agent = cf.build_agent(StateDim=StateDim, checkpoint=checkpoint)
    env = _recording_env(target_qty)
    return render_video(name, env, 'run', agent=agent, out_dir=out_dir)


def capture(env, label: str, out_dir: str, agent=None, max_sec: int = 60 * 86400):
    summary = env.run(agent=agent, max_sec=max_sec)
    path = os.path.join(out_dir, f'events_{label}.jsonl')
    with open(path, 'w', encoding='utf-8') as fp:
        for (m, pc, ln, t0, t_cycle, t_total) in env.events:
            fp.write(json.dumps({'model': m, 'pc': pc, 'line': ln,
                                 't0': float(t0), 't_cycle': float(t_cycle),
                                 't_total': float(t_total)}) + '\n')
    return summary, path


def capture_compare(out_dir: str, agents: Dict[str, object], max_sec: int = 60 * 86400,
                    target_qty: Optional[Dict[str, int]] = None, render: bool = True) -> Dict[str, tuple]:
    os.makedirs(out_dir, exist_ok=True)
    results = {}
    for label, agent in agents.items():
        env = _recording_env(target_qty)
        summary, path = capture(env, label, out_dir, agent=agent, max_sec=max_sec)
        results[label] = (summary, path)
    if render:
        xmax = 0.0
        for label, (summary, path) in results.items():
            ms = max((json.loads(l).get('t_total', 0)
                      for l in open(path, encoding='utf-8')), default=0)
            xmax = max(xmax, t_to_disp(ms) / 3600)
        xmax *= 1.02
        for label, (summary, path) in results.items():
            render_gantt(label, path, os.path.join(out_dir, f'gantt_{label}.png'), xmax_disp_h=xmax)
    return results


if __name__ == '__main__':
    import sys
    cmd = sys.argv[1] if len(sys.argv) > 1 else 'greedy'
    if cmd == 'greedy':
        render_greedy()
    elif cmd == 'trained':
        render_trained(checkpoint=sys.argv[2], StateDim=int(sys.argv[3]) if len(sys.argv) > 3 else 0)
    elif cmd == 'gantt':
        capture_compare(os.path.join(_ROOT, 'result', 'viz'), {'greedy': None}, max_sec=86400)
