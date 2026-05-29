import asyncio
import json
import time
import websockets

CLIENT_WS_URL = "ws://localhost:8000/ws/client"
SENSOR_WS_URL = "ws://localhost:8000/ws/sensor"

async def receive_prediction(prediction_future):
    """
    Listens on the client WebSocket for the final prediction response.
    """
    try:
        async with websockets.connect(CLIENT_WS_URL) as ws:
            print("[Test Client] Connected to Client WebSocket.")
            
            # Send command to start recording
            await ws.send(json.dumps({"command": "start_recording"}))
            print("[Test Client] Sent start_recording command.")
            
            while True:
                msg_str = await ws.recv()
                msg = json.loads(msg_str)
                event = msg.get("event")
                
                if event == "recording_progress":
                    print(f"[Test Client] Recording progress: {msg.get('progress')}% ({msg.get('frames')}/50 frames)")
                elif event == "prediction":
                    print(f"\n[Test Client] RECEIVED PREDICTION RESULT:")
                    print(f"  Gesture:    {msg.get('gesture')}")
                    print(f"  Confidence: {msg.get('confidence') * 100:.2f}%")
                    print(f"  Status:     {msg.get('status')}")
                    prediction_future.set_result(msg)
                    break
                elif event == "status":
                    print(f"[Test Client] Status: {msg.get('message')}")
    except Exception as e:
        print(f"[Test Client] Error: {e}")
        prediction_future.set_exception(e)

async def stream_sensor_data():
    """
    Streams a simulated circular gesture to the sensor WebSocket at 50Hz.
    """
    # Wait a moment for recording to start
    await asyncio.sleep(1.0)
    
    print("\n[Test Sensor] Connecting to Sensor WebSocket...")
    try:
        async with websockets.connect(SENSOR_WS_URL) as ws:
            print("[Test Sensor] Connected to Sensor WebSocket. Starting stream...")
            
            # Simulate a 50-frame circular gesture
            import math
            gravity_x = -7.07
            gravity_y = -2.30
            gravity_z = 0.80
            
            for i in range(50):
                t = i * (2 * math.pi / 50)
                # Generate circular force vector
                ax = gravity_x + 4.0 * math.sin(t)
                ay = gravity_y + 4.0 * math.cos(t)
                az = gravity_z
                
                packet = {
                    "ax": float(ax),
                    "ay": float(ay),
                    "az": float(az),
                    "gx": 0.0,
                    "gy": 0.0,
                    "gz": 0.0,
                    "timestamp": int(time.time() * 1000)
                }
                
                await ws.send(json.dumps(packet))
                # 50Hz (20ms interval)
                await asyncio.sleep(0.02)
                
            print("[Test Sensor] Completed streaming 50 frames.")
    except Exception as e:
        print(f"[Test Sensor] Error: {e}")

async def run_integration_test():
    loop = asyncio.get_running_loop()
    prediction_future = loop.create_future()
    
    # Run client listener and sensor streamer concurrently
    await asyncio.gather(
        receive_prediction(prediction_future),
        stream_sensor_data()
    )
    
    result = prediction_future.result()
    print("\n==================== INTEGRATION TEST SUCCESS ====================")
    print(f"Server correctly classified gesture as: {result.get('gesture')} ({result.get('confidence')*100:.1f}%)")

if __name__ == "__main__":
    print("Starting automated integration test...")
    asyncio.run(run_integration_test())
