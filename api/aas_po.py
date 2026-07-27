# -*- coding: utf-8 -*-
# AAS PurchaseOrder 읽기/쓰기 — aas_data JSON 파일이 단일 진실.
# 쓰기는 외과적: 각 모델 Property 의 value(수량)와 Qualifier DueDay 만 바꾸고
# 그 외 구조·필드는 그대로 둔다. 모델 추가/삭제는 불가(StateDim 고정 — 재학습 필요).
import json
import os

PSM_FILE = 'ProvisionOfSimulationModel.json'


def _po_element(doc: dict) -> dict:
    for submodel in doc['submodels']:
        if submodel.get('idShort') != 'SimulationModels':
            continue
        for model_group in submodel.get('submodelElements', []):
            if model_group.get('idShort') != 'SimulationModel':
                continue
            for element in model_group.get('value', []):
                if element.get('idShort') == 'PurchaseOrder':
                    return element
    raise KeyError('SimulationModels>SimulationModel>PurchaseOrder 를 찾을 수 없습니다.')


def _qualifier(prop: dict, type_name: str) -> dict:
    for qualifier in prop.get('qualifiers', []):
        if qualifier.get('type') == type_name:
            return qualifier
    raise KeyError(f"{prop.get('idShort')} 에 Qualifier {type_name} 이 없습니다.")


def read_po(aas_dir: str) -> dict:
    with open(os.path.join(aas_dir, PSM_FILE), encoding='utf-8') as fp:
        doc = json.load(fp)
    po = {}
    for prop in _po_element(doc)['value']:
        po[prop['idShort']] = {
            'qty'           : int(prop['value']),
            'due_day'       : int(_qualifier(prop, 'DueDay')['value']),
            'registered_day': int(_qualifier(prop, 'RegisteredDay')['value']),
        }
    return po


def write_po(aas_dir: str, updates: dict) -> dict:
    """updates = {model_id: {'qty': int?, 'due_day': int?}} 부분 갱신. 갱신 후 전체 PO 반환."""
    path = os.path.join(aas_dir, PSM_FILE)
    with open(path, encoding='utf-8') as fp:
        doc = json.load(fp)
    element = _po_element(doc)
    props = {prop['idShort']: prop for prop in element['value']}

    unknown = sorted(set(updates) - set(props))
    if unknown:
        raise ValueError(f"등록할 수 없는 모델: {unknown} — 모델 추가/삭제는 불가합니다. "
                         f"등록 가능한 모델: {sorted(props)}")
    for model_id, spec in updates.items():
        prop = props[model_id]
        if 'qty' in spec and spec['qty'] is not None:
            qty = int(spec['qty'])
            if qty < 0:
                raise ValueError(f'{model_id} 의 PO 수량은 0 이상이어야 합니다: {qty}')
            prop['value'] = str(qty)
        if 'due_day' in spec and spec['due_day'] is not None:
            due_day = int(spec['due_day'])
            if due_day < 1:
                raise ValueError(f'{model_id} 의 납기일은 1 이상이어야 합니다: {due_day}')
            _qualifier(prop, 'DueDay')['value'] = str(due_day)

    # 원본 포맷 유지: 2칸 들여쓰기 + CRLF, 끝 개행 없음
    tmp = f'{path}.tmp'
    with open(tmp, 'w', encoding='utf-8', newline='\r\n') as fp:
        json.dump(doc, fp, ensure_ascii=False, indent=2)
    os.replace(tmp, path)
    return read_po(aas_dir)
