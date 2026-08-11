import json

SHEET = '2-1) PO납기일 기반 생산계획'
P_COL = 16                       # P = 총 전력소모량[kWh]

# 시트 배분표 행 → run 태그 (배분 조합으로 대조 확인 후 기입)
ROWS = [(5,  '41112-semi2', [4, 1, 1, 1, 2, 2]),
        (6,  '41113',       [4, 1, 1, 1, 3, 1]),
        (7,  '51112',       [5, 1, 1, 1, 2, 1]),
        (8,  '41122',       [4, 1, 1, 2, 2, 1]),
        (9,  '61111',       [6, 1, 1, 1, 1, 1]),
        (10, '31114',       [3, 1, 1, 1, 4, 1]),
        (11, '21124',       [2, 1, 1, 2, 4, 1]),
        (12, '22222',       [2, 2, 2, 2, 2, 1]),
        (13, 'none',        [0, 0, 0, 0, 0, 11])]


def apply(app, doc, kind):
    ws = doc.Worksheets(SHEET)
    for row, tag, quota in ROWS:
        got = [ws.Cells(row, c).Value for c in range(9, 15)]     # I..N
        if [int(v) for v in got] != quota:                        # 행-배분 대조
            raise ValueError(f'row {row} 배분 불일치: 시트={got} 기대={quota}')
        s = json.load(open(f'result/runs/q540s__compbase-due4__realloc-{tag}/summary.json',
                           encoding='utf-8'))
        ws.Cells(row, P_COL).Value = s['total_energy_kwh']
    ws.Range(f'P5:P{ROWS[-1][0]}').NumberFormat = '0.00'
