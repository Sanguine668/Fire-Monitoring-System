"""把 D-Fire 整理成 ultralytics 可用的数据集描述文件。

不复制图片：用 txt 列表指向原图，避免多占 3GB 磁盘。
val 从 train 里按“编号尾部连续块”切出 10%，避免相邻帧泄漏。
空标注文件保留为负样本；仅剔除退化框（宽或高为 0）所在的行。
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
D_FIRE = ROOT / "datasets" / "d-fire"
OUT = ROOT / "datasets" / "fire-smoke-v2"
EXTRA = ROOT / "datasets" / "extra"
REPORTS = ROOT / "datasets" / "reports"
SMALL_AREA = 0.01
VAL_RATIO = 0.1
VAL_START = 0.45


def clean_label(label: Path, dropped: list[str]) -> tuple[bool, bool]:
    """去掉退化框行，返回（标注是否存在，是否含有效框）。

    空标注是合法负样本，必须保留。
    """
    if not label.is_file():
        return False, False
    lines = label.read_text(encoding="utf-8", errors="ignore").splitlines()
    kept: list[str] = []
    changed = False
    for line in lines:
        parts = line.split()
        if len(parts) != 5:
            if line.strip():
                changed = True
            continue
        try:
            w, h = float(parts[3]), float(parts[4])
        except ValueError:
            changed = True
            continue
        if w <= 0 or h <= 0:
            dropped.append(f"{label}: {line}")
            changed = True
            continue
        kept.append(line)
    if changed:
        label.write_text("\n".join(kept) + ("\n" if kept else ""), encoding="utf-8")
    return True, bool(kept)


def seq_key(stem: str) -> tuple[str, int]:
    m = re.match(r"^([A-Za-z]+)", stem)
    prefix = m.group(1) if m else stem[:3]
    n = re.search(r"(\d+)", stem)
    return prefix, int(n.group(1)) if n else 0


def collect(split: str, dropped: list[str]) -> list[tuple[Path, bool]]:
    img_dir = D_FIRE / split / "images"
    label_dir = D_FIRE / split / "labels"
    out: list[tuple[Path, bool]] = []
    for p in sorted(img_dir.glob("*.jpg")):
        exists, has_boxes = clean_label(label_dir / (p.stem + ".txt"), dropped)
        if exists:
            out.append((p, has_boxes))
    return out


def dump(name: str, files: list[Path]) -> None:
    (OUT / name).write_text("\n".join(p.as_posix() for p in files), encoding="utf-8")


def extra_images(pattern: str) -> list[Path]:
    return sorted(p for p in EXTRA.glob(pattern) if p.suffix.lower() in {".jpg", ".jpeg", ".png"})


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    REPORTS.mkdir(parents=True, exist_ok=True)
    dropped: list[str] = []

    train_all = collect("train", dropped)
    by_prefix: dict[str, list[tuple[Path, bool]]] = {}
    for p, has in train_all:
        by_prefix.setdefault(seq_key(p.stem)[0], []).append((p, has))

    val, train = [], []
    for files in by_prefix.values():
        files.sort(key=lambda item: seq_key(item[0].stem)[1])
        cut = max(1, int(len(files) * VAL_RATIO))
        start = min(int(len(files) * VAL_START), len(files) - cut)
        val.extend(p for p, _ in files[start:start + cut])
        train.extend(p for p, _ in files[:start] + files[start + cut:])

    test_pairs = collect("test", dropped)
    test_all = [p for p, _ in test_pairs]
    farfield: list[Path] = []
    for p in test_all:
        label = D_FIRE / "test" / "labels" / (p.stem + ".txt")
        boxes = [ln.split() for ln in label.read_text().splitlines() if ln.strip()]
        ratios = [float(b[3]) * float(b[4]) for b in boxes if len(b) == 5]
        if ratios and all(r < SMALL_AREA for r in ratios):
            farfield.append(p)

    dump("train.txt", train)
    dump("val.txt", val)
    dump("test.txt", test_all)
    dump("farfield.txt", farfield)

    direct = extra_images("*")
    pyronear = [p for p in direct if "_pos_" in p.name]
    hardneg = [p for p in direct if "_pos_" not in p.name]
    hardneg += extra_images("sunrise/*.jpeg")
    hardneg += extra_images("other_neg/**/*.jpg")
    dump("hardneg.txt", hardneg)
    dump("pyronear.txt", pyronear)

    (OUT / "data.yaml").write_text(
        "path: {p}\ntrain: {t}\nval: {v}\ntest: {s}\nnames:\n  0: smoke\n  1: fire\n".format(
            p=OUT.as_posix(),
            t=(OUT / "train.txt").as_posix(),
            v=(OUT / "val.txt").as_posix(),
            s=(OUT / "test.txt").as_posix(),
        ),
        encoding="utf-8",
    )
    (REPORTS / "dropped_degenerate_boxes.txt").write_text("\n".join(dropped), encoding="utf-8")
    train_set, val_set = set(train), set(val)
    train_neg = sum(1 for p, has in train_all if not has and p in train_set)
    val_neg = sum(1 for p, has in train_all if not has and p in val_set)
    print(f"train {len(train)}（负样本 {train_neg}）  val {len(val)}（负样本 {val_neg}）")
    print(f"test {len(test_all)}  远景小目标 {len(farfield)}")
    print(f"hardneg {len(hardneg)}  pyronear {len(pyronear)}  退化框剔除 {len(dropped)} 行")


if __name__ == "__main__":
    main()
