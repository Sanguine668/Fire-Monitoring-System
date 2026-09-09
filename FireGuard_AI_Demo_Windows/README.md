# FireGuard AI - Fire/Smoke Alert System Demo

A runnable demonstration system with a real FastAPI backend, WebSocket event channel, SQLite alarm history, and a browser monitoring dashboard. The AI detection output is simulated so the complete product workflow can be demonstrated before connecting a real YOLO model and RTSP camera.

## Windows quick start

1. Install Python 3.10 or newer. During installation, enable **Add Python to PATH**.
2. Double-click `start_demo.bat`.
3. On the first run, the script installs required Python packages automatically.
4. The browser should open `http://127.0.0.1:8000` automatically.

If Windows blocks the BAT file, open Command Prompt in this folder and run:

```bat
start_demo.bat
```

## Demo workflow

1. Open the Real-time Monitor page.
2. Click the Smoke test button to simulate a smoke detection warning.
3. Click the Fire test button to simulate a critical fire alarm.
4. Open Alarm Center to see persisted alarm records.
5. Acknowledge an alarm and review dashboard statistics.
6. Change thresholds and alarm settings in System Settings.

## Implemented

- Dashboard and monitoring UI
- Four simulated camera sources
- AI detection boxes, FPS, latency, and risk score
- Smoke warning and fire critical alarm simulation
- FastAPI REST API
- WebSocket real-time events
- SQLite alarm persistence
- Alarm acknowledgement
- Detection settings
- Real detector integration entry point: `backend/detector_adapter.py`

## Later: connect real YOLO + RTSP

Replace the demo detector with a real pipeline:

`MP4/Camera -> RTSP -> OpenCV/FFmpeg -> YOLO -> DetectorAdapter -> Alarm Engine -> FastAPI/WebSocket -> Frontend`

The frontend and business API do not need to be rewritten when the detector is replaced.
