"""에이전트 TSV 의 형식 문제를 원문 대조로 고친다.

두 가지를 고친다.
  1) 탭 개수가 4가 아닌 행 (값·단위가 비었을 때 탭이 더 들어간 경우)
  2) 파라미터명이 CamelCase 로 붙어버린 것 → 원문 표기로 복원

원문 표기는 같은 폴더의 원문 md 에서 라벨 후보를 모아 대조한다.
공백·문장부호만 제거해 비교하므로 원문에 없는 이름을 새로 만들지 않는다.
"""

import csv
import glob
import os
import re
import sys

SRC = r"C:\Users\KangTaehui\KG\keti\CPRO_조립공정\시뮬레이션\Package\docs\원본자료\keti-fab\AAS원문묶음"

CAMEL = re.compile(r"^[A-Z][a-z]+[A-Z]")


def norm(s):
    return re.sub(r"[^0-9a-z가-힣]", "", s.lower())


def labels_from(md_path):
    """원문에서 파라미터 라벨로 쓰였을 문자열을 모은다."""
    out = set()
    for raw in open(md_path, encoding="utf-8").read().split("\n"):
        l = raw.strip(" -+·*○◦●⦁\t")
        if not l or l.startswith(("#", "```", "출처", "URL", "- 출처", "- URL")):
            continue
        # '(2) Centering unit', '1. Light source module' 처럼 번호가 앞에 붙은 머리글도 라벨이다
        l = re.sub(r"^\(?\d+\)?[.)]?\s+", "", l).strip()
        if not l:
            continue
        m = re.match(r"^\[([^\]]+)\]\s*(.+?)\s*:\s*", l)      # 매뉴얼: [유닛] 이름 : 값
        if m:
            out.add(m.group(1).strip())
            out.add(m.group(2).strip())
            continue
        m = re.match(r"^(.{1,60}?)\s*:\s*\S", l)               # 이름 : 값
        if m:
            out.add(m.group(1).strip())
            continue
        # 'Buffer unit\t1 set' 처럼 탭·다중공백으로 값이 이어진 머리글
        head = re.split(r"\t|\s{2,}", l)[0].strip()
        for cand in {l, head}:
            if 2 < len(cand) < 50:
                out.add(cand)
    return out


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    total_fix_name = total_fix_tab = 0

    for tsv in sorted(glob.glob(os.path.join(SRC, "out_*.tsv"))):
        base = os.path.basename(tsv).replace("out_", "").replace(".tsv", "")
        md = os.path.join(SRC, base + ".md")
        idx = {}
        if os.path.exists(md):
            for lb in labels_from(md):
                idx.setdefault(norm(lb), lb)

        rows = list(csv.DictReader(open(tsv, encoding="utf-8"), delimiter="\t"))
        if not rows:
            continue
        cols = ["파라미터명", "값", "단위", "출처", "근거URL"]

        n_name = 0
        for r in rows:
            nm = (r.get("파라미터명") or "").strip()
            if not CAMEL.match(nm):
                continue
            parts, out, changed = nm.split("."), [], False
            for p in parts:
                c = idx.get(norm(p))
                # 원문에 있는 표기로만 바꾼다. 없으면 그대로 둔다.
                if c and c != p:
                    out.append(c)
                    changed = True
                else:
                    out.append(p)
            if changed:
                r["파라미터명"] = ".".join(out)
                n_name += 1

        # 항상 5열로 다시 쓴다 (탭 개수 문제 해소)
        before = sum(1 for l in open(tsv, encoding="utf-8").read().split("\n")[1:]
                     if l.strip() and l.count("\t") != 4)
        # csv.writer 는 값에 구분자·따옴표가 있으면 이스케이프하려다 실패한다.
        # TSV 는 단순 join 이 안전하다 (탭·개행만 공백으로 바꿔 준다).
        out_lines = ["\t".join(cols)]
        for r in rows:
            out_lines.append("\t".join(
                (r.get(c) or "").replace("\t", " ").replace("\n", " ") for c in cols))
        with open(tsv, "w", encoding="utf-8", newline="") as f:
            f.write("\n".join(out_lines) + "\n")

        total_fix_name += n_name
        total_fix_tab += before
        if n_name or before:
            print(f"{base[:30]:32} 이름복원 {n_name:>3} / 열정리 {before:>3}")

    print(f"\n이름 복원 {total_fix_name}건 / 열 정리 {total_fix_tab}건")


if __name__ == "__main__":
    main()
