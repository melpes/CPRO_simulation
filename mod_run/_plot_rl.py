# -*- coding: utf-8 -*-
"""rl_log_qty10 / qty100 의 reward·task 값 추이 그래프.

로그에 있는 값만 사용. 주의: 보상은 W5·throughput − W1·time − W2·energy 3항뿐
(W3/W4/W6 재고·유휴는 env 미추적 → 보상·로그에 없음). r1..r6 분해도 미로깅.
출력: result/rl_curve_qty10.png, result/rl_curve_qty100.png
"""
import json, os
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

R = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'result')


def load(f):
    return [json.loads(x) for x in open(os.path.join(R, f), encoding='utf-8')]


def plot(rows, tag):
    ep = [r['episode'] for r in rows]
    fig, ax = plt.subplots(2, 3, figsize=(17, 8))
    fig.suptitle(f'RL training curves - {tag}  (n_ep={len(rows)})  '
                 f'reward = W5*thru - W1*time - W2*energy  '
                 f'[W3/W4/W6 stock/idle NOT in reward]', fontsize=12)

    a = ax[0, 0]
    a.plot(ep, [r['train/rollout_reward'] for r in rows], lw=0.6, alpha=.5, label='rollout_reward')
    a.plot(ep, [r['train/rollout_reward_mean'] for r in rows], lw=1.6, label='rollout_reward_mean')
    a.plot(ep, [r['eval/return_best_so_far'] for r in rows], lw=1.6, label='best_so_far')
    a.set_title('reward (episode scalar R)'); a.set_xlabel('episode'); a.legend(fontsize=8)

    a = ax[0, 1]
    a.plot(ep, [r['task/primary_metric'] / 3600 for r in rows], lw=0.9, color='C3')
    a.set_title('task/primary_metric = makespan (h)'); a.set_xlabel('episode')

    a = ax[0, 2]
    a.plot(ep, [r['task/energy_kwh'] for r in rows], lw=0.9, color='C1')
    a.set_title('task/energy_kwh'); a.set_xlabel('episode')

    a = ax[1, 0]
    a.plot(ep, [r['task/throughput_ratio'] for r in rows], lw=1.2, color='C2', label='throughput_ratio')
    a.plot(ep, [r['task/feasibility_rate'] for r in rows], lw=1.0, ls='--', color='C4', label='feasibility_rate')
    a.set_title('task/throughput & feasibility (1.0=saturated)'); a.set_xlabel('episode')
    a.set_ylim(0, 1.05); a.legend(fontsize=8)

    a = ax[1, 1]
    a.plot(ep, [r['sanity/reward_std'] for r in rows], lw=1.0, color='C5')
    a.set_title('sanity/reward_std (reward variation)'); a.set_xlabel('episode')

    a = ax[1, 2]
    a.plot(ep, [r.get('critic/explained_variance') for r in rows], lw=1.0, color='C0', label='EV')
    a.plot(ep, [r.get('critic/returns_var') for r in rows], lw=1.0, color='C6', label='returns_var')
    a.axhline(0, color='0.7', lw=.6)
    a.set_title('critic: explained_variance / returns_var'); a.set_xlabel('episode'); a.legend(fontsize=8)

    fig.tight_layout(rect=[0, 0, 1, 0.95])
    out = os.path.join(R, f'rl_curve_{tag}.png')
    fig.savefig(out, dpi=130)
    plt.close(fig)
    print('saved', out)


if __name__ == '__main__':
    plot(load('rl_log_qty10.jsonl'),  'qty10')
    plot(load('rl_log_qty100.jsonl'), 'qty100')
