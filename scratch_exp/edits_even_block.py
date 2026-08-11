import json

SHEET = '2-1) PO납기일 기반 생산계획'
RUN = 'result/runs/q540s__compbase-due4__realloc-22222'

HDR_SRC = 'R2:AZ4'        # 최적해 블록: 제목행 + 그룹헤더 + 항목헤더 (+ R열 '비고')
HDR_DST = 68              # 균등 블록 제목행 (최적해 데이터가 65행에서 끝남)
R0 = HDR_DST + 3          # 데이터 첫 행 = 71
C0 = 20                   # T = 경과 작업시간(h)
TOTAL = 52                # AZ = 전체
NOTE = 18                 # R = 비고
LABEL = '균등 분배 (2/2/2/2/2)'


def apply(app, doc, kind):
    pl = json.load(open(f'{RUN}/xlsx_payload.json', encoding='utf-8'))
    rows = [[b['wh'], *b['cum'], *b['idle'], b['base'], *b['smt'], *b['asm']]
            for b in pl['buckets']]
    n, w = len(rows), len(rows[0])          # w = 32

    ws = doc.Worksheets(SHEET)
    ws.Range(HDR_SRC).Copy(ws.Range(f'R{HDR_DST}'))           # 헤더 3행을 서식째로
    app.CutCopyMode = False
    ws.Cells(HDR_DST, C0).Value = LABEL                        # 제목행: '최적해' → 균등

    ws.Range(ws.Cells(R0, C0), ws.Cells(R0 + n - 1, C0 + w - 1)).Value = rows
    for i in range(n):
        r = R0 + i
        ws.Cells(r, TOTAL).Formula = f'=SUM(AH{r}:AY{r})'      # 기저 + SMT7 + 조립10

    ws.Cells(R0, NOTE).Value = LABEL                           # 데이터 첫 행 비고 (최적해와 동일 배치)
