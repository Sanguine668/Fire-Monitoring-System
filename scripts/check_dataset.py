"""用 ultralytics 自带函数验证 data.yaml 可读、类别数为 2。"""
from pathlib import Path

from ultralytics.data.utils import check_det_dataset

data = check_det_dataset(str(Path("datasets/fire-smoke-v2/data.yaml")))
print("names:", data["names"])
print("train:", data["train"])
print("val:", data["val"])
assert len(data["names"]) == 2, "类别数应为 2"
print("OK")
