import math
import numpy as np
from config import PITCH_FMIN, PITCH_FMAX, PITCH_MIN_CORR, GUITAR_STRINGS


def rms_dbfs(x: np.ndarray) -> float:
    if x is None or x.size == 0:
        return -np.inf
    rms = np.sqrt(np.mean(np.square(x), dtype=np.float64))
    if rms <= 1e-12:
        return -np.inf
    return 20.0 * np.log10(rms)


def estimate_pitch_autocorr(y: np.ndarray, sr: int) -> float:
    if y.size < 32:
        return np.nan
    
    y = y.astype(np.float64, copy=False)
    y -= np.mean(y)
    if np.allclose(y, 0.0):
        return np.nan
    y *= np.hanning(y.size)

    corr = np.correlate(y, y, mode='full')
    corr = corr[corr.size // 2:]
    if corr[0] <= 1e-12:
        return np.nan
    corr /= corr[0]

    min_lag = max(1, int(sr / PITCH_FMAX))
    max_lag = min(len(corr) - 1, int(sr / PITCH_FMIN))
    if max_lag <= min_lag + 2:
        return np.nan

    seg = corr[min_lag:max_lag]
    peak_rel = np.argmax(seg)
    peak_idx = peak_rel + min_lag
    peak_val = corr[peak_idx]
    if peak_val < PITCH_MIN_CORR:
        return np.nan

    if 1 < peak_idx < len(corr) - 2:
        y0, y1, y2 = corr[peak_idx - 1], corr[peak_idx], corr[peak_idx + 1]
        denom = 2 * (y0 - 2*y1 + y2)
        if abs(denom) > 1e-12:
            delta = (y0 - y2) / denom
            peak_idx = peak_idx + delta

    f0 = sr / peak_idx if peak_idx > 0 else np.nan
    if not np.isfinite(f0) or f0 < PITCH_FMIN or f0 > PITCH_FMAX:
        return np.nan
    return f0


def nearest_guitar_string(freq: float):
    if not np.isfinite(freq):
        return None
    
    best = None
    best_abs = 1e9
    for name, fref in GUITAR_STRINGS:
        cents = 1200.0 * math.log2(freq / fref)
        if abs(cents) < best_abs:
            best = (name, fref, cents)
            best_abs = abs(cents)
    return best

