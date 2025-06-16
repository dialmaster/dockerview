# dockerview

An interactive terminal dashboard for monitoring and managing Docker Compose environments.
This is designed to replicate, somewhat, the main UI view from Docker Desktop.

## Overview

dockerview is a modern terminal user interface (TUI) for real-time monitoring and management of Docker containers and Docker Compose stacks. It provides an intuitive, keyboard-driven interface for viewing container status, resource usage, logs, and container management.

## Screenshots

![dockerview_shot1](https://github.com/user-attachments/assets/2aa27bdf-345f-43dd-9b03-28843ffb72a2)
![dockerview_shot2](https://github.com/user-attachments/assets/87a61238-33d5-4f2a-9c17-58f3b34c5815)

## Quick Start

### Prerequisites

- Python 3.8 or higher
- Docker Engine installed and running
- Docker Compose v2 (the `docker compose` command)
- Unix-like terminal (Linux, macOS, or WSL2 on Windows)
- No Docker CLI required - dockerview uses the Docker SDK directly

**Important:** dockerview must be run on the same filesystem where your Docker Compose files are located. It cannot currently monitor remote Docker instances.

### Installation and Usage

```bash
# Clone the repository
git clone https://github.com/dialmaster/dockerview.git
cd dockerview

# Run dockerview (automatically installs dependencies)
./start.sh
```

That's it! The `start.sh` script will handle dependency installation via Poetry automatically.

### Start Script Options

```bash
./start.sh           # Run normally
./start.sh -d        # Run with debug logging enabled
./start.sh --debug   # Same as -d
./start.sh -h        # Show help
./start.sh --help    # Show help
```

## Configuration

dockerview supports configuration via a YAML file to customize various settings, particularly for log viewing performance.

### Configuration File Location

dockerview looks for configuration files in the following order:
1. Path specified in `DOCKERVIEW_CONFIG` environment variable
2. `./dockerview.yaml` in the current directory (a default file is provided)
3. `~/.config/dockerview/dockerview.yaml` (created automatically with defaults if not found)

A default `dockerview.yaml` configuration file is included in the repository that you can customize.

### Configuration Options

The default configuration file contains:

```yaml
# DockerView Configuration File
# This file controls various settings for the DockerView application

# Log Display Settings
log:
  # Maximum number of log lines to keep in memory per container/stack
  # Higher values use more memory but allow viewing more history
  # Default: 4000
  max_lines: 4000

  # Number of log lines to initially fetch when viewing a container/stack
  # Lower values load faster but show less history
  # Default: 400
  tail: 400

  # Time range of logs to fetch (e.g., '15m', '1h', '24h')
  # Only logs from this time period will be shown initially
  # This significantly improves performance for long-running containers
  # Default: '30m'
  since: '30m'
```

### Environment Variable Overrides

You can override any configuration value using environment variables:
- `DOCKERVIEW_LOG_MAX_LINES` - Override `log.max_lines`
- `DOCKERVIEW_LOG_TAIL` - Override `log.tail`
- `DOCKERVIEW_LOG_SINCE` - Override `log.since`

Example:
```bash
export DOCKERVIEW_LOG_TAIL=500
export DOCKERVIEW_LOG_SINCE=1h
./start.sh
```

### Performance Tuning

The log settings significantly impact performance when viewing containers with extensive log output:

- **For faster initial load times**: Use lower `tail` values (e.g., 100-200) and shorter `since` durations (e.g., '5m', '15m')
- **For more log history**: Increase `tail` (e.g., 1000) and `since` (e.g., '1h', '24h'), but expect slower initial loading
- **Memory usage**: The `max_lines` setting caps the total lines kept in memory. Lower values use less memory but limit scrollback

When no logs are found within the configured time range, dockerview will display an informative message explaining the configuration settings and continue waiting for new logs.

## Keyboard Shortcuts

### Navigation
- `↑/↓`: Navigate through containers and stacks
- `←/→`: Collapse/expand stacks
- `Tab`: Switch focus between panes
- `q`: Quit the application

### Container/Stack Management
- `s`: Start selected container or stack
- `t`: Stop selected container or stack
- `e`: Restart selected container or stack
- `u`: Recreate selected container or stack (docker compose up -d)

### Log Viewer
- Click and drag: Select text in log viewer
- Right-click: Copy selected text to clipboard
- Filter box: Type to filter log entries in real-time
- Auto-follow checkbox: Toggle automatic scrolling of new log entries

## Features

- Real-time monitoring of Docker containers and Docker Compose stacks
- Interactive terminal interface with keyboard navigation
- Collapsible/expandable Docker Compose stack views
- Live resource usage statistics (CPU, Memory, PIDs)
- Container port mapping display
- Split-pane log viewer with real-time log streaming
- Container and stack management (start/stop/restart/recreate)
- Log filtering and auto-follow functionality
- Text selection and clipboard support in log viewer
- Status bar with detailed selection information
- Low system resource footprint
- Cross-platform support (Linux, macOS, Windows)
- Debug mode with detailed logging

## Manual Installation

If you prefer to install manually or the start script doesn't work:

```bash
# Install Poetry if not already installed
pip install poetry

# Install dependencies and create virtual environment
poetry install

# Activate the virtual environment
poetry shell

# Run dockerview
python -m dockerview
```

### Debug Mode

To enable debug mode with detailed logging:

```bash
# Using the start script (recommended)
./start.sh -d

# Or manually
export DOCKERVIEW_DEBUG=1
python -m dockerview
```

### WSL2 Clipboard Support

If you're running dockerview in WSL2 and want to use the clipboard functionality (right-click copy in log pane), you may need to install `xclip`:

```bash
sudo apt-get install xclip
```

This is optional - dockerview will attempt to use PowerShell's clipboard integration first, but xclip provides a fallback.

## Limitations and Known Issues

- **Local Filesystem Only**: dockerview must be run on the same filesystem where your Docker Compose files are located. Remote Docker daemon monitoring is not currently supported.
- **Docker Compose v2**: Requires Docker Compose v2 (the `docker compose` command, not the older `docker-compose`).
- **Terminal Requirements**: Best experience in modern terminal emulators with full mouse and color support.
- **Large Deployments**: Performance may degrade with hundreds of containers; optimizations are ongoing.

## Technical Design

### Architecture

dockerview is built using Python with the following core components:

1. **UI Layer** (Textual)
   - Main dashboard view with collapsible stack sections
   - Container detail rows with resource usage information
   - Split-pane log viewer with real-time streaming
   - Status bar for selection information
   - Error display for showing error messages
   - Interactive controls for log filtering and auto-follow
   - Modal dialogs for actions and confirmations

2. **Docker Integration Layer** (docker-py SDK)
   - Direct SDK integration without Docker CLI dependency
   - Real-time container statistics collection using concurrent threading
   - Docker Compose stack detection and grouping
   - Container port mapping display
   - Non-blocking container and stack operations (start/stop/restart/recreate)
   - Real-time log streaming with configurable time ranges and tail limits
   - Event monitoring for container state changes
   - Thread-safe concurrent operations for improved performance

3. **State Management**
   - Container and stack state tracking
   - User interface state (selections, expanded/collapsed sections)
   - Performance optimizations for handling many containers

### Data Flow

Docker Engine <-> docker-py SDK <-> DockerManager (with threading) <-> UI Components

### Key Components

- **DockerViewApp**: Main Textual application class with keyboard bindings for container management
- **ContainerList**: Navigable list of containers with real-time stats, now with separate sections for Docker networks and Compose stacks
- **StackHeader**: Collapsible headers for Docker Compose stacks
- **NetworkHeader**: Separate section headers for Docker networks
- **StatusBar**: Displays detailed information about the selected container or stack
- **DockerManager**: Handles direct Docker SDK integration with concurrent operations:
  - Thread-based non-blocking container operations
  - Parallel stats collection for all containers
  - Multi-stream log aggregation for stacks
- **LogPane**: Split-pane view with enhanced log streaming:
  - Real-time filtering with proper empty filter handling
  - Session-based log streaming to prevent duplicates
  - Configurable time ranges and tail limits
- **StateManager**: Dedicated state management component

## Development

### Setting Up Development Environment

```bash
# Clone the repository
git clone https://github.com/dialmaster/dockerview.git
cd dockerview

# Install dependencies
make install
# or
poetry install

# Install pre-commit hooks (recommended)
poetry run pre-commit install
```

### Code Quality and Testing

dockerview uses automated tools to maintain code quality:

- **Black**: Code formatting
- **isort**: Import sorting
- **pytest**: Unit testing
- **pre-commit**: Git hooks for automatic checks

#### Using Make Commands

The project includes a Makefile for common development tasks:

```bash
make help       # Show all available commands
make format     # Auto-format code with black and isort
make lint       # Check code formatting without changes
make test       # Run unit tests
make check      # Run all checks (lint + test)
make all        # Format code and run tests
make clean      # Remove cache files
```

#### Manual Commands

If you prefer running commands directly:

```bash
# Format code
poetry run black dockerview/
poetry run isort dockerview/

# Check formatting
poetry run black --check dockerview/
poetry run isort --check-only dockerview/

# Run tests
poetry run pytest
poetry run pytest -v  # Verbose output

# Run pre-commit on all files
poetry run pre-commit run --all-files
```

### CI/CD

GitHub Actions automatically runs on all pull requests and pushes to main:

- Tests on Python 3.8 (minimum supported version)
- Code formatting checks (black and isort)
- Unit test execution

All checks must pass before merging pull requests.

### Contributing Guidelines

1. **Before committing**: Run `make check` to ensure code passes all checks
2. **Code style**: Code is automatically formatted with black (line length 88)
3. **Imports**: Organized with isort using the black profile
4. **Pre-commit hooks**: Automatically run formatting and checks on commit
5. **Testing**: Add tests for new features and ensure existing tests pass

### Project Structure

- `dockerview/`: Main package directory
  - `app.py`: Main application and UI layout
  - `docker_mgmt/`: Docker integration layer
  - `ui/`: UI components (containers list, log pane, etc.)
  - `config.py`: Configuration management
- `tests/`: Unit tests
- `pyproject.toml`: Poetry configuration and tool settings
- `Makefile`: Development task automation
- `.pre-commit-config.yaml`: Pre-commit hook configuration
- `.github/workflows/`: CI/CD configuration