import time
import threading
import numpy as np
import sounddevice as sd
from dataclasses import dataclass, field
from collections import deque


@dataclass
class AudioState:
    """Shared audio state accessible from all modules."""
    last_db_value: float = -np.inf
    peak_db_value: float = -np.inf
    peak_db_time: float = 0.0
    
    pitch_hz: float = np.nan
    pitch_cents: float = np.nan
    pitch_note_name: str = None
    
    calibration_offset_db: float = 60.0
    
    def reset_peak(self):
        """Reset peak hold values."""
        self.peak_db_value = -np.inf
        self.peak_db_time = 0.0


@dataclass
class AudioStream:
    """Manages audio input stream with buffering."""
    sample_rate: int
    block_size: int
    
    _stream: sd.InputStream = field(default=None, init=False, repr=False)
    _buffer: deque = field(default_factory=deque, init=False, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)
    _running: bool = field(default=False, init=False, repr=False)
    
    def start(self):
        """Start the audio input stream."""
        if self._running:
            return
        
        def callback(indata, frames, time_info, status):
            if status:
                print(f"[Audio] Status: {status}")
            
            # Convert to mono if stereo
            if indata.ndim > 1:
                mono = np.mean(indata, axis=1)
            else:
                mono = indata[:, 0] if indata.ndim == 2 else indata
            
            with self._lock:
                self._buffer.append(mono.copy())
        
        try:
            self._stream = sd.InputStream(
                samplerate=self.sample_rate,
                blocksize=self.block_size,
                channels=1,
                callback=callback,
                dtype=np.float32
            )
            self._stream.start()
            self._running = True
            print(f"[Audio] Stream started: {self.sample_rate} Hz, block size {self.block_size}")
        except Exception as e:
            print(f"[Audio] Failed to start stream: {e}")
            raise
    
    def stop(self):
        """Stop the audio input stream."""
        if not self._running:
            return
        
        self._running = False
        if self._stream:
            self._stream.stop()
            self._stream.close()
            self._stream = None
        
        with self._lock:
            self._buffer.clear()
        
        print("[Audio] Stream stopped")
    
    def read_block(self) -> np.ndarray:
        """Read the oldest audio block from the buffer."""
        with self._lock:
            if self._buffer:
                return self._buffer.popleft()
        return np.array([], dtype=np.float32)
    
    def read_window(self, num_samples: int) -> np.ndarray:
        """Read multiple blocks to form a window of the requested size."""
        chunks = []
        total = 0
        
        with self._lock:
            while self._buffer and total < num_samples:
                chunk = self._buffer.popleft()
                chunks.append(chunk)
                total += len(chunk)
        
        if not chunks:
            return np.array([], dtype=np.float32)
        
        combined = np.concatenate(chunks)
        return combined[-num_samples:] if len(combined) > num_samples else combined
    
    @property
    def is_running(self) -> bool:
        """Check if the stream is running."""
        return self._running
