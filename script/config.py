import yaml
from pathlib import Path
from typing import Dict

def load_config(config_path: str) -> Dict:
    with open(config_path, 'r') as f:
        return yaml.safe_load(f)

def save_config(config: Dict, config_path: str):
    with open(config_path, 'w') as f:
        yaml.dump(config, f, default_flow_style=False)
