/**
 * ESP32 Real-Time Gesture Recognition Firmware
 * --------------------------------------------
 * Connects to WiFi, initializes the MPU6050 IMU, establishes a WebSocket 
 * connection to the FastAPI backend, and streams sensor data at 50Hz.
 * 
 * Dependencies (Install via Arduino Library Manager):
 * - ArduinoJson (by Benoit Blanchon)
 * - WebSockets (by Markus Sattler)
 */

#include <WiFi.h>
#include <Wire.h>
#include <ArduinoJson.h>
#include <WebSocketsClient.h>

// =============================================================================
// USER CONFIGURATION
// =============================================================================
const char* ssid     = "SKY";     // Replace with your WiFi SSID
const char* password = "A++987654321++A"; // Replace with your WiFi password

// Server IP address and port (Replace with your computer's IP address)
const char* server_host = "192.168.0.112";  
const int server_port = 8000;
const char* server_path = "/ws/sensor";

// =============================================================================
// HARDWARE DEFINITIONS
// =============================================================================
#define SDA_PIN 21
#define SCL_PIN 22

// MPU6050 sensitivity factors
// Accel range ±2g: sensitivity = 16384 LSB/g. Gravity = 9.81 m/s²
const float ACCEL_SCALE = 16384.0;
const float GRAVITY = 9.80665;
// Gyro range ±250 deg/s: sensitivity = 131 LSB/(deg/s)
const float GYRO_SCALE = 131.0;

// =============================================================================
// DATA STRUCTURES & GLOBALS
// =============================================================================
struct SensorData {
  float ax, ay, az;
  float gx, gy, gz;
};

uint8_t mpu_addr = 0x68;
bool useSimulationMode = false;

// Global Instances
WebSocketsClient webSocket;
unsigned long lastSendTime = 0;
const unsigned long sendIntervalMs = 20; // 50Hz (20ms interval)

// =============================================================================
// MPU6050 LOW-LEVEL FUNCTIONS
// =============================================================================
void writeRegister(uint8_t reg, uint8_t val) {
  Wire.beginTransmission(mpu_addr);
  Wire.write(reg);
  Wire.write(val);
  Wire.endTransmission();
}

bool initMPU6050() {
  // Use 100kHz I2C clock (standard mode) for much higher signal integrity and noise resilience
  Wire.begin(SDA_PIN, SCL_PIN, 100000); 
  
  uint8_t addresses[] = {0x68, 0x69};
  for (int i = 0; i < 2; i++) {
    uint8_t addr = addresses[i];
    
    // Wake up sensor (write 0 to PWR_MGMT_1 register 0x6B)
    Wire.beginTransmission(addr);
    Wire.write(0x6B);
    Wire.write(0x00);
    if (Wire.endTransmission() != 0) {
      continue; // No device responded at this address
    }
    delay(10);
    
    // Verify communication by reading WHO_AM_I register (0x75)
    Wire.beginTransmission(addr);
    Wire.write(0x75);
    Wire.endTransmission(false);
    Wire.requestFrom(addr, 1);
    
    if (Wire.available()) {
      uint8_t whoAmI = Wire.read();
      // MPU6050 is 0x68, MPU6500 is 0x70, MPU9250/MPU9255 is 0x71/0x73, MPU6000 is 0x68/0x69
      if (whoAmI == 0x68 || whoAmI == 0x70 || whoAmI == 0x71 || whoAmI == 0x72 || whoAmI == 0x73 || whoAmI == 0x69) {
        mpu_addr = addr;
        Serial.printf("[MPU6050] Sensor found successfully at address 0x%02X (WHO_AM_I = 0x%02X).\n", addr, whoAmI);
        
        // Configure Accelerometer Config: ±2g
        writeRegister(0x1C, 0x00);
        
        // Configure Gyro Config: ±250 deg/s
        writeRegister(0x1B, 0x00);
        
        // Configure Digital Low Pass Filter (DLPF): ~44Hz bandwidth
        writeRegister(0x1A, 0x03);
        
        return true;
      }
    }
  }
  Serial.println("[MPU6050] Error: Could not find sensor on 0x68 or 0x69. Check wiring!");
  return false;
}

SensorData readSensorData() {
  SensorData data = {0.0, 0.0, 0.0, 0.0, 0.0, 0.0};
  
  if (useSimulationMode) {
    // Generate synthetic motion data (slow circular wave)
    float t = millis() / 1000.0;
    data.ax = -7.07 + 3.0 * sin(t);
    data.ay = -2.30 + 3.0 * cos(t);
    data.az = 0.80 + 0.5 * sin(t * 2);
    data.gx = 0.1 * sin(t);
    data.gy = 0.1 * cos(t);
    data.gz = 0.05 * sin(t * 1.5);
    return data;
  }
  
  // Request 14 bytes starting from register 0x3B (ACCEL_XOUT_H)
  Wire.beginTransmission(mpu_addr);
  Wire.write(0x3B);
  Wire.endTransmission(false);
  Wire.requestFrom(mpu_addr, 14);
  
  if (Wire.available() >= 14) {
    // Read raw 16-bit values
    int16_t raw_ax = (Wire.read() << 8) | Wire.read();
    int16_t raw_ay = (Wire.read() << 8) | Wire.read();
    int16_t raw_az = (Wire.read() << 8) | Wire.read();
    int16_t raw_temp = (Wire.read() << 8) | Wire.read(); // Skip temp
    int16_t raw_gx = (Wire.read() << 8) | Wire.read();
    int16_t raw_gy = (Wire.read() << 8) | Wire.read();
    int16_t raw_gz = (Wire.read() << 8) | Wire.read();
    
    // Scale values to physical units: m/s² for accel, rad/s for gyro
    data.ax = (raw_ax / ACCEL_SCALE) * GRAVITY;
    data.ay = (raw_ay / ACCEL_SCALE) * GRAVITY;
    data.az = (raw_az / ACCEL_SCALE) * GRAVITY;
    
    // DEG_TO_RAD is globally defined by Arduino.h core
    data.gx = (raw_gx / GYRO_SCALE) * DEG_TO_RAD;
    data.gy = (raw_gy / GYRO_SCALE) * DEG_TO_RAD;
    data.gz = (raw_gz / GYRO_SCALE) * DEG_TO_RAD;
  }
  
  return data;
}

// =============================================================================
// WEBSOCKET EVENTS
// =============================================================================
void webSocketEvent(WStype_t type, uint8_t * payload, size_t length) {
  switch(type) {
    case WStype_DISCONNECTED:
      Serial.println("[WS] Disconnected from server.");
      break;
    case WStype_CONNECTED:
      Serial.printf("[WS] Connected to URL: %s\n", payload);
      break;
    case WStype_TEXT:
      Serial.printf("[WS] Received instruction: %s\n", payload);
      break;
    case WStype_BIN:
      break;
    case WStype_ERROR:
      Serial.println("[WS] Connection error occurred.");
      break;
    case WStype_FRAGMENT_TEXT_START:
    case WStype_FRAGMENT_BIN_START:
    case WStype_FRAGMENT:
    case WStype_FRAGMENT_FIN:
      break;
  }
}

// =============================================================================
// ARDUINO SETUP & LOOP
// =============================================================================
void setup() {
  Serial.begin(115200);
  delay(1000);
  
  // 1. Initialize MPU6050 Sensor
  if (!initMPU6050()) {
    Serial.println("[System] WARNING: MPU6050 connection failed!");
    Serial.println("[System] Bypassing infinite loop block.");
    Serial.println("[System] Entering Mock Simulation Mode. Generating synthetic motion data...");
    useSimulationMode = true;
  }

  // 2. Connect to WiFi network
  Serial.printf("[WiFi] Connecting to %s ", ssid);
  WiFi.begin(ssid, password);
  int retries = 0;
  while (WiFi.status() != WL_CONNECTED && retries < 20) { // 10 seconds timeout
    delay(500);
    Serial.print(".");
    retries++;
  }
  if (WiFi.status() == WL_CONNECTED) {
    Serial.println("\n[WiFi] Connected successfully!");
    Serial.print("[WiFi] ESP32 IP address: ");
    Serial.println(WiFi.localIP());
    
    // 3. Initialize WebSocket client
    webSocket.begin(server_host, server_port, server_path);
    webSocket.onEvent(webSocketEvent);
    webSocket.setReconnectInterval(5000); // Reconnect every 5s if disconnected
  } else {
    Serial.println("\n[WiFi] Failed to connect to WiFi. Running in Serial USB mode.");
  }
}

void loop() {
  if (WiFi.status() == WL_CONNECTED) {
    webSocket.loop();
  }
  
  // Send data at 50Hz (every 20 milliseconds)
  unsigned long currentTime = millis();
  if (currentTime - lastSendTime >= sendIntervalMs) {
    lastSendTime = currentTime;
    
    SensorData data = readSensorData();
    
    // Create JSON payload
    StaticJsonDocument<256> jsonDoc;
    jsonDoc["ax"] = data.ax;
    jsonDoc["ay"] = data.ay;
    jsonDoc["az"] = data.az;
    jsonDoc["gx"] = data.gx;
    jsonDoc["gy"] = data.gy;
    jsonDoc["gz"] = data.gz;
    jsonDoc["timestamp"] = currentTime; // Millisecond timestamp

    String payload;
    serializeJson(jsonDoc, payload);
    
    // Always print to Serial (USB) so direct connection works
    Serial.println(payload);
    
    // Also stream to FastAPI Server via WebSocket if connected
    if (WiFi.status() == WL_CONNECTED && webSocket.isConnected()) {
      webSocket.sendTXT(payload);
    } else {
      // Periodic notice if websocket is active but disconnected
      if (WiFi.status() == WL_CONNECTED && (currentTime % 3000 < sendIntervalMs)) {
        Serial.println("[WS] Client disconnected. Attempting reconnect...");
      }
    }
  }
}
