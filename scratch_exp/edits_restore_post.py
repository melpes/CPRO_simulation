import json

SHEET = '2) PO납기일 기반 생산계획'
BLK = 'scratch_exp/post_block.json'

C0 = 8                   # H열
TITLE, HDR, DATA = 104, 105, 107      # 제목 / 헤더 2행 / 데이터 74행
TOTAL_COL = 38           # AL = 전체


def _cl(col):
    s = ''
    while col:
        col, r = divmod(col - 1, 26)
        s = chr(65 + r) + s
    return s


def apply(app, doc, kind):
    blk = json.load(open(BLK, encoding='utf-8'))
    ws = doc.Worksheets(SHEET)
    w = len(blk['title'][0])              # 31 (H..AL)

    for r0, rows in ((TITLE, blk['title']), (HDR, blk['hdr']), (DATA, blk['data'])):
        n = len(rows)
        ws.Range(ws.Cells(r0, C0), ws.Cells(r0 + n - 1, C0 + w - 1)).Value = rows

    # 전체(AL) 열은 수식으로 되살린다 — 기저(U) + SMT7 + 조립9
    for i in range(len(blk['data'])):
        r = DATA + i
        ws.Cells(r, TOTAL_COL).Formula = f'=SUM(U{r}:AK{r})'
