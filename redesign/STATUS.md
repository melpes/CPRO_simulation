# redesign 패키지 구현 상태 (2026-05-15 갱신 — 워커 병렬 동작 확인)

CPRO 시뮬레이션 + GNN/PPO RL 의 모듈 분할 구현 현황. ver3 (`cpro_simulation_ver3.py`) 의 동작을 ver0 스타일로 옮기는 중.

**갱신 규칙**: 각 묶음 작업 직후 본 문서를 갱신한다.

---

## 1. 파일 구성

```
Package/
├── simulation_ver0.py              사용자 원본 (변경 없음)
├── simulation_ver0_mod.py          우리 작업본 (redesign 의 시뮬 모델 base)
├── simulation_ver0_mod_CHANGELOG.md  ver0 → ver0_mod 변경 history
└── redesign/                       ver0_mod 의 모듈 분할
    ├── __init__.py                 전체 흐름 docstring
    ├── cpro_config.py              정책 상수 / TARGET_QTY / 학습 하이퍼파라미터
    ├── kg.py                       GraphNode / GraphEdge / KnowledgeGraph + GNN 입력 API
    ├── sim_env.py                  Warehouse / 트래커 3종 / process_job / produce_unit / CproSimEnv
    ├── factory.py                  Factory (정규화 분모 + embedding index 매핑)
    ├── networks.py                 RelationalGCNLayer / ProcessGNN / PPOAgent
    ├── runner.py                   load_all_aas / build_env / build_agent + 학습 루프
    ├── _experiments.py             실험 스크립트
    └── STATUS.md                   본 문서
```

**동기화 흐름**: `simulation_ver0.py` (사용자) → `simulation_ver0_mod.py` (우리 작업본 + CHANGELOG) → `redesign/` 패키지 (모듈 분할).

스타일 지침은 CLAUDE.md 의 `## redesign / ver0 코딩 스타일` 섹션.

---

## 2. 새 PSM AAS 스키마 (2026-05-15 동기화)

PSM (`ProvisionofSimulationModelsAAS`) 의 구조가 갱신됨:

```
SimulationModel
├── SimulationConfig          {TypeOfModel, MaxEpisodes}
├── KnowledgeGraph
│   ├── Node                  {SIM_MODEL_A, SIM_MODEL_B, SIM_MODEL_C, ProcessOQC, ProcessRMA}
│   └── Action                {IndependentSequence, DependentSequence, DependentJoin, AssignedProcessGroups}
├── RewardWeights             {W1_TimeElapsed ~ W6_IdleWorker}
├── DefaultParameters         {WorkStartTime, WorkEndTime, BreakDurationMin,
│                              ReplenishLeadDay, IdleWorkerThreshold, MinOutsourcing, ...}
├── RuntimeVariables          {CycleCompleted, Throughput, EpisodeEnergyKwh,
│                              StockShortageCount, StockOverflowCount, IdleViolationCount,
│                              MaxEpisodeEnergyKwh}
├── Warehouse                 {InputBOM, MinStock, OrderRatio, MaxStock}
└── ModelArchitecture         {GNN, PPO}
```

이전 스키마 (`SimulationModel.Action` 직접) 에서 변경:
- `Action` → `KnowledgeGraph.Action` 으로 이동
- `KnowledgeGraph.Node` 신설 (모델별 SIM_MODEL_A/B/C + 공정 OQC/RMA)
- `RuntimeVariables`, `ModelArchitecture` 신설
- `RewardWeights` 의 W1~W6 명명 (옛 `REWARD_W_*` 대체)

`path_extractor` 가 자동 분류 — `PSM.SimulationModels.SimulationModel.KnowledgeGraph.Action.IndependentSequence` 등.

### AAS JSON 데이터 fix 누적

PSM/WWM JSON 의 데이터 결함을 패치본으로 유지 중 (.bak / .bak2 백업):

| 결함 | 위치 | 패치 |
|---|---|---|
| `VD7_70_1` 누락 | PSM `KnowledgeGraph.Action.DependentSequence[MODEL_A]` | URL key 추가 |
| `BT5_31` 누락 | PSM `KnowledgeGraph.Action.DependentJoin[MODEL_B]` | URL key 추가 |
| `NVD_52` 누락 | PSM `KnowledgeGraph.Action.DependentJoin[MODEL_C]` | URL key 추가 |
| `BT5_60` WS 미매핑 | WWM `WWM_SemiAssemblyLine.AssignedProcessGroups[MODEL_B]` | URL key 추가 |

AAS 데이터 갱신 시 같은 fix 재적용 필요.

---

## 3. 현재 동작 (검증됨, 2026-05-15 ver3 패턴 도입)

```
[build]      N nodes=81  state_dim=15  target_qty=300
[greedy 300u] wall=11.6s  Throughput=300/300  makespan=1.61d  kwh=2318.66  idle=5.2M
[greedy 9u]   wall=0.0s   Throughput=  9/9    makespan=0.40d  kwh=  69.56
[PPO ep0 9u]  wall=4.9s   Throughput=  9/9    makespan=0.40d  kwh=  69.56  reward=-267
```

🎉 **300 unit 완주** — 13 시간 work-time 안에 모든 unit 완성. ver3 의 워커 병렬 처리 패턴 동작.

흐름 (ver3 패턴 — 위에서 아래로):

```
1) load_all_aas()                            AAS 4 JSON → PSM
2) build_env()
   ├─ KnowledgeGraph.build(...)              81 PC 노드, 5종 adj
   ├─ Warehouse.build(...)                   BOMCategory 기반 inventory
   ├─ Factory.build(...)                     정규화 분모 4종 + embedding index 2종
   └─ CproSimEnv(...)                        모든 의존 self 보관
3) build_agent(env)                          ProcessGNN(34 GroupIdShort + 10 WS) + PPOAgent
4) for episode in range(MaxEpisodes):
       env.run(agent=agent, max_sec=...)     ← ver3 패턴 — 한 번에 시뮬 진행
           ├─ reset()
           ├─ 모든 unit produce_unit 등록 (TARGET_QTY 만큼, 예: 300 process)
           ├─ _check_done process 등록 (30s 마다 throughput 검사)
           └─ env.run(until=stop_event)      ← 한 번에 진행, 워커 수 만큼 병렬 흐름

       produce_unit(env, model_id, unit_id, cpro_env):  ← 각 unit 마다 동시
           done_set = set()
           while not terminal_pcs ⊆ done_set:
               ready = kg.ready_queue(IS, DS, DJ, model_id, done_set, warehouse)
               if not ready: yield env.timeout(60); continue
               ProcessCode = agent.choose(ready, model_id, done_set, env)
                                            ↑ unit 내부 callback
                                              kg.build_H_static_scalar()
                                              kg.build_H_dynamic(done_set, ...)
                                              GNN forward → mask + softmax → sample
                                              직전 transition reward 갱신
                                              새 transition push
               yield env.process(process_job(...))
                   1. BOM wait
                   2. 워커 자원 점유 (simpy.Resource — 워커 수 만큼 동시)
                   3. WIP enter / idle.acquire / work_timeout / energy.record
                   4. ... / warehouse.consume → 부족 시 replenish
                   5. done_set.add(ProcessCode)
           throughput_counter[0] += 1

       agent.finalize_episode(env.reward())  ← 마지막 transition 의 reward
       agent.update()                         ← GAE + PPO clip + value MSE + entropy
```

**핵심 차이 (ver0_mod fork 전 vs 후)**:
- 옛: `env.step((PC,WS))` + `env.run(until=job)` — 한 시점에 한 PC, 워커 병렬 X
- 새: `env.run(agent)` + `produce_unit × N` 동시 등록 + `env.run(until=stop_event)` — **전체 공장 워커 수만큼 병렬**

---

## 4. 모듈별 구현 상태

### 4.1 `cpro_config.py`

| 항목 | 상태 | 비고 |
|---|---|---|
| `RANDOM_SEED`, `MAX_DAYS=60`, `DAY_SEC` | ✓ | `MAX_DAYS` 는 무한루프 방지 상한선 (PSM 의 makespan 측정 한도와 다름) |
| `WWM_LINE_TO_WORKER` | △ | redesign 시뮬은 미사용 |
| `RATED_POWER_KW` SMT fallback | △ | 미사용 (PSM ProcessNode.RatedPowerKw 만 사용) |
| `TARGET_QTY` (모델별 100/100/100) | ✓ | AAS 미반영, 추후 PSM 으로 이동 가능 |
| `WIP_LIMIT_PER_GROUP` | × | 미사용 |
| `WORK_SCHEDULE` dict | × | PSM 의 DefaultParameters 사용. 미사용 |
| `GNN_*`, `PPO_*`, `*_EMBEDDING_DIM` | ✓ | networks.py 가 사용 |
| `REWARD_W_*` | × | PSM 의 RewardWeights.W1~W6 로 대체. **사용 안 함** |

→ `cpro_config` 의 절반 이상이 사용 안 됨. 정리 가능.

### 4.2 `kg.py`

| 항목 | 상태 | 비고 |
|---|---|---|
| `GraphNode` (ProcessCode/GroupIdShort/WorkstationId/model_id/CycleTimeSec/DefectRate/RatedPowerKw/InputBOM/DepPrev/DepType) | ✓ |  |
| `GraphEdge` (ProcessCode/DepType) | ✓ | ver0 동기화로 DepPrev 필드 제거 (edges dict key 가 이미 DepPrev) |
| `R_FWD_SEQ`, `R_FWD_JOIN`, `R_BWD_SEQ`, `R_BWD_JOIN`, `R_SELF`, `NUM_RELATIONS=5` | ✓ |  |
| `KnowledgeGraph.build()` | ✓ | workers 역인덱스 + 평탄화 + 5종 adj |
| `ready_queue(IS, DS, DJ, completed, warehouse)` | ✓ | ver0 동기화. DS 는 any(dep), DJ 는 all(dep). `pc not in completed` 검사 |
| `_dispatchable`, `_bom_satisfied` | ✓ | WS 매핑 + BOM 검사 |
| `GroupIdShort_ids(factory)`, `WorkstationId_ids(factory)` | ✓ | (N,) int |
| `build_H_static_scalar()` (N, 5) | ✓ | CycleTime/3600, DefectRate, kw/100, worker_count/20, is_join |
| `build_H_dynamic(completed, warehouse, wip_tracker)` (N, 4) | ✓ | completed 기반 binary. ver0 동기화 |

### 4.3 `sim_env.py`

| 항목 | 상태 | 비고 |
|---|---|---|
| `WorkSchedule`, `is_work_time`, `next_work_start`, `work_timeout` | ✓ |  |
| `StockItem`, `Warehouse.build/wait_stock/consume/replenish` | ✓ |  |
| `WIPTracker`, `EnergyLogger`, `IdleTracker` | ✓ | 단순 dataclass + 메서드 |
| `process_job` (8 단계) | ✓ | ver0 동기화 — terminal PC 도달 시 Throughput +1 + completed.clear |
| `CproSimEnv.__init__/reset/step` | ✓ | 새 PSM 변수 (RewardWeights W1~W6 / IdleWorkerThreshold) 받음 |
| `_compute_reward` (ver0 공식) | △ | 6항 공식 그대로. `work_day_sec` 분모가 1일 단위라 시뮬 진행 시 r1 항 누적 큼. 분모 의미 재검토 필요 |
| `IdleViolationCount` (idle slot 가 IdleWorkerThreshold 초 이상 누적 시 +) | ✓ |  |
| `StockShortageCount`, `StockOverflowCount` | ✓ | 매 step 마다 모든 item 검사 (O(items)) |
| `Throughput` (terminal PC 완료 카운트) | ✓ | ver0 모델 |

### 4.4 `factory.py`

| 항목 | 상태 |
|---|---|
| `total_work_seconds`, `total_expected_kwh`, `total_target_qty`, `total_pc_progressions`, `total_worker_capacity` | ✓ |
| `GroupIdShort_to_embedding_index`, `WorkstationId_to_embedding_index` | ✓ |
| `Factory.build(kg, workers, schedule, TARGET_QTY, MAX_DAYS)` | ✓ |

### 4.5 `networks.py`

| 항목 | 상태 | 비고 |
|---|---|---|
| `RelationalGCNLayer` (5종 W + bias) | ✓ |  |
| `ProcessGNN` (Embedding 2종 + R-GCN 2-layer + score head) | ✓ |  |
| `Transition` dataclass | ✓ |  |
| `PPOAgent.__init__` | ✓ |  |
| `build_H_tensor(env)` | ✓ | ver0 동기화 — `env.completed` 사용 |
| `build_state_vec(env)` | ✓ | progress_t / 모델별 완료 PC 비율 / worker_util / energy_norm |
| `act(env, ready_mask)` → action_idx | ✓ |  |
| `store_reward(r, done)` | ✓ |  |
| `update()` GAE + clip + value MSE + entropy | ✓ | loss / advantage 모니터링 미반환 |

### 4.6 `runner.py`

| 항목 | 상태 | 비고 |
|---|---|---|
| `load_all_aas` (4 JSON) | ✓ |  |
| `build_env()` | ✓ | 새 PSM 경로 (`SimulationModel.KnowledgeGraph.Action`), RewardWeights/IdleWorkerThreshold/ReplenishLeadDay 가져옴 |
| `build_agent(env)` | ✓ |  |
| `ready_to_mask` | ✓ |  |
| `__main__` 2 epi × 100 step 학습 데모 | ✓ |  |

---

## 5. ver3 에서 아직 옮기지 않은 컴포넌트

### 5.1 ✅ **워커 병렬 처리 — 완료 (2026-05-15)**

`simulation_ver0_mod.py` fork + redesign 동기화로 ver3 패턴 도입 완료:

```python
# 새 모델 (env.run(agent))
for model_id, qty in TARGET_QTY.items():
    for unit_id in range(qty):
        env.process(produce_unit(env, model_id, unit_id, cpro_env))  # 300 unit
env.run(until=stop_event)                                            # 한 번에
```

각 produce_unit 안에서 `agent.choose(ready_pcs, model_id, done_set, env)` 호출 (per-unit callback). 워커 `simpy.Resource(capacity=worker_count)` 가 자연 contention → **300 unit 동시 흐름 + 전체 공장 워커 수만큼 병렬 작업**.

검증: 300 unit 완주, makespan 1.61d, wall-time 11.6s.

`simulation_ver0.py` (사용자 원본) 는 변경 없음. `simulation_ver0_mod.py` (우리 작업본) 가 redesign 의 base. CHANGELOG.md 에 변경 history.

### 5.2 도메인 시뮬

| ver3 컴포넌트 | redesign 진척 | 비고 |
|---|---|---|
| **defect 분기** (DefectRate 적용) | 미구현 | `process_job` 안에 random 비교 + AOI/INSP 분기 + RMA 진입 |
| **RMA 재투입** | 미구현 | `simpy.Store(rma)` + `run_rma` 핸들러 |
| **SMT 컨베이어 라인** (`SMTLine`) | 미구현 | KG 토폴로지와 분리된 컨베이어 시뮬 |
| **THT 외주** (`OutsourceTruckPool`) | 미구현 |  |
| **OQC 샘플링** | 미구현 | `SamplingRate` qualifier 도입 |
| **transfer_time / dep_wait_hr** | 미구현 | ProcessNode qualifier 추가 시 |
| **skill 차등 ct/dr** | 미구현 |  |
| **워커 결근 / SMT 라인 고장** (event_*) | 미구현 |  |
| **단가 / 비용** | 미구현 |  |

### 5.3 시뮬 인프라

| 항목 | 상태 |
|---|---|
| **이벤트 로깅 (`_log_event`, `_EVENT_BUF`)** | 미구현 |
| **콘솔 dashboard `monitor`** | 미구현 |
| **`wh.snapshot_loop`, `wip.snapshot_loop`** | 미구현 |
| **randomness (CT_STD_RATIO)** | 미구현 |

### 5.4 RL 학습 인프라

| 항목 | 상태 |
|---|---|
| **`ExperimentRunner` 별도 클래스** | 미구현 (runner.py 에 inline) |
| **체크포인트 (state_dict 저장/복원)** | 미구현 |
| **`run_ppo_training` / `run_inference`** | 미구현 |
| **조기 종료 (CONV_WINDOW / THRESHOLD)** | 미구현 |
| **loss / advantage / entropy 모니터링** | 미구현 |

### 5.5 시각화

| 항목 | 상태 |
|---|---|
| **`cpro_visualization.save_results`** (엑셀) | 미연결 |
| **`cpro_visualization.save_figures`** (PNG) | 미연결 |
| **에피소드별 reward 곡선** | 미구현 |

---

## 6. AAS 템플릿 확장 후보 (cpro_config → PSM 이동)

| 항목 | 현재 위치 | PSM 이동 시 위치 |
|---|---|---|
| `TARGET_QTY` (모델별 주문량) | `cpro_config.py` | PSM 의 새 `Order` submodel 또는 `ProductAAS` qualifier |
| `RATED_POWER_KW` SMT fallback | `cpro_config.py` | `ProcessNode.RatedPowerKw` 가 모두 채워지면 제거 |
| 학습 하이퍼파라미터 (`GNN_*`, `PPO_*`) | `cpro_config.py` | PSM 의 `ModelArchitecture.GNN/PPO` 로 이동 (이미 PSM 에 존재) |
| `MAX_DAYS` | `cpro_config.py` | makespan 측정 한도라 시뮬 정책 — 위치 그대로 |
| `RANDOM_SEED` | `cpro_config.py` | 실험 정책 — 위치 그대로 |

---

## 7. 실험적 발견 (2026-05-14 측정 — **ver0_mod fork 전 옛 step 모델 기준, 무효**)

⚠️ **주의**: 이 섹션의 결과는 ver0_mod fork 전 (`env.step((PC,WS))` + `env.run(until=job)` 모델) 측정값. **새 모델 (env.run(agent)) 에서 재실험 필요**. `_experiments.py` 의 정책 함수도 새 시그니처 (`agent.choose` callback) 로 갱신 필요.

기존 발견 중 살아남는 것:
- 7.5 의 **PPO 학습 신호 잡힘**은 여전히 유효 (PPO buf / update 코드 그대로)
- 7.6 의 **IdleTracker 의 야간/휴게 누적** 문제는 여전 유효 (트래커 코드 변경 없음)

기존 발견 중 무효화된 것:
- 7.1 deterministic — 새 모델에서도 확인 필요. 워커 capacity contention 으로 동시 점유 순서가 simpy 내부 이벤트 순서에 의존, 일부 비결정성 가능.
- 7.2 WS 편향 — 새 모델은 워커 병렬이라 자연 분산. greedy_last 의 100% 한 WS 같은 극단 사라짐.
- 7.3 random_min_wip ≡ greedy_first — 새 모델은 동시 흐름이라 WIP 가 실시간 변동. WIP heuristic 이 의미 가질 수 있음.
- 7.4 random 시드 무관 결과 — 새 모델은 동시 흐름이라 시드 영향 다를 가능성.
- 7.7 (옛 8.7) ~3000 step deadlock — **완전 무효**. 새 모델은 300 unit 완주 (위 Section 3).
- 7.8 (옛 8.10a) PSM.Action 누락 / BOM deadlock — Action 누락은 patch 적용 (Section 2.4). BOM deadlock 도 워커 병렬로 자연 해소 (다른 unit consume 후 wait_stock 깨움).

### 7.1 시뮬은 deterministic (random 외)

`std=0` for greedy_*, random_min_wip. cycle_time 결정적, defect 미적용. `CT_STD_RATIO` 등 ver3 randomness 미반영.

### 7.2 WS / PC 편향이 정책별로 극단

`greedy_last`: WWM_SemiAssemblyLine 100% (3 종 NVD PC 만 dispatch). `greedy_first`: 3 WS (50/40/10%). `random`: 5+ WS 분산. **5.1 의 라인 병렬 미구현 결과** — 한 시점에 한 PC 만이라 정책이 WS 선택을 좌우.

### 7.3 `random_min_wip` ≡ `greedy_first` (정확히 동일)

WIP 측정이 process_job 안 enter/leave 동기적이라 step 끝 측정 시점에 항상 0 → tie-breaking 이 ready[0] 와 같음. **WIP heuristic 가 현재 구현에서 무의미**. WIP measurement hook 위치 재설계 필요.

### 7.4 random 시드별 결과가 deadlock 까지 가면 같아짐

200 step 까지는 시드별 변동 있지만 deadlock 까지 진행되면 같은 multiset → kwh/makespan 동일. **dispatch 한 PC 들의 집합이 정책 의존 아닌 시뮬 상태 의존**.

### 7.5 PPO 가 학습 신호를 잡음 (50 epi × 500 step 측정)

- ep 0:  reward=-67 kwh=122
- ep 15: reward=-14 kwh=39
- ep 49: reward=-19 kwh=31 (수렴)

학습 효과 확인. 다만 unit 카운팅 모델 + step 단위 시뮬 한계 안에서의 효율 개선.

### 7.6 IdleTracker 가 야간/휴게도 idle 로 누적

`IdleTracker.flush` 가 wall-clock 적분. `_work_seconds_between` 미적용. idle reward 가 비대.

---

## 8. 다음 작업 우선순위 (워커 병렬 동작 완료 후)

1. ✅ ~~라인 병렬 / unit 동시 진행~~ — **완료** (Section 5.1)
2. **새 모델 기준 재실험** — `_experiments.py` 의 정책 함수를 `agent.choose` callback 스타일로 갱신 후 다양한 정책 × 시드 측정. 새 invariant 파악 (Section 7 의 옛 발견들 재검증).
3. **PPO 학습 efficacy** — 300 unit 풀 시뮬에서 다수 epi 학습 곡선. greedy baseline 대비 우월성 측정.
4. **IdleTracker 보정** — `_work_seconds_between` (근무시간만 적분).
5. **시뮬 randomness 도입** — ver3 의 `CT_STD_RATIO` (`act = normalvariate(ct, ct × ratio)`).
6. **defect / RMA** — `ProcessNode.DefectRate` 적용 + RMA 큐 + `run_rma` 핸들러.
7. **state_vec 의 모델별 throughput 분리** — 현재 글로벌 throughput 만. 모델별 카운터 추가.
8. **reward 공식 튜닝** — 현재 delta reward + W1\~W6. 의미 명확화.
9. **PPO 학습 인프라** — 체크포인트 / 평가 모드 / 학습 모니터링 (loss / advantage / entropy).
10. **시각화 연결** — `cpro_visualization` 의 reward 곡선 / KG 토폴로지.
11. **`ModelArchitecture` (PSM) 연결** — 학습 하이퍼파라미터를 PSM 에서 가져옴.

---

## 9. 참조

- 스타일 지침: `CLAUDE.md` `## redesign / ver0 코딩 스타일`
- ver0 진척: `CLAUDE.md` `## simulation_ver0.py 구동 진행률`
- AAS contract: `CLAUDE.md` `## 입력 데이터 contract`, `## path_extractor (AAS 접근 계층) 구조 규칙`
- 금지 사항: `CLAUDE.md` `## 금지 사항`
- 실험 스크립트: `redesign/_experiments.py` (정책 함수가 옛 step API 기반 — agent.choose callback 으로 갱신 필요)
- ver0_mod 변경 history: `simulation_ver0_mod_CHANGELOG.md`
