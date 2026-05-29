'use client';

import React, { useState, useEffect, useRef } from 'react';
import { Activity, Radio, Play, Square, RefreshCw, Layers, Database, FileText } from 'lucide-react';
import { CONNECT_PATH, RECORD_PATH, STOP_PATH, RESET_PATH } from './icons';

export default function Home() {
  // WebSocket refs
  const wsRef = useRef(null);

  // Canvas refs
  const oscilloscopeCanvasRef = useRef(null);
  const trajectoryCanvasRef = useRef(null);

  // Trajectory physics variables
  const trajState = useRef({
    px: 150, py: 150,
    vx: 0, vy: 0,
    points: []
  });

  // State Management
  const [wsStatus, setWsStatus] = useState('DISCONNECTED'); // DISCONNECTED, CONNECTING, CONNECTED
  const [sensorConnected, setSensorConnected] = useState(false);
  const [isRecording, setIsRecording] = useState(false);
  const [recordingProgress, setRecordingProgress] = useState(0);
  const [recordedFrames, setRecordedFrames] = useState(0);

  const [prediction, setPrediction] = useState({ gesture: 'None', confidence: 0.0, status: '' });
  const [predictionHistory, setPredictionHistory] = useState([]);
  const [instruction, setInstruction] = useState('Click CONNECT to establish ESP32 communication.');
  const [latestTelemetry, setLatestTelemetry] = useState(null);
  const [isSensingMotion, setIsSensingMotion] = useState(false);
  const recentTelemetryRef = useRef([]);
  const [consoleLogs, setConsoleLogs] = useState([]);

  // Telemetry buffer for table and trajectory
  const [recordedTelemetry, setRecordedTelemetry] = useState([]);
  const recordedFramesRef = useRef([]);
  const isRecordingRef = useRef(false);
  const lastTelemetryTimestampRef = useRef(null);

  // Telemetry buffer for Oscilloscope
  const telemetryHistory = useRef([]);

  // Log message helper
  const addLog = (message) => {
    const timestamp = new Date().toLocaleTimeString();
    setConsoleLogs((prev) => [...prev.slice(-49), `[${timestamp}] ${message}`]);
  };

  // Connect to FastAPI WS Client
  const connectWebSocket = () => {
    if (wsRef.current && wsRef.current.readyState !== WebSocket.CLOSED) {
      addLog("WebSocket is already active or connecting.");
      return;
    }

    setWsStatus('CONNECTING');
    setInstruction('Connecting to server...');
    addLog("Attempting connection to ws://localhost:8000/ws/client...");

    const ws = new WebSocket('ws://localhost:8000/ws/client');
    wsRef.current = ws;

    ws.onopen = () => {
      setWsStatus('CONNECTED');
      setInstruction('Connection established successfully.');
      addLog("✔ Connected to FastAPI Backend.");
    };

    ws.onmessage = (event) => {
      try {
        const payload = JSON.parse(event.data);

        switch (payload.event) {
          case 'status':
            setInstruction(payload.message);
            addLog(`[SERVER] ${payload.message}`);
            break;

          case 'stream_status':
            setSensorConnected(payload.connected);
            if (payload.connected) {
              addLog("📡 ESP32 Sensor streaming stream detected.");
            } else {
              addLog("⚠ ESP32 Sensor is offline.");
            }
            break;

          case 'recording_progress':
            setIsRecording(true);
            isRecordingRef.current = true;
            setRecordedFrames(payload.frames);
            setRecordingProgress(payload.progress);
            break;

          case 'telemetry':
            // Deduplicate telemetry frames based on timestamp
            if (payload.data.timestamp && payload.data.timestamp === lastTelemetryTimestampRef.current) {
              break;
            }
            lastTelemetryTimestampRef.current = payload.data.timestamp;

            // Push to oscilloscope buffer
            telemetryHistory.current.push(payload.data);
            if (telemetryHistory.current.length > 200) {
              telemetryHistory.current.shift();
            }

            // Push to rolling window for motion sensing
            recentTelemetryRef.current.push(payload.data);
            if (recentTelemetryRef.current.length > 10) {
              recentTelemetryRef.current.shift();
            }

            // Calculate aggregate variance over the last 10 frames
            if (recentTelemetryRef.current.length >= 2) {
              const frames = recentTelemetryRef.current;
              const n = frames.length;
              const meanAx = frames.reduce((acc, f) => acc + f.ax, 0) / n;
              const meanAy = frames.reduce((acc, f) => acc + f.ay, 0) / n;
              const meanAz = frames.reduce((acc, f) => acc + f.az, 0) / n;
              const varAx = frames.reduce((acc, f) => acc + Math.pow(f.ax - meanAx, 2), 0) / n;
              const varAy = frames.reduce((acc, f) => acc + Math.pow(f.ay - meanAy, 2), 0) / n;
              const varAz = frames.reduce((acc, f) => acc + Math.pow(f.az - meanAz, 2), 0) / n;

              const totalVar = varAx + varAy + varAz;
              // Senses motion if total variance >= 0.15
              setIsSensingMotion(totalVar >= 0.15);
            } else {
              setIsSensingMotion(false);
            }

            setLatestTelemetry({
              ax: payload.data.ax,
              ay: payload.data.ay,
              az: payload.data.az
            });

            // Draw to canvases
            updateOscilloscope();
            
            // Accumulate recorded telemetry if recording is active
            if (isRecordingRef.current) {
              const frameWithSr = {
                srNo: recordedFramesRef.current.length + 1,
                ax: payload.data.ax,
                ay: payload.data.ay,
                az: payload.data.az,
                gx: payload.data.gx,
                gy: payload.data.gy,
                gz: payload.data.gz,
                timestamp: payload.data.timestamp
              };
              recordedFramesRef.current.push(frameWithSr);
            }
            break;

          case 'prediction':
            setIsRecording(false);
            isRecordingRef.current = false;
            setRecordingProgress(100);

            const confidencePercent = (payload.confidence * 100).toFixed(1);
            const isPass = payload.confidence >= 0.70;
            const statusLabel = isPass ? 'Pass' : 'Fail';

            setPrediction({
              gesture: payload.gesture,
              confidence: payload.confidence,
              status: payload.status
            });

            // Draw the predicted gesture shape statically on the canvas
            drawPredictedGestureShape(payload.gesture);

            // Append only the final sensor telemetry reading of this gesture iteration to the table
            if (recordedFramesRef.current.length > 0) {
              const finalFrame = recordedFramesRef.current[recordedFramesRef.current.length - 1];
              setRecordedTelemetry((prev) => [
                ...prev,
                {
                  ...finalFrame,
                  srNo: prev.length + 1
                }
              ]);
            }

            // Append to table history
            setPredictionHistory((prev) => [
              ...prev,
              {
                srNo: prev.length + 1,
                gesture: payload.gesture,
                accuracy: `${confidencePercent}%`,
                status: statusLabel,
                isPass: isPass
              }
            ]);

            setInstruction(payload.status);
            addLog(`🎯 PREDICTION: ${payload.gesture} (${confidencePercent}%) - ${statusLabel}`);
            break;

          case 'reset_complete':
            setPrediction({ gesture: 'None', confidence: 0.0, status: '' });
            setRecordingProgress(0);
            setRecordedFrames(0);
            setIsRecording(false);
            isRecordingRef.current = false;
            setLatestTelemetry(null);
            setIsSensingMotion(false);
            recentTelemetryRef.current = [];
            setRecordedTelemetry([]);
            recordedFramesRef.current = [];
            lastTelemetryTimestampRef.current = null;
            // Clear trajectory canvas
            if (trajectoryCanvasRef.current) {
              const canvas = trajectoryCanvasRef.current;
              const ctx = canvas.getContext('2d');
              ctx.clearRect(0, 0, canvas.width, canvas.height);
            }
            addLog("System reset complete. Local canvas cleared.");
            break;

          default:
            break;
        }
      } catch (err) {
        addLog(`Error parsing packet: ${err.message}`);
      }
    };

    ws.onclose = () => {
      setWsStatus('DISCONNECTED');
      setSensorConnected(false);
      setIsRecording(false);
      isRecordingRef.current = false;
      setLatestTelemetry(null);
      setIsSensingMotion(false);
      recentTelemetryRef.current = [];
      setInstruction('Connection lost. Reconnecting...');
      addLog("❌ WebSocket disconnected. Will attempt auto-reconnect.");

      // Auto-reconnect after 3 seconds
      setTimeout(() => {
        if (wsStatus === 'DISCONNECTED') {
          connectWebSocket();
        }
      }, 3000);
    };

    ws.onerror = (error) => {
      addLog("WebSocket Error occurred.");
      ws.close();
    };
  };

  // Commands triggers
  const startRecording = () => {
    if (wsStatus !== 'CONNECTED') {
      addLog("Cannot record: Server not connected.");
      return;
    }
    if (!sensorConnected) {
      addLog("Cannot record: Waiting for sensor stream...");
      return;
    }
    setIsRecording(true);
    isRecordingRef.current = true;
    setRecordedFrames(0);
    setRecordingProgress(0);

    // Clear old trajectory drawing and temporary frames buffer for the new gesture
    recordedFramesRef.current = [];
    lastTelemetryTimestampRef.current = null;
    if (trajectoryCanvasRef.current) {
      const canvas = trajectoryCanvasRef.current;
      const ctx = canvas.getContext('2d');
      ctx.clearRect(0, 0, canvas.width, canvas.height);
    }

    wsRef.current.send(JSON.stringify({ command: "start_recording" }));
    addLog("Sent command: start_recording");
  };

  const stopRecording = () => {
    if (wsStatus !== 'CONNECTED') return;
    wsRef.current.send(JSON.stringify({ command: "stop_recording" }));
    setIsRecording(false);
    isRecordingRef.current = false;
    addLog("Sent command: stop_recording");
  };

  const resetSystem = () => {
    if (wsStatus !== 'CONNECTED') return;
    wsRef.current.send(JSON.stringify({ command: "reset" }));
    setPredictionHistory([]);
    setRecordedTelemetry([]);
    recordedFramesRef.current = [];
    lastTelemetryTimestampRef.current = null;
    if (trajectoryCanvasRef.current) {
      const canvas = trajectoryCanvasRef.current;
      const ctx = canvas.getContext('2d');
      ctx.clearRect(0, 0, canvas.width, canvas.height);
    }
    addLog("Sent command: reset");
  };

  // Canvas Oscilloscope Renderer
  const updateOscilloscope = () => {
    const canvas = oscilloscopeCanvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    const width = canvas.width;
    const height = canvas.height;

    ctx.fillStyle = '#000000';
    ctx.fillRect(0, 0, width, height);

    // Draw horizontal grid lines
    ctx.strokeStyle = '#222222';
    ctx.lineWidth = 1;
    for (let y = 0; y < height; y += 30) {
      ctx.beginPath();
      ctx.moveTo(0, y);
      ctx.lineTo(width, y);
      ctx.stroke();
    }

    const data = telemetryHistory.current;
    if (data.length < 2) return;

    const midY = height / 2;
    const scale = height / 30; // 30 m/s^2 scale limit

    const axes = [
      { key: 'ax', color: '#FF3B30' }, // Red X
      { key: 'ay', color: '#4CD964' }, // Green Y
      { key: 'az', color: '#5AC8FA' }  // Blue Z
    ];

    axes.forEach(({ key, color }) => {
      ctx.strokeStyle = color;
      ctx.lineWidth = 1.5;
      ctx.beginPath();

      const step = width / 200;
      data.forEach((frame, idx) => {
        const x = idx * step;
        const y = midY - (frame[key] * scale);

        if (idx === 0) {
          ctx.moveTo(x, y);
        } else {
          ctx.lineTo(x, y);
        }
      });
      ctx.stroke();
    });
  };

  // Canvas Trajectory Renderer (Draws static shapes matching the predicted gesture)
  const drawPredictedGestureShape = (gesture) => {
    const canvas = trajectoryCanvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    const w = canvas.width;
    const h = canvas.height;

    // Normalizing gesture name to match case-insensitively
    const normalizedGesture = gesture ? gesture.toLowerCase().replace(/[\s_-]/g, '') : '';

    let points = [];

    if (normalizedGesture === 'circle') {
      const steps = 60;
      for (let i = 0; i <= steps; i++) {
        const theta = (i / steps) * 2 * Math.PI - Math.PI / 2;
        points.push({
          x: 150 + 60 * Math.cos(theta),
          y: 120 + 60 * Math.sin(theta)
        });
      }
    } else if (normalizedGesture === 'rectangle') {
      points = [
        { x: 80, y: 70 },
        { x: 220, y: 70 },
        { x: 220, y: 170 },
        { x: 80, y: 170 },
        { x: 80, y: 70 }
      ];
    } else if (normalizedGesture === 'doubletap') {
      points = [
        { x: 50, y: 120 },
        { x: 100, y: 120 },
        { x: 110, y: 50 },
        { x: 120, y: 120 },
        { x: 170, y: 120 },
        { x: 180, y: 50 },
        { x: 190, y: 120 },
        { x: 250, y: 120 }
      ];
    } else if (normalizedGesture === 'figure8') {
      const steps = 80;
      const a = 85;
      for (let i = 0; i <= steps; i++) {
        const t = (i / steps) * 2 * Math.PI;
        const denom = 1 + Math.sin(t) * Math.sin(t);
        const x = 150 + (a * Math.cos(t)) / denom;
        const y = 120 + (a * Math.sin(t) * Math.cos(t)) / denom;
        points.push({ x, y });
      }
    } else if (normalizedGesture === 'rest') {
      points = [
        { x: 50, y: 120 },
        { x: 250, y: 120 }
      ];
    }

    // Draw the static shape
    ctx.clearRect(0, 0, w, h);

    if (points.length > 1) {
      ctx.strokeStyle = '#245DDA'; // Windows XP primary blue
      ctx.lineWidth = 3;
      ctx.lineCap = 'round';
      ctx.lineJoin = 'round';
      ctx.beginPath();
      ctx.moveTo(points[0].x, points[0].y);
      for (let i = 1; i < points.length; i++) {
        ctx.lineTo(points[i].x, points[i].y);
      }
      ctx.stroke();
    }

    if (points.length > 0) {
      const lastPoint = points[points.length - 1];
      ctx.fillStyle = '#FF2D55';
      ctx.beginPath();
      ctx.arc(lastPoint.x, lastPoint.y, 6, 0, 2 * Math.PI);
      ctx.fill();
      ctx.strokeStyle = '#FFFFFF';
      ctx.lineWidth = 1;
      ctx.stroke();
    }
  };

  // Connect on load
  useEffect(() => {
    connectWebSocket();
    return () => {
      if (wsRef.current) wsRef.current.close();
    };
  }, []);

  return (
    <main className="min-h-screen p-4 flex flex-col items-center justify-between text-xs" style={{ minWidth: '850px' }}>

      {/* 1. Header Banner Title */}
      <header className="w-full max-w-5xl xp-outset flex items-center justify-between px-3 py-1.5 mb-3 bg-[#E9E6D3]">
        <div className="flex items-center gap-2">
          <svg viewBox="90 30 1150 720" className="w-5 h-5 text-xp-blue" fill="currentColor">
            <path d="M1008.5 34.201c-3.202 1.824-6.163 5.727-7.326 9.656-1.871 6.321-6.563 70.815-8.157 112.143-1.601 41.475-1.473 42.083 4.297 20.5 14.773-55.257 29.445-123.951 28.22-132.122-1.339-8.927-10.072-14.145-17.034-10.177m-106.39 42.14c-6.029 3.479-6.653 11.012-1.753 21.187 9.94 20.641 56.716 99.732 58.142 98.307.419-.42-4.51-16.787-11.996-39.835-5.782-17.802-22.906-63.853-26.03-70-4.575-9.005-12.381-13.11-18.363-9.659m224.321 3.671c-6.913 1.49-11.404 5.995-34.881 34.988-19.931 24.614-59.114 75.65-64.107 83.5-1.895 2.979-1.895 2.99.074 1.533 15.53-11.491 64.792-55.339 97.699-86.963 11.276-10.836 15.436-17.667 14.451-23.734-1.049-6.462-7.014-10.665-13.236-9.324m-253.202 87.039c-4.681 2.388-9.47 7.731-19.227 21.449-36.603 51.468-77.255 83.008-140.502 109.01-53.422 21.962-62.393 29.772-120.025 104.49-31.358 40.655-36.515 46.147-54.171 57.695-9.821 6.424-27.865 15.27-37.399 18.335-9.072 2.918-9.757 4.776-8.002 21.717 6.59 63.608 42.235 148.837 78.171 186.908 7.748 8.208 6.316 7.962 19.589 3.373 41.385-14.309 68.509-17.47 104.837-12.217 55.854 8.076 97.651 7.656 146.5-1.47 93.358-17.441 164.373-56.475 188.001-103.337 14.275-28.309 10.487-55.962-9.413-68.724-13.628-8.741-78.807-21.865-95.488-19.227-19.022 3.008-56.747 18.342-65.758 26.727-15.743 14.651-7.282 42.088 15.032 48.745 11.119 3.318 34.062 2.378 51.253-2.1l5.569-1.451 5.652 3.38c3.109 1.859 7.902 4.189 10.652 5.178 6.161 2.216 7.128 3.002 5.756 4.676-.774.944-.153 3.448 2.307 9.292 5.939 14.113 4.48 14.797-7.859 3.683-4.774-4.299-10.751-8.851-13.283-10.116l-4.604-2.299-13.272 2.116c-22.703 3.62-42.238 2.368-53.737-3.445-22.062-11.151-31.085-35.97-20.545-56.514l3.649-7.112-6.002-5.557c-8.372-7.751-12.536-15.433-14.383-26.534-.812-4.885-1.476-4.35-6.878 5.542-19.873 36.387-58.851 67.641-101.681 81.532-17.416 5.649-41.211 10.024-39.505 7.265.36-.584 1.416-1.067 2.346-1.074 3.042-.023 27.643-8.702 38.79-13.685 50.214-22.444 89.906-64.255 104.715-110.302 2.865-8.909 3.72-10.551 5.641-10.834 2.232-.329 2.254-.227 1.534 6.948l-.732 7.281 5.078-6.101c2.792-3.355 7.347-8.015 10.121-10.354 6.184-5.214 6.191-4.865-.206-9.912-19.534-15.413-24.471-42.95-11.206-62.497 5.545-8.171 2.347-7.503-21.478 4.485-19.303 9.713-27.914 13.469-28.813 12.57-2.518-2.517 11.976-17.106 23.818-23.975 39.766-23.063 58.232-37.102 76.33-58.026 29.576-34.196 40.346-77.021 26.703-106.177-7.996-17.087-25.144-25.851-37.875-19.357m307.271 1.379c-28.298 8.617-94.653 40.881-160 77.798-25.244 14.261-71.703 41.218-75.439 43.772-1.959 1.339-.501 1.369 13.623.279 8.699-.672 29.316-1.506 45.816-1.854 42.777-.901 54.016 1.186 69.236 12.857l5.764 4.419 10-6.625c10.982-7.276 32.311-20.922 54-34.548 7.7-4.838 17.6-11.064 22-13.836 49.833-31.396 59.225-39.599 61.045-53.32 3.014-22.722-19.663-36.975-46.045-28.942m-190 133.712c-43.386 1.265-67.192 4.392-81.799 10.742-17.66 7.679-59.921 43.457-65.692 55.616-7.675 16.169.265 37.383 16.729 44.7 4.884 2.17 4.184 2.42 16.947-6.052 28.813-19.126 42.839-23.151 80.637-23.144 46.393.009 81.963 4.424 94.634 11.747l4.456 2.575 5.914-6.413c25.433-27.578 27.957-57.548 6.519-77.396-13.165-12.188-24.325-13.951-78.345-12.375m-60 95.852c-21.754 3.238-55.404 22.324-80.571 45.699-15.615 14.504-13.775 38.44 3.898 50.687l4.032 2.794 7.821-4.031c18.793-9.689 43.848-18.945 57.288-21.164 9.399-1.552 20.068-.788 43.098 3.086 35.767 6.017 54.237 11.771 65.86 20.514l7.387 5.557 6.91-6.818c17.07-16.842 24.791-35.782 21.872-53.65-3.091-18.925-15.513-32.595-33.708-37.095-17.431-4.312-87.221-8.06-103.887-5.579m-554 5.002c-45.256 1.138-110.781 4.952-112.371 6.541-.254.255.175.477.954.494.78.017 4.792.47 8.917 1.007 58.005 7.546 238.965 8.858 254.36 1.844 17.437-7.945-51.232-12.415-151.86-9.886M296 460.669c-57.346 1.766-115 5.938-115 8.322 0 2.024 34.5 5.142 89.5 8.086 30.602 1.639 106.309 2.36 111.065 1.058 12.221-3.345 11.218-14.3-1.56-17.041-4.568-.979-57.34-1.246-84.005-.425m169 13.942c-88.745 32.497-84.994 30.361-84.986 48.389.025 62.05 42.984 168.511 86.204 213.633 10.336 10.791 6.933 11.165 59.444-6.538 48.675-16.41 51.187-17.593 45.665-21.515-14.264-10.131-37.22-43.064-54.086-77.594-24.894-50.965-39.419-102.627-39.64-140.986-.091-15.742-.556-19.126-2.601-18.919-.275.028-4.775 1.616-10 3.53m-250 50.504c-61.688 1.949-114.707 5.983-116.487 8.863-4.236 6.854 228.759 16.09 241.659 9.579 8.791-4.437 8.505-13.138-.573-17.405-4.499-2.115-5.388-2.149-51.838-1.998-25.994.085-58.736.517-72.761.961" fillRule="evenodd" />
          </svg>
          <h1 className="text-sm font-bold text-[#002E94] tracking-tight">
            Gesture Prediction
          </h1>
        </div>
        <div className="flex items-center gap-4">
          <div className="flex items-center gap-1.5">
            <span className="font-bold">WS Status:</span>
            <div className={`px-2 py-0.5 font-bold rounded-sm text-white ${wsStatus === 'CONNECTED' ? 'bg-[#388E3C]' : wsStatus === 'CONNECTING' ? 'bg-[#FFA000]' : 'bg-[#D32F2F]'
              }`}>
              {wsStatus}
            </div>
          </div>
          <div className="flex items-center gap-1.5">
            <span className="font-bold">ESP32 Sensor:</span>
            <div className="flex items-center gap-1">
              <span className={`w-3 h-3 rounded-full border border-gray-600 block ${sensorConnected ? 'bg-[#4CAF50] animate-pulse' : 'bg-[#9E9E9E]'
                }`} id="sensor-led"></span>
              <span className="font-bold text-[10px]">{sensorConnected ? 'ONLINE' : 'OFFLINE'}</span>
            </div>
          </div>
        </div>
      </header>

      {/* 2. Instruction Bar */}
      <section className="w-full max-w-5xl xp-outset py-2 px-3 mb-3 bg-[#FFFFE1] border-l-4 border-l-xp-blue flex items-center gap-2">
        <Radio className="w-4 h-4 text-xp-blue animate-pulse flex-shrink-0" />
        <span className="font-bold text-[#002E94]" id="instruction-txt">{instruction}</span>
      </section>

      {/* 3. Main Workspace Grid */}
      <div className="w-full max-w-5xl grid grid-cols-12 gap-3 mb-3">

        {/* Left Panel: Control Box & Telemetry Graph */}
        <div className="col-span-8 flex flex-col gap-3">

          {/* A. Compact Control Panel */}
          <div className="xp-outset p-3">
            <div className="xp-title-bar px-2 py-0.5 text-xs font-bold flex items-center justify-between mb-2">
              <span>Control Command Center</span>
              <Activity className="w-3.5 h-3.5" />
            </div>

            <div className="grid grid-cols-4 gap-2.5">
              <button
                id="connect-btn"
                onClick={connectWebSocket}
                disabled={wsStatus === 'CONNECTED' || wsStatus === 'CONNECTING'}
                className={`xp-button py-2 px-3 flex items-center justify-center gap-1.5 font-bold text-xs ${
                  wsStatus === 'CONNECTED' || wsStatus === 'CONNECTING' ? 'opacity-50 cursor-not-allowed' : 'hover:bg-[#FFF]'
                }`}
              >
                <svg viewBox="70 120 1225 575" className="w-5 h-5 text-[#7A7A7A]" fill="currentColor">
                  <path d={CONNECT_PATH} fillRule="evenodd" />
                </svg>
                CONNECT
              </button>

              <button
                id="record-btn"
                onClick={startRecording}
                disabled={isRecording || wsStatus !== 'CONNECTED' || !sensorConnected}
                className={`xp-button py-2 px-3 flex items-center justify-center gap-1.5 font-bold text-xs ${
                  isRecording || wsStatus !== 'CONNECTED' || !sensorConnected ? 'opacity-50 cursor-not-allowed' : 'hover:bg-[#FFF]'
                }`}
              >
                <svg viewBox="180 50 1020 695" className="w-5 h-5 text-[#D32F2F]" fill="currentColor">
                  <path d={RECORD_PATH} fillRule="evenodd" />
                </svg>
                RECORD
              </button>

              <button
                id="stop-btn"
                onClick={stopRecording}
                disabled={!isRecording || wsStatus !== 'CONNECTED'}
                className={`xp-button py-2 px-3 flex items-center justify-center gap-1.5 font-bold text-xs ${
                  !isRecording || wsStatus !== 'CONNECTED' ? 'opacity-50 cursor-not-allowed' : 'hover:bg-[#FFF]'
                }`}
              >
                <svg viewBox="130 55 1085 645" className="w-5 h-5 text-[#000000]" fill="currentColor">
                  <path d={STOP_PATH} fillRule="evenodd" />
                </svg>
                STOP
              </button>

              <button
                id="reset-btn"
                onClick={resetSystem}
                disabled={wsStatus !== 'CONNECTED'}
                className={`xp-button py-2 px-3 flex items-center justify-center gap-1.5 font-bold text-xs ${
                  wsStatus !== 'CONNECTED' ? 'opacity-50 cursor-not-allowed' : 'hover:bg-[#FFF]'
                }`}
              >
                <svg viewBox="100 100 1175 600" className="w-5 h-5 text-[#388E3C]" fill="currentColor">
                  <path d={RESET_PATH} fillRule="evenodd" />
                </svg>
                RESET
              </button>
            </div>

            {/* Recording Frame Progress Bar */}
            {isRecording && (
              <div className="mt-3">
                <div className="flex justify-between font-bold text-[10px] mb-1">
                  <span>Capturing Motion Window:</span>
                  <span>{recordedFrames} / 50 Frames ({Math.round(recordingProgress)}%)</span>
                </div>
                <div className="w-full bg-[#E0E0E0] h-4 rounded-sm border border-gray-400 overflow-hidden flex">
                  {/* XP Green segmented style progress */}
                  <div
                    className="bg-gradient-to-r from-[#7ED321] to-[#417505] h-full"
                    style={{ width: `${recordingProgress}%`, transition: 'width 0.1s ease-out' }}
                  ></div>
                </div>
              </div>
            )}
          </div>

          {/* B. Recorded Sensor Telemetry Panel */}
          <div className="xp-outset p-3 flex flex-col flex-grow min-h-[220px]">
            <div className="xp-title-bar px-2 py-0.5 text-xs font-bold flex items-center justify-between mb-2">
              <span>Recorded Sensor Telemetry</span>
              <Database className="w-3.5 h-3.5" />
            </div>

            <div className="xp-inset flex-grow overflow-y-auto max-h-[180px] bg-white border border-gray-400">
              <table className="w-full text-center border-collapse text-[10px]" style={{ fontFamily: 'monospace', borderTop: '1.5px solid black', borderBottom: '1.5px solid black' }}>
                <thead>
                  <tr style={{ borderBottom: '1px solid black' }}>
                    <th className="p-1 font-bold">Sr No</th>
                    <th className="p-1 font-bold">ax</th>
                    <th className="p-1 font-bold">ay</th>
                    <th className="p-1 font-bold">az</th>
                    <th className="p-1 font-bold">gx</th>
                    <th className="p-1 font-bold">gy</th>
                    <th className="p-1 font-bold">gz</th>
                    <th className="p-1 font-bold">timestamp</th>
                  </tr>
                </thead>
                <tbody>
                  {recordedTelemetry.length === 0 ? (
                    <tr>
                      <td colSpan="8" className="text-center py-8 text-gray-400 italic" style={{ fontFamily: 'Tahoma, Geneva, sans-serif' }}>
                        No telemetry recorded yet. Press RECORD to capture.
                      </td>
                    </tr>
                  ) : (
                    recordedTelemetry.map((item, index) => (
                      <tr 
                        key={index} 
                        style={index === recordedTelemetry.length - 1 ? { borderBottom: '1px solid black' } : {}}
                      >
                        <td className="p-1 text-gray-500 font-bold">{item.srNo}</td>
                        <td className="p-1">{item.ax !== undefined ? item.ax.toFixed(6) : '0.000000'}</td>
                        <td className="p-1">{item.ay !== undefined ? item.ay.toFixed(6) : '0.000000'}</td>
                        <td className="p-1">{item.az !== undefined ? item.az.toFixed(6) : '0.000000'}</td>
                        <td className="p-1">{item.gx !== undefined ? item.gx.toFixed(6) : '0.000000'}</td>
                        <td className="p-1">{item.gy !== undefined ? item.gy.toFixed(6) : '0.000000'}</td>
                        <td className="p-1">{item.gz !== undefined ? item.gz.toFixed(6) : '0.000000'}</td>
                        <td className="p-1">{item.timestamp}</td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>
          </div>

        </div>

        {/* Right Panel: Motion Drawing Canvas */}
        <div className="col-span-4 flex flex-col gap-3">
          <div className="xp-outset p-3 h-full flex flex-col">
            <div className="xp-title-bar px-2 py-0.5 text-xs font-bold flex items-center justify-between mb-2">
              <span>2D Gesture Trajectory</span>
              <Square className="w-3.5 h-3.5" />
            </div>

            <div className="xp-grid-bg relative flex-grow flex items-center justify-center p-0.5 min-h-[240px]">
              <canvas
                id="trajectory-canvas"
                ref={trajectoryCanvasRef}
                width={300}
                height={240}
                className="w-full h-full block"
              ></canvas>
            </div>
          </div>
        </div>

      </div>

      {/* 4. Telemetry prediction & Table panel */}
      <div className="w-full max-w-5xl grid grid-cols-12 gap-3 mb-3">

        {/* Prediction Analysis Board */}
        <div className="col-span-12 xp-outset p-3 flex flex-col">
          <div className="xp-title-bar px-2 py-0.5 text-xs font-bold flex items-center justify-between mb-2">
            <span>Prediction Analysis Board</span>
            <FileText className="w-3.5 h-3.5" />
          </div>

          {/* Large Live Status Meter */}
          <div className="xp-inset p-2 mb-3 bg-[#F5F5F5] grid grid-cols-2 border border-gray-400">
            <div className="flex flex-col justify-center">
              <span className="text-gray-600 font-bold text-[9px]">LATEST GESTURE:</span>
              <span id="prediction-name" className="text-2xl font-extrabold text-[#002E94]">{prediction.gesture}</span>
            </div>
            <div className="flex flex-col justify-center border-l border-gray-300 pl-3">
              <span className="text-gray-600 font-bold text-[9px]">CONFIDENCE ACCURACY:</span>
              <span id="prediction-conf" className="text-2xl font-extrabold text-[#388E3C]">
                {(prediction.confidence * 100).toFixed(1)}%
              </span>
              {/* Custom Confidence Bar */}
              <div className="w-full bg-gray-300 h-2 mt-1 rounded-sm border border-gray-400 overflow-hidden">
                <div
                  className={`h-full ${prediction.confidence >= 0.70 ? 'bg-[#4CAF50]' : 'bg-[#D32F2F]'}`}
                  style={{ width: `${prediction.confidence * 100}%` }}
                ></div>
              </div>
            </div>
          </div>

          {/* Predictions History Table */}
          <div className="flex-grow xp-inset overflow-y-auto max-h-[140px] bg-white border border-gray-400" style={{ minHeight: '140px' }}>
            <table id="prediction-table" className="w-full text-left border-collapse text-[10px]">
              <thead>
                <tr className="bg-[#ECE9D8] text-gray-700 font-bold sticky top-0 border-b border-gray-400">
                  <th className="p-1.5 border-r border-gray-300 w-12 text-center">Sr No</th>
                  <th className="p-1.5 border-r border-gray-300">Gesture Name</th>
                  <th className="p-1.5 border-r border-gray-300 w-24 text-center">Accuracy</th>
                  <th className="p-1.5 w-20 text-center">Status</th>
                </tr>
              </thead>
              <tbody>
                {predictionHistory.length === 0 ? (
                  <tr>
                    <td colSpan="4" className="text-center py-6 text-gray-400 italic">No gestures predicted yet.</td>
                  </tr>
                ) : (
                  predictionHistory.map((item, index) => (
                    <tr
                      key={index}
                      className={`border-b border-gray-200 ${index % 2 === 0 ? 'bg-white' : 'bg-[#F9F8F0]'}`}
                    >
                      <td className="p-1 border-r border-gray-200 text-center font-bold text-gray-500">{item.srNo}</td>
                      <td className="p-1 border-r border-gray-200 font-bold text-[#002E94]">{item.gesture}</td>
                      <td className="p-1 border-r border-gray-200 text-center font-bold text-[#388E3C]">{item.accuracy}</td>
                      <td className="p-1 text-center font-bold">
                        <span className={`px-2 py-0.5 rounded-sm text-[9px] text-white ${item.isPass ? 'bg-[#388E3C]' : 'bg-[#D32F2F]'}`}>
                          {item.status}
                        </span>
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </div>

      </div>



    </main>
  );
}
