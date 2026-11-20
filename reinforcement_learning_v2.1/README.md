# reinforcement_learning_v2.1

simulation_v2.1의 강화학습 코드를 모아 둔 폴더. 현재 시뮬레이션 인스턴스와는 아직 연결되지 않음.

- 원본: `simulation_v2.1/` 의 `reinforcement_learning/`(action·model·ppo·reward·state), `episode_procedure.py`, `train_model.py`, `evaluate_model.py`, `knowledge_graph.py`, `export.py`, `scenario_conditions.py`. 파일 내용은 수정 없이 한 폴더에 펼쳐 둠
- 원래 `from reinforcement_learning import ...`로 불러오던 부분과 v2.1의 `aas_preprocessing`, `discrete_event_simulation` import는 이 구조에서 그대로는 실행되지 않음. 다시 연결할 때 함께 맞춤
- 학습된 모델(`model/integrated_model.pt`)은 올리지 않음
