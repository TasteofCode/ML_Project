import json
import logging
import asyncio
from fastapi import WebSocket, WebSocketDisconnect
from typing import Set
from gesture_buffer import GestureBuffer
from prediction_engine import PredictionEngine

logger = logging.getLogger("WebSocketHandler")

class WebSocketManager:
    """
    Manages active WebSocket connections for ESP32 sensors and React clients.
    Handles data routing, feature extraction, and realtime prediction dispatch.
    """
    def __init__(self, buffer: GestureBuffer, engine: PredictionEngine):
        self.buffer = buffer
        self.engine = engine
        
        # Connection pools
        self.frontend_connections: Set[WebSocket] = set()
        self.sensor_connections: Set[WebSocket] = set()
        
        # System states
        self.is_recording = False
        self.recorded_frames = 0
        self.is_sensor_connected = False
        self.is_serial_connected = False
        self.is_android_connected = False

    async def update_sensor_connected_status(self):
        """
        Calculates and updates overall sensor connection status across all sources.
        """
        was_connected = self.is_sensor_connected
        self.is_sensor_connected = (
            len(self.sensor_connections) > 0 or 
            self.is_serial_connected or 
            self.is_android_connected
        )
        if was_connected != self.is_sensor_connected:
            await self.broadcast_to_frontend({
                "event": "stream_status",
                "connected": self.is_sensor_connected
            })

    async def connect_frontend(self, websocket: WebSocket):
        """
        Accepts and registers a new frontend React client.
        """
        await websocket.accept()
        self.frontend_connections.add(websocket)
        logger.info(f"Frontend client connected. Total clients: {len(self.frontend_connections)}")
        
        # Send initial status
        await websocket.send_json({
            "event": "status",
            "message": "Connection established successfully."
        })
        
        # Update stream status indicator
        await websocket.send_json({
            "event": "stream_status",
            "connected": self.is_sensor_connected
        })

    def disconnect_frontend(self, websocket: WebSocket):
        """
        Deregisters a frontend React client.
        """
        self.frontend_connections.discard(websocket)
        logger.info(f"Frontend client disconnected. Remaining clients: {len(self.frontend_connections)}")

    async def connect_sensor(self, websocket: WebSocket):
        """
        Accepts and registers a new ESP32 sensor.
        """
        await websocket.accept()
        self.sensor_connections.add(websocket)
        logger.info(f"ESP32 sensor connected. Total sensors: {len(self.sensor_connections)}")
        
        # Notify frontends
        await self.broadcast_to_frontend({
            "event": "status",
            "message": "Connection established with ESP32 sensor (WebSocket)."
        })
        await self.update_sensor_connected_status()

    async def disconnect_sensor(self, websocket: WebSocket):
        """
        Deregisters an ESP32 sensor connection.
        """
        if websocket in self.sensor_connections:
            self.sensor_connections.remove(websocket)
        logger.info(f"ESP32 sensor disconnected. Remaining sensors: {len(self.sensor_connections)}")
        
        # Notify frontends
        await self.broadcast_to_frontend({
            "event": "status",
            "message": "Connection lost with ESP32 (WebSocket)."
        })
        await self.update_sensor_connected_status()

    async def broadcast_to_frontend(self, data: dict):
        """
        Sends JSON data to all registered frontend clients.
        """
        if not self.frontend_connections:
            return
            
        disconnected = []
        for connection in self.frontend_connections:
            try:
                await connection.send_json(data)
            except Exception:
                disconnected.append(connection)
                
        for conn in disconnected:
            self.disconnect_frontend(conn)

    async def handle_sensor_stream(self, raw_data_str: str):
        """
        Processes a raw JSON sensor packet from the ESP32.
        Buffers data, broadcasts telemetry, and performs inference if ready.
        """
        try:
            data = json.loads(raw_data_str)
        except json.JSONDecodeError:
            logger.warning("Received invalid JSON sensor packet. Discarding.")
            await self.broadcast_to_frontend({
                "event": "status",
                "message": "Corrupted sensor values: invalid JSON packet."
            })
            return

        # Validate packet fields
        required_fields = ["ax", "ay", "az", "timestamp"]
        if not all(field in data for field in required_fields):
            logger.warning(f"Sensor packet missing required fields. Got: {list(data.keys())}")
            return

        ax, ay, az = data["ax"], data["ay"], data["az"]
        gx, gy, gz = data.get("gx", 0.0), data.get("gy", 0.0), data.get("gz", 0.0)
        timestamp = data["timestamp"]

        # Forward raw telemetry to frontend for graphing and drawing
        await self.broadcast_to_frontend({
            "event": "telemetry",
            "data": {
                "ax": ax, "ay": ay, "az": az,
                "gx": gx, "gy": gy, "gz": gz,
                "timestamp": timestamp
            }
        })

        # Feature processing logic
        if self.is_recording:
            self.buffer.add_frame(ax, ay, az, timestamp)
            self.recorded_frames += 1
            
            # Send progress update
            progress_pct = min(100.0, (self.recorded_frames / self.buffer.window_size) * 100.0)
            await self.broadcast_to_frontend({
                "event": "recording_progress",
                "frames": self.recorded_frames,
                "progress": progress_pct
            })

            # Check if discrete window recording finished
            if self.recorded_frames >= self.buffer.window_size:
                self.is_recording = False
                logger.info("Recording complete. Processing gesture window...")
                await self.broadcast_to_frontend({
                    "event": "status",
                    "message": "Realtime prediction active."
                })
                
                # Perform inference
                is_stationary = self.buffer.is_stationary()
                try:
                    features, _ = self.buffer.extract_features()
                    gesture, confidence = self.engine.predict(features, is_stationary)
                    
                    status_message = "Gesture recognized successfully." if confidence >= 0.70 else "Low confidence prediction detected."
                    
                    await self.broadcast_to_frontend({
                        "event": "prediction",
                        "gesture": gesture,
                        "confidence": confidence,
                        "status": status_message
                    })
                except Exception as e:
                    logger.error(f"Failed to process recording window: {e}")
                    await self.broadcast_to_frontend({
                        "event": "status",
                        "message": "Prediction timeout or feature processing error."
                    })
                finally:
                    self.buffer.clear()
                    self.recorded_frames = 0
        else:
            # Continuous sliding-window prediction (if buffer ready, run continuously)
            self.buffer.add_frame(ax, ay, az, timestamp)
            pass

    async def process_client_command(self, message_str: str):
        """
        Handles incoming control messages from React frontend.
        """
        try:
            msg = json.loads(message_str)
            command = msg.get("command")
            
            if command == "start_recording":
                self.is_recording = True
                self.recorded_frames = 0
                self.buffer.clear()
                logger.info("Recording started.")
                await self.broadcast_to_frontend({
                    "event": "status",
                    "message": "Click RECORD and perform gesture. Capturing..."
                })
                
            elif command == "stop_recording":
                self.is_recording = False
                self.recorded_frames = 0
                self.buffer.clear()
                logger.info("Recording stopped.")
                await self.broadcast_to_frontend({
                    "event": "status",
                    "message": "Recording stopped."
                })
                
            elif command == "reset":
                self.is_recording = False
                self.recorded_frames = 0
                self.buffer.clear()
                logger.info("System reset triggered.")
                await self.broadcast_to_frontend({
                    "event": "status",
                    "message": "Waiting for sensor stream..." if self.is_sensor_connected else "Click CONNECT to establish ESP32 communication."
                })
                await self.broadcast_to_frontend({
                    "event": "reset_complete"
                })
                
        except Exception as e:
            logger.error(f"Error parsing client command: {e}")
