import os
import time
import numpy as np
import logging
from datetime import datetime
from typing import Tuple, Dict, Any
from model_loader import ModelLoader

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("PredictionEngine")

class PredictionEngine:
    """
    Executes the real-time SVM machine learning inference pipeline
    and logs results to persistent output files.
    """
    def __init__(self, model_loader: ModelLoader, results_dir: str = "../Results"):
        self.loader = model_loader
        self.results_dir = results_dir
        
        self.inference_results_path = os.path.join(results_dir, "inference_results.txt")
        self.prediction_logs_path = os.path.join(results_dir, "prediction_logs.txt")
        
        # Ensure results directory exists
        os.makedirs(results_dir, exist_ok=True)
        self._initialize_log_files()

    def _initialize_log_files(self):
        """
        Creates log files and writes headers if they do not exist.
        """
        if not os.path.exists(self.inference_results_path):
            with open(self.inference_results_path, "w") as f:
                f.write("Timestamp,GestureName,Confidence,Status\n")
                
        if not os.path.exists(self.prediction_logs_path):
            with open(self.prediction_logs_path, "w") as f:
                f.write("Timestamp,InferenceTimeMs,PredictedIndex,PredictedLabel,Confidence,FeaturesVector\n")

    def predict(self, features: np.ndarray, is_stationary: bool) -> Tuple[str, float]:
        """
        Executes prediction using loaded models, applying scale normalization.
        Supports fallback "Rest" detection for stationary sensors.
        """
        start_time = time.time()
        
        # 1. Stationary Override Check
        if is_stationary:
            logger.info("Motion below threshold. Stationary rest state detected.")
            gesture_name = "Rest"
            confidence = 1.0
            self._log_prediction(gesture_name, confidence, features, start_time)
            return gesture_name, confidence

        try:
            # 2. Standardize Features
            features_reshaped = features.reshape(1, -1)
            features_scaled = self.loader.scaler.transform(features_reshaped)

            # 3. Model Inference (predict_proba for soft voting)
            probs = self.loader.ensemble.predict_proba(features_scaled)[0]
            pred_class_idx = int(np.argmax(probs))
            confidence = float(probs[pred_class_idx])

            # 4. Decode Label
            decoded_labels = self.loader.encoder.inverse_transform([pred_class_idx])
            gesture_name = str(decoded_labels[0])
            
            self._log_prediction(gesture_name, confidence, features, start_time, pred_class_idx)
            return gesture_name, confidence

        except Exception as e:
            logger.error(f"Prediction inference error: {e}", exc_info=True)
            return "Rest", 0.0

    def _log_prediction(self, label: str, confidence: float, features: np.ndarray, start_time: float, class_idx: int = -1):
        """
        Saves prediction details to log files.
        """
        duration_ms = (time.time() - start_time) * 1000
        timestamp_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        status = "Pass" if confidence >= 0.70 else "Fail"

        # Log to inference_results.txt (Simple table summary)
        try:
            with open(self.inference_results_path, "a") as f:
                f.write(f"{timestamp_str},{label},{confidence * 100:.1f}%,{status}\n")
        except Exception as e:
            logger.error(f"Failed to write to inference_results.txt: {e}")

        # Log to prediction_logs.txt (Detailed CSV log for debugging)
        features_str = ";".join([f"{val:.4f}" for val in features])
        try:
            with open(self.prediction_logs_path, "a") as f:
                f.write(f"{timestamp_str},{duration_ms:.2f},{class_idx},{label},{confidence:.4f},{features_str}\n")
        except Exception as e:
            logger.error(f"Failed to write to prediction_logs.txt: {e}")
            
        logger.info(f"✔ Prediction: {label} ({confidence * 100:.1f}%) | Latency: {duration_ms:.2f}ms | Status: {status}")
