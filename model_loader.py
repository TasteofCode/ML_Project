import os
import joblib
import logging
from typing import Tuple, List, Optional
from sklearn.ensemble import VotingClassifier
from sklearn.preprocessing import StandardScaler, LabelEncoder

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("ModelLoader")

class ModelLoader:
    """
    Handles loading, validation, and integrity checks for gesture recognition models.
    """
    def __init__(self, models_dir: str):
        self.models_dir = models_dir
        self.ensemble_path = os.path.join(models_dir, "stable_gesture_ensemble.pkl")
        self.scaler_path = os.path.join(models_dir, "gesture_scaler.pkl")
        self.features_path = os.path.join(models_dir, "gesture_features.pkl")
        self.encoder_path = os.path.join(models_dir, "gesture_encoder.pkl")
        
        self.ensemble: Optional[VotingClassifier] = None
        self.scaler: Optional[StandardScaler] = None
        self.features: Optional[List[str]] = None
        self.encoder: Optional[LabelEncoder] = None

    def load_all_models(self) -> bool:
        """
        Loads all model files, validates them, and returns True if successful, False otherwise.
        """
        try:
            logger.info("Initializing model loading process...")
            
            # 1. Load Feature List
            if not os.path.exists(self.features_path):
                raise FileNotFoundError(f"Missing features file: {self.features_path}")
            with open(self.features_path, "rb") as f:
                self.features = joblib.load(f)
            logger.info(f"Loaded features list. Size: {len(self.features)}. Features: {self.features}")

            # 2. Load Scaler
            if not os.path.exists(self.scaler_path):
                raise FileNotFoundError(f"Missing scaler file: {self.scaler_path}")
            with open(self.scaler_path, "rb") as f:
                self.scaler = joblib.load(f)
            logger.info("Loaded StandardScaler.")

            # 3. Load Ensemble Model
            if not os.path.exists(self.ensemble_path):
                raise FileNotFoundError(f"Missing ensemble model file: {self.ensemble_path}")
            with open(self.ensemble_path, "rb") as f:
                self.ensemble = joblib.load(f)
            logger.info("Loaded Ensemble Model (VotingClassifier).")

            # 4. Load Label Encoder
            if not os.path.exists(self.encoder_path):
                raise FileNotFoundError(f"Missing label encoder file: {self.encoder_path}")
            with open(self.encoder_path, "rb") as f:
                self.encoder = joblib.load(f)
            logger.info(f"Loaded LabelEncoder. Classes: {list(self.encoder.classes_)}")

            # 5. Validate integrity
            self._validate_integrity()
            logger.info("✔ All models loaded and validated successfully.")
            return True

        except Exception as e:
            logger.error(f"❌ Model loading failed: {e}", exc_info=True)
            self._load_fallback_mock_models()
            return False

    def _validate_integrity(self):
        """
        Validates the structure and attributes of loaded model files.
        """
        # Validate feature list size
        if len(self.features) != 15:
            raise ValueError(f"Features size mismatch. Expected 15 features, got {len(self.features)}")

        # Validate scaler features
        if getattr(self.scaler, "n_features_in_", None) != 15:
            raise ValueError(f"Scaler features dimension mismatch. Expected 15 features, got {self.scaler.n_features_in_}")

        # Validate model estimators and features
        if getattr(self.ensemble, "n_features_in_", None) != 15:
            raise ValueError(f"Ensemble model feature count mismatch. Expected 15 features, got {self.ensemble.n_features_in_}")

        if not hasattr(self.ensemble, "predict_proba"):
            raise ValueError("Ensemble model must support probability predictions (predict_proba).")

    def _load_fallback_mock_models(self):
        """
        Loads mock objects in case of missing or corrupted files, to prevent FastAPI crash.
        """
        logger.warning("⚠ Loading fallback mock model configuration due to errors.")
        # Mock features
        self.features = [
            'ax_mean', 'ay_mean', 'az_mean',
            'ax_std', 'ay_std', 'az_std',
            'ax_max', 'ay_max', 'az_max',
            'ax_min', 'ay_min', 'az_min',
            'ax_var', 'ay_var', 'az_var'
        ]
        
        # Mock LabelEncoder classes
        class MockEncoder:
            def __init__(self):
                self.classes_ = ["Circle", "Double Tap", "Figure 8", "Rectangle"]
            def inverse_transform(self, preds):
                mapping = {0: "Circle", 1: "Double Tap", 2: "Figure 8", 3: "Rectangle"}
                return [mapping.get(p, "Rest") for p in preds]
        self.encoder = MockEncoder()

        # Mock Scaler
        class MockScaler:
            def transform(self, X):
                return X  # Return unscaled features
        self.scaler = MockScaler()

        # Mock Ensemble Model
        class MockEnsemble:
            def __init__(self):
                self.classes_ = [0, 1, 2, 3]
            def predict(self, X):
                import numpy as np
                return np.zeros(X.shape[0], dtype=int)  # Always predict first class
            def predict_proba(self, X):
                import numpy as np
                probs = np.zeros((X.shape[0], 4))
                probs[:, 0] = 1.0  # 100% confidence for Mock
                return probs
        self.ensemble = MockEnsemble()
