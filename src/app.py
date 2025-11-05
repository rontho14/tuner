import time
import threading
import numpy as np
import pygame
from datetime import datetime
from collections import deque

from config import IS_PI, PROFILE_ECO, PROFILE_FULL, PEAK_HOLD_SECONDS, MAX_RECORD_DURATION, TUNER_UPDATE_MS, TUNER_EMA_ALPHA
from audio import AudioState, AudioStream
from dsp import rms_dbfs, estimate_pitch_autocorr, nearest_guitar_string
from ui import UIRenderer
from ubidots import ubidots_worker, UBIDOTS_TOKEN


class App:
    
    def __init__(self):
        self.profile = PROFILE_ECO if IS_PI else PROFILE_FULL
        print(f"[App] Using profile: {'ECO (Raspberry Pi)' if IS_PI else 'FULL (Desktop)'}")
        print(f"[App] Sample rate: {self.profile.sample_rate} Hz, Block size: {self.profile.block_size}")
        
        pygame.init()
        self.size = (800, 480) if IS_PI else (900, 700)
        self.screen = pygame.display.set_mode(self.size)
        pygame.display.set_caption("Decibelímetro & Afinador")
        

        self.state = AudioState()
        self.audio_stream = AudioStream(
            sample_rate=self.profile.sample_rate,
            block_size=self.profile.block_size
        )
        self.renderer = UIRenderer(self.screen, self.size)

        self.active_tab = "db"  
        self.clock = pygame.time.Clock()
        self.running = False
        
        self.peak_hold_buffer = deque(maxlen=100)
        
        self.last_tuner_update = 0
        self.smoothed_cents = 0.0
        
        self.recording = False
        self.record_start_time = 0.0
        self.record_samples = []
        self.record_report = None
        self.show_report = False
        
        self.ubidots_thread = None
        if UBIDOTS_TOKEN:
            print("[App] Ubidots token found, IoT enabled")
        else:
            print("[App] No Ubidots token, IoT disabled")
    
    def start(self):
        self.running = True
        self.audio_stream.start()
        
        if UBIDOTS_TOKEN:
            self.ubidots_thread = threading.Thread(target=ubidots_worker, args=(self,), daemon=True)
            self.ubidots_thread.start()
            print("[App] Ubidots worker started")
    
    def stop(self):
        self.running = False
        self.audio_stream.stop()
        pygame.quit()
        print("[App] Application stopped")
    
    def process_audio_db(self):
        block = self.audio_stream.read_block()
        if block.size == 0:
            return
        
        db_raw = rms_dbfs(block)
        db_calibrated = db_raw + self.state.calibration_offset_db
        self.state.last_db_value = db_calibrated
        

        current_time = time.time()
        self.peak_hold_buffer.append((current_time, db_calibrated))
        

        while self.peak_hold_buffer and current_time - self.peak_hold_buffer[0][0] > PEAK_HOLD_SECONDS:
            self.peak_hold_buffer.popleft()

        if self.peak_hold_buffer:
            valid_values = [v for t, v in self.peak_hold_buffer if np.isfinite(v)]
            if valid_values:
                peak = max(valid_values)
                if peak > self.state.peak_db_value or not np.isfinite(self.state.peak_db_value):
                    self.state.peak_db_value = peak
                    self.state.peak_db_time = current_time
        

        if self.recording:
            elapsed = current_time - self.record_start_time
            if np.isfinite(db_calibrated):
                self.record_samples.append((elapsed, db_calibrated))
            

            if elapsed >= MAX_RECORD_DURATION:
                self.stop_recording()
    
    def process_audio_tuner(self):
        current_time = pygame.time.get_ticks()
        

        if current_time - self.last_tuner_update < TUNER_UPDATE_MS:
            return
        
        self.last_tuner_update = current_time
        

        window = self.audio_stream.read_window(self.profile.pitch_win)
        if window.size < self.profile.pitch_win // 2:
            return
        

        f0 = estimate_pitch_autocorr(window, self.profile.sample_rate)
        self.state.pitch_hz = f0

        if np.isfinite(f0):
            result = nearest_guitar_string(f0)
            if result:
                note_name, f_ref, cents = result
                self.state.pitch_note_name = note_name
                self.state.pitch_cents = cents
                
                self.smoothed_cents += TUNER_EMA_ALPHA * (cents - self.smoothed_cents)
            else:
                self.state.pitch_note_name = None
                self.state.pitch_cents = np.nan
        else:
            self.state.pitch_note_name = None
            self.state.pitch_cents = np.nan
    
    def start_recording(self):
        self.recording = True
        self.record_start_time = time.time()
        self.record_samples = []
        print("[App] Recording started")
    
    def stop_recording(self):
        self.recording = False
        print(f"[App] Recording stopped, {len(self.record_samples)} samples")
        
        if self.record_samples:
            self.record_report = self.generate_report()
            self.show_report = True
        else:
            self.record_report = None
    
    def generate_report(self) -> dict:
        if not self.record_samples:
            return {}
        
        times = np.array([t for t, v in self.record_samples])
        values = np.array([v for t, v in self.record_samples])
        
        duration = times[-1] if len(times) > 0 else 0.0
        
        max_idx = np.argmax(values)
        min_idx = np.argmin(values)
        
        report = {
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "duration": duration,
            "samples": self.record_samples.copy(),
            "max_db": float(values[max_idx]),
            "peak_time": float(times[max_idx]),
            "min_db": float(values[min_idx]),
            "min_time": float(times[min_idx]),
            "mean_db": float(np.mean(values)),
            "median_db": float(np.median(values)),
            "std_db": float(np.std(values))
        }
        
        return report
    
    def handle_events(self):
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                self.running = False
            
            elif event.type == pygame.MOUSEBUTTONDOWN:
                mx, my = event.pos
                
                if self.renderer.exit_btn_rect and self.renderer.exit_btn_rect.collidepoint(mx, my):
                    self.running = False
                
                if not self.show_report:
                    db_rect, tn_rect = self.renderer.draw_appbar(self.active_tab)
                    
                    if db_rect.collidepoint(mx, my):
                        self.active_tab = "db"
                    elif tn_rect.collidepoint(mx, my):
                        self.active_tab = "tuner"
                
                if self.active_tab == "db" and not self.show_report:
                    if self.renderer.record_btn_rect and self.renderer.record_btn_rect.collidepoint(mx, my):
                        if self.recording:
                            self.stop_recording()
                        else:
                            self.start_recording()
                
                if self.show_report:
                    if self.renderer.report_close_rect and self.renderer.report_close_rect.collidepoint(mx, my):
                        self.show_report = False
    
    def render(self):
        self.screen.fill((11, 18, 32))
        
        self.renderer.draw_appbar(self.active_tab)
        
        y_offset = 64
        
        if self.active_tab == "db":
            self.renderer.render_db_view(y_offset, self.state, self.recording, self.record_start_time)
        else:
            self.renderer.render_tuner_view(y_offset, self.state, self.smoothed_cents)
        
        if self.show_report and self.record_report:
            self.renderer.render_report_overlay(self.record_report)
        
        pygame.display.flip()
    
    def run(self):
        self.start()
        
        print("[App] Entering main loop")
        
        while self.running:
            if self.active_tab == "db":
                self.process_audio_db()
            else:
                self.process_audio_tuner()
            
            self.handle_events()
            
            self.render()
            
            self.clock.tick(1000 // self.profile.ui_ms)
        
        self.stop()
