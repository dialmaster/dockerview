import logging
import queue
import re
import threading
from collections import deque

import docker
from rich.text import Text
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical
from textual.events import MouseDown
from textual.widgets import Checkbox, Input, Label, Select, Static, TextArea

from ...config import config
from ...utils.clipboard import copy_to_clipboard_async

logger = logging.getLogger("dockerview.log_pane")

# ANSI escape code pattern for stripping color codes
ANSI_ESCAPE_PATTERN = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")


def strip_ansi_codes(text: str) -> str:
    """Strip ANSI escape codes from text.

    Args:
        text: The text containing ANSI codes

    Returns:
        The text with ANSI codes removed
    """
    return ANSI_ESCAPE_PATTERN.sub("", text)


class LogTextArea(TextArea):
    """Custom TextArea that handles right-click to copy."""

    def on_mouse_down(self, event: MouseDown) -> None:
        """Handle mouse down events for right-click copy."""
        if event.button == 3:
            # Check if there's selected text
            selection = self.selected_text
            if selection:
                # Define callback to show notification from main thread
                def on_copy_complete(success):
                    if success:
                        logger.info(
                            f"Copied {len(selection)} characters to clipboard via right-click"
                        )
                        # Use call_from_thread to ensure notification happens on main thread
                        self.app.call_from_thread(
                            self.app.notify,
                            "Text copied to clipboard",
                            severity="information",
                            timeout=1,
                        )
                    else:
                        logger.error("Failed to copy to clipboard")
                        # Show error notification from main thread
                        self.app.call_from_thread(
                            self.app.notify,
                            "Failed to copy to clipboard. Please install xclip or pyperclip.",
                            severity="error",
                            timeout=3,
                        )

                # Copy in background thread
                copy_to_clipboard_async(selection, on_copy_complete)
                # Prevent the right-click from starting a new selection
                return

        # For non-right-clicks, check if parent has the method before calling it
        if hasattr(super(), "on_mouse_down"):
            super().on_mouse_down(event)


class LogPane(Vertical):
    """A pane that displays real-time Docker logs for selected containers or stacks."""

    BINDINGS = [
        # Use different keybinding to avoid conflict with app's Ctrl+C (quit)
        Binding("ctrl+shift+c", "copy_selection", "Copy selected text", show=False),
        Binding("ctrl+a", "select_all", "Select all text", show=False),
    ]

    DEFAULT_CSS = """
    LogPane {
        width: 50% !important;
        max-width: 50% !important;
        height: 100%;
        padding: 0;
        border-left: solid $primary-darken-1;
        background: $surface-darken-2;
        overflow-y: auto;
    }

    LogPane > Static.log-header {
        background: $primary-darken-1;
        color: white !important;
        text-align: center;
        height: 1;
        text-style: bold;
        padding: 0 1;
        border: none;
        dock: top;
    }

    .log-controls {
        height: 5;
        max-height: 5 !important;
        padding-top: 1;
        padding-bottom: 1;
        background: $surface;
        margin-top: 1;
        dock: top;
    }

    .log-controls-label {
        margin-top: 1;
        margin-left: 2;
    }

    .log-controls-search {
        height: 4;
        max-height: 4 !important;
        padding: 0 1;
        background: $surface;
        margin-top: 6;
        dock: top;
    }


    /* Container for the middle content, this contains the log display and the no selection display */
    .log-content-container {
        min-height: 1fr;  /* Fill remaining space */
        width: 100%;
        overflow: auto;
    }

    .no-selection {
        height: 100%;
        text-align: center;
        color: $text-muted;
        width: 100%;
        padding: 0 0;
        content-align: center middle;
        background: $surface-darken-2;
        border: none;
    }

    .log-display {
        height: 100%;  /* Fill parent container */
        background: $surface-darken-1;
        padding: 0 1;
        border: none;
        display: none;
    }

    .log-display:focus {
        border: none;
    }

    /* TextArea specific styling */
    .log-display .text-area--cursor {
        background: $primary;
        color: $text;
    }

    .log-display .text-area--selection {
        background: $primary-lighten-1;
    }

    #tail-select {
        width: 40%;
        height: 3;
        margin: 0 1 0 0;
    }

    #since-select {
        width: 40%;
        height: 3;
        margin: 0 1 0 0;
    }

    #search-input {
        width: 70%;
        height: 3;
        margin: 0 1 0 0;
    }

    #auto-follow-checkbox {
        width: 30%;
        height: 3;
        padding: 0 1;
        content-align: center middle;
    }
    """

    def __init__(self):
        """Initialize the log pane."""
        super().__init__(id="log-pane")

        # State management
        self.current_item = None  # ("container", id) or ("stack", name)
        self.current_item_data = None
        self.search_filter = ""
        self.auto_follow = True

        # Performance optimization: Use deque with maxlen to cap memory usage
        self.MAX_LINES = config.get("log.max_lines", 2000)
        self.all_log_lines = deque(
            maxlen=self.MAX_LINES
        )  # Store all log lines for filtering
        self.filtered_line_count = 0  # Track number of lines matching filter

        # Log tail and since configuration
        self.LOG_TAIL = str(config.get("log.tail", 200))
        self.LOG_SINCE = config.get("log.since", "15m")

        # Track if we've received any logs yet
        self.initial_log_check_done = False
        self.waiting_for_logs = False
        self.showing_no_logs_message = (
            False  # Track when we're showing the "no logs found" message
        )

        # Docker client for SDK streaming
        try:
            self.docker_client = docker.from_env()
        except Exception as e:
            logger.error(f"Failed to initialize Docker client: {e}")
            self.docker_client = None

        # Threading for log streaming
        self.log_thread = None
        self.log_queue = queue.Queue()
        self.stop_event = threading.Event()
        self.log_session_id = 0  # Track log sessions to prevent mixing old/new logs

        # UI components
        self.header = None
        self.log_display = None
        self.no_selection_display = None
        self.search_input = None
        self.auto_follow_checkbox = None
        self.content_container = None
        self.tail_select = None
        self.since_select = None

        # Timer for processing log queue
        self.queue_timer = None

    def compose(self):
        """Compose the log pane UI."""
        # Create the header
        self.header = Static("📋 Log Pane - No Selection", classes="log-header")

        # Create search and auto-follow controls
        self.search_input = Input(placeholder="Filter logs...", id="search-input")
        self.auto_follow_checkbox = Checkbox(
            "Auto-follow", self.auto_follow, id="auto-follow-checkbox"
        )

        # Create dropdown options for log settings
        tail_options = [
            ("50 lines", "50"),
            ("100 lines", "100"),
            ("200 lines", "200"),
            ("400 lines", "400"),
            ("800 lines", "800"),
            ("1600 lines", "1600"),
            ("3200 lines", "3200"),
            ("6400 lines", "6400"),
            ("12800 lines", "12800"),
        ]

        since_options = [
            ("5 minutes", "5m"),
            ("10 minutes", "10m"),
            ("15 minutes", "15m"),
            ("30 minutes", "30m"),
            ("1 hour", "1h"),
            ("2 hours", "2h"),
            ("4 hours", "4h"),
            ("8 hours", "8h"),
            ("24 hours", "24h"),
            ("48 hours", "48h"),
        ]

        # Create dropdowns with current values selected
        # If current value is not in options, add it
        if not any(opt[1] == self.LOG_TAIL for opt in tail_options):
            tail_options.insert(0, (f"{self.LOG_TAIL} lines", self.LOG_TAIL))

        self.tail_select = Select(
            options=tail_options,
            value=self.LOG_TAIL,
            id="tail-select",
            classes="log-setting",
        )

        # If current value is not in options, add it
        if not any(opt[1] == self.LOG_SINCE for opt in since_options):
            since_options.insert(0, (f"{self.LOG_SINCE}", self.LOG_SINCE))

        self.since_select = Select(
            options=since_options,
            value=self.LOG_SINCE,
            id="since-select",
            classes="log-setting",
        )

        # Create the no-selection display
        self.no_selection_display = Static(
            Text.assemble(
                ("Select a container or stack to view logs\n\n", "dim"),
                "• Click on a container to see its logs\n",
                "• Click on a stack header to see logs for all containers in the stack\n",
                "• Use the search box to filter log entries\n",
                "• Toggle auto-follow to stop/start automatic scrolling\n",
                "• Adjust log settings to change time range and line count\n\n",
                ("Text Selection:\n", "bold"),
                "• Click and drag with mouse to select text\n",
                "• Right-click on selected text to copy",
            ),
            classes="no-selection",
        )
        self.no_selection_display.display = True

        # Create the log display with LogTextArea for proper text selection and right-click copy
        self.log_display = LogTextArea(
            read_only=True,
            classes="log-display",
            tab_behavior="focus",  # Don't insert tabs, just move focus
        )
        self.log_display.display = False
        # TextArea is focusable by default

        # Yield widgets in order: header, controls, content
        yield self.header

        # First control row - log settings
        yield Horizontal(
            Label("Show last:", classes="log-controls-label"),
            self.tail_select,
            Label("From past:", classes="log-controls-label"),
            self.since_select,
            classes="log-controls",
        )

        # Second control row - search and auto-follow
        yield Horizontal(
            self.search_input, self.auto_follow_checkbox, classes="log-controls-search"
        )

        # Content container that will expand to fill space
        yield Container(
            self.no_selection_display, self.log_display, classes="log-content-container"
        )

    def on_mount(self):
        """Set up the log pane after mounting."""
        # Get reference to content container if needed
        self.content_container = self.query_one(".log-content-container")
        # Start the queue processing timer
        self.queue_timer = self.set_interval(0.1, self._process_log_queue)

    def on_unmount(self):
        """Clean up when unmounting."""
        self._stop_logs()
        if self.queue_timer:
            self.queue_timer.stop()

    def update_selection(self, item_type: str, item_id: str, item_data: dict):
        """Update the log pane with a new selection.

        Args:
            item_type: Type of item ("container" or "stack")
            item_id: ID of the item
            item_data: Dictionary containing item information
        """

        # Check if this is the same item that's already selected
        if self.current_item == (item_type, item_id):
            # If it's the same container, check if status changed
            if item_type == "container" and self.current_item_data:
                old_status = self.current_item_data.get("status", "").lower()
                new_status = item_data.get("status", "").lower()

                # Check if container stopped
                if ("running" in old_status or "up" in old_status) and (
                    "exited" in new_status or "stopped" in new_status
                ):
                    # Container was stopped, update the display
                    self._handle_status_change(item_data)
                    return

                # Check if container started
                elif ("exited" in old_status or "stopped" in old_status) and (
                    "running" in new_status or "up" in new_status
                ):
                    # Container was started, resume logs
                    self._handle_status_change(item_data)
                    return

            # Update the stored data but don't restart logs for the same selection
            self.current_item_data = item_data
            return

        # Update state
        self.current_item = (item_type, item_id)
        self.current_item_data = item_data

        # Update header
        if item_type == "container":
            self.header.update(
                f"📋 Log Pane - Container: {item_data.get('name', item_id)}"
            )
        elif item_type == "stack":
            self.header.update(f"📋 Log Pane - Stack: {item_data.get('name', item_id)}")
        elif item_type == "network":
            self.header.update(
                f"📋 Log Pane - Network: {item_data.get('name', item_id)}"
            )
            # Networks don't have logs, show a message
            self._show_no_logs_message_for_item_type("Networks")
            return
        elif item_type == "image":
            self.header.update(f"📋 Log Pane - Image: {item_id[:12]}")
            # Images don't have logs, show a message
            self._show_no_logs_message_for_item_type("Images")
            return
        elif item_type == "volume":
            self.header.update(
                f"📋 Log Pane - Volume: {item_data.get('name', item_id)}"
            )
            # Volumes don't have logs, show a message
            self._show_no_logs_message_for_item_type("Volumes")
            return
        else:
            self.header.update("📋 Log Pane - Unknown Selection")

        # Show log display, hide no-selection display
        self.log_display.display = True
        self.no_selection_display.display = False

        # Clear previous logs and stored lines
        self.log_display.clear()
        self.all_log_lines.clear()  # Clear the deque
        self.filtered_line_count = 0
        self.showing_no_logs_message = False  # Reset when clearing logs

        # Check if this is a container and if it's not running - do this BEFORE stopping logs
        if item_type == "container" and item_data.get("status"):
            status = item_data["status"].lower()
            if "exited" in status or "stopped" in status or "created" in status:
                # Container is not running, show appropriate message immediately
                self.log_display.text = f"Container '{item_data.get('name', item_id)}' is not running.\nStatus: {item_data['status']}"
                # Stop any existing log streaming (non-blocking)
                self._stop_logs_async()
                return

        # Show loading message immediately
        self.log_display.text = f"Loading logs for {item_type}: {item_id}...\n"

        # Stop any existing log streaming asynchronously to avoid blocking
        self._stop_logs_async()

        # Start streaming logs without refresh to avoid blocking
        self._start_logs()

    def clear_selection(self):
        """Clear the current selection and show the no-selection state."""

        # Stop any existing log streaming
        self._stop_logs()

        # Clear state
        self.current_item = None
        self.current_item_data = None

        # Update header
        self.header.update("📋 Log Pane - No Selection")

        # Hide log display, show no-selection display
        self.log_display.display = False
        self.no_selection_display.display = True

        # Clear logs and stored lines
        self.log_display.clear()
        self.all_log_lines.clear()  # Clear the deque

        # Refresh to ensure visibility changes take effect
        self.refresh()

    def _handle_status_change(self, item_data: dict):
        """Handle container status changes (started/stopped).

        Args:
            item_data: Updated container data with new status
        """
        # Stop any existing log streaming
        self._stop_logs()

        # Update stored data
        self.current_item_data = item_data

        # Clear previous logs
        self.log_display.clear()
        self.all_log_lines.clear()  # Clear the deque
        self.filtered_line_count = 0
        self.showing_no_logs_message = False  # Reset when status changes

        status = item_data.get("status", "").lower()

        if "exited" in status or "stopped" in status or "created" in status:
            # Container is not running, show message
            self.log_display.text = f"Container '{item_data.get('name', self.current_item[1])}' is not running.\nStatus: {item_data['status']}"
            self.refresh()
        elif "running" in status or "up" in status:
            # Container is running, start streaming logs
            self.log_display.clear()
            self.log_display.text = f"Container '{item_data.get('name', self.current_item[1])}' started. Loading logs...\n"
            self._start_logs()

    def _start_logs(self):
        """Start streaming logs for the current selection."""
        if not self.current_item:
            logger.warning("_start_logs called but no current_item")
            return

        item_type, item_id = self.current_item

        # Increment session ID to distinguish this log stream from previous ones
        self.log_session_id += 1
        current_session_id = self.log_session_id

        # Note: Loading message is already shown in update_selection()
        self.waiting_for_logs = True
        self.initial_log_check_done = False
        self.showing_no_logs_message = False  # Reset the flag when starting new logs

        # Clear stop event for the new thread
        self.stop_event.clear()
        self.log_thread = threading.Thread(
            target=self._log_worker, args=(current_session_id,), daemon=True
        )
        self.log_thread.start()

    def _stop_logs(self):
        """Stop the current log streaming."""

        # Signal the thread to stop
        self.stop_event.set()

        # Wait for the thread to finish
        if self.log_thread and self.log_thread.is_alive():
            self.log_thread.join(timeout=2)

        # Clear the queue
        while not self.log_queue.empty():
            try:
                self.log_queue.get_nowait()
            except queue.Empty:
                break

    def _stop_logs_async(self):
        """Stop the current log streaming without blocking."""
        # Signal the thread to stop
        self.stop_event.set()

        # Clear the queue without waiting for thread
        while not self.log_queue.empty():
            try:
                self.log_queue.get_nowait()
            except queue.Empty:
                break

    def _log_worker(self, session_id):
        """Worker thread that reads Docker logs and puts them in the queue.

        Args:
            session_id: The session ID for this log stream
        """
        item_type, item_id = self.current_item if self.current_item else (None, None)

        if not self.docker_client:
            self.log_queue.put((session_id, "error", "Docker client not available"))
            return

        try:
            if item_type == "container":
                # Stream logs for a single container
                self._stream_container_logs(item_id, session_id)
            elif item_type == "stack":
                # Stream logs for all containers in a stack
                self._stream_stack_logs(session_id)
            else:
                self.log_queue.put(
                    (session_id, "error", f"Unknown item type: {item_type}")
                )
        except Exception as e:
            logger.error(f"Error in log worker: {e}", exc_info=True)
            self.log_queue.put((session_id, "error", f"Error streaming logs: {str(e)}"))

    def _stream_container_logs(self, container_id, session_id):
        """Stream logs for a single container using Docker SDK.

        Args:
            container_id: The container ID
            session_id: The session ID for this log stream
        """
        try:
            container = self.docker_client.containers.get(container_id)

            # Convert tail and since parameters
            tail = int(self.LOG_TAIL)

            # Convert since parameter to proper format
            # Docker SDK expects since as datetime or Unix timestamp
            since = self._convert_since_to_timestamp(self.LOG_SINCE)

            # First, quickly check if there are any logs without following
            initial_logs = container.logs(
                stream=False,
                follow=False,
                tail=1,  # Just check for one line
                since=since,
                stdout=True,
                stderr=True,
                timestamps=False,
            )

            # If no logs found initially, show message quickly
            if not initial_logs or not initial_logs.strip():
                self._check_no_logs_found()
                # Still continue to stream in case new logs appear

            # Now stream logs with follow
            log_stream = container.logs(
                stream=True,
                follow=True,
                tail=tail,
                since=since,
                stdout=True,
                stderr=True,
                timestamps=False,
            )

            line_count = 0

            for line in log_stream:
                if self.stop_event.is_set():
                    break

                # Decode and strip the line
                if isinstance(line, bytes):
                    line = line.decode("utf-8", errors="replace")
                line = line.rstrip()
                # Strip ANSI escape codes to prevent text selection issues
                line = strip_ansi_codes(line)

                if line:
                    line_count += 1
                    self.log_queue.put((session_id, "log", line))

        except docker.errors.NotFound:
            self.log_queue.put(
                (session_id, "error", f"Container {container_id} not found")
            )
        except Exception as e:
            logger.error(f"Error streaming container logs: {e}", exc_info=True)
            raise

    def _stream_stack_logs(self, session_id):
        """Stream logs for all containers in a stack using Docker SDK.

        Args:
            session_id: The session ID for this log stream
        """
        try:
            stack_name = self.current_item_data.get("name", self.current_item[1])

            # Get all containers for this stack
            containers = self.docker_client.containers.list(
                all=True, filters={"label": f"com.docker.compose.project={stack_name}"}
            )

            # Remove any duplicate containers (shouldn't happen, but just in case)
            seen_ids = set()
            unique_containers = []
            for container in containers:
                if container.id not in seen_ids:
                    seen_ids.add(container.id)
                    unique_containers.append(container)
            containers = unique_containers

            if not containers:
                self.log_queue.put(
                    (session_id, "error", f"No containers found for stack {stack_name}")
                )
                return

            # Create log streams for all containers
            log_streams = []
            for container in containers:
                try:
                    # Convert tail and since parameters
                    tail = int(self.LOG_TAIL)
                    since = self._convert_since_to_timestamp(self.LOG_SINCE)

                    log_stream = container.logs(
                        stream=True,
                        follow=True,
                        tail=tail,
                        since=since,
                        stdout=True,
                        stderr=True,
                        timestamps=False,
                    )

                    # Store container name with the stream for prefixing
                    log_streams.append((container.name, log_stream))
                except Exception as e:
                    logger.warning(
                        f"Failed to get logs for container {container.name}: {e}"
                    )

            if not log_streams:
                self.log_queue.put(
                    (
                        session_id,
                        "error",
                        f"Could not stream logs for any containers in stack {stack_name}",
                    )
                )
                return

            # Stream logs from all containers
            has_any_logs = False

            # Set a shorter timer to check if we've received any logs
            # This is a compromise - we can't do instant checks for stacks without
            # potentially missing logs from some containers
            check_timer = threading.Timer(
                0.5, lambda: self._check_no_logs_found() if not has_any_logs else None
            )
            check_timer.start()

            # Create threads to read from each stream
            from queue import Queue

            # Queue to collect logs from all container threads
            combined_queue = Queue()

            def read_container_logs(name, stream):
                """Read logs from a single container stream."""
                try:
                    for line in stream:
                        if self.stop_event.is_set():
                            break

                        # Decode and strip the line
                        if isinstance(line, bytes):
                            line = line.decode("utf-8", errors="replace")
                        line = line.rstrip()
                        # Strip ANSI escape codes to prevent text selection issues
                        line = strip_ansi_codes(line)

                        if line:
                            # Prefix with container name for stack logs
                            prefixed_line = f"[{name}] {line}"
                            combined_queue.put(prefixed_line)
                except Exception as e:
                    logger.error(f"Error reading logs from {name}: {e}")

            # Start threads for each container
            threads = []
            for name, stream in log_streams:
                thread = threading.Thread(
                    target=read_container_logs, args=(name, stream), daemon=True
                )
                thread.start()
                threads.append(thread)

            # Read from combined queue and forward to main log queue
            while not self.stop_event.is_set():
                try:
                    # Use timeout to periodically check stop_event
                    line = combined_queue.get(timeout=0.1)
                    has_any_logs = True
                    self.log_queue.put((session_id, "log", line))
                except:
                    # Check if all threads have finished
                    if all(not t.is_alive() for t in threads):
                        break

            # Cancel timer if still running
            check_timer.cancel()

        except Exception as e:
            logger.error(f"Error streaming stack logs: {e}", exc_info=True)
            raise

    def _process_log_queue(self):
        """Timer callback to process queued log lines."""
        try:
            processed = 0
            # Process up to 50 lines per tick to avoid blocking
            for _ in range(50):
                if self.log_queue.empty():
                    break

                try:
                    queue_item = self.log_queue.get_nowait()

                    # Handle both old format (msg_type, content) and new format (session_id, msg_type, content)
                    if len(queue_item) == 2:
                        # Old format - shouldn't happen but handle gracefully
                        msg_type, content = queue_item
                        session_id = 0
                    else:
                        # New format with session ID
                        session_id, msg_type, content = queue_item

                    # Skip if this is from an old session
                    if session_id != 0 and session_id != self.log_session_id:
                        continue

                    processed += 1

                    if msg_type == "log":
                        # Store all log lines
                        self.all_log_lines.append(content)

                        # Apply search filter if set (empty string means no filter)
                        if (
                            not self.search_filter
                            or self.search_filter.lower() in content.lower()
                        ):
                            # If this is the first matching line and we had no matches before, clear the "no matches" message
                            if self.search_filter and self.filtered_line_count == 0:
                                self.log_display.clear()

                            # If we're showing the "no logs found" message, clear it
                            if self.showing_no_logs_message:
                                self.log_display.clear()
                                self.showing_no_logs_message = False

                            # Append to the text area
                            # Move cursor to end first, then insert
                            self.log_display.move_cursor(self.log_display.document.end)
                            self.log_display.insert(content + "\n")

                            self.filtered_line_count += 1

                            # Auto-scroll if enabled
                            if self.auto_follow:
                                # Move cursor to end of document
                                self.log_display.move_cursor(
                                    self.log_display.document.end
                                )
                                # Ensure cursor is visible (this scrolls to it)
                                self.log_display.scroll_cursor_visible()

                            # First line processing handled elsewhere
                    elif msg_type == "error":
                        # Display errors (don't store these in all_log_lines)
                        error_msg = f"ERROR: {content}"
                        # Move cursor to end first, then insert
                        self.log_display.move_cursor(self.log_display.document.end)
                        self.log_display.insert(error_msg + "\n")
                        logger.error(f"Queue error message: {content}")
                    elif msg_type == "no_logs":
                        # Show informative message when no logs are found
                        if self.waiting_for_logs:
                            self.log_display.clear()
                            self.waiting_for_logs = False
                            self.log_display.text = self._get_no_logs_message()
                            self.showing_no_logs_message = (
                                True  # Mark that we're showing the no logs message
                            )

                except queue.Empty:
                    break

            if processed > 0:
                self.initial_log_check_done = True

                # If we have a filter, have processed some logs, but no lines matched, show message
                if (
                    self.search_filter
                    and len(self.all_log_lines) > 0
                    and self.filtered_line_count == 0
                ):
                    self.log_display.text = "No log lines match filter"

        except Exception as e:
            logger.error(f"Error processing log queue: {e}", exc_info=True)

    def _get_no_logs_message(self):
        """Get the formatted 'No logs found' message."""
        item_type, item_id = self.current_item if self.current_item else ("", "")
        return (
            f"No logs found for {item_type}: {item_id}\n\n"
            "This could mean:\n"
            "  • The container/stack hasn't produced logs in the selected time range\n"
            "  • The container/stack was recently started\n"
            "  • Logs may have been cleared or rotated\n\n"
            "Try adjusting the log settings above to see more history.\n\n"
            "Waiting for new logs..."
        )

    def _check_no_logs_found(self):
        """Check if no logs were found and show an informative message."""
        if self.waiting_for_logs and not self.initial_log_check_done:
            # No logs received yet
            # Note: We don't have session_id here, but it's okay for no_logs message
            self.log_queue.put((0, "no_logs", ""))

    def _convert_since_to_timestamp(self, since_str):
        """Convert a time string like '5m' or '1h' to a Unix timestamp.

        Args:
            since_str: Time string (e.g., '5m', '1h', '24h')

        Returns:
            Unix timestamp for the 'since' parameter
        """
        import re
        import time

        # Parse the time unit and value
        match = re.match(r"^(\d+)([mhd])$", since_str)
        if not match:
            # If format is invalid, default to 15 minutes
            logger.warning(f"Invalid since format: {since_str}, defaulting to 15m")
            return int(time.time() - 15 * 60)

        value = int(match.group(1))
        unit = match.group(2)

        # Convert to seconds
        if unit == "m":
            seconds = value * 60
        elif unit == "h":
            seconds = value * 3600
        elif unit == "d":
            seconds = value * 86400
        else:
            seconds = 15 * 60  # Default to 15 minutes

        # Return Unix timestamp for 'since' time
        return int(time.time() - seconds)

    def _refilter_logs(self):
        """Re-filter and display all stored log lines based on current search filter."""
        self.log_display.clear()
        self.filtered_line_count = 0  # Reset count

        # If we're showing the "no logs found" message and there are no logs,
        # preserve that message regardless of filter
        if self.showing_no_logs_message and len(self.all_log_lines) == 0:
            self.log_display.text = self._get_no_logs_message()
            return

        # Build filtered text
        filtered_lines = []
        for line in self.all_log_lines:
            if not self.search_filter or self.search_filter.lower() in line.lower():
                filtered_lines.append(line)
                self.filtered_line_count += 1

        # Set all filtered lines at once
        if filtered_lines:
            self.log_display.text = "\n".join(filtered_lines) + "\n"
        elif self.search_filter and len(self.all_log_lines) > 0:
            # If we have a filter and no lines match, show a message
            self.log_display.text = "No log lines match filter"
        else:
            self.log_display.text = ""

        # Auto-scroll to bottom if auto-follow is enabled
        if self.auto_follow and filtered_lines:
            # Move cursor to end of document
            self.log_display.move_cursor(self.log_display.document.end)
            # Ensure cursor is visible (this scrolls to it)
            self.log_display.scroll_cursor_visible()

    def on_input_changed(self, event):
        """Handle search input changes."""
        if event.input.id == "search-input":
            self.search_filter = (
                event.value.strip()
            )  # Strip whitespace to treat empty strings as no filter
            # Re-filter existing logs when search filter changes
            self._refilter_logs()

    def on_checkbox_changed(self, event):
        """Handle auto-follow checkbox changes."""
        if event.checkbox.id == "auto-follow-checkbox":
            self.auto_follow = event.value

            # If auto-follow is enabled, immediately scroll to the bottom
            if self.auto_follow:
                # Move cursor to end of document
                self.log_display.move_cursor(self.log_display.document.end)
                # Ensure cursor is visible (this scrolls to it)
                self.log_display.scroll_cursor_visible()

    def on_select_changed(self, event):
        """Handle dropdown selection changes."""
        if event.select.id == "tail-select":
            # Update tail setting
            self.LOG_TAIL = event.value
            logger.info(f"Log tail setting changed to: {self.LOG_TAIL}")

            # If logs are currently displayed, restart them with new settings
            if self.current_item and self.log_display.display:
                self._restart_logs()

        elif event.select.id == "since-select":
            # Update since setting
            self.LOG_SINCE = event.value
            logger.info(f"Log since setting changed to: {self.LOG_SINCE}")

            # If logs are currently displayed, restart them with new settings
            if self.current_item and self.log_display.display:
                self._restart_logs()

    def _restart_logs(self):
        """Restart log streaming with new settings."""
        # Clear display and show loading message immediately
        self.log_display.clear()
        self.all_log_lines.clear()
        self.filtered_line_count = 0
        self.showing_no_logs_message = False  # Reset when restarting logs

        # Show loading message
        item_type, item_id = self.current_item
        self.log_display.text = f"Reloading logs for {item_type}: {item_id}...\n"
        self.waiting_for_logs = True
        self.initial_log_check_done = False

        # Stop current logs after showing the loading message
        self._stop_logs()

        # Start logs again
        self._start_logs()

    def _show_no_logs_message_for_item_type(self, item_type: str):
        """Show a message for item types that don't have logs and handle the UI state.

        Args:
            item_type: The type of item (e.g., 'Networks', 'Images', 'Volumes')
        """
        self.log_display.display = True
        self.no_selection_display.display = False
        self.log_display.clear()
        self.all_log_lines.clear()  # Clear the log buffer
        self.log_display.text = (
            f"{item_type} do not have logs. Select a container or stack to view logs."
        )
        # Stop any existing log streaming
        self._stop_logs_async()
        self.refresh()

    def action_copy_selection(self):
        """Copy the selected text to the clipboard."""
        if self.log_display.display:
            selection = self.log_display.selected_text
            if selection:
                # Define callback to show notification from main thread
                def on_copy_complete(success):
                    if success:
                        logger.info(f"Copied {len(selection)} characters to clipboard")
                        # Show notification in the app, not in the log display to avoid disrupting logs
                        self.app.notify(
                            "Text copied to clipboard",
                            severity="information",
                            timeout=2,
                        )
                    else:
                        logger.error("Failed to copy to clipboard")
                        # Show error notification
                        self.app.notify(
                            "Failed to copy to clipboard. Please install xclip or pyperclip.",
                            severity="error",
                            timeout=3,
                        )

                # Copy in background thread
                copy_to_clipboard_async(selection, on_copy_complete)

    def action_select_all(self):
        """Select all text in the log display."""
        if self.log_display.display:
            self.log_display.select_all()
