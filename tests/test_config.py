"""Tests for the configuration management module."""

import os
import tempfile
from pathlib import Path
from unittest.mock import patch, Mock, mock_open

import pytest
import yaml

from dockerview.config import Config, DEFAULT_CONFIG


class TestConfig:
    """Test cases for the Config class."""

    def test_default_config_values(self):
        """Test that default configuration values are loaded correctly."""
        # Save current directory and change to temp dir to avoid local config files
        original_cwd = os.getcwd()
        with tempfile.TemporaryDirectory() as tmpdir:
            os.chdir(tmpdir)
            try:
                # Clear environment variables
                with patch.dict(os.environ, {}, clear=True):
                    config = Config()
                    
                    # Check default values (from DEFAULT_CONFIG)
                    assert config.get("log.max_lines") == 2000
                    assert config.get("log.tail") == 200
                    assert config.get("log.since") == "15m"
            finally:
                os.chdir(original_cwd)

    def test_get_with_default(self):
        """Test the get method with default values."""
        original_cwd = os.getcwd()
        with tempfile.TemporaryDirectory() as tmpdir:
            os.chdir(tmpdir)
            try:
                with patch.dict(os.environ, {}, clear=True):
                    config = Config()
                    
                    # Test getting non-existent key with default
                    assert config.get("non.existent.key", "default_value") == "default_value"
                    
                    # Test getting existing key ignores default
                    assert config.get("log.max_lines", 9999) == 2000  # Should return actual value, not default param
            finally:
                os.chdir(original_cwd)

    def test_environment_variable_override(self):
        """Test that environment variables override config file values."""
        original_cwd = os.getcwd()
        with tempfile.TemporaryDirectory() as tmpdir:
            os.chdir(tmpdir)
            try:
                with patch.dict(os.environ, {
                    "DOCKERVIEW_LOG_MAX_LINES": "5000",
                    "DOCKERVIEW_LOG_TAIL": "500",
                    "DOCKERVIEW_LOG_SINCE": "2h"
                }):
                    config = Config()
                    
                    # Environment variables should override defaults
                    assert config.get("log.max_lines") == 5000
                    assert config.get("log.tail") == 500
                    assert config.get("log.since") == "2h"
            finally:
                os.chdir(original_cwd)

    def test_load_custom_config_file(self):
        """Test loading configuration from a custom YAML file."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            custom_config = {
                "log": {
                    "max_lines": 3000,
                    "tail": 300,
                    "since": "30m"
                }
            }
            yaml.dump(custom_config, f)
            config_path = f.name
        
        try:
            with patch.dict(os.environ, {"DOCKERVIEW_CONFIG": config_path}):
                config = Config()
                
                # Custom values should be loaded
                assert config.get("log.max_lines") == 3000
                assert config.get("log.tail") == 300
                assert config.get("log.since") == "30m"
        finally:
            os.unlink(config_path)

    def test_merge_config(self):
        """Test the configuration merge functionality."""
        original_cwd = os.getcwd()
        with tempfile.TemporaryDirectory() as tmpdir:
            os.chdir(tmpdir)
            try:
                with patch.dict(os.environ, {}, clear=True):
                    config = Config()
                    
                    base = {"a": {"b": 1, "c": 2}, "d": 3}
                    update = {"a": {"b": 10, "e": 4}, "f": 5}
                    
                    config._merge_config(base, update)
                    
                    # Check merged values
                    assert base["a"]["b"] == 10  # Updated
                    assert base["a"]["c"] == 2   # Preserved
                    assert base["a"]["e"] == 4   # Added
                    assert base["d"] == 3        # Preserved
                    assert base["f"] == 5        # Added
            finally:
                os.chdir(original_cwd)

    def test_type_conversion_from_env(self):
        """Test that environment variable values are converted to appropriate types."""
        original_cwd = os.getcwd()
        with tempfile.TemporaryDirectory() as tmpdir:
            os.chdir(tmpdir)
            try:
                with patch.dict(os.environ, {
                    "DOCKERVIEW_LOG_MAX_LINES": "1234",
                    "DOCKERVIEW_SOME_BOOL": "true",
                    "DOCKERVIEW_ANOTHER_BOOL": "false",
                    "DOCKERVIEW_SOME_STRING": "hello world"
                }):
                    config = Config()
                    
                    # Integer conversion
                    assert config.get("log.max_lines") == 1234
                    assert isinstance(config.get("log.max_lines"), int)
                    
                    # Boolean conversion
                    assert config.get("some.bool") is True
                    assert config.get("another.bool") is False
                    
                    # String remains string
                    assert config.get("some.string") == "hello world"
                    assert isinstance(config.get("some.string"), str)
            finally:
                os.chdir(original_cwd)

    def test_config_file_creation(self):
        """Test that default config file is created when it doesn't exist."""
        original_cwd = os.getcwd()
        with tempfile.TemporaryDirectory() as tmpdir:
            os.chdir(tmpdir)  # Change to temp dir to avoid local config
            try:
                # Clear environment and set HOME to temp directory
                with patch.dict(os.environ, {'HOME': tmpdir}, clear=True):
                    config = Config()
                    
                    # Check that config file was created
                    config_path = Path(tmpdir) / '.config' / 'dockerview' / 'dockerview.yaml'
                    assert config_path.exists()
                    
                    # Check file contents
                    content = config_path.read_text()
                    assert "DockerView Configuration File" in content
                    assert "max_lines: 2000" in content
                    assert "tail: 200" in content
                    assert "since: '15m'" in content
            finally:
                os.chdir(original_cwd)