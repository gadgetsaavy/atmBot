import numpy as np
from sklearn.preprocessing import StandardScaler
from tensorflow.keras.models import Sequential
from tensorflow.keras.layers import Dense
from collections import deque
import logging
from typing import List, Dict, Optional

class TradingAgent:
    def __init__(self):
        # Initialize ML model
        self.model = self._build_model()
        self.scaler = StandardScaler()
        self.memory = deque(maxlen=1000)
        
        # Initialize logging
        self.logger = logging.getLogger(__name__)
        
    def _build_model(self) -> Sequential:
        """Build the neural network model for trade amount optimization."""
        model = Sequential([
            Dense(64, input_dim=4, activation='relu'),  # Input layer (4 features)
            Dense(32, activation='relu'),              # Hidden layer
            Dense(1, activation='linear')              # Output layer (trade amount)
        ])
        model.compile(optimizer='adam', loss='mse')
        return model
    
    def get_optimal_trade_amount(self, state: Dict) -> float:
        """Get optimal trade amount based on the given state."""
        try:
            # Ensure state is valid
            if state is None:
                self.logger.warning("Received None state in get_optimal_trade_amount")
                return 0.0
            
            # Convert state to numpy array and scale
            state_array = np.array(list(state.values())).reshape(1, -1)
            scaled_state = self.scaler.transform(state_array)
            
            # Make prediction
            prediction = self.model.predict(scaled_state)
            return max(0.0, prediction[0][0])
            
        except Exception as e:
            self.logger.error(f"Error in get_optimal_trade_amount: {str(e)}")
            return 0.0
    
    def train(self, states: List[Dict], targets: List[float]) -> None:
        """Train the model with historical data."""
        try:
            # Convert lists to numpy arrays
            states_array = np.array([list(state.values()) for state in states])
            targets_array = np.array(targets)
            
            # Check for mismatched dimensions
            if states_array.shape[0] != targets_array.shape[0]:
                self.logger.error(f"Dimension mismatch: states shape {states_array.shape}, targets shape {targets_array.shape}")
                return
            
            # Scale the states
            scaled_states = self.scaler.fit_transform(states_array)
            
            # Train the model
            self.model.fit(
                scaled_states,
                targets_array,
                epochs=10,
                batch_size=32,
                verbose=0
            )
            
            self.logger.info("Model training completed successfully")
            
        except Exception as e:
            self.logger.error(f"Error during model training: {str(e)}")