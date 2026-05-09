"""AAS 입력 데이터 검증 모듈.

시뮬레이션 진입 직전에 한 번 호출하여 AAS 템플릿이 시뮬에 필요한 형태로
채워졌는지 확인한다. 시뮬 코드 본문은 검증 결과를 신뢰하고 fallback 없이
필드를 직접 사용해야 한다.

사용법:
    from cpro_aas_validator import validate_aas
    validate_aas(aas_models)   # 위반 발견 시 RuntimeError
"""
from path_extractor import AASModel


def validate_aas(aas_models: dict) -> None:
    errors: list[str] = []

    for model_id, aas in aas_models.items():
        _check_manufacturing_process(model_id, aas, errors)
        _check_workstations(model_id, aas, errors)
        _check_skill_levels(model_id, aas, errors)
        _check_hierarchical_structures(model_id, aas, errors)

    _check_process_to_workstation_mapping(aas_models, errors)

    if not any(aas.SkillLevelType for aas in aas_models.values()):
        errors.append('[GLOBAL] SkillLevelType 정의된 AAS 가 하나도 없음')
    if not any(aas.WorkstationWorkerMatchingData for aas in aas_models.values()):
        errors.append('[GLOBAL] WorkstationWorkerMatchingData 정의된 AAS 가 하나도 없음')
    if not any(aas.schedule for aas in aas_models.values()):
        errors.append('[GLOBAL] schedule(WorkStartTime/WorkEndTime/BreakDurationMin) 정의된 AAS 가 하나도 없음')

    if errors:
        raise RuntimeError(
            'AAS 검증 실패 ({}건):\n  '.format(len(errors))
            + '\n  '.join(errors))


def _check_manufacturing_process(model_id: str, aas: AASModel, errors: list) -> None:
    if model_id == 'COMMON':
        return
    if not aas.ManufacturingProcess:
        errors.append(f'[{model_id}] ManufacturingProcess 비어있음')
        return

    codes = set(aas.ManufacturingProcess)
    for pc, node in aas.ManufacturingProcess.items():
        if node.CycleTimeSec < 0:
            errors.append(f'[{model_id}.{pc}] CycleTimeSec={node.CycleTimeSec} (≥0 필요)')
        if not 0.0 <= node.DefectRate <= 1.0:
            errors.append(f'[{model_id}.{pc}] DefectRate={node.DefectRate} (∈[0,1] 필요)')
        if not node.ProcessGroup:
            errors.append(f'[{model_id}.{pc}] ProcessGroup 비어있음')
        if not node.DepType:
            errors.append(f'[{model_id}.{pc}] DepType 비어있음')
        for prev in node.DepPrev:
            if prev not in codes:
                errors.append(f'[{model_id}.{pc}] DepPrev "{prev}" — 같은 모델 내 미정의 공정 참조')
        for item in node.InputBOM:
            if not item.item_code:
                errors.append(f'[{model_id}.{pc}] InputBOM 항목의 item_code 비어있음')
            if item.Quantity <= 0:
                errors.append(f'[{model_id}.{pc}.{item.item_code}] Quantity={item.Quantity} (>0 필요)')


def _check_workstations(model_id: str, aas: AASModel, errors: list) -> None:
    for ws_id, ws in aas.WorkstationWorkerMatchingData.items():
        if ws.WorkstationConfigurationRecords < 1:
            errors.append(f'[{model_id}.{ws_id}] WorkstationConfigurationRecords={ws.WorkstationConfigurationRecords} (≥1 필요)')
        if ws.WorkStartTime >= ws.WorkEndTime:
            errors.append(f'[{model_id}.{ws_id}] WorkStartTime({ws.WorkStartTime}) >= WorkEndTime({ws.WorkEndTime})')
        if ws.BreakDurationMin.min < 0 or ws.BreakDurationMin.max < ws.BreakDurationMin.min:
            errors.append(f'[{model_id}.{ws_id}] BreakDurationMin range 비정상: '
                          f'min={ws.BreakDurationMin.min}, max={ws.BreakDurationMin.max}')


def _check_skill_levels(model_id: str, aas: AASModel, errors: list) -> None:
    for name, sl in aas.SkillLevelType.items():
        if sl.ct_factor <= 0:
            errors.append(f'[{model_id}.SkillLevel.{name}] ct_factor={sl.ct_factor} (>0 필요)')
        if sl.dr_factor <= 0:
            errors.append(f'[{model_id}.SkillLevel.{name}] dr_factor={sl.dr_factor} (>0 필요)')


def _check_process_to_workstation_mapping(aas_models: dict, errors: list) -> None:
    """모든 ProcessCode 가 정확히 1개의 Workstation 의 AssignedProcessGroups 에
    등록되어 있어야 한다 (0개=미배정, 2개 이상=중복배정 모두 위반).
    또한 AssignedProcessGroups 의 모든 token 이 어떤 모델의 ProcessCode 에
    실제로 정의되어 있어야 한다 (dangling 참조 금지).
    """
    all_process_codes: dict[str, str] = {}
    for model_id, aas in aas_models.items():
        if model_id == 'COMMON':
            continue
        for pc in aas.ManufacturingProcess:
            all_process_codes[pc] = model_id

    process_to_ws: dict[str, list] = {}
    for model_id, aas in aas_models.items():
        for ws_id, ws in aas.WorkstationWorkerMatchingData.items():
            for token in ws.AssignedProcessGroups:
                process_to_ws.setdefault(token, []).append(f'{model_id}.{ws_id}')

    for pc, model_id in all_process_codes.items():
        ws_list = process_to_ws.get(pc, [])
        if len(ws_list) == 0:
            errors.append(f'[{model_id}.{pc}] 어떤 Workstation 의 AssignedProcessGroups 에도 등록 안 됨 (정확히 1개 필요)')
        elif len(ws_list) > 1:
            errors.append(f'[{model_id}.{pc}] 복수 Workstation 에 중복 등록: {ws_list}')

    for token, ws_list in process_to_ws.items():
        if token not in all_process_codes:
            errors.append(f'[{ws_list[0]}] AssignedProcessGroups 의 "{token}" — 어느 모델의 ProcessCode 에도 정의 안 됨 (dangling)')


def _check_hierarchical_structures(model_id: str, aas: AASModel, errors: list) -> None:
    if model_id == 'COMMON':
        return
    hs = aas.HierarchicalStructures
    if not hs.pcb_entries:
        errors.append(f'[{model_id}] HierarchicalStructures.pcb_entries 비어있음')
    for pcb_id, pcb in hs.pcb_entries.items():
        if pcb.Quantity <= 0:
            errors.append(f'[{model_id}.{pcb_id}] Quantity={pcb.Quantity} (>0 필요)')
        if not pcb.SMT_Side:
            errors.append(f'[{model_id}.{pcb_id}] SMT_Side 비어있음')
        for comp in pcb.components:
            if not comp.item_code:
                errors.append(f'[{model_id}.{pcb_id}] component item_code 비어있음')
            if comp.Quantity <= 0:
                errors.append(f'[{model_id}.{pcb_id}.{comp.item_code}] Quantity={comp.Quantity} (>0 필요)')
