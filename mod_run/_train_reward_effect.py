# -*- coding: utf-8 -*-
"""W3/W4/W6 학습효과 실험 — 1일 horizon 다수 epoch 학습 후 위반 카운터 추세 분석.

질문: 보상에 재고부족(W4)·재고초과(W3)·유휴(W6) 를 넣었을 때 정책이 실제로 이들을
줄이는 방향으로 학습하는가? (단 W4 는 공급 리드타임 발 외생분이 커 감소 여지 제한적,
W6 유휴는 스케줄링으로 줄일 여지 큼 — advisor.)

qty=100(비포화·보상균형 regime), episode_max_sec=86400(1일). 매 ep rl_log 에
task/throughput·stock_shortage·stock_overflow·idle_violation 기록(rl_logger 확장).
초기 N vs 후기 N 평균 + 선형 기울기로 추세 판정 + 다패널 플롯.

출력: mod_run/result/runs/{MMDDHHMM}_reward_effect/
"""
import os, sys, json, time
import matplotlib; matplotlib.use('Agg')
import matplotlib.pyplot as plt

DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, DIR); sys.path.insert(0, os.path.dirname(DIR))
import _timeit as T

QTY      = 100
EP       = int(sys.argv[1]) if len(sys.argv) > 1 else 60
RUN_NAME = time.strftime('%m%d%H%M') + '_reward_effect'
OUT      = os.path.join(DIR, 'result', 'runs', RUN_NAME)

# 추세 추적 대상 (방향: throughput↑ 좋음, 나머지↓ 좋음)
SERIES = [
    ('train/rollout_reward', 'reward Φ',        'up'),
    ('task/throughput',      'throughput/day',  'up'),
    ('task/stock_shortage',  'stock shortage',  'down'),
    ('task/stock_overflow',  'stock overflow',  'down'),
    ('task/idle_violation',  'idle violation',  'down'),
    ('exploration/entropy',  'policy entropy',  '-'),
]


def slope(ys):
    n = len(ys)
    if n < 2: return 0.0
    xs = list(range(n)); mx = sum(xs)/n; my = sum(ys)/n
    den = sum((x-mx)**2 for x in xs) or 1.0
    return sum((x-mx)*(y-my) for x, y in zip(xs, ys)) / den


def main():
    sv, env, agent = T.build('simulation_ver1', QTY, EP)
    horizon = sv.EPISODE_DURATION_SEC                      # 3일 (학습 horizon — B 24h 본드 포함)
    print(f'[{time.strftime("%H:%M:%S")}] train {EP}ep qty={QTY} '
          f'{horizon/86400:.0f}일({horizon}s) → result/runs/{RUN_NAME}/', flush=True)
    t0 = time.time()
    sv.train(env, agent, EP, run_name=RUN_NAME, episode_max_sec=horizon)
    print(f'[{time.strftime("%H:%M:%S")}] train 완료 dt={time.time()-t0:.0f}s', flush=True)

    rows = [json.loads(l) for l in open(os.path.join(OUT, 'rl_log.jsonl'), encoding='utf-8')]
    n = len(rows)
    win = max(1, n // 5)                       # 초기/후기 윈도 = 전체의 1/5
    print(f'\n===== 학습효과 추세 (n={n}ep, 초기/후기 {win}ep 평균) =====')
    print(f'{"metric":<18}{"초기":>12}{"후기":>12}{"Δ":>12}{"기울기/ep":>12}  방향')
    summary = {}
    for key, label, want in SERIES:
        ys = [r.get(key) for r in rows if r.get(key) is not None]
        if not ys:
            continue
        early = sum(ys[:win]) / win
        late  = sum(ys[-win:]) / win
        sl    = slope(ys)
        good  = (want == 'up' and late > early) or (want == 'down' and late < early) or want == '-'
        flag  = '✓ 개선' if good and want != '-' else ('—' if want == '-' else '✗ 악화')
        print(f'{label:<18}{early:>12.3f}{late:>12.3f}{late-early:>+12.3f}{sl:>+12.4f}  {flag}')
        summary[key] = (early, late, sl)

    # 다패널 플롯
    fig, axes = plt.subplots(len(SERIES), 1, figsize=(11, 2.0*len(SERIES)), sharex=True)
    for ax, (key, label, want) in zip(axes, SERIES):
        ys = [r.get(key) for r in rows]
        xs = [r['episode'] for r in rows]
        pts = [(x, y) for x, y in zip(xs, ys) if y is not None]
        if pts:
            ax.plot([p[0] for p in pts], [p[1] for p in pts], lw=1.3,
                    color=('#2E8B3F' if want != 'down' else '#C04040'))
        ax.set_ylabel(label, fontsize=9)
        ax.grid(alpha=0.3)
    axes[-1].set_xlabel('episode')
    axes[0].set_title(f'W3/W4/W6 learning effect  qty={QTY} 1day-horizon  {EP}ep  /  {RUN_NAME}', fontsize=11)
    fig.tight_layout()
    p = os.path.join(OUT, 'reward_effect.png')
    fig.savefig(p, dpi=130); plt.close(fig)
    print(f'\n  plot → {p}')


if __name__ == '__main__':
    main()
