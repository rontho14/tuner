
import math
import time
import queue
import threading
import platform
import os
import requests
from collections import deque
from dataclasses import dataclass
from datetime import datetime

import numpy as np
import pygame
import sounddevice as sd

# =========================
# Integração Ubidots HTTP
# =========================
#export UBIDOTS_TOKEN="BBUS-5y9cUes4WxsHDm3hJPyjkvIISaYUPq"

UBIDOTS_TOKEN = os.getenv("UBIDOTS_TOKEN")
DEVICE_LABEL = "raspi_vapireca_001"
API_URL = f"https://industrial.api.ubidots.com/api/v1.6/devices/{DEVICE_LABEL}"

HEADERS = {
    "Content-Type": "application/json",
    "X-Auth-Token": UBIDOTS_TOKEN
}

def post_to_ubidots(payload: dict) -> bool:
    """Envia dicionário de dados ao Ubidots (HTTP REST)."""
    if not UBIDOTS_TOKEN:
        # token não configurado; não enviar
        return False
    try:
        resp = requests.post(API_URL, headers=HEADERS, json=payload, timeout=6)
        resp.raise_for_status()
        return True
    except Exception as e:
        print("[Ubidots] erro ao enviar:", e)
        return False

def ubidots_worker(app_instance):
    """Thread que periodicamente envia dados de estado para Ubidots."""
    interval = 5.0  
    while app_instance.running:
        try:
            payload = {
                "db": round(app_instance.state.last_db_value, 2)
                    if np.isfinite(app_instance.state.last_db_value) else None,
                "peak_db": round(app_instance.state.peak_db_value, 2)
                    if np.isfinite(app_instance.state.peak_db_value) else None,
                "pitch_hz": round(app_instance.state.pitch_hz, 2)
                    if np.isfinite(app_instance.state.pitch_hz) else None,
                "pitch_cents": round(app_instance.state.pitch_cents, 2)
                    if np.isfinite(app_instance.state.pitch_cents) else None
            }
            payload = {k: v for k, v in payload.items() if v is not None}
            if payload:
                post_to_ubidots(payload)
        except Exception as e:
            print("[Ubidots] falha no worker:", e)
        time.sleep(interval)

# =========================
# Ambiente e perfis
# =========================
IS_PI = platform.machine().startswith(("arm", "aarch64")) or "raspbian" in platform.platform().lower()

@dataclass
class Profile:
    sample_rate: int
    block_size: int
    pitch_win: int
    ui_ms: int

PROFILE_ECO  = Profile(12_000, 2048, 2048, 100)  
PROFILE_FULL = Profile(24_000, 2048, 4096, 80)    

# Afinador
PITCH_FMIN = 65.0
PITCH_FMAX = 1000.0
PITCH_MIN_CORR = 0.2
TUNER_UPDATE_MS = 180
TUNER_RANGE_CENTS = 100.0
TUNER_EMA_ALPHA = 0.15

# Decibelímetro
PEAK_HOLD_SECONDS = 1.5
MAX_RECORD_DURATION = 60.0  # segundos

# Cordas padrão (violão/guitarra)
GUITAR_STRINGS = [
    ("E2", 82.41), ("A2", 110.00), ("D3", 146.83),
    ("G3", 196.00), ("B3", 246.94), ("E4", 329.63)
]

# =========================
# DSP util
# =========================
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

    # interpolação parabólica
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

# =========================
# Áudio
# =========================
@dataclass
class AudioState:
    device_index: int | None = None
    calibration_offset_db: float = 60.0
    last_db_value: float = -np.inf
    peak_db_value: float = -np.inf
    peak_timestamp: float = 0.0
    pitch_hz: float = float('nan')
    pitch_note_name: str | None = None
    pitch_note_ref: float = float('nan')
    pitch_cents: float = float('nan')

class AudioStream:
    def __init__(self, profile: Profile, state: AudioState):
        self.profile = profile
        self.state = state
        self.q = queue.Queue(maxsize=32)
        self.pitch_buf = deque(maxlen=profile.pitch_win)
        self.stream = None
        self.running = False

    def _callback(self, indata, frames, time_info, status):
        if status:
            pass
        try:
            x = indata[:, 0].astype(np.float32, copy=False) if indata.ndim > 1 else indata.astype(np.float32, copy=False)
            self.q.put_nowait(x.copy())
        except queue.Full:
            pass

    def start(self):
        if self.running:
            return
        kwargs = dict(
            samplerate=self.profile.sample_rate,
            blocksize=self.profile.block_size,
            channels=1, dtype='float32',
            latency='high',
            callback=self._callback
        )
        if self.state.device_index is not None:
            kwargs['device'] = (self.state.device_index, None)
        self.stream = sd.InputStream(**kwargs)
        self.stream.start()
        self.running = True

    def stop(self):
        if self.stream is not None:
            try:
                self.stream.stop()
                self.stream.close()
            except Exception:
                pass
        self.running = False

    def read_block(self, timeout=0.2) -> np.ndarray | None:
        try:
            return self.q.get(timeout=timeout)
        except queue.Empty:
            return None

    def push_pitch(self, x: np.ndarray):
        if x is not None and x.size > 0:
            self.pitch_buf.extend(x.tolist())

    def get_pitch_window(self) -> np.ndarray:
        if len(self.pitch_buf) < int(self.profile.pitch_win * 0.6):
            return np.array([], dtype=np.float32)
        return np.asarray(self.pitch_buf, dtype=np.float32)

# =========================
# UI (Pygame)
# =========================
class App:
    def __init__(self):
        pygame.init()
        pygame.display.set_caption("Áudio Toolkit")
        self.fullscreen = True
        self.size = (800, 480)  # display 7"
        self.screen = pygame.display.set_mode(self.size, pygame.FULLSCREEN)
        pygame.mouse.set_visible(False)

        # Paleta
        self.BG = (11, 18, 32)
        self.SURF = (18, 26, 42)
        self.ACCENT = (45, 164, 78)
        self.ACCENT2 = (31, 111, 235)
        self.TEXT = (230, 237, 243)
        self.SUBTLE = (122, 134, 153)
        self.WARN = (240, 173, 78)
        self.RED = (200, 60, 60)

        # Fontes
        self.font12 = pygame.font.SysFont(None, 12)
        self.font14 = pygame.font.SysFont(None, 14)
        self.font16 = pygame.font.SysFont(None, 16, bold=True)
        self.font20 = pygame.font.SysFont(None, 20, bold=True)
        self.font28 = pygame.font.SysFont(None, 28, bold=True)
        self.font32 = pygame.font.SysFont(None, 32, bold=True)
        self.font48 = pygame.font.SysFont(None, 48, bold=True)
        self.font72 = pygame.font.SysFont(None, 72, bold=True)
        self.font96 = pygame.font.SysFont(None, 96, bold=True)

        # Estado
        self.active_tab = "db"  # db | tuner
        self.profile = PROFILE_ECO if IS_PI else PROFILE_FULL
        self.state = AudioState()
        self.audio = AudioStream(self.profile, self.state)
        self.running = True

        # Timers
        self.last_tuner = 0.0

        # gravação (manual)
        self.recording = False
        self.record_start_time = 0.0
        self.record_samples = []  # (rel_time, db)
        self.record_report = None
        self.report_overlay = False  

        # smoothing do ponteiro do afinador
        self.smoothed_cents = 0.0

        # Worker de áudio
        self.worker = threading.Thread(target=self._audio_worker, daemon=True)
        self.worker.start()

        # Iniciar stream
        self._restart_stream()

        # Iniciar thread Ubidots (HTTP)
        threading.Thread(target=ubidots_worker, args=(self,), daemon=True).start()

    # ---------- worker ----------
    def _audio_worker(self):
        while self.running:
            blk = self.audio.read_block(timeout=0.2)
            if blk is None:
                continue
            db = rms_dbfs(blk) + self.state.calibration_offset_db
            self.state.last_db_value = db
            now = time.time()
            if (db > self.state.peak_db_value) or ((now - self.state.peak_timestamp) > PEAK_HOLD_SECONDS):
                self.state.peak_db_value = db
                self.state.peak_timestamp = now

            # gravação manual + timeout
            if self.recording:
                rel = now - self.record_start_time
                self.record_samples.append((rel, float(db)))
                if rel >= MAX_RECORD_DURATION:
                    self._stop_and_finalize_recording()

            # afinador (throttle)
            if (now - self.last_tuner) * 1000.0 >= TUNER_UPDATE_MS:
                self.audio.push_pitch(blk)
                win = self.audio.get_pitch_window()
                f0 = estimate_pitch_autocorr(win, self.profile.sample_rate) if win.size > 0 else np.nan
                self.state.pitch_hz = f0
                info = nearest_guitar_string(f0) if np.isfinite(f0) else None
                if info:
                    name, fref, cents = info
                    self.state.pitch_note_name = name
                    self.state.pitch_note_ref = fref
                    self.state.pitch_cents = cents
                else:
                    self.state.pitch_note_name = None
                    self.state.pitch_note_ref = float('nan')
                    self.state.pitch_cents = float('nan')
                # suavização EMA do ponteiro
                target = self.state.pitch_cents if np.isfinite(self.state.pitch_cents) else 0.0
                self.smoothed_cents = (1.0 - TUNER_EMA_ALPHA) * self.smoothed_cents + TUNER_EMA_ALPHA * target
                self.last_tuner = now

    # ---------- gravação / relatório ----------
    def _start_recording(self):
        self.record_samples = []
        self.record_start_time = time.time()
        self.recording = True
        self.record_report = None
        self.report_overlay = False

    def _stop_and_finalize_recording(self):
        self.recording = False
        self._finalize_recording()
        self.report_overlay = True

    def _finalize_recording(self):
        if not self.record_samples:
            self.record_report = {
                'samples': [],
                'min_db': None, 'max_db': None,
                'mean_db': None, 'median_db': None, 'std_db': None,
                'peak_time': None, 'min_time': None,
                'peak_value': None, 'min_value': None,
                'duration': 0.0, 'timestamp': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }
            return

        times = np.array([t for (t, v) in self.record_samples], dtype=np.float64)
        vals = np.array([v for (t, v) in self.record_samples], dtype=np.float64)

        max_idx = int(np.nanargmax(vals))
        min_idx = int(np.nanargmin(vals))
        self.record_report = {
            'samples': list(zip(times.tolist(), vals.tolist())),
            'min_db': float(np.nanmin(vals)),
            'max_db': float(np.nanmax(vals)),
            'mean_db': float(np.nanmean(vals)),
            'median_db': float(np.nanmedian(vals)),
            'std_db': float(np.nanstd(vals)),
            'peak_time': float(times[max_idx]),
            'peak_value': float(vals[max_idx]),
            'min_time': float(times[min_idx]),
            'min_value': float(vals[min_idx]),
            'duration': float(times[-1]) if times.size else 0.0,
            'timestamp': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }

    # ---------- stream ----------
    def _restart_stream(self):
        try:
            self.audio.stop()
            self.audio = AudioStream(self.profile, self.state)
            self.audio.start()
        except Exception as e:
            print("Falha ao iniciar captura:", e)

    # ---------- UI helpers ----------
    def _draw_appbar(self):
        bar_h = 56
        pygame.draw.rect(self.screen, self.SURF, (0, 0, self.size[0], bar_h))
        # Tabs
        tab_w = 140
        pads = 12
        db_rect = pygame.Rect(pads, 8, tab_w, bar_h - 16)
        tn_rect = pygame.Rect(pads + tab_w + 8, 8, tab_w, bar_h - 16)
        pygame.draw.rect(self.screen, self.ACCENT2 if self.active_tab == "db" else self.SURF, db_rect, border_radius=10)
        pygame.draw.rect(self.screen, self.ACCENT2 if self.active_tab == "tuner" else self.SURF, tn_rect, border_radius=10)
        self._blit_center("dB", self.font16, self.TEXT, db_rect)
        self._blit_center("Afinador", self.font16, self.TEXT, tn_rect)

        # Botão SAIR (direita)
        exit_rect = pygame.Rect(self.size[0] - 8 - 100, 8, 100, bar_h - 16)
        pygame.draw.rect(self.screen, (120, 40, 40), exit_rect, border_radius=10)
        self._blit_center("SAIR", self.font16, self.TEXT, exit_rect)
        self._exit_btn_rect = exit_rect

        return db_rect, tn_rect

    def _blit_center(self, text, font, color, rect):
        surf = font.render(text, True, color)
        x = rect.x + (rect.w - surf.get_width()) // 2
        y = rect.y + (rect.h - surf.get_height()) // 2
        self.screen.blit(surf, (x, y))

    def _draw_card(self, y, title, h):
        rect = pygame.Rect(12, y, self.size[0] - 24, h)
        pygame.draw.rect(self.screen, self.SURF, rect, border_radius=16)
        title_surf = self.font14.render(title, True, self.TEXT)
        self.screen.blit(title_surf, (rect.x + 16, rect.y + 10))
        pygame.draw.line(self.screen, (27, 39, 64), (rect.x + 12, rect.y + 34), (rect.right - 12, rect.y + 34), 1)
        return rect

    # ---------- telas ----------
    def _render_db(self, y0):
        # Leitura atual
        card = self._draw_card(y0, "Leitura Atual", 120)
        val = self.state.last_db_value
        txt = f"{val:5.1f} dB" if np.isfinite(val) else "--.- dB"
        self._blit_center(txt, self.font72, self.TEXT, pygame.Rect(card.x, card.y + 40, card.w, 70))

        # Intensidade
        card2 = self._draw_card(card.bottom + 8, "Intensidade", 80)
        self._draw_db_bar(pygame.Rect(card2.x + 16, card2.y + 36, card2.w - 32, 32))

        # Infos
        card3 = self._draw_card(card2.bottom + 8, "Informações", 64)
        peak = self.state.peak_db_value
        t1 = f"Pico: {peak:5.1f} dB (últimos {PEAK_HOLD_SECONDS:.1f} s)" if np.isfinite(peak) else f"Pico: --.- dB (últimos {PEAK_HOLD_SECONDS:.1f} s)"
        off = f"Offset: {self.state.calibration_offset_db:+.1f} dB"
        self.screen.blit(self.font14.render(t1, True, self.SUBTLE), (card3.x + 16, card3.y + 36))
        self.screen.blit(self.font14.render(off, True, self.SUBTLE), (card3.right - 180, card3.y + 36))

        # Área de gravação
        card4 = self._draw_card(card3.bottom + 8, "Decibelímetro (Gravação)", self.size[1] - (card3.bottom + 8) - 12)
        inner = pygame.Rect(card4.x + 16, card4.y + 40, card4.w - 32, card4.h - 52)

        btn_h = 64
        btn_w = 320
        btn_rect = pygame.Rect(inner.x + (inner.w - btn_w)//2, inner.y + (inner.h - btn_h)//2, btn_w, btn_h)
        bg_col = self.RED if self.recording else self.ACCENT
        pygame.draw.rect(self.screen, bg_col, btn_rect, border_radius=12)
        label = "PARAR (máx 60s)" if self.recording else "INICIAR GRAVAÇÃO"
        self._blit_center(label, self.font20, self.TEXT, btn_rect)

        if self.recording:
            elapsed = time.time() - self.record_start_time
            remain = max(0.0, MAX_RECORD_DURATION - elapsed)
            info_txt = f"Tempo: {elapsed:04.1f}s  |  Restante (auto): {remain:04.1f}s"
            info_surf = self.font16.render(info_txt, True, self.SUBTLE)
            self.screen.blit(info_surf, (btn_rect.centerx - info_surf.get_width()//2, btn_rect.bottom + 12))

        self._record_btn_rect = btn_rect

    def _draw_static_graph(self, rect, samples):
        pygame.draw.rect(self.screen, (8, 14, 24), rect, border_radius=8)
        if not samples:
            self.screen.blit(self.font14.render("Nenhuma amostra", True, self.SUBTLE), (rect.x + 8, rect.y + 8))
            return
        times = np.array([t for (t, v) in samples], dtype=np.float64)
        vals = np.array([v for (t, v) in samples], dtype=np.float64)
        if times.size < 2:
            self.screen.blit(self.font14.render("Amostras insuficientes", True, self.SUBTLE), (rect.x + 8, rect.y + 8))
            return

        t0, t1 = float(times[0]), float(times[-1])
        vmin = float(np.nanmin(vals))
        vmax = float(np.nanmax(vals))
        pad_v = max(1.0, (vmax - vmin) * 0.05)
        vmin -= pad_v
        vmax += pad_v
        if vmax - vmin < 1e-3:
            vmax = vmin + 1.0

        def x_from(t):
            return rect.x + int((t - t0) / (t1 - t0) * (rect.w - 1))
        def y_from(v):
            frac = (v - vmin) / (vmax - vmin)
            frac = max(0.0, min(1.0, frac))
            return rect.bottom - int(frac * (rect.h - 1))

        pts = [(x_from(float(t)), y_from(float(v))) for (t, v) in samples]
        if len(pts) >= 2:
            pygame.draw.lines(self.screen, self.ACCENT2, False, pts, 2)

        self.screen.blit(self.font12.render(f"0.0s", True, self.SUBTLE), (rect.x + 2, rect.bottom - 18))
        self.screen.blit(self.font12.render(f"{t1:.1f}s", True, self.SUBTLE), (rect.right - 46, rect.bottom - 18))
        self.screen.blit(self.font12.render(f"{vmax:.1f} dB", True, self.SUBTLE), (rect.x + 2, rect.y + 2))
        self.screen.blit(self.font12.render(f"{vmin:.1f} dB", True, self.SUBTLE), (rect.x + 2, rect.bottom - 18))

    def _draw_db_bar(self, rect):
        pygame.draw.rect(self.screen, (26, 39, 66), rect, border_radius=8)
        v = self.state.last_db_value
        min_db, max_db = 0.0, 100.0
        if np.isfinite(v):
            frac = max(0.0, min(1.0, (v - min_db) / (max_db - min_db)))
            fill = rect.copy()
            fill.w = int(rect.w * frac)
            pygame.draw.rect(self.screen, self.ACCENT, fill, border_radius=8)

        peak = self.state.peak_db_value
        if np.isfinite(peak):
            p = max(0.0, min(1.0, (peak - min_db) / (max_db - min_db)))
            x = rect.x + int(rect.w * p)
            pygame.draw.line(self.screen, self.WARN, (x, rect.y), (x, rect.bottom), 3)

        for d in range(0, 101, 10):
            x = rect.x + int(rect.w * (d / 100.0))
            pygame.draw.line(self.screen, (37, 53, 87), (x, rect.y), (x, rect.bottom), 1)

    def _render_tuner(self, y0):
        # Mostra NOTA grande e frequência embaixo
        card = self._draw_card(y0, "Nota Detectada", 140)
        note = self.state.pitch_note_name or "--"
        self._blit_center(note, self.font96, self.TEXT, pygame.Rect(card.x, card.y + 30, card.w, 74))
        f0 = self.state.pitch_hz
        freq_txt = f"{f0:6.1f} Hz" if np.isfinite(f0) else "--.- Hz"
        self._blit_center(freq_txt, self.font28, self.SUBTLE, pygame.Rect(card.x, card.y + 100, card.w, 32))

        # Medidor analógico
        card2 = self._draw_card(card.bottom + 8, "Afinador (ponteiro analógico)", self.size[1] - (card.bottom + 8) - 12)
        inner = pygame.Rect(card2.x + 16, card2.y + 40, card2.w - 32, card2.h - 52)

        cents_disp = self.smoothed_cents
        gauge_rect = pygame.Rect(inner.x, inner.y, inner.w, inner.h)
        self._draw_analog_gauge(gauge_rect, cents_disp)

    def _draw_analog_gauge(self, rect, cents):
        pygame.draw.rect(self.screen, (15, 22, 36), rect, border_radius=16)
        cx = rect.x + rect.w // 2
        cy = rect.y + rect.h - 10
        radius = min(rect.w // 2 - 20, rect.h - 30)
        radius = max(60, radius)

        # arco -100..+100 mapeado
        start_angle = math.radians(210)
        end_angle   = math.radians(330)
        pygame.draw.arc(self.screen, (36,53,88), (cx - radius, cy - radius, 2*radius, 2*radius), start_angle, end_angle, 4)

        # marcações a cada 20 cents
        for val in range(-100, 101, 20):
            ang = np.interp(val, [-TUNER_RANGE_CENTS, TUNER_RANGE_CENTS], [start_angle, end_angle])
            x1 = cx + int((radius - 10) * math.cos(ang))
            y1 = cy + int((radius - 10) * math.sin(ang))
            x2 = cx + int(radius * math.cos(ang))
            y2 = cy + int(radius * math.sin(ang))
            pygame.draw.line(self.screen, (60,80,120), (x1, y1), (x2, y2), 2)
            tx = cx + int((radius + 14) * math.cos(ang))
            ty = cy + int((radius + 14) * math.sin(ang))
            lbl = self.font12.render(f"{val}", True, self.SUBTLE)
            self.screen.blit(lbl, (tx - lbl.get_width()//2, ty - lbl.get_height()//2))

        # zona OK ±5
        ok_start = np.interp(-5, [-TUNER_RANGE_CENTS, TUNER_RANGE_CENTS], [start_angle, end_angle])
        ok_end   = np.interp( 5, [-TUNER_RANGE_CENTS, TUNER_RANGE_CENTS], [start_angle, end_angle])
        pygame.draw.arc(self.screen, self.ACCENT2, (cx - radius, cy - radius, 2*radius, 2*radius), ok_start, ok_end, 10)

        # ponteiro
        if not np.isfinite(cents):
            cents = 0.0
        cents = max(-TUNER_RANGE_CENTS, min(TUNER_RANGE_CENTS, float(cents)))
        ang = np.interp(cents, [-TUNER_RANGE_CENTS, TUNER_RANGE_CENTS], [start_angle, end_angle])
        x_end = cx + int((radius - 18) * math.cos(ang))
        y_end = cy + int((radius - 18) * math.sin(ang))
        pygame.draw.line(self.screen, self.ACCENT, (cx, cy), (x_end, y_end), 5)
        pygame.draw.circle(self.screen, (220, 220, 220), (cx, cy), 8)

        legenda = self.font14.render("−100            0            +100  (cents)", True, self.SUBTLE)
        self.screen.blit(legenda, (cx - legenda.get_width()//2, cy + 8))

    # ---------- overlay de relatório ----------
    def _render_report_overlay(self):
        overlay = pygame.Surface(self.size, pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 190))
        self.screen.blit(overlay, (0, 0))

        margin = 24
        rect = pygame.Rect(margin, margin + 20, self.size[0] - 2*margin, self.size[1] - 2*margin - 20)
        pygame.draw.rect(self.screen, self.SURF, rect, border_radius=22)

        title = "Relatório da Gravação"
        self.screen.blit(self.font32.render(title, True, self.TEXT), (rect.x + 16, rect.y + 10))

        # Botão FECHAR
        btn_w, btn_h = 160, 40
        close_btn = pygame.Rect(rect.right - btn_w - 16, rect.y + 10, btn_w, btn_h)
        pygame.draw.rect(self.screen, self.SURF, close_btn, border_radius=10)
        pygame.draw.rect(self.screen, (40, 55, 80), close_btn, width=1, border_radius=10)
        self._blit_center("FECHAR", self.font16, self.TEXT, close_btn)
        self._report_close_rect = close_btn

        inner = pygame.Rect(rect.x + 16, rect.y + 64, rect.w - 32, rect.h - 80)
        left_w = int(inner.w * 0.36)
        left_rect = pygame.Rect(inner.x, inner.y, left_w, inner.h)
        right_rect = pygame.Rect(inner.x + left_w + 12, inner.y, inner.w - left_w - 12, inner.h)

        rpt = self.record_report or {}
        def puttxt(txt, yy, font=self.font16):
            self.screen.blit(font.render(txt, True, self.TEXT), (left_rect.x + 4, yy))

        yy = left_rect.y
        puttxt(f"Início: {rpt.get('timestamp', '--')}", yy); yy += 28
        puttxt(f"Duração: {rpt.get('duration', 0.0):.1f}s", yy); yy += 28
        puttxt(f"Pico: {rpt.get('max_db', 0.0):.1f} dB @ {rpt.get('peak_time', 0.0):.1f}s", yy); yy += 26
        puttxt(f"Mínimo: {rpt.get('min_db', 0.0):.1f} dB @ {rpt.get('min_time', 0.0):.1f}s", yy); yy += 26
        puttxt(f"Média: {rpt.get('mean_db', 0.0):.1f} dB", yy); yy += 26
        puttxt(f"Mediana: {rpt.get('median_db', 0.0):.1f} dB", yy); yy += 26
        puttxt(f"Desvio padrão: {rpt.get('std_db', 0.0):.2f} dB", yy); yy += 26

        self._draw_static_graph(right_rect, rpt.get('samples', []))

    # ---------- main loop ----------
    def run(self):
        clock = pygame.time.Clock()
        while self.running:
            for event in pygame.event.get():
                if event.type in (pygame.QUIT,):
                    self.running = False
                elif event.type == pygame.MOUSEBUTTONUP:
                    self._handle_touch(event.pos)

            self.screen.fill(self.BG)

            if self.report_overlay:
                self._draw_appbar()
                self._render_report_overlay()
            else:
                db_rect, tn_rect = self._draw_appbar()
                body_y = 56 + 8
                if self.active_tab == "db":
                    self._render_db(body_y)
                else:
                    self._render_tuner(body_y)

            pygame.display.flip()
            clock.tick(50)

        self.audio.stop()
        pygame.quit()

    def _handle_touch(self, pos):
        # overlay ativo
        if self.report_overlay:
            if hasattr(self, '_report_close_rect') and self._report_close_rect.collidepoint(pos):
                self.report_overlay = False
                return
            return

        # barra superior
        db_rect, tn_rect = self._draw_appbar()
        if db_rect.collidepoint(pos):
            self.active_tab = "db"; return
        if tn_rect.collidepoint(pos):
            self.active_tab = "tuner"; return
        if hasattr(self, '_exit_btn_rect') and self._exit_btn_rect.collidepoint(pos):
            self.running = False
            return

        # botão de gravação
        if hasattr(self, '_record_btn_rect') and self._record_btn_rect.collidepoint(pos):
            if not self.recording:
                self._start_recording()
            else:
                self._stop_and_finalize_recording()
            return

if __name__ == "__main__":
    try:
        app = App()
        app.run()
    except KeyboardInterrupt:
        pass
