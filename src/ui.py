import math
import time
import numpy as np
import pygame
from datetime import datetime
from config import (
    PEAK_HOLD_SECONDS, MAX_RECORD_DURATION, TUNER_RANGE_CENTS,
    COLOR_BG, COLOR_SURF, COLOR_ACCENT, COLOR_ACCENT2, COLOR_TEXT,
    COLOR_SUBTLE, COLOR_WARN, COLOR_RED
)


class UIRenderer:
    
    def __init__(self, screen, size):
        self.screen = screen
        self.size = size
        
        self.BG = COLOR_BG
        self.SURF = COLOR_SURF
        self.ACCENT = COLOR_ACCENT
        self.ACCENT2 = COLOR_ACCENT2
        self.TEXT = COLOR_TEXT
        self.SUBTLE = COLOR_SUBTLE
        self.WARN = COLOR_WARN
        self.RED = COLOR_RED
        
        self.font12 = pygame.font.SysFont(None, 12)
        self.font14 = pygame.font.SysFont(None, 14)
        self.font16 = pygame.font.SysFont(None, 16, bold=True)
        self.font20 = pygame.font.SysFont(None, 20, bold=True)
        self.font28 = pygame.font.SysFont(None, 28, bold=True)
        self.font32 = pygame.font.SysFont(None, 32, bold=True)
        self.font48 = pygame.font.SysFont(None, 48, bold=True)
        self.font72 = pygame.font.SysFont(None, 72, bold=True)
        self.font96 = pygame.font.SysFont(None, 96, bold=True)
        
        self._exit_btn_rect = None
        self._record_btn_rect = None
        self._report_close_rect = None

    def blit_center(self, text, font, color, rect):
        surf = font.render(text, True, color)
        x = rect.x + (rect.w - surf.get_width()) // 2
        y = rect.y + (rect.h - surf.get_height()) // 2
        self.screen.blit(surf, (x, y))

    def draw_card(self, y, title, h):
        rect = pygame.Rect(12, y, self.size[0] - 24, h)
        pygame.draw.rect(self.screen, self.SURF, rect, border_radius=16)
        title_surf = self.font14.render(title, True, self.TEXT)
        self.screen.blit(title_surf, (rect.x + 16, rect.y + 10))
        pygame.draw.line(self.screen, (27, 39, 64), 
                        (rect.x + 12, rect.y + 34), 
                        (rect.right - 12, rect.y + 34), 1)
        return rect

    def draw_appbar(self, active_tab):
        bar_h = 56
        pygame.draw.rect(self.screen, self.SURF, (0, 0, self.size[0], bar_h))
        
        tab_w = 140
        pads = 12
        db_rect = pygame.Rect(pads, 8, tab_w, bar_h - 16)
        tn_rect = pygame.Rect(pads + tab_w + 8, 8, tab_w, bar_h - 16)
        
        pygame.draw.rect(self.screen, 
                        self.ACCENT2 if active_tab == "db" else self.SURF, 
                        db_rect, border_radius=10)
        pygame.draw.rect(self.screen, 
                        self.ACCENT2 if active_tab == "tuner" else self.SURF, 
                        tn_rect, border_radius=10)
        
        self.blit_center("dB", self.font16, self.TEXT, db_rect)
        self.blit_center("Afinador", self.font16, self.TEXT, tn_rect)

        exit_rect = pygame.Rect(self.size[0] - 8 - 100, 8, 100, bar_h - 16)
        pygame.draw.rect(self.screen, (120, 40, 40), exit_rect, border_radius=10)
        self.blit_center("SAIR", self.font16, self.TEXT, exit_rect)
        self._exit_btn_rect = exit_rect

        return db_rect, tn_rect

    def draw_db_bar(self, rect, last_db_value, peak_db_value):
        pygame.draw.rect(self.screen, (26, 39, 66), rect, border_radius=8)
        
        min_db, max_db = 0.0, 100.0
        
        if np.isfinite(last_db_value):
            frac = max(0.0, min(1.0, (last_db_value - min_db) / (max_db - min_db)))
            fill = rect.copy()
            fill.w = int(rect.w * frac)
            pygame.draw.rect(self.screen, self.ACCENT, fill, border_radius=8)

        if np.isfinite(peak_db_value):
            p = max(0.0, min(1.0, (peak_db_value - min_db) / (max_db - min_db)))
            x = rect.x + int(rect.w * p)
            pygame.draw.line(self.screen, self.WARN, (x, rect.y), (x, rect.bottom), 3)

        for d in range(0, 101, 10):
            x = rect.x + int(rect.w * (d / 100.0))
            pygame.draw.line(self.screen, (37, 53, 87), (x, rect.y), (x, rect.bottom), 1)

    def draw_static_graph(self, rect, samples):
        pygame.draw.rect(self.screen, (8, 14, 24), rect, border_radius=8)
        
        if not samples:
            self.screen.blit(self.font14.render("Nenhuma amostra", True, self.SUBTLE), 
                           (rect.x + 8, rect.y + 8))
            return
        
        times = np.array([t for (t, v) in samples], dtype=np.float64)
        vals = np.array([v for (t, v) in samples], dtype=np.float64)
        
        if times.size < 2:
            self.screen.blit(self.font14.render("Amostras insuficientes", True, self.SUBTLE), 
                           (rect.x + 8, rect.y + 8))
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

        self.screen.blit(self.font12.render(f"0.0s", True, self.SUBTLE), 
                        (rect.x + 2, rect.bottom - 18))
        self.screen.blit(self.font12.render(f"{t1:.1f}s", True, self.SUBTLE), 
                        (rect.right - 46, rect.bottom - 18))
        self.screen.blit(self.font12.render(f"{vmax:.1f} dB", True, self.SUBTLE), 
                        (rect.x + 2, rect.y + 2))
        self.screen.blit(self.font12.render(f"{vmin:.1f} dB", True, self.SUBTLE), 
                        (rect.x + 2, rect.bottom - 18))

    def draw_analog_gauge(self, rect, cents):
        pygame.draw.rect(self.screen, (15, 22, 36), rect, border_radius=16)
        
        cx = rect.x + rect.w // 2
        cy = rect.y + rect.h - 10
        radius = min(rect.w // 2 - 20, rect.h - 30)
        radius = max(60, radius)

        start_angle = math.radians(210)
        end_angle = math.radians(330)
        pygame.draw.arc(self.screen, (36, 53, 88), 
                       (cx - radius, cy - radius, 2*radius, 2*radius), 
                       start_angle, end_angle, 4)

        for val in range(-100, 101, 20):
            ang = np.interp(val, [-TUNER_RANGE_CENTS, TUNER_RANGE_CENTS], 
                          [start_angle, end_angle])
            x1 = cx + int((radius - 10) * math.cos(ang))
            y1 = cy + int((radius - 10) * math.sin(ang))
            x2 = cx + int(radius * math.cos(ang))
            y2 = cy + int(radius * math.sin(ang))
            pygame.draw.line(self.screen, (60, 80, 120), (x1, y1), (x2, y2), 2)
            
            tx = cx + int((radius + 14) * math.cos(ang))
            ty = cy + int((radius + 14) * math.sin(ang))
            lbl = self.font12.render(f"{val}", True, self.SUBTLE)
            self.screen.blit(lbl, (tx - lbl.get_width()//2, ty - lbl.get_height()//2))

        ok_start = np.interp(-5, [-TUNER_RANGE_CENTS, TUNER_RANGE_CENTS], 
                            [start_angle, end_angle])
        ok_end = np.interp(5, [-TUNER_RANGE_CENTS, TUNER_RANGE_CENTS], 
                          [start_angle, end_angle])
        pygame.draw.arc(self.screen, self.ACCENT2, 
                       (cx - radius, cy - radius, 2*radius, 2*radius), 
                       ok_start, ok_end, 10)

        if not np.isfinite(cents):
            cents = 0.0
        cents = max(-TUNER_RANGE_CENTS, min(TUNER_RANGE_CENTS, float(cents)))
        ang = np.interp(cents, [-TUNER_RANGE_CENTS, TUNER_RANGE_CENTS], 
                       [start_angle, end_angle])
        x_end = cx + int((radius - 18) * math.cos(ang))
        y_end = cy + int((radius - 18) * math.sin(ang))
        pygame.draw.line(self.screen, self.ACCENT, (cx, cy), (x_end, y_end), 5)
        pygame.draw.circle(self.screen, (220, 220, 220), (cx, cy), 8)

        legenda = self.font14.render("−100            0            +100  (cents)", 
                                     True, self.SUBTLE)
        self.screen.blit(legenda, (cx - legenda.get_width()//2, cy + 8))

    def render_db_view(self, y0, state, recording, record_start_time):
        card = self.draw_card(y0, "Leitura Atual", 120)
        val = state.last_db_value
        txt = f"{val:5.1f} dB" if np.isfinite(val) else "--.- dB"
        self.blit_center(txt, self.font72, self.TEXT, 
                        pygame.Rect(card.x, card.y + 40, card.w, 70))

        card2 = self.draw_card(card.bottom + 8, "Intensidade", 80)
        self.draw_db_bar(pygame.Rect(card2.x + 16, card2.y + 36, card2.w - 32, 32),
                        state.last_db_value, state.peak_db_value)

        card3 = self.draw_card(card2.bottom + 8, "Informações", 64)
        peak = state.peak_db_value
        t1 = f"Pico: {peak:5.1f} dB (últimos {PEAK_HOLD_SECONDS:.1f} s)" if np.isfinite(peak) else f"Pico: --.- dB (últimos {PEAK_HOLD_SECONDS:.1f} s)"
        off = f"Offset: {state.calibration_offset_db:+.1f} dB"
        self.screen.blit(self.font14.render(t1, True, self.SUBTLE), 
                        (card3.x + 16, card3.y + 36))
        self.screen.blit(self.font14.render(off, True, self.SUBTLE), 
                        (card3.right - 180, card3.y + 36))

        card4 = self.draw_card(card3.bottom + 8, "Decibelímetro (Gravação)", 
                              self.size[1] - (card3.bottom + 8) - 12)
        inner = pygame.Rect(card4.x + 16, card4.y + 40, card4.w - 32, card4.h - 52)

        btn_h = 64
        btn_w = 320
        btn_rect = pygame.Rect(inner.x + (inner.w - btn_w)//2, 
                              inner.y + (inner.h - btn_h)//2, btn_w, btn_h)
        bg_col = self.RED if recording else self.ACCENT
        pygame.draw.rect(self.screen, bg_col, btn_rect, border_radius=12)
        label = "PARAR (máx 60s)" if recording else "INICIAR GRAVAÇÃO"
        self.blit_center(label, self.font20, self.TEXT, btn_rect)

        if recording:
            elapsed = time.time() - record_start_time
            remain = max(0.0, MAX_RECORD_DURATION - elapsed)
            info_txt = f"Tempo: {elapsed:04.1f}s  |  Restante (auto): {remain:04.1f}s"
            info_surf = self.font16.render(info_txt, True, self.SUBTLE)
            self.screen.blit(info_surf, 
                           (btn_rect.centerx - info_surf.get_width()//2, 
                            btn_rect.bottom + 12))

        self._record_btn_rect = btn_rect
        return btn_rect

    def render_tuner_view(self, y0, state, smoothed_cents):
        card = self.draw_card(y0, "Nota Detectada", 140)
        note = state.pitch_note_name or "--"
        self.blit_center(note, self.font96, self.TEXT, 
                        pygame.Rect(card.x, card.y + 30, card.w, 74))
        f0 = state.pitch_hz
        freq_txt = f"{f0:6.1f} Hz" if np.isfinite(f0) else "--.- Hz"
        self.blit_center(freq_txt, self.font28, self.SUBTLE, 
                        pygame.Rect(card.x, card.y + 100, card.w, 32))

        card2 = self.draw_card(card.bottom + 8, "Afinador (ponteiro analógico)", 
                              self.size[1] - (card.bottom + 8) - 12)
        inner = pygame.Rect(card2.x + 16, card2.y + 40, card2.w - 32, card2.h - 52)
        
        self.draw_analog_gauge(inner, smoothed_cents)

    def render_report_overlay(self, record_report):
        overlay = pygame.Surface(self.size, pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 190))
        self.screen.blit(overlay, (0, 0))

        margin = 24
        rect = pygame.Rect(margin, margin + 20, 
                          self.size[0] - 2*margin, 
                          self.size[1] - 2*margin - 20)
        pygame.draw.rect(self.screen, self.SURF, rect, border_radius=22)

        title = "Relatório da Gravação"
        self.screen.blit(self.font32.render(title, True, self.TEXT), 
                        (rect.x + 16, rect.y + 10))

        btn_w, btn_h = 160, 40
        close_btn = pygame.Rect(rect.right - btn_w - 16, rect.y + 10, btn_w, btn_h)
        pygame.draw.rect(self.screen, self.SURF, close_btn, border_radius=10)
        pygame.draw.rect(self.screen, (40, 55, 80), close_btn, width=1, border_radius=10)
        self.blit_center("FECHAR", self.font16, self.TEXT, close_btn)
        self._report_close_rect = close_btn

        inner = pygame.Rect(rect.x + 16, rect.y + 64, rect.w - 32, rect.h - 80)
        left_w = int(inner.w * 0.36)
        left_rect = pygame.Rect(inner.x, inner.y, left_w, inner.h)
        right_rect = pygame.Rect(inner.x + left_w + 12, inner.y, 
                                inner.w - left_w - 12, inner.h)

        rpt = record_report or {}
        yy = left_rect.y
        
        def puttxt(txt, y):
            self.screen.blit(self.font16.render(txt, True, self.TEXT), 
                           (left_rect.x + 4, y))
            return y + 28

        yy = puttxt(f"Início: {rpt.get('timestamp', '--')}", yy)
        yy = puttxt(f"Duração: {rpt.get('duration', 0.0):.1f}s", yy)
        yy = puttxt(f"Pico: {rpt.get('max_db', 0.0):.1f} dB @ {rpt.get('peak_time', 0.0):.1f}s", yy) - 2
        yy = puttxt(f"Mínimo: {rpt.get('min_db', 0.0):.1f} dB @ {rpt.get('min_time', 0.0):.1f}s", yy) - 2
        yy = puttxt(f"Média: {rpt.get('mean_db', 0.0):.1f} dB", yy) - 2
        yy = puttxt(f"Mediana: {rpt.get('median_db', 0.0):.1f} dB", yy) - 2
        yy = puttxt(f"Desvio padrão: {rpt.get('std_db', 0.0):.2f} dB", yy)

        self.draw_static_graph(right_rect, rpt.get('samples', []))
        
        return close_btn

    @property
    def exit_btn_rect(self):
        return self._exit_btn_rect

    @property
    def record_btn_rect(self):
        return self._record_btn_rect

    @property
    def report_close_rect(self):
        return self._report_close_rect

