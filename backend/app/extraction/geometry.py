from dataclasses import dataclass, field
from typing import Protocol
from PIL import Image


def area(b):
    return max(0, b[2]-b[0]) * max(0, b[3]-b[1])


def intersect(a, b):
    return [max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3])]


def iou(a, b):
    intersection = area(intersect(a, b))
    return intersection / max(1e-9, area(a) + area(b) - intersection)


def containment(a, b):
    return area(intersect(a, b)) / max(1e-9, area(a))


@dataclass
class Detection:
    bbox: list[float]
    confidence: float
    method: str
    source: dict | None = None
    reasons: list[str] = field(default_factory=list)


class Detector(Protocol):
    name: str
    def detect(self, image: Image.Image, settings) -> list[Detection]: ...
