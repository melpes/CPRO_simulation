# CPRO_simulation

AAS(일반화 템플릿)를 읽어 바로 실행할 수 있는 SimPy 시뮬레이션 인스턴스를 만든다. 생산성과 탄소배출량(MCF)을 함께 계산한다.

| 위치 | 내용 |
|---|---|
| `path_extractor.py` | AAS 파일 읽기, 경로 표현으로 요소 접근 |
| `knowledge_graph.py` | AAS → KG(노드 Process·Machine·Worker·Warehouse·MCF 요소, 관계 Require·Sequence·Join·ContributeTo) |
| `simulation_generator.py` | KG 관계와 AAS 값 → 인스턴스 값(json)과 실행 코드(py) 생성. SMT 라인·기저부하·MCF 계산 모듈 포함 |
| `aas_data/` | 입력 AAS(제품·공정·자원·창고·시뮬레이션, `Machine/` 설비 AAS, `MCF/` 탄소 경계) |
| `instances/` | 생성된 인스턴스 예 |
| `tests/` | v2.1 결과와 비교하는 단위테스트 |
| `reinforcement_learning_v2.1/` | v2.1 강화학습 코드 보관(아직 미연결) |

```
python simulation_generator.py aas_data instances/sim_instance.py
python instances/sim_instance.py --quantity 540
python -m unittest tests.test_compare_v21
```

이전 코드(옛 Package 루트 코드, simulation_v2.0)는 태그 `archive/main-before-cleanup-20261120`에 있다.
