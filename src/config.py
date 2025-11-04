import platform
from dataclasses import dataclass

IS_PI = platform.machine().startswith(("arm", "aarch64")) or "raspbian" in platform.platform().lower()

@dataclass
class Profile:
    sample_rate: int
    block_size: int
    pitch_win: int
    ui_ms: int

PROFILE_ECO = Profile(12_000, 2048, 2048, 100)
PROFILE_FULL = Profile(24_000, 2048, 4096, 80)

PITCH_FMIN = 65.0
PITCH_FMAX = 1000.0
PITCH_MIN_CORR = 0.2
TUNER_UPDATE_MS = 180
TUNER_RANGE_CENTS = 100.0
TUNER_EMA_ALPHA = 0.15

PEAK_HOLD_SECONDS = 1.5
MAX_RECORD_DURATION = 60.0

GUITAR_STRINGS = [
    ("E2", 82.41),
    ("A2", 110.00),
    ("D3", 146.83),
    ("G3", 196.00),
    ("B3", 246.94),
    ("E4", 329.63)
]

COLOR_BG = (11, 18, 32)
COLOR_SURF = (18, 26, 42)
COLOR_ACCENT = (45, 164, 78)
COLOR_ACCENT2 = (31, 111, 235)
COLOR_TEXT = (230, 237, 243)
COLOR_SUBTLE = (122, 134, 153)
COLOR_WARN = (240, 173, 78)
COLOR_RED = (200, 60, 60)

