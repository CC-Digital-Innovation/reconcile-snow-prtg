from enum import Enum

class Status(Enum):
    UNKNOWN=1
    SCANNING=2
    UP=3
    WARNING=4
    DOWN=5
    NO_PROBE=6
    PAUSED_BY_USER=7
    PAUSED_BY_DEPENDENCY=8
    PAUSED_BY_SCHEDULE=9
    UNUSUAL=10
    NOT_LICENSED=11
    PAUSED_UNTIL=12
    DOWN_ACKNOWLEDGED=13
    DOWN_PARTIAL=14

class BaseObject:
    """"""