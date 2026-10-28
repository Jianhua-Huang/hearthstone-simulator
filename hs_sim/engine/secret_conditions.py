"""Transient Secret admission requirements; these are never frame work."""
from dataclasses import dataclass


@dataclass(frozen=True)
class SecretHandSpace:
    """A pure card match whose effective hand admission belongs to the engine."""
    matched: bool

    def __post_init__(self):
        if type(self.matched) is not bool:
            raise ValueError('Secret hand admission requires a boolean match')
