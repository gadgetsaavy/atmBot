# Import required libraries for blockchain interaction, ML, and data processing
import networkx as nx
from web3 import Web3
import json
import time
import logging
import csv
import os
from decimal import Decimal
import pandas as pd
from sklearn.preprocessing import StandardScaler
import tensorflow as tf
from tensorflow.keras.models import Sequential
from tensorflow.keras.layers import Dense
from collections import deque
import numpy as np
import warnings
warnings.filterwarnings("ignore")

class ArbitrageAgent:
    def __init__(self, rpc_url, contract_address, private_key):
        """
        Initialize the ArbitrageAgent with blockchain connection parameters.
        
        Args:
            rpc_url (str): URL of the Ethereum RPC provider
            contract_address (str): Address of the flash arbitrage contract
            private_key (str): Private key for transaction signing
        """
        # --- Basic Setup ---
        self.contract_address = contract_address
        self.rpc_url = rpc_url  # Ethereum RPC URL for blockchain interaction
        self.private_key = private_key
        self.web3 = None  # Initialize Web3 provider to None
        self.account = None  # Initialize Ethereum account to None
        self.contract = None  # Initialize contract instance to None
        
        # --- Graph Setup ---
        self.arbitrage_graph = nx.DiGraph()  # Directed graph for tracking token relationships
        
        # --- ML Setup ---
        self.agent = TradingAgent()  # Initialize ML trading agent
        self.scaler = StandardScaler()  # Feature scaler for ML inputs
        self.memory = deque(maxlen=1000)  # Memory buffer for recent trades
        self.scaler_fitted = False  # Flag to track if scaler has been fitted
        
        # --- Logging Setup ---
        logging.basicConfig(
            level=logging.INFO, 
            format='%(asctime)s - %(levelname)s - %(message)s'
        )
        self.logger = logging.getLogger(__name__)
        
        # --- Initialize Web3 and Contract with Error Handling ---
        try:
            self.web3 = Web3(Web3.HTTPProvider(self.rpc_url))
            self.account = self.web3.eth.account.from_key(self.private_key)
            
            # Load contract ABI from JSON file
            with open("FlashArbitrage_ABI.json", 'r') as f:
                contract_abi = json.load(f)
            
            # Initialize contract instance
            self.contract = self.web3.eth.contract(
                address=self.contract_address, 
                abi=contract_abi
            )
            self.logger.info("Web3 connection and contract initialization successful.")
        except Exception as e:
            self.logger.error(f"Error initializing Web3 or contract: {str(e)}")
            raise  # Re-raise exception to prevent further execution if initialization fails

    def fetch_reserves(self):
        """
        Fetch token reserves from Uniswap/Sushiswap pools.
        Returns a dictionary of token pairs and their reserves.
        
        Returns:
            dict: Dictionary containing token pair reserves
        """
        try:
            # Get all token pairs from the contract
            token_pairs = self.contract.functions.getTokenPairs().call()
            reserves = {}
            
            # Fetch reserves for each token pair
            for token0, token1 in token_pairs:
                try:
                    # Get reserves for the pair
                    reserves[(token0, token1)] = self.contract.functions.getReserves(
                        token0, 
                        token1
                    ).call()
                    self.logger.info(f"Fetched reserves for {token0} - {token1}")
                except Exception as e:
                    self.logger.error(f"Error fetching reserves for {token0} - {token1}: {str(e)}")
                    continue
            return reserves
        except Exception as e:
            self.logger.error(f"Error fetching reserves: {str(e)}")
            return {}

    def build_graph(self):
        """
        Build the arbitrage graph using token pairs and their reserves.
        Uses log prices to prevent numerical overflow.
        
        Returns:
            bool: True if graph building was successful, False otherwise
        """
        try:
            # Clear existing graph
            self.arbitrage_graph.clear()
            
            # Get current reserves
            reserves = self.fetch_reserves()
            
            # Build graph with token pairs and their prices
            for (token0, token1), (reserve0, reserve1, _) in reserves.items():
                # Calculate log price to prevent overflow
                log_price = Decimal(reserve1) / Decimal(reserve0)
                log_price = log_price.ln()
                
                # Add edges in both directions with opposite weights
                self.arbitrage_graph.add_edge(
                    token0, 
                    token1, 
                    weight=-float(log_price)
                )
                self.arbitrage_graph.add_edge(
                    token1, 
                    token0, 
                    weight=float(log_price)
                )
            self.logger.info("Graph built successfully")
            return True
        except Exception as e:
            self.logger.error(f"Error building graph: {str(e)}")
            return False

    def detect_arbitrage(self):
        """
        Detect arbitrage opportunities using Bellman-Ford algorithm.
        Returns list of negative cycles.
        
        Returns:
            list: List of negative cycles in the graph
        """
        try:
            negative_cycles = []
            
            # Check each node as potential starting point
            for node in self.arbitrage_graph.nodes:
                try:
                    # Find negative cycles starting from this node
                    cycle = nx.find_negative_cycle(self.arbitrage_graph, source=node)
                    if cycle:
                        negative_cycles.append(cycle)
                except nx.NetworkXNoCycle:
                    continue
            return negative_cycles
        except Exception as e:
            self.logger.error(f"Error detecting arbitrage: {str(e)}")
            return []

    def get_current_state(self, path):
        """
        Get current state for ML agent.
        Features include:
        1. Available liquidity
        2. Current gas prices
        3. Historical price impact
        4. Path complexity
        
        Args:
            path (list): List of token addresses representing the trade path
            
        Returns:
            dict: Dictionary containing current state features
        """
        try:
            # Create state dictionary with current market conditions
            state = {
                'liquidity': self.get_path_liquidity(path),
                'gas_price': self.web3.eth.gasPrice,
                'price_impact': self.calculate_price_impact(path),
                'path_length': len(path)
            }
            return state
        except Exception as e:
            self.logger.error(f"Error getting current state: {str(e)}")
            return None

    def get_path_liquidity(self, path):
        """
        Calculate available liquidity for the path.
        
        Args:
            path (list): List of token addresses representing the trade path
            
        Returns:
            float: Total available liquidity along the path
        """
        try:
            total_liquidity = 0
            # Calculate total liquidity along the path
            for i in range(len(path) - 1):
                pair = (path[i], path[i + 1])
                if pair in self.arbitrage_graph.edges():
                    total_liquidity += self.arbitrage_graph.edges[pair]['weight']
            return total_liquidity
        except Exception as e:
            self.logger.error(f"Error calculating path liquidity: {str(e)}")
            return 0

    def calculate_price_impact(self, path):
        """
        Calculate expected price impact for the path.
        
        Args:
            path (list): List of token addresses representing the trade path
            
        Returns:
            float: Expected price impact along the path
        """
        try:
            impact = 0
            # Calculate cumulative price impact along the path
            for i in range(len(path) - 1):
                pair = (path[i], path[i + 1])
                if pair in self.arbitrage_graph.edges():
                    impact += self.arbitrage_graph.edges[pair]['weight']
            return impact
        except Exception as e:
            self.logger.error(f"Error calculating price impact: {str(e)}")
            return 0

    def execute_arbitrage(self, path):
        """
        Execute arbitrage with ML-optimized amount.
        
        Args:
            path (list): List of token addresses representing the trade path
            
        Returns:
            str: Transaction hash if successful, None otherwise
        """
        try:
            # Get current market state
            state = self.get_current_state(path)
            if state is None:
                self.logger.warning("Could not get current state. Aborting arbitrage.")
                return None
            
            # Get optimal trade amount from ML agent
            amount = self.agent.get_optimal_trade_amount(state)
            if amount is None:
                self.logger.warning("Could not get optimal trade amount. Aborting arbitrage.")
                return None
            
            # Prepare transaction
            tx = self.contract.functions.executeArbitrage(
                path,
                int(amount)  # Convert to integer for contract
            ).build_transaction({
                'from': self.account.address,
                'gas': 500000,
                'gasPrice': self.web3.to_wei('30', 'gwei'),
                'nonce': self.web3.eth.get_transaction_count(self.account.address),
            })
            
            # Sign and send transaction
            signed_tx = self.web3.eth.account.sign_transaction(tx, self.private_key)
            tx_hash = self.web3.eth.send_raw_transaction(signed_tx.rawTransaction)
            
            # Log trade data for ML training
            self.log_trade_data(path, amount, tx_hash)
            return tx_hash
        except Exception as e:
            self.logger.error(f"Error executing arbitrage: {str(e)}")
            return None

    def log_trade_data(self, path, amount, tx_hash):
        """
        Log trade data for ML training.
        
        Args:
            path (list): List of token addresses in the trade
            amount (float): Amount traded
            tx_hash (str): Transaction hash
        """
        try:
            # Open CSV file in append mode
            with open("arbitrage_logs.csv", "a", newline='') as f:
                writer = csv.writer(f)
                
                # Write header if file is new
                if f.tell() == 0:
                    writer.writerow(["path", "amount", "tx_hash", "gas_used", "profit"])
                
                # Write trade data
                writer.writerow([path, amount, tx_hash, 0, 0])
        except Exception as e:
            self.logger.error(f"Error logging trade data: {str(e)}")

    def train_model(self, epochs=10):
        """
        Train the model with historical data from arbitrage_logs.csv.
        
        Args:
            epochs (int): Number of training epochs
        """
        try:
            # Load historical data
            df = pd.read_csv("arbitrage_logs.csv")
            
            # Check if data exists
            if df.empty:
                self.logger.warning("No training data available in arbitrage_logs.csv.")
                return
            
            # Prepare training data
            states = []
            targets = []
            
            # Process each trade in the dataset
            for index, row in df.iterrows():
                path = eval(row['path'])  # Convert string to list
                amount = row['amount']
                state = self.get_current_state(path)
                
                # Skip invalid states
                if state is None:
                    self.logger.warning(f"Skipping training data due to None state for path: {path}")
                    continue
                
                # Add to training data
                states.append(list(state.values()))
                targets.append(amount)
            
            # Check if we have valid data
            if not states:
                self.logger.warning("No valid training data found after processing CSV.")
                return
            
            # Fit scaler if not already fitted
            if not self.scaler_fitted:
                self.scaler.fit(states)
                self.scaler_fitted = True
                self.logger.info("Scaler fitted with training data.")
            else:
                self.logger.info("Scaler already fitted, using existing scaler.")
            
            # Convert to numpy arrays
            states = np.array(states)
            targets = np.array(targets)
            
            # Check for dimension mismatch
            if states.shape[0] != targets.shape[0]:
                self.logger.error(f"Dimension mismatch: states shape {states.shape}, targets shape {targets.shape}")
                return
            
            # Scale states
            states_scaled = self.scaler.transform(states)
            
            # Train the model
            self.agent.train(states_scaled, targets)
            self.logger.info("Model training complete.")
        except FileNotFoundError:
            self.logger.warning("The file 'arbitrage_logs.csv' was not found. Skipping model training.")
        except Exception as e:
            self.logger.error(f"Error during model training: {str(e)}")

class TradingAgent:
    def __init__(self):
        """
        Initialize the TradingAgent with ML model and scaling components.
        """
        # Initialize ML model
        self.model = self.build_model()
        self.scaler = StandardScaler()
        self.memory = deque(maxlen=1000)  # Memory buffer for recent trades

    def build_model(self):
        """
        Build the neural network model for trade amount optimization.
        
        Returns:
            Sequential: Compiled Keras model
        """
        model = Sequential()
        model.add(Dense(64, input_dim=4, activation='relu'))  # Input layer (4 features)
        model.add(Dense(32, activation='relu'))  # Hidden layer
        model.add(Dense(1, activation='linear'))  # Output layer (trade amount)
        model.compile(optimizer='adam', loss='mse')
        return model

    def get_optimal_trade_amount(self, state):
        """
        Get optimal trade amount based on the given state.
        
        Args:
            state (dict): Dictionary containing market features
            
        Returns:
            float: Optimal trade amount
        """
        try:
            # Validate state is not None
            if state is None:
                print("Warning: Received None state in get_optimal_trade_amount.")
                return None
            
            # Validate state has correct keys
            if len(state) != 4:
                print(f"Warning: Unexpected state length ({len(state)}). Expected 4.")
                return None
            
            # Convert state to numpy array and reshape for prediction
            state_array = np.array(list(state.values())).reshape(1, -1)
            
            # Transform state using scaler
            state_scaled = self.scaler.transform(state_array)
            
            # Make prediction
            prediction = self.model.predict(state_scaled)
            
            # Return predicted trade amount
            return prediction[0][0]
        except Exception as e:
            print(f"Error in get_optimal_trade_amount: {e}")
            return None

    def train(self, states, targets):
        """
        Train the model with historical data.
        
        Args:
            states (list): List of state vectors
            targets (list): List of corresponding trade amounts
        """
        try:
            # Check if data exists
            if not states:
                print("Warning: No states data provided for training.")
                return
            
            # Convert to numpy arrays
            states = np.array(states)
            targets = np.array(targets)
            
            # Check for dimension mismatch
            if states.shape[0] != targets.shape[0]:
                print(f"Dimension mismatch: states shape {states.shape}, targets shape {targets.shape}")
                return
            
            # Scale states
            states_scaled = self.scaler.transform(states)
            
            # Train the model
            self.model.fit(states_scaled, targets, epochs=10, verbose=0)
            print("Model training completed successfully.")
        except Exception as e:
            print(f"Error during model training: {e}")
