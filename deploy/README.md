# CPRO 추론 모델 — 자족 실행 패키지

이 폴더 하나로 **단독 실행**된다(부모 repo 불필요). 학습된 정책(`agent_mod.pt`)을 시뮬레이터에 돌려, **PO(모델별 수량·납기)나 수치 몇 개만 바꿔** KPI + 워커 스케줄을 낸다.

> 이 폴더는 특정 학습 1회의 스냅샷이다. 코드(추론 8모듈) · `aas_data/`(공장 구조) · `agent_mod.pt`(가중치)가 모두 동봉돼 있다. 이 셋은 분리 불가 — 정책은 경합점(워커가 비고 후보공정 ≥2)에서 "어느 공정 먼저"만 고르고, makespan·throughput·에너지·납기·스케줄 자체는 시뮬레이터가 만든다.

## 실행

```
pip install -r requirements-infer.txt
python run_trained.py --in scenario.example.json --out result.json
```
- `--ckpt`/`--aas-dir` 생략 시 이 폴더의 `agent_mod.pt`·`aas_data/`를 자동 사용.
- 결정형(시드 고정 + argmax) — 같은 입력 = 같은 출력.
- 라이브러리: `from run_trained import TrainedModel; TrainedModel("agent_mod.pt", "aas_data").run(po=..., overrides=...)`.

## 입출력

입력 `scenario.json` (`scenario.example.json` 참고):
```json
{ "po": { "MODEL_A": {"qty": 6, "due_day": 22}, "MODEL_B": {"qty": 12, "due_day": 22}, "MODEL_C": {"qty": 24, "due_day": 22} },
  "overrides": { "ReplenishLeadDay": 3, "IdleWorkerThreshold": 1800, "seed": 42 } }
```
- `po` 생략 시 AAS 기본 PurchaseOrder. 일부 모델만 줘도 됨(나머지 기본 유지).
- `overrides` 허용 키: `ReplenishLeadDay`(일), `IdleWorkerThreshold`(초), `seed`. 그 외는 오류.

출력 `result.json`:
- `kpi`: makespan(sec/days) · 모델별 throughput/target · throughput_ratio · feasibility · energy_kwh · carbon_kgco2e · 모델별 납기 · due_pace_deficit(집계+모델별) · violations.
- `schedule`: 워커 스케줄 — `[{workstation, model, process_code, start_sec, end_sec}, ...]` (`end_sec` = 사이클 종료=워커 점유 끝).

## 제약 (중요)

- **모델 set 고정.** 이 `.pt`는 학습된 3모델(A/B/C) 전용 — **수량·납기 변경은 OK, 모델 추가/삭제는 신경망 입력차원(StateDim)이 바뀌어 로드 불가 → 재학습 필요.**
- **SMT 미포함.** 5파일(SMT 라인 비활성)로 학습/추론. SMT 반영하려면 6파일 재학습 후 재패키지.
- **외삽 주의.** 정책은 학습 때 본 PO 분포 기준 — 크게 다른 PO는 "최적"이 아닌 "학습정책 추정".

## 동결(.exe / Docker) — 추후

지금은 파이썬으로 직접 실행. 단일 실행파일이 필요하면 PyInstaller(.exe, 빌드 OS 전용) 또는 Docker(크로스플랫폼)로 이 폴더를 묶을 수 있다. 코드는 이미 동결 대비(`run_trained._resource_path`가 `sys._MEIPASS` 처리)돼 있다.
