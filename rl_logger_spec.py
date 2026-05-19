# ============================================================
# RL TRAINING DIAGNOSTIC LOG SPEC
# ============================================================
# Policy gradient (PPO 중심, A2C/TRPO/SAC에도 거의 그대로 적용 가능)
# 학습의 진단 가독성을 DL의 validation loss curve 수준으로 끌어올리기
# 위한 logging schema. 각 panel이 하나의 specific 질문에 답하도록
# 목적별로 그룹화됨.
#
# 로깅 빈도 convention:
#   PER_UPDATE  : 매 gradient update마다 (저렴)
#   PER_EVAL    : 매 N update마다 (예: 1000), fixed eval set 위에서
#                 deterministic rollout 필요
#   PER_EPISODE : training rollout episode 종료 시점
#
# Eval rollout 측정 조건 (세 개 모두 동시에 잠가야 의미 있음):
#   - 고정된 eval instance set (학습 중 절대 안 보는 held-out)
#   - 고정된 environment seed
#   - Deterministic policy (sampling 아님, argmax 또는 distribution mode)
# ============================================================


# ============================================================
# [A] LEARNING SIGNAL — "학습이 진짜로 되고 있는가"
# ============================================================
# DL의 validation loss에 직접 대응. 진동하는 train reward 대신
# 이 panel을 보고 학습 진행 여부 판단. 단일 metric으로 본다면 이것.
# ============================================================
log_A = {
    # 핵심 metric. RL의 "validation loss" 대응물.
    'eval/return_mean': None,                 # PER_EVAL

    # Instance variability. 작으면 robust, 크면 일부 instance만 잘 풂.
    'eval/return_std': None,                  # PER_EVAL

    # 정의상 monotonic 비감소. 학습 곡선이 진동해도 이 값은 깔끔.
    # Best policy archiving과 함께 사용.
    'eval/return_best_so_far': None,          # PER_EVAL

    # Random policy 대비 ratio. 1.0이면 random 수준.
    # 학습 시작점 sanity + 진짜 학습 여부 빠른 판정.
    'eval/return_vs_random': None,            # PER_EVAL

    # Heuristic 또는 expert baseline 대비 ratio. 1.0 넘기면 baseline 이김.
    # 산업 도메인에서 가장 의미 있는 단일 metric.
    'eval/return_vs_baseline': None,          # PER_EVAL
}


# ============================================================
# [B] CRITIC QUALITY — "Critic이 진짜 배우고 있는가"
# ============================================================
# Actor-critic 계열에서 critic이 망가지면 actor의 policy gradient가
# 사실상 random direction이 됨. "보상 진동만 한다"의 가장 흔한 원인.
# ============================================================
log_B = {
    # 1 - Var(R - V) / Var(R). Critic이 return을 얼마나 설명하는가.
    #   1 근처 : 잘 예측 중.
    #   0 근처 : critic이 평균만 학습 중. actor 업데이트 거의 noise.
    #   음수    : critic 발산. lr 낮추거나 target network 점검.
    'critic/explained_variance': None,        # PER_UPDATE

    # Value regression loss. 초기 감소 후 plateau가 정상.
    # 발산하면 bootstrapping instability.
    'critic/value_loss': None,                # PER_UPDATE

    # V 추정값의 magnitude. reward와 같은 자릿수여야 함.
    # 급증하면 발산 신호.
    'critic/v_mean': None,                    # PER_UPDATE
    'critic/v_max': None,                     # PER_UPDATE
}


# ============================================================
# [C] UPDATE STABILITY — "Policy update step이 안정적인가"
# ============================================================
# TRPO/PPO의 trust region 가정이 깨지면 monotonic improvement 보장이
# 사라지고 후퇴 발생. 이 지표들이 step의 크기를 본다.
# ============================================================
log_C = {
    # 업데이트 전후 policy 간 KL divergence (sample 기반 추정).
    #   0.01 ~ 0.05 : 일반적 안정 범위
    #   > 0.1       : step too large. lr 낮추거나 PPO clip ε 줄이기
    'stability/approx_kl': None,              # PER_UPDATE

    # PPO ratio가 clipping range 밖으로 나간 sample 비율.
    #   0.1 ~ 0.3 : 정상
    #   > 0.5     : trust region 거의 무의미
    'stability/clip_fraction': None,          # PER_UPDATE

    # 전체 gradient L2 norm. spike하면 수치 불안정.
    # Gradient clipping 적용 권장 (보통 max_norm = 0.5 ~ 1.0).
    'stability/grad_norm': None,              # PER_UPDATE

    # Scheduler 사용 시 현재 lr.
    'stability/learning_rate': None,          # PER_UPDATE
}


# ============================================================
# [D] EXPLORATION HEALTH — "탐색이 죽지 않았는가"
# ============================================================
# Entropy collapse가 PPO에서 학습 멈춤의 주요 원인 중 하나.
# 너무 빨리 deterministic해지면 local optimum에 갇힘.
# ============================================================
log_D = {
    # Policy distribution의 평균 entropy.
    #   초기 높음 → 점진 감소 → 작은 양수에서 plateau가 정상.
    #   너무 빨리 0 근처 : premature collapse. entropy bonus 늘리기.
    #   안 떨어짐         : 학습 자체가 진행 안 됨.
    'exploration/entropy': None,              # PER_UPDATE

    # 최근 N update에서의 entropy 기울기. collapse 속도 직접 측정.
    'exploration/entropy_slope': None,        # PER_UPDATE

    # (Discrete action) 가장 자주 선택된 action의 빈도.
    #   1.0 근처   : mode collapse
    #   1/|A| 근처 : uniform exploration
    'exploration/action_mode_concentration': None,  # PER_UPDATE
}


# ============================================================
# [E] TASK-SPECIFIC DEPLOYMENT — "실제로 쓸만한가"
# ============================================================
# Reward function 설계와 무관하게 도메인 의미를 갖는 metric.
# Reward shaping이 만든 인공 신호와 분리해서 진짜 task quality를 봄.
# 아래는 scheduling 도메인 예시, 다른 도메인이면 교체.
# ============================================================
log_E = {
    # Domain outcome. Eval set 위에서 측정.
    'task/primary_metric': None,              # PER_EVAL — 예: makespan
    'task/feasibility_rate': None,            # PER_EVAL — feasible 해 비율
    'task/constraint_violation_count': None,  # PER_EVAL

    # Optimal solution 또는 expert teacher 대비 gap.
    #   (eval - optimal) / optimal
    # CP-SAT/exact solver optimum이 알려진 instance에서 측정.
    'task/optimality_gap': None,              # PER_EVAL
}


# ============================================================
# [F] SANITY & DEBUGGING — "기본 가정이 안 깨졌는가"
# ============================================================
# Bug 또는 환경 설정 오류 진단용. 셋업 초기엔 필수,
# 안정화되면 가끔만 확인해도 됨.
# ============================================================
log_F = {
    # Train과 eval reward의 차이.
    #   너무 큼 : train 분포에 overfit, eval과 분포 차이.
    #   너무 작음 : eval이 train과 사실상 동일, generalization 측정 의미 없음.
    'sanity/train_eval_gap': None,            # PER_EVAL

    # Episode length 분포.
    #   학습 초기엔 짧다가 길어지는 게 일반적 (early termination 감소).
    #   max_steps hit rate 높으면 policy가 무한루프 패턴 학습.
    'sanity/episode_length_mean': None,       # PER_EPISODE
    'sanity/episode_length_max_hit_rate': None,  # PER_EPISODE

    # Reward magnitude. 너무 크거나 작으면 normalization 필요.
    # Value loss 발산의 흔한 원인.
    'sanity/reward_mean': None,               # PER_EPISODE
    'sanity/reward_std': None,                # PER_EPISODE

    # Train rollout reward. 진동하는 게 정상이고 단독 사용 금지.
    # eval/return_mean과 함께만 의미 있음.
    'train/rollout_reward_mean': None,        # PER_EPISODE
}


# ============================================================
# RECOMMENDED PLOT LAYOUT — 6 panel in one figure
# ============================================================
# 진동의 종류 분리(noise vs instability)를 위해 같이 띄워야 함.
#
#   Panel 1 [A] eval/return_mean (with IQR band)
#               + eval/return_best_so_far
#               → "진짜로 학습 중인가"
#
#   Panel 2 [B] critic/explained_variance
#               + critic/value_loss
#               → "critic이 망가졌는가"
#
#   Panel 3 [C] stability/approx_kl + stability/clip_fraction
#               → "step이 너무 큰가"
#
#   Panel 4 [D] exploration/entropy (+ entropy_slope)
#               → "탐색이 죽었는가"
#
#   Panel 5 [E] task/optimality_gap (또는 domain-specific primary metric)
#               → "실제로 쓸만한가"
#
#   Panel 6 [F] train/rollout_reward_mean (참고)
#               → 분야 관습이라 같이 보지만 단독 신뢰 금지


# ============================================================
# MULTI-SEED REQUIREMENT
# ============================================================
# 위 모든 곡선은 최소 3 seed (권장 5 seed) 의 mean + IQR band로 표시.
# Single-seed 결과는 통계적으로 noise와 구별 불가능.
# Henderson et al. 2018 "Deep Reinforcement Learning that Matters"
# 가 정확히 이 문제를 정량화한 표준 reference.


# ============================================================
# DIAGNOSTIC FLOW — "학습이 안 됨" 진단 순서
# ============================================================
# 1. Panel 1 [A]: eval return이 random/baseline 대비 의미 있게 위인가?
#       NO  → 학습 자체가 시작 안 됨. 다음 단계 진단.
#       YES → 학습 진행 중. 미세 조정 단계.
#
# 2. Panel 2 [B]: explained_variance가 0 근처에서 안 올라가는가?
#       YES → critic 문제. State representation 의심, lr 낮추기.
#
# 3. Panel 4 [D]: entropy가 너무 빨리 collapse하는가?
#       YES → exploration 문제. entropy bonus 늘리기, init 점검.
#
# 4. Panel 3 [C]: approx_kl 또는 grad_norm spike가 있는가?
#       YES → step too large. lr 낮추기, clip range 줄이기.
#
# 5. Panel 6 [F]: train reward만 보고 판단 안 했는가?
#       YES → 그것만 보면 항상 noisy함. Panel 1으로 다시.