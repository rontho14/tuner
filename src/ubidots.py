import os
import time
import requests
import numpy as np

#export UBIDOTS_TOKEN="BBUS-5y9cUes4WxsHDm3hJPyjkvIISaYUPq"
UBIDOTS_TOKEN = os.getenv("UBIDOTS_TOKEN")
DEVICE_LABEL = "raspi_vapireca_001"
API_URL = f"https://industrial.api.ubidots.com/api/v1.6/devices/{DEVICE_LABEL}"

HEADERS = {
    "Content-Type": "application/json",
    "X-Auth-Token": UBIDOTS_TOKEN
}


def post_to_ubidots(payload: dict) -> bool:
    if not UBIDOTS_TOKEN:
        return False
    
    try:
        resp = requests.post(API_URL, headers=HEADERS, json=payload, timeout=6)
        resp.raise_for_status()
        return True
    except Exception as e:
        print("[Ubidots] Error sending data:", e)
        return False


def ubidots_worker(app_instance):
    interval = 0.1
    
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
            print("[Ubidots] Worker error:", e)
        
        time.sleep(interval)

