import asyncio
import json
import time
import websockets
import os

# Server endpoint
WS_URL = "ws://localhost:8000/ws/sensor"

# CSV dataset path
DOWNLOADS_DIR = r"c:\Users\hp\Downloads"

def generate_synthetic_data(gesture_type: str, frame_idx: int) -> tuple:
    """
    Generates synthetic motion data representing standard gestures in m/s^2.
    """
    # Base gravity
    gravity_x = -7.07
    gravity_y = -2.30
    gravity_z = 0.80

    t = frame_idx * (2 * 3.14159 / 50) # 1 full cycle over 50 frames (1s)

    if gesture_type == "circle":
        # Traces a circle in X/Y plane
        ax = gravity_x + 5.0 * int(frame_idx > 5 and frame_idx < 45) * (0.5 * (1 + 0.5 * (1 + 0.5 * 1))) * (1.0 if frame_idx % 2 == 0 else -1.0)
        # Better model for circle
        ax = gravity_x + 4.0 * float(np.sin(t)) if 'np' in globals() else gravity_x + 4.0 * (t % 2.0 - 1.0)
        ay = gravity_y + 4.0 * float(np.cos(t)) if 'np' in globals() else gravity_y + 4.0 * (t % 2.0 - 1.0)
        az = gravity_z + 1.0 * (t % 2.0 - 1.0)
        return ax, ay, az
    elif gesture_type == "rectangle":
        # Rectangle motion
        if frame_idx < 12:
            return gravity_x + 4.0, gravity_y, gravity_z
        elif frame_idx < 25:
            return gravity_x, gravity_y + 4.0, gravity_z
        elif frame_idx < 37:
            return gravity_x - 4.0, gravity_y, gravity_z
        else:
            return gravity_x, gravity_y - 4.0, gravity_z
    elif gesture_type == "double_tap":
        # Double spike impulse
        if frame_idx == 15 or frame_idx == 30:
            return gravity_x, gravity_y, gravity_z + 15.0
        return gravity_x, gravity_y, gravity_z
    else: # Rest
        return gravity_x, gravity_y, gravity_z

async def stream_gesture(gesture_type: str):
    """
    Streams a single 50-frame gesture to the server.
    """
    csv_file = os.path.join(DOWNLOADS_DIR, f"{gesture_type.replace('_', ' ').title()}.csv")
    use_csv = os.path.exists(csv_file)
    
    print(f"\n==================== STREAMING GESTURE: {gesture_type.upper()} ====================")
    if use_csv:
        print(f"Reading from dataset: {csv_file}")
        import pandas as pd
        df = pd.read_csv(csv_file)
        if df.shape[1] == 1:
            df = pd.read_csv(csv_file, sep=',')
        
        # Read the first 50 frames
        frames = df.iloc[:50]
        # Clean quotes from column values if string
        ax_vals = frames['ax'].values
        ay_vals = frames['ay'].values
        az_vals = frames['az'].values
    else:
        print("Using synthetic generator...")
        ax_vals = []
        ay_vals = []
        az_vals = []
        for i in range(50):
            # Fallback simple math
            import math
            t = i * (2 * math.pi / 50)
            if gesture_type == "circle":
                ax_vals.append(-7.07 + 4.0 * math.sin(t))
                ay_vals.append(-2.30 + 4.0 * math.cos(t))
                az_vals.append(0.80)
            elif gesture_type == "rectangle":
                ax_vals.append(-7.07 + (4.0 if i % 25 < 12 else -4.0))
                ay_vals.append(-2.30 + (4.0 if (i+6) % 25 < 12 else -4.0))
                az_vals.append(0.80)
            elif gesture_type == "double_tap":
                ax_vals.append(-7.07)
                ay_vals.append(-2.30)
                az_vals.append(0.80 + (12.0 if i in [15, 30] else 0.0))
            else: # rest
                ax_vals.append(-7.07)
                ay_vals.append(-2.30)
                az_vals.append(0.80)

    try:
        async with websockets.connect(WS_URL) as ws:
            print("Connected to FastAPI /ws/sensor.")
            for i in range(50):
                packet = {
                    "ax": float(ax_vals[i]),
                    "ay": float(ay_vals[i]),
                    "az": float(az_vals[i]),
                    "gx": 0.0,
                    "gy": 0.0,
                    "gz": 0.0,
                    "timestamp": int(time.time() * 1000)
                }
                await ws.send(json.dumps(packet))
                # Stream at 50Hz (20ms delay)
                await asyncio.sleep(0.02)
            print("✔ Streamed 50 frames successfully.")
    except Exception as e:
        print(f"Connection error: {e}")

async def main():
    print(f"Mock client started. Target host: {WS_URL}")
    while True:
        print("\nAvailable Gestures to stream:")
        print("1. Circle")
        print("2. Double Tap")
        print("3. Figure 8")
        print("4. Rectangle")
        print("5. Rest")
        print("6. Exit")
        choice = input("Select a gesture to stream (1-6): ").strip()
        
        mapping = {
            "1": "circle",
            "2": "double_tap",
            "3": "figure_8",
            "4": "rectangle",
            "5": "rest"
        }
        
        if choice == "6":
            print("Exiting mock client.")
            break
        elif choice in mapping:
            await stream_gesture(mapping[choice])
        else:
            print("Invalid choice.")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nClient terminated by user.")
