# reinforcement_learning_v2.1

simulation_v2.1의 강화학습 코드를 그대로 모은 폴더. simulation_v2.2 시뮬레이션 인스턴스와는 아직 연결되지 않음.

- 원본: `simulation_v2.1/` 의 `reinforcement_learning/`, `episode_procedure.py`, `train_model.py`, `evaluate_model.py`, `knowledge_graph.py`, `export.py`, `scenario_conditions.py` (수정 없음)
- 이 코드가 import하는 v2.1의 `aas_preprocessing`, `discrete_event_simulation`은 이 폴더에 없음. v2.2의 `simulation_generator.py`·인스턴스에 맞게 다시 연결해야 실행 가능
- 학습된 모델(`model/integrated_model.pt`)은 저장소 `.gitignore`의 `*.pt` 규칙으로 올리지 않음
