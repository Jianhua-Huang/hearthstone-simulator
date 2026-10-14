"""Public failure categories; failed actions never commit partially."""


class EngineError(ValueError):
    pass


class IllegalAction(EngineError):
    pass


class ResolutionError(EngineError):
    pass


class ResolutionLimitExceeded(ResolutionError):
    pass


class SnapshotError(EngineError):
    pass
