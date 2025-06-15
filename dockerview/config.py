"""Configuration management for DockerView."""

import logging
import os
from pathlib import Path
from typing import Any, Dict

import yaml

logger = logging.getLogger("dockerview.config")

# Default configuration values
DEFAULT_CONFIG = {"log": {"max_lines": 2000, "tail": 200, "since": "15m"}}


class Config:
    """Configuration manager for DockerView."""

    def __init__(self):
        self.config = DEFAULT_CONFIG.copy()
        self.config_file = None
        self._load_config()

    def _get_config_path(self) -> Path:
        """Get the configuration file path."""
        # Check for config file in order of preference:
        # 1. Environment variable
        if os.environ.get("DOCKERVIEW_CONFIG"):
            return Path(os.environ["DOCKERVIEW_CONFIG"])

        # 2. Current directory
        local_config = Path("./dockerview.yaml")
        if local_config.exists():
            return local_config

        # 3. User config directory
        config_dir = Path.home() / ".config" / "dockerview"
        config_file = config_dir / "dockerview.yaml"

        # Create config directory if it doesn't exist
        if not config_dir.exists():
            config_dir.mkdir(parents=True, exist_ok=True)

        # Create default config if it doesn't exist
        if not config_file.exists():
            self._create_default_config(config_file)

        return config_file

    def _create_default_config(self, config_file: Path):
        """Create a default configuration file with comments."""
        default_config_content = """# DockerView Configuration File
# This file controls various settings for the DockerView application

# Log Display Settings
log:
  # Maximum number of log lines to keep in memory per container/stack
  # Higher values use more memory but allow viewing more history
  # Default: 2000
  max_lines: 2000
  
  # Number of log lines to initially fetch when viewing a container/stack
  # Lower values load faster but show less history
  # Default: 200
  tail: 200
  
  # Time range of logs to fetch (e.g., '15m', '1h', '24h')
  # Only logs from this time period will be shown initially
  # This significantly improves performance for long-running containers
  # Default: '15m'
  since: '15m'

# Note: You can also override these settings with environment variables:
# - DOCKERVIEW_LOG_MAX_LINES
# - DOCKERVIEW_LOG_TAIL
# - DOCKERVIEW_LOG_SINCE
"""
        try:
            config_file.write_text(default_config_content)
            logger.info(f"Created default configuration file at {config_file}")
        except Exception as e:
            logger.warning(f"Failed to create default config file: {e}")

    def _load_config(self):
        """Load configuration from file."""
        try:
            self.config_file = self._get_config_path()

            if self.config_file.exists():
                with open(self.config_file, "r") as f:
                    loaded_config = yaml.safe_load(f) or {}

                # Merge with defaults
                self._merge_config(self.config, loaded_config)
                logger.info(f"Loaded configuration from {self.config_file}")
        except Exception as e:
            logger.warning(f"Failed to load config file, using defaults: {e}")

    def _merge_config(self, base: Dict[str, Any], update: Dict[str, Any]):
        """Recursively merge configuration dictionaries."""
        for key, value in update.items():
            if key in base and isinstance(base[key], dict) and isinstance(value, dict):
                self._merge_config(base[key], value)
            else:
                base[key] = value

    def get(self, key: str, default: Any = None) -> Any:
        """Get a configuration value using dot notation (e.g., 'log.max_lines')."""
        # Check environment variable override first
        env_key = f"DOCKERVIEW_{key.upper().replace('.', '_')}"
        if env_key in os.environ:
            value = os.environ[env_key]
            # Try to convert to appropriate type
            try:
                if value.isdigit():
                    return int(value)
                elif value.lower() in ("true", "false"):
                    return value.lower() == "true"
            except:
                pass
            return value

        # Navigate through nested config
        keys = key.split(".")
        value = self.config

        for k in keys:
            if isinstance(value, dict) and k in value:
                value = value[k]
            else:
                return default

        return value

    def get_config_info(self) -> str:
        """Get information about the current configuration."""
        return f"Config file: {self.config_file or 'Using defaults'}"


# Global config instance
config = Config()
