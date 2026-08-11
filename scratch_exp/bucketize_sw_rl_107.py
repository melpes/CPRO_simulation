# -*- coding: utf-8 -*-
"""exp_run(trained) events.jsonl → 실험기록.xlsx 강화학습 후 시트 시계열 payload.
   규약 = 강화학습 후 Q180-S(26.07.03) 시트(0.5h 작업시간 버킷, S:AY 열)와 동일:
   · busy/에너지 구간 = [t0, t0+CycleTimeSec] (DepWaitSec 제외)
   · cum = 모델 터미널 공정 완료 누적
   · idle = 작업자당 평균 유휴(h) — type=realloc 이벤트로 라인 인원을 시변 적분(재배분 반영)
   · base = 공장 기저 10kW × 버킷, smt = type=smt_eq(설비 on/off 분해) 합산
   사용: python bucketize_sw_rl.py <run_dir> <out.json>
"""
import json
import math
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', '..'))
sys.path.insert(0, ROOT)

DAY = 86400
WS_S, WS_E, LB, LE = 32400, 64800, 43200, 46800
WORK_PER_DAY = (WS_E - WS_S) - (LE - LB)
B = 1800.0
LINES = ['WWM_FwInputLine', 'WWM_LensHolderLine', 'WWM_FocusLine', 'WWM_SemiAssemblyLine',
         'WWM_SetAssemblyLine', 'WWM_InspectionLine', 'WWM_AgingLine', 'WWM_OqcLine',
         'WWM_RMALine', 'WWM_PackagingLine']            # 시트 W..AF / AO..AX 열 순서
SMT_EQ = ['Loader', 'ScreenPrinter', 'SPI', 'Mounter', 'Reflow', 'Unloader', 'AOI']
MODELS = ['MODEL_A', 'MODEL_B', 'MODEL_C']
BASE_KW = 107.0                                         # 공장 10 + 컴프레서 97 상시(07.09 세대)


def T(t):
    d = int(t // DAY); s = t - d * DAY
    if s < WS_S:   x = 0.0
    elif s < LB:   x = s - WS_S
    elif s < LE:   x = float(LB - WS_S)
    elif s < WS_E: x = (s - LE) + (LB - WS_S)
    else:          x = float(WORK_PER_DAY)
    return d * WORK_PER_DAY + x


def spread(store, key, a, b, amount):
    d = store.setdefault(key, {})
    if b <= a:
        d[int(a // B)] = d.get(int(a // B), 0.0) + amount
        return
    i0, i1 = int(a // B), int((b - 1e-9) // B)
    for i in range(i0, i1 + 1):
        lo, hi = max(a, i * B), min(b, (i + 1) * B)
        d[i] = d.get(i, 0.0) + amount * (hi - lo) / (b - a)


def main(run_dir, out_path):
    S = json.load(open(os.path.join(run_dir, 'summary.json'), encoding='utf-8'))
    CFG = json.load(open(os.path.join(run_dir, 'settings.resolved.json'), encoding='utf-8'))
    workers = CFG['workers']                            # 초기 인원 스냅숏

    import path_extractor, build
    for f in CFG['fileset_files']:
        path_extractor.load(os.path.join(ROOT, 'aas_data', f))
    env = build.build_simulation(target_qty=S['target'],
                                 due_day={m: 3 for m in S['target']})
    kg = env.KnowledgeGraph
    terminal = {m: {pc for pc, n in kg.nodes.items()
                    if n.model_id == m and pc not in kg.edges} for m in MODELS}
    n_term = {m: max(1, len(terminal[m])) for m in MODELS}

    busy, ekwh, smt_e = {}, {}, {}
    term_ends = {m: [] for m in MODELS}
    reallocs = []
    t_max = 0.0
    for row in open(os.path.join(run_dir, 'events.jsonl'), encoding='utf-8'):
        e = json.loads(row)
        if e['type'] == 'job':
            node = kg.nodes[e['pc']]
            upw = workers[e['line']].get('UnitsPerWorker', 1)
            t0, t1 = e['t0'], e['t0'] + node.CycleTimeSec
            w0, w1 = T(t0), T(t1)
            spread(busy, e['line'], w0, w1, (t1 - t0) / upw)
            spread(ekwh, e['line'], w0, w1, node.CycleTimeSec * node.RatedPowerKw / 3600.0)
            if e['pc'] in terminal.get(node.model_id, ()):
                term_ends[node.model_id].append(w1)
            t_max = max(t_max, w1)
        elif e['type'] == 'smt_eq':
            eq = e['eq'][:-len('Process')] if e['eq'].endswith('Process') else e['eq']
            spread(smt_e, eq, T(e['t0']), T(e['t_total']), e['kwh'])
            t_max = max(t_max, T(e['t_total']))
        elif e['type'] == 'realloc':
            reallocs.append(e)

    mk_work = T(S['makespan_sec'])
    t_max = max(t_max, mk_work)
    nb = int(math.ceil(t_max / B))
    for m in MODELS:
        term_ends[m].sort()

    def wc_integral(ws, a, b):
        """작업축 [a,b) 인원 적분 — realloc 이벤트로 구간화."""
        segs = [(0.0, workers[ws]['worker_count'])]
        for r in reallocs:
            tw = T(r['t0'])
            delta = r['moves'].get(ws, 0) - (sum(r['moves'].values()) if r['src'] == ws else 0)
            if delta:
                segs.append((tw, segs[-1][1] + delta))
        total = 0.0
        for i, (t0, wc) in enumerate(segs):
            t1 = segs[i + 1][0] if i + 1 < len(segs) else float('inf')
            lo, hi = max(a, t0), min(b, t1)
            if hi > lo:
                total += wc * (hi - lo)
        return total

    ci = {m: 0 for m in MODELS}
    buckets = []
    for i in range(nb):
        t_a = i * B
        wsec = max(0.0, min(B, mk_work - t_a))
        cum = []
        for m in MODELS:
            lst = term_ends[m]
            while ci[m] < len(lst) and lst[ci[m]] <= t_a + B:
                ci[m] += 1
            cum.append(int(ci[m] // n_term[m]))
        idle = []
        for ws in LINES:
            avail = wc_integral(ws, t_a, t_a + wsec)
            if avail <= 0 or wsec <= 0:
                idle.append(None)
                continue
            bz = min(busy.get(ws, {}).get(i, 0.0), avail)
            wc_avg = avail / wsec
            idle.append(round((avail - bz) / wc_avg / 3600.0, 4))
        buckets.append({
            'wh':   round(t_a / 3600.0, 2),
            'cum':  cum,
            'idle': idle,
            'base': round(BASE_KW * wsec / 3600.0, 4),      # 마지막 부분 버킷은 잔여 작업시간만큼
            'smt':  [round(smt_e.get(eq, {}).get(i, 0.0), 4) for eq in SMT_EQ],
            'asm':  [round(ekwh.get(ws, {}).get(i, 0.0), 4) for ws in LINES],
        })

    payload = {'makespan_h': S['makespan_h'],
               'makespan_work_h': round(mk_work / 3600.0, 3),
               'energy': S['total_energy_kwh'],
               'buckets': buckets,
               'reallocs': reallocs}
    json.dump(payload, open(out_path, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print(json.dumps({'buckets': nb, 'cum_final': {m: ci[m] // n_term[m] for m in MODELS},
                      'asm_total': round(sum(sum(d.values()) for d in ekwh.values()), 2),
                      'smt_total': round(sum(sum(d.values()) for d in smt_e.values()), 2),
                      'realloc_count': len(reallocs)}, ensure_ascii=False))


if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2])
