import os
import uvicorn
import json
import time
import asyncio
import websockets
import threading
from contextlib import asynccontextmanager
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from model_loader import ModelLoader
from gesture_buffer import GestureBuffer
from prediction_engine import PredictionEngine
from websocket_handler import WebSocketManager

@asynccontextmanager
async def lifespan(app: FastAPI):
    global main_loop
    main_loop = asyncio.get_running_loop()
    asyncio.create_task(android_sensor_bridge())
    # Start the Serial bridge in a dedicated thread
    threading.Thread(target=serial_thread_worker, daemon=True).start()
    yield

app = FastAPI(title="ESP32 Realtime Gesture Recognition System", version="1.0", lifespan=lifespan)
main_loop = None

# Enable CORS for Next.js frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 1. Initialize Components
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODELS_DIR = os.path.join(PROJECT_ROOT, "Models")
RESULTS_DIR = os.path.join(PROJECT_ROOT, "Results")

model_loader = ModelLoader(MODELS_DIR)
# Attempt to load model files
model_load_status = model_loader.load_all_models()

gesture_buffer = GestureBuffer(window_size=50)
prediction_engine = PredictionEngine(model_loader, RESULTS_DIR)
ws_manager = WebSocketManager(gesture_buffer, prediction_engine)

@app.get("/")
async def root():
    """
    Health check and system status endpoint.
    """
    return {
        "status": "online",
        "models_loaded": model_load_status,
        "active_frontend_clients": len(ws_manager.frontend_connections),
        "active_sensor_streams": len(ws_manager.sensor_connections),
        "is_recording": ws_manager.is_recording,
        "recorded_frames": ws_manager.recorded_frames
    }

@app.websocket("/ws/sensor")
async def websocket_sensor_endpoint(websocket: WebSocket):
    """
    WebSocket endpoint for ESP32 sensor streams.
    """
    await ws_manager.connect_sensor(websocket)
    try:
        while True:
            # Receive raw accelerometer frames
            data = await websocket.receive_text()
            await ws_manager.handle_sensor_stream(data)
    except WebSocketDisconnect:
        await ws_manager.disconnect_sensor(websocket)
    except Exception as e:
        print(f"Error in sensor WebSocket loop: {e}")
        await ws_manager.disconnect_sensor(websocket)

@app.websocket("/ws/client")
async def websocket_client_endpoint(websocket: WebSocket):
    """
    WebSocket endpoint for frontend React clients.
    """
    await ws_manager.connect_frontend(websocket)
    try:
        # Notify the client of model loading status
        if model_load_status:
            await websocket.send_json({
                "event": "status",
                "message": "Model loaded successfully."
            })
        else:
            await websocket.send_json({
                "event": "status",
                "message": "Corrupted or missing model files. Running in mock simulation mode."
            })
            
        while True:
            # Receive commands from frontend (Start/Stop/Reset)
            command = await websocket.receive_text()
            await ws_manager.process_client_command(command)
    except WebSocketDisconnect:
        ws_manager.disconnect_frontend(websocket)
    except Exception as e:
        print(f"Error in frontend client WebSocket loop: {e}")
        ws_manager.disconnect_frontend(websocket)

# Background task to connect to the Android sensor stream
async def android_sensor_bridge():
    url = "ws://192.168.0.112:8080/sensor/connect?type=android.sensor.accelerometer"
    print(f"[Android Bridge] Starting bridge connection loop to: {url}")
    while True:
        try:
            async with websockets.connect(url, ping_interval=None) as ws:
                print("[Android Bridge] Connected successfully to Android sensor stream!")
                ws_manager.is_android_connected = True
                await ws_manager.broadcast_to_frontend({
                    "event": "status",
                    "message": "Connection established with Android sensor."
                })
                await ws_manager.update_sensor_connected_status()
                
                while True:
                    message = await ws.recv()
                    try:
                        payload = json.loads(message)
                        values = payload.get("values", [])
                        if len(values) >= 3:
                            ax, ay, az = values[0], values[1], values[2]
                            timestamp = payload.get("timestamp", int(time.time() * 1000))
                            
                            # Forward to standard sensor stream handler
                            sensor_packet = {
                                "ax": float(ax),
                                "ay": float(ay),
                                "az": float(az),
                                "gx": 0.0,
                                "gy": 0.0,
                                "gz": 0.0,
                                "timestamp": int(timestamp)
                            }
                            await ws_manager.handle_sensor_stream(json.dumps(sensor_packet))
                    except Exception as e:
                        pass
        except Exception as e:
            ws_manager.is_android_connected = False
            await ws_manager.update_sensor_connected_status()
            await asyncio.sleep(3)

# Background task to connect to physical ESP32 via Serial USB connection
def serial_thread_worker():
    import serial
    import serial.tools.list_ports
    print("[Serial Bridge] Starting serial thread worker...")
    ser = None
    while True:
        try:
            if ser is None or not ser.is_open:
                # Find available ports
                ports = list(serial.tools.list_ports.comports())
                target_port = None
                for p in ports:
                    desc = p.description.lower()
                    hwid = p.hwid.lower()
                    # Check for typical ESP32/USB-Serial device descriptions or IDs
                    if any(term in desc or term in hwid for term in ["cp210", "ch340", "usb", "uart", "serial"]):
                        target_port = p.device
                        break
                
                # Fallback to the first available COM port if no matches but some exist
                if not target_port and ports:
                    target_port = ports[0].device
                
                if target_port:
                    print(f"[Serial Bridge] Attempting to connect to {target_port} at 115200 baud...")
                    ser = serial.Serial(target_port, 115200, timeout=1)
                    print(f"[Serial Bridge] Connected to {target_port} successfully!")
                    
                    ws_manager.is_serial_connected = True
                    if main_loop:
                        asyncio.run_coroutine_threadsafe(
                            ws_manager.broadcast_to_frontend({
                                "event": "status",
                                "message": f"Connected to ESP32 via Serial ({target_port})."
                            }),
                            main_loop
                        )
                        asyncio.run_coroutine_threadsafe(
                            ws_manager.update_sensor_connected_status(),
                            main_loop
                        )
                else:
                    time.sleep(2)
                    continue

            # Read a line from serial (blocking read on dedicated thread)
            line = ser.readline()
            if line:
                line_str = line.decode('utf-8', errors='ignore').strip()
                if line_str.startswith('{') and line_str.endswith('}'):
                    try:
                        payload = json.loads(line_str)
                        if "ax" in payload and "ay" in payload and "az" in payload:
                            if main_loop:
                                asyncio.run_coroutine_threadsafe(
                                    ws_manager.handle_sensor_stream(line_str),
                                    main_loop
                                )
                    except Exception as e:
                        print(f"[Serial Bridge] Failed to parse JSON payload: {line_str} | Error: {e}")
                else:
                    if line_str:
                        print(f"[Serial Bridge] ESP32 Message: {line_str}")
        except Exception as e:
            print(f"[Serial Bridge] Connection lost or error: {e}")
            if ser:
                try:
                    ser.close()
                except Exception:
                    pass
                ser = None
            ws_manager.is_serial_connected = False
            if main_loop:
                asyncio.run_coroutine_threadsafe(
                    ws_manager.update_sensor_connected_status(),
                    main_loop
                )
            time.sleep(2)

# Lifespan events are handled via the lifespan generator defined at the top

if __name__ == "__main__":
    # Run uvicorn on 0.0.0.0 to allow connection from ESP32 via WiFi if desired
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")
