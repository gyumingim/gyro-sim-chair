"""Compatibility shim: the lessons / instructor moved to training/ (engine.py, lessons.py). Kept so old imports work."""
from training.engine import Trainer as Tutorial          # noqa: F401
from training.lessons import LESSONS                     # noqa: F401
