import numpy as np
from typing import List, Dict, Optional, Tuple

class GestureBuffer:
    """
    Manages a sliding or discrete temporal window buffer of motion sensor frames,
    and extracts the 15 statistical features required for prediction.
    """
    def __init__(self, window_size: int = 50):
        self.window_size = window_size
        self.ax_buffer: List[float] = []
        self.ay_buffer: List[float] = []
        self.az_buffer: List[float] = []
        self.timestamps: List[int] = []

    def add_frame(self, ax: float, ay: float, az: float, timestamp: int):
        """
        Adds a single motion frame to the buffer.
        """
        self.ax_buffer.append(ax)
        self.ay_buffer.append(ay)
        self.az_buffer.append(az)
        self.timestamps.append(timestamp)

        # Maintain window size for sliding window
        if len(self.ax_buffer) > self.window_size:
            self.ax_buffer.pop(0)
            self.ay_buffer.pop(0)
            self.az_buffer.pop(0)
            self.timestamps.pop(0)

    def is_ready(self) -> bool:
        """
        Returns True if the buffer contains enough frames to run inference.
        """
        return len(self.ax_buffer) >= self.window_size

    def clear(self):
        """
        Resets/clears the buffer.
        """
        self.ax_buffer.clear()
        self.ay_buffer.clear()
        self.az_buffer.clear()
        self.timestamps.clear()

    def get_length(self) -> int:
        """
        Returns current buffer size.
        """
        return len(self.ax_buffer)

    def is_stationary(self, rest_threshold: float = 0.15) -> bool:
        """
        Checks if the sensor is stationary based on aggregate variance across all axes.
        Useful for override logic to detect the "Rest" gesture class.
        """
        if not self.is_ready():
            return False
            
        var_x = float(np.var(self.ax_buffer))
        var_y = float(np.var(self.ay_buffer))
        var_z = float(np.var(self.az_buffer))
        
        # Sum of variances
        total_var = var_x + var_y + var_z
        return total_var < rest_threshold

    def extract_features(self) -> Tuple[np.ndarray, Dict[str, float]]:
        """
        Extracts 15 statistical features from the current window buffer.
        Returns a NumPy array of shape (15,) and a dictionary of raw features.
        """
        if not self.is_ready():
            raise ValueError(f"Buffer size {len(self.ax_buffer)} is smaller than window size {self.window_size}")

        ax = np.array(self.ax_buffer)
        ay = np.array(self.ay_buffer)
        az = np.array(self.az_buffer)

        # Calculate statistics per axis
        mean_x, mean_y, mean_z = np.mean(ax), np.mean(ay), np.mean(az)
        std_x, std_y, std_z = np.std(ax, ddof=0), np.std(ay, ddof=0), np.std(az, ddof=0)
        max_x, max_y, max_z = np.max(ax), np.max(ay), np.max(az)
        min_x, min_y, min_z = np.min(ax), np.min(ay), np.min(az)
        var_x, var_y, var_z = np.var(ax), np.var(ay), np.var(az)

        # Assemble features list (MUST match order defined in gesture_features.pkl)
        features = [
            mean_x, mean_y, mean_z,
            std_x, std_y, std_z,
            max_x, max_y, max_z,
            min_x, min_y, min_z,
            var_x, var_y, var_z
        ]

        feature_names = [
            'ax_mean', 'ay_mean', 'az_mean',
            'ax_std', 'ay_std', 'az_std',
            'ax_max', 'ay_max', 'az_max',
            'ax_min', 'ay_min', 'az_min',
            'ax_var', 'ay_var', 'az_var'
        ]

        features_dict = dict(zip(feature_names, features))
        
        return np.array(features, dtype=float), features_dict
