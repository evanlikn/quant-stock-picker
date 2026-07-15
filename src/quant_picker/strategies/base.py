from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Literal

import pandas as pd

Action = Literal["buy", "hold", "sell"]
Interval = str


@dataclass
class Signal:
    action: Action
    strength: float
    reason: str


class Strategy(ABC):
    name: str

    @abstractmethod
    def param_space(self, interval: Interval) -> dict[str, list]:
        ...

    @abstractmethod
    def with_params(self, params: dict) -> Strategy:
        ...

    @abstractmethod
    def analyze(self, df: pd.DataFrame) -> Signal:
        ...

    @abstractmethod
    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        ...

    def format_params(self) -> str:
        return str(getattr(self, "_params", {}))
