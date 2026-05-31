# -*- coding: utf-8 -*-
"""trained vs greedy 두 run 의 env.events 사후 분석 → 라인별 util/idle 비교.
events 는 mp4 렌더 후 메모리 휘발이라, 재실행해 events 만 다시 수집.
"""
import os, sys, time
import torch
_DIR = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_DIR); sys.path.insert(0,_DIR); sys.path.insert(0,_ROOT)
import simulation_ver1 as svm
import _timeit as TT
import cpro_ver1_viz as viz

WS_START = 32400; WS_END = 64800; LUNCH_S = 43200; LUNCH_E = 46800
DAY = 86400
WORK_PER_DAY = (WS_END-WS_START) - (LUNCH_E-LUNCH_S)   # 28800s/day = 8h

def work_overlap(t0, t1):
    # [t0,t1] 와 일별 [WS_START,WS_END]\[LUNCH_S,LUNCH_E] 의 총 overlap(초)
    if t1 <= t0: return 0.0
    tot = 0.0
    d0, d1 = int(t0//DAY), int(t1//DAY)
    for d in range(d0, d1+1):
        a = max(t0, d*DAY+WS_START); b = min(t1, d*DAY+WS_END)
        if b<=a: continue
        # 점심 제외
        la = max(a, d*DAY+LUNCH_S); lb = min(b, d*DAY+LUNCH_E)
        tot += (b-a) - max(0.0, lb-la)
    return tot


def analyze(events, ws_caps, makespan):
    # events: list of (model_id, pc, ws, t0, t1)
    # ws_caps: {ws: worker_count}
    by_ws = {ws:0.0 for ws in ws_caps}
    for (_m,_pc,ws,t0,t1) in events:
        if ws not in by_ws: continue
        by_ws[ws] += work_overlap(t0,t1)
    # 가용근무시간 per ws = makespan 안의 work_overlap × capacity
    avail = work_overlap(0, makespan)
    rows = []
    for ws,used in by_ws.items():
        cap = ws_caps[ws]; ws_avail = avail*cap
        util = used/ws_avail if ws_avail>0 else 0
        rows.append((ws,cap,used,ws_avail,util))
    return rows, avail


def run_collect(agent):
    envs = viz.make_envs()
    name, env, mode = next(e for e in envs if e[0]=='ver1')
    summary = env.run(agent=agent)
    caps = {ws:info['worker_count'] for ws,info in env.workers.items()}
    return env.events, summary, caps


def main():
    print(f'[{time.strftime("%H:%M:%S")}] greedy 재실행...')
    e_g, s_g, caps = run_collect(None)
    print(f'  events={len(e_g)} makespan={s_g["makespan_sec"]:.0f}s thru={s_g["Throughput"]}')

    print(f'[{time.strftime("%H:%M:%S")}] trained 재실행...')
    _,_,ag = TT.build('simulation_ver1',100,1)
    ag.load_state_dict(torch.load(os.path.join(_DIR,'result','agent_horizon_qty100.pt')))
    ag.eval(); ag.reset_buffer()
    e_t, s_t, _ = run_collect(ag)
    print(f'  events={len(e_t)} makespan={s_t["makespan_sec"]:.0f}s thru={s_t["Throughput"]}')

    rg, av_g = analyze(e_g, caps, s_g['makespan_sec'])
    rt, av_t = analyze(e_t, caps, s_t['makespan_sec'])
    print(f'\n근무시간내 makespan(work_overlap): greedy={av_g:.0f}s({av_g/3600:.1f}h) trained={av_t:.0f}s({av_t/3600:.1f}h)')
    print(f'\n{"line":<24} {"cap":>3}  {"util(greedy)":>14}  {"util(trained)":>15}  {"Δ":>6}')
    rd = {r[0]:r for r in rg}
    overall_g_used=overall_t_used=overall_g_avail=overall_t_avail=0
    for (ws,cap,used_t,avail_t,util_t) in sorted(rt):
        (_,_,used_g,avail_g,util_g) = rd[ws]
        overall_g_used+=used_g; overall_g_avail+=avail_g
        overall_t_used+=used_t; overall_t_avail+=avail_t
        print(f'{ws:<24} {cap:>3}  {util_g:>14.1%}  {util_t:>15.1%}  {(util_t-util_g):>+6.1%}')
    print(f'{"--TOTAL--":<24} {sum(caps.values()):>3}  {overall_g_used/overall_g_avail:>14.1%}  {overall_t_used/overall_t_avail:>15.1%}  {(overall_t_used/overall_t_avail - overall_g_used/overall_g_avail):>+6.1%}')


if __name__=='__main__':
    main()
