from enum import Enum

class Status(str, Enum):
    UNKNOWN='unknown'
    SCANNING='scanning'
    UP='up'
    WARNING='warning'
    DOWN='down'
    NO_PROBE='no probe'
    PAUSED = 'paused  (paused)'
    PAUSED_BY_USER='paused by user'
    PAUSED_BY_DEPENDENCY='paused by dependency'
    PAUSED_BY_SCHEDULE='paused by schedule'
    PAUSED_BY_PARENT='paused  (paused by parent)'
    UNUSUAL='unusual'
    NOT_LICENSED='not licensed'
    PAUSED_UNTIL='paused until'
    DOWN_ACKNOWLEDGED='down acknowledged'
    DOWN_PARTIAL='down partial'
