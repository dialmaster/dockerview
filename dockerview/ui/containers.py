import logging

from rich.console import RenderableType
from rich.style import Style
from rich.text import Text
from textual.binding import Binding
from textual.containers import Container, VerticalScroll
from textual.message import Message
from textual.widget import Widget
from textual.widgets import DataTable, Static

logger = logging.getLogger("dockerview.containers")


class SelectionChanged(Message):
    """Message sent when the selection changes in the container list."""

    def __init__(self, item_type: str, item_id: str, item_data: dict):
        self.item_type = item_type
        self.item_id = item_id
        self.item_data = item_data
        super().__init__()


class SectionHeader(Static):
    """A section header widget for grouping related items (Networks, Stacks, etc.).

    Displays a prominent section title to organize the UI into logical groups.
    """

    DEFAULT_CSS = """
    SectionHeader {
        background: $primary;
        color: $text;
        padding: 0 1;
        height: 1;
        margin: 2 0 0 0;
        text-style: bold;
        text-align: center;
    }
    """

    def __init__(self, title: str):
        """Initialize the section header.

        Args:
            title: The section title to display
        """
        super().__init__(title)
        self.can_focus = False  # Section headers are not focusable


class NetworkHeader(Static):
    """A header widget for displaying Docker network information.

    Displays network name, driver, scope, and connected container/stack counts with
    collapsible/expandable functionality.
    """

    COMPONENT_CLASSES = {"header": "network-header--header"}

    DEFAULT_CSS = """
    NetworkHeader {
        background: $surface-darken-1;
        padding: 0 0;
        height: 3;
        border-bottom: solid $accent-darken-3;
        margin: 0 0 0 0;
        color: $text;
    }

    NetworkHeader:hover {
        background: $surface-lighten-1;
        color: $accent-lighten-1;
        text-style: bold;
    }

    NetworkHeader:focus {
        background: $surface-lighten-2;
        color: $accent-lighten-2;
        text-style: bold;
    }

    .network-header--header {
        color: $text;
        text-style: bold;
    }
    """

    class Selected(Message):
        """Event emitted when the header is selected."""

        def __init__(self, network_header: "NetworkHeader") -> None:
            self.network_header = network_header
            super().__init__()

    class Clicked(Message):
        """Event emitted when the header is clicked."""

        def __init__(self, network_header: "NetworkHeader") -> None:
            self.network_header = network_header
            super().__init__()

    def __init__(
        self,
        network_name: str,
        driver: str,
        scope: str,
        subnet: str,
        total_containers: int,
        connected_stacks: set,
    ):
        """Initialize the network header.

        Args:
            network_name: Name of the Docker network
            driver: Network driver (bridge, overlay, host, etc.)
            scope: Network scope (local, swarm)
            subnet: Network subnet/IP range
            total_containers: Total number of connected containers
            connected_stacks: Set of stack names using this network
        """
        super().__init__("")
        self.network_name = network_name
        self.driver = driver
        self.scope = scope
        self.subnet = subnet
        self.total_containers = total_containers
        self.connected_stacks = connected_stacks
        self.expanded = False  # Start collapsed by default
        self.can_focus = True
        self._last_click_time = 0
        self._update_content()

    def _update_content(self) -> None:
        """Update the header's displayed content based on current state."""
        icon = "▼" if self.expanded else "▶"

        # Format connected stacks list
        if self.connected_stacks:
            stacks_text = ", ".join(sorted(self.connected_stacks))
            if len(stacks_text) > 40:
                stacks_text = stacks_text[:37] + "..."
        else:
            stacks_text = "No stacks"

        content = Text.assemble(
            Text(f"{icon} ", style="bold"),
            Text(self.network_name, style="bold cyan"),
            " ",
            Text(f"({self.driver}/{self.scope})", style="dim"),
            " ",
            Text(f"Subnet: {self.subnet}", style="blue"),
            "\n",
            Text(
                f"Containers: {self.total_containers}, Stacks: {stacks_text}",
                style="yellow",
            ),
        )
        self.update(content)

    def on_focus(self) -> None:
        """Called when the header gets focus."""
        self.refresh()
        self.post_message(self.Selected(self))

    def on_blur(self) -> None:
        """Called when the header loses focus."""
        self.refresh()

    def toggle(self) -> None:
        """Toggle the expanded/collapsed state of the network."""
        self.expanded = not self.expanded
        self._update_content()

    def on_click(self) -> None:
        """Handle click events for double-click detection."""
        import time

        current_time = time.time()

        self.post_message(self.Clicked(self))

        if current_time - self._last_click_time < 0.5:
            # Check if the search input is currently focused
            # If it is, don't steal focus from it
            if self.screen and self.screen.focused:
                focused_widget = self.screen.focused
                if not (
                    hasattr(focused_widget, "id")
                    and focused_widget.id == "search-input"
                ):
                    # Focus the header only if search input is not focused
                    self.focus()
            else:
                self.focus()

            if self.screen:
                container_list = self.screen.query_one("ContainerList")
                container_list.action_toggle_network()

        self._last_click_time = current_time


class StackHeader(Static):
    """A header widget for displaying Docker Compose stack information.

    Displays stack name, configuration file path, and container counts with
    collapsible/expandable functionality.
    """

    COMPONENT_CLASSES = {"header": "stack-header--header"}

    DEFAULT_CSS = """
    StackHeader {
        background: $surface-darken-2;
        padding: 0 0;
        height: 3;
        border-bottom: solid $primary-darken-3;
        margin: 0 0 0 0;
        color: $text;
    }

    StackHeader:hover {
        background: $surface-lighten-1;
        color: $primary-lighten-1;
        text-style: bold;
    }

    StackHeader:focus {
        background: $surface-lighten-2;
        color: $primary-lighten-2;
        text-style: bold;
    }

    .stack-header--header {
        color: $text;
        text-style: bold;
    }
    """

    class Selected(Message):
        """Event emitted when the header is selected."""

        def __init__(self, stack_header: "StackHeader") -> None:
            self.stack_header = stack_header
            super().__init__()

    class Clicked(Message):
        """Event emitted when the header is clicked."""

        def __init__(self, stack_header: "StackHeader") -> None:
            self.stack_header = stack_header
            super().__init__()

    def __init__(
        self, stack_name: str, config_file: str, running: int, exited: int, total: int
    ):
        """Initialize the stack header.

        Args:
            stack_name: Name of the Docker Compose stack
            config_file: Path to the compose configuration file
            running: Number of running containers
            exited: Number of exited containers
            total: Total number of containers
        """
        super().__init__("")
        self.stack_name = stack_name
        self.expanded = True
        self.running = running
        self.exited = exited
        self.total = total
        self.config_file = config_file
        self.can_focus = True
        self._last_click_time = 0
        self._update_content()

    def _update_content(self) -> None:
        """Update the header's displayed content based on current state."""
        icon = "▼" if self.expanded else "▶"
        running_text = Text(f"Running: {self.running}", style="green")
        exited_text = Text(f"Exited: {self.exited}", style="yellow")
        status = Text.assemble(
            running_text, ", ", exited_text, f", Total: {self.total}"
        )

        content = Text.assemble(
            Text(f"{icon} ", style="bold"),
            Text(self.stack_name, style="bold"),
            " ",
            Text(f"({self.config_file})", style="dim"),
            "\n",
            status,
        )
        self.update(content)

    def on_focus(self) -> None:
        """Called when the header gets focus."""
        self.refresh()
        # Emit a selected event when focused
        self.post_message(self.Selected(self))

    def on_blur(self) -> None:
        """Called when the header loses focus."""
        self.refresh()

    def toggle(self) -> None:
        """Toggle the expanded/collapsed state of the stack."""
        self.expanded = not self.expanded
        self._update_content()

    def on_click(self) -> None:
        """Handle click events for double-click detection."""
        import time

        current_time = time.time()

        # Emit a clicked event
        self.post_message(self.Clicked(self))

        if current_time - self._last_click_time < 0.5:
            # Check if the search input is currently focused
            # If it is, don't steal focus from it
            if self.screen and self.screen.focused:
                focused_widget = self.screen.focused
                if not (
                    hasattr(focused_widget, "id")
                    and focused_widget.id == "search-input"
                ):
                    # Focus the header only if search input is not focused
                    self.focus()
            else:
                self.focus()

            if self.screen:
                container_list = self.screen.query_one("ContainerList")
                container_list.action_toggle_stack()

        self._last_click_time = current_time


class ContainerList(VerticalScroll):
    """A scrollable widget that displays Docker containers grouped by their stacks.

    Provides collapsible stack sections with container details including resource usage
    and status information. Supports keyboard navigation and interaction.
    """

    DEFAULT_CSS = """
    ContainerList {
        background: transparent;
        height: auto;
        border: none;
        padding: 0;
    }

    StackHeader {
        layout: horizontal;
        width: 100%;
        height: 3;
    }

    .network-container {
        layout: vertical;
        width: 100%;
        height: auto;
        margin: 0 0 1 0;
        background: $surface;
        border: solid $accent-darken-3;
    }

    .stack-container {
        layout: vertical;
        width: 100%;
        height: auto;
        margin: 0 0 1 0;
        background: $surface;
        border: solid $primary-darken-3;
    }

    .stack-container:first-of-type {
        margin-bottom: 1;
    }

    .stack-container StackHeader {
        background: $surface-darken-2;
        border-bottom: solid $primary-darken-3;
    }

    DataTable {
        margin: 0;
        padding: 0 1;
        border: none;
        display: none;
        background: transparent;
    }

    .stack-container DataTable {
        border: none;
        background: $surface;
    }

    /* Make sure the cursor is visible and properly styled */
    DataTable > .datatable--cursor {
        background: $primary-darken-3;
        color: $text;
    }

    DataTable:focus > .datatable--cursor {
        background: $primary;
        color: $text;
    }

    /* Style for row hover */
    DataTable > .datatable--row:hover {
        background: $primary-darken-2;
        color: $text;
    }
    """

    BINDINGS = [
        Binding("up", "cursor_up", "Up", show=False),
        Binding("down", "cursor_down", "Down", show=False),
        Binding("enter", "toggle_item", "Expand/Collapse", show=True),
        Binding("space", "toggle_item", "Expand/Collapse", show=False),
    ]

    def __init__(self):
        """Initialize the container list widget."""
        try:
            super().__init__()
            # Network components
            self.network_tables = {}  # Dictionary to store tables for each network
            self.network_headers = {}  # Dictionary to store headers for each network
            self.network_rows = (
                {}
            )  # Dictionary to track container rows by network/container ID
            self.expanded_networks = set()  # Keep track of which networks are expanded

            # Stack components
            self.stack_tables = {}  # Dictionary to store tables for each stack
            self.stack_headers = {}  # Dictionary to store headers for each stack
            self.container_rows = {}  # Dictionary to track container rows by ID
            self.expanded_stacks = set()  # Keep track of which stacks are expanded

            # Section headers
            self.networks_section_header = None
            self.stacks_section_header = None

            # General state
            self.current_focus = None
            self._is_updating = False  # Track if we're in a batch update
            self._pending_clear = False  # Track if we need to clear during batch update

            # Selection tracking
            self.selected_item = None  # Will store ("network", network_name), ("stack", stack_name) or ("container", container_id)
            self.selected_container_data = (
                None  # Will store container data if a container is selected
            )
            self.selected_stack_data = (
                None  # Will store stack data if a stack is selected
            )
            self.selected_network_data = (
                None  # Will store network data if a network is selected
            )

            # Track which stacks/networks exist in current update cycle
            self._stacks_in_new_data = set()
            self._networks_in_new_data = set()
        except Exception as e:
            logger.error(
                f"Error during ContainerList initialization: {str(e)}", exc_info=True
            )
            raise

    def create_network_table(self, network_name: str) -> DataTable:
        """Create a new DataTable for displaying network container information.

        Args:
            network_name: Name of the network this table will display

        Returns:
            DataTable: A configured table for displaying network container information
        """
        table = DataTable()
        table.add_columns("Container ID", "Container Name", "Stack", "IP Address")

        # Configure cursor behavior
        table.cursor_type = "row"
        table.display = False  # Start collapsed
        table.can_focus = True
        table.show_cursor = True
        table.watch_cursor = True

        return table

    def _ensure_section_headers(self) -> None:
        """Ensure section headers exist for stacks and networks."""
        if self.stacks_section_header is None:
            self.stacks_section_header = SectionHeader("📦 DOCKER COMPOSE STACKS")
            # Remove top margin for the first section header
            self.stacks_section_header.styles.margin = (0, 0, 0, 0)

        if self.networks_section_header is None:
            self.networks_section_header = SectionHeader("🌐 DOCKER NETWORKS")

    def create_stack_table(self, stack_name: str) -> DataTable:
        """Create a new DataTable for displaying container information.

        Args:
            stack_name: Name of the stack this table will display

        Returns:
            DataTable: A configured table for displaying container information
        """
        table = DataTable()
        table.add_columns("ID", "Name", "Status", "CPU %", "Memory", "PIDs", "Ports")

        # Configure cursor behavior
        table.cursor_type = "row"  # Ensure we're using row selection

        # Make sure the table is visible and can be interacted with
        table.display = False  # Start collapsed
        table.can_focus = True

        # Enable cursor and highlighting
        table.show_cursor = True  # Always show cursor
        table.watch_cursor = True

        return table

    def begin_update(self) -> None:
        """Begin a batch update to prevent UI flickering during data updates."""

        self._is_updating = True
        # Only set pending_clear if we have no children yet
        self._pending_clear = len(self.children) == 0

        # Clear all tables to ensure fresh data
        for table in self.network_tables.values():
            table.clear()
        for table in self.stack_tables.values():
            table.clear()

        # Clear the tracking dictionaries to ensure we properly update all data
        self.container_rows.clear()
        self.network_rows.clear()

        # Track which networks and stacks should exist after this update (reset each update cycle)
        self._networks_in_new_data = set()
        self._stacks_in_new_data = set()

        # Ensure section headers are created
        self._ensure_section_headers()

    def end_update(self) -> None:
        """End a batch update and apply pending changes to the UI."""

        try:
            # First, clean up networks and stacks that no longer exist in the Docker data

            # Networks cleanup
            networks_to_remove = []
            for network_name in list(self.network_headers.keys()):
                if network_name not in self._networks_in_new_data:
                    networks_to_remove.append(network_name)

            # Stacks cleanup
            stacks_to_remove = []
            for stack_name in list(self.stack_headers.keys()):
                if stack_name not in self._stacks_in_new_data:
                    stacks_to_remove.append(stack_name)

            # More efficient: collect all containers to remove in one pass
            containers_to_remove = {}  # stack_name -> [container_ids]
            for cid, (cstack, _) in self.container_rows.items():
                if cstack in stacks_to_remove:
                    if cstack not in containers_to_remove:
                        containers_to_remove[cstack] = []
                    containers_to_remove[cstack].append(cid)

            # Remove obsolete networks and their associated data
            for network_name in networks_to_remove:
                # Remove from expanded networks tracking
                self.expanded_networks.discard(network_name)

                # Remove actual UI widgets - find and remove the network container
                for child in list(self.children):
                    if (
                        isinstance(child, Container)
                        and "network-container" in child.classes
                    ):
                        # Find the network name by looking at the header
                        for widget in child.children:
                            if (
                                isinstance(widget, NetworkHeader)
                                and widget.network_name == network_name
                            ):
                                child.remove()
                                break

                # Remove from internal tracking dictionaries
                if network_name in self.network_headers:
                    del self.network_headers[network_name]
                if network_name in self.network_tables:
                    del self.network_tables[network_name]

                # Clear selection if it was pointing to this network
                if (
                    self.selected_item
                    and self.selected_item[0] == "network"
                    and self.selected_item[1] == network_name
                ):
                    self.selected_item = None
                    self.selected_network_data = None

            # Remove obsolete stacks and their associated data
            for stack_name in stacks_to_remove:
                # Remove from expanded stacks tracking
                self.expanded_stacks.discard(stack_name)

                # Remove actual UI widgets - find and remove the stack container
                for child in list(self.children):
                    if (
                        isinstance(child, Container)
                        and "stack-container" in child.classes
                    ):
                        # Find the stack name by looking at the header
                        for widget in child.children:
                            if (
                                isinstance(widget, StackHeader)
                                and widget.stack_name == stack_name
                            ):
                                child.remove()
                                break

                # Remove from internal tracking dictionaries
                if stack_name in self.stack_headers:
                    del self.stack_headers[stack_name]
                if stack_name in self.stack_tables:
                    del self.stack_tables[stack_name]

                # Remove container rows that belonged to this stack
                if stack_name in containers_to_remove:
                    for cid in containers_to_remove[stack_name]:
                        del self.container_rows[cid]

                # Clear selection if it was pointing to this stack or its containers
                if (
                    self.selected_item
                    and self.selected_item[0] == "stack"
                    and self.selected_item[1] == stack_name
                ):
                    self.selected_item = None
                    self.selected_stack_data = None
                elif (
                    self.selected_item
                    and self.selected_item[0] == "container"
                    and stack_name in containers_to_remove
                    and self.selected_item[1] in containers_to_remove[stack_name]
                ):
                    self.selected_item = None
                    self.selected_container_data = None

            # Then, determine what needs to be added, updated, or removed

            # Track existing and new containers (both networks and stacks)
            existing_network_containers = {}
            existing_stack_containers = {}
            new_network_containers = {}
            new_stack_containers = {}

            # Find all existing containers in the UI
            if not self._pending_clear:
                for child in self.children:
                    if (
                        isinstance(child, Container)
                        and "network-container" in child.classes
                    ):
                        # Find the network name by looking at the header
                        for widget in child.children:
                            if isinstance(widget, NetworkHeader):
                                existing_network_containers[widget.network_name] = child
                                break
                    elif (
                        isinstance(child, Container)
                        and "stack-container" in child.classes
                    ):
                        # Find the stack name by looking at the header
                        for widget in child.children:
                            if isinstance(widget, StackHeader):
                                existing_stack_containers[widget.stack_name] = child
                                break

            # Prepare all new network containers that need to be added
            for network_name in sorted(self.network_headers.keys()):
                header = self.network_headers[network_name]
                table = self.network_tables[network_name]

                # If this network is not already in the UI, prepare it for mounting
                if network_name not in existing_network_containers:
                    network_container = Container(classes="network-container")
                    new_network_containers[network_name] = (
                        network_container,
                        header,
                        table,
                    )

            # Prepare all new stack containers that need to be added
            for stack_name in sorted(self.stack_headers.keys()):
                header = self.stack_headers[stack_name]
                table = self.stack_tables[stack_name]

                # If this stack is not already in the UI, prepare it for mounting
                if stack_name not in existing_stack_containers:
                    stack_container = Container(classes="stack-container")
                    new_stack_containers[stack_name] = (stack_container, header, table)

            # If we need to clear everything, do it all at once
            if self._pending_clear:
                self.remove_children()
                self._pending_clear = False

                # Ensure section headers exist
                self._ensure_section_headers()

                # Mount all containers at once (stacks first, then networks)

                # Mount stacks section
                if new_stack_containers or self.stack_headers:
                    self.mount(self.stacks_section_header)
                    for stack_name, (
                        stack_container,
                        header,
                        table,
                    ) in new_stack_containers.items():
                        self.mount(stack_container)
                        stack_container.mount(header)
                        stack_container.mount(table)
                        table.styles.display = "block" if header.expanded else "none"

                # Mount networks section
                if new_network_containers or self.network_headers:
                    self.mount(self.networks_section_header)
                    for network_name, (
                        network_container,
                        header,
                        table,
                    ) in new_network_containers.items():
                        self.mount(network_container)
                        network_container.mount(header)
                        network_container.mount(table)
                        table.styles.display = "block" if header.expanded else "none"

                total_containers = len(new_network_containers) + len(
                    new_stack_containers
                )
            else:
                # Update existing containers and add new ones

                # First update all existing network containers (in place)
                for network_name, container in existing_network_containers.items():
                    if network_name in self.network_headers:
                        # Update the header and table display state
                        header = self.network_headers[network_name]
                        table = self.network_tables[network_name]

                        # Find the existing header and table in the container
                        for widget in container.children:
                            if isinstance(widget, NetworkHeader):
                                # Update header content without remounting
                                widget._update_content()
                            elif isinstance(widget, DataTable):
                                # Update table display state
                                widget.styles.display = (
                                    "block" if header.expanded else "none"
                                )
                    else:
                        # This network no longer exists, remove it
                        container.remove()

                # Then update all existing stack containers (in place)
                for stack_name, container in existing_stack_containers.items():
                    if stack_name in self.stack_headers:
                        # Update the header and table display state
                        header = self.stack_headers[stack_name]
                        table = self.stack_tables[stack_name]

                        # Find the existing header and table in the container
                        for widget in container.children:
                            if isinstance(widget, StackHeader):
                                # Update header content without remounting
                                widget._update_content()
                            elif isinstance(widget, DataTable):
                                # Update table display state
                                widget.styles.display = (
                                    "block" if header.expanded else "none"
                                )
                    else:
                        # This stack no longer exists, remove it
                        container.remove()

                # Ensure section headers exist
                self._ensure_section_headers()

                # Check if we need to mount section headers
                networks_header_exists = self.networks_section_header in self.children
                stacks_header_exists = self.stacks_section_header in self.children

                # Mount section headers if needed
                if (
                    new_stack_containers or self.stack_headers
                ) and not stacks_header_exists:
                    self.mount(self.stacks_section_header)

                if (
                    new_network_containers or self.network_headers
                ) and not networks_header_exists:
                    self.mount(self.networks_section_header)

                # Then add any new containers (stacks first, then networks)
                for stack_name, (
                    stack_container,
                    header,
                    table,
                ) in new_stack_containers.items():
                    self.mount(stack_container)
                    stack_container.mount(header)
                    stack_container.mount(table)
                    table.styles.display = "block" if header.expanded else "none"

                for network_name, (
                    network_container,
                    header,
                    table,
                ) in new_network_containers.items():
                    self.mount(network_container)
                    network_container.mount(header)
                    network_container.mount(table)
                    table.styles.display = "block" if header.expanded else "none"

            # Restore selection and focus
            self._restore_selection()

            # Update cursor visibility based on the restored selection
            self._update_cursor_visibility()

            self._is_updating = False
        finally:
            if len(self.children) > 0:
                self.refresh()

            self._is_updating = False

    def _restore_selection(self) -> None:
        """Restore the previously selected item after a refresh."""
        try:
            if self.selected_item is None:
                # No selection to restore
                return

            # Check if the search input is currently focused
            # If it is, don't steal focus from it
            if self.screen and self.screen.focused:
                focused_widget = self.screen.focused
                # Check if the focused widget is the search input
                if (
                    hasattr(focused_widget, "id")
                    and focused_widget.id == "search-input"
                ):
                    # Still update the selection state but don't focus
                    self._update_footer_with_selection()
                    return

            item_type, item_id = self.selected_item

            if item_type == "stack" and item_id in self.stack_headers:
                # Restore stack selection
                header = self.stack_headers[item_id]
                header.focus()
                # Update footer with current selection
                self._update_footer_with_selection()

            elif item_type == "container" and item_id in self.container_rows:
                # Restore container selection
                stack_name, row_idx = self.container_rows[item_id]
                if stack_name in self.stack_tables:
                    table = self.stack_tables[stack_name]
                    header = self.stack_headers[stack_name]

                    # Make sure the stack is expanded
                    if not header.expanded:
                        header.expanded = True
                        table.styles.display = "block"
                        header._update_content()

                    # Focus and select the container row
                    table.focus()
                    table.move_cursor(row=row_idx)
                    # Update footer with current selection
                    self._update_footer_with_selection()
        except Exception as e:
            logger.error(f"Error restoring selection: {str(e)}", exc_info=True)

    def clear(self) -> None:
        """Clear all stacks and containers while preserving expansion states."""

        # Save expanded states before clearing
        self.expanded_stacks = {
            name for name, header in self.stack_headers.items() if header.expanded
        }
        # Also save focused widget if any
        focused = self.screen.focused if self.screen else None
        if focused in self.stack_headers.values():
            self.current_focus = next(
                name for name, header in self.stack_headers.items() if header == focused
            )
        elif focused in self.stack_tables.values():
            self.current_focus = next(
                name for name, table in self.stack_tables.items() if table == focused
            )

        # Clear all widgets
        self.stack_tables.clear()
        self.stack_headers.clear()
        self.container_rows.clear()  # Clear container row tracking
        self.remove_children()

    def add_network(self, network_data: dict) -> None:
        """Add or update a network section in the container list.

        Args:
            network_data: Dictionary containing network information
        """
        network_name = network_data["name"]

        # Track that this network exists in the new data
        self._networks_in_new_data.add(network_name)

        if network_name not in self.network_tables:
            header = NetworkHeader(
                network_name,
                network_data["driver"],
                network_data["scope"],
                network_data["subnet"],
                network_data["total_containers"],
                network_data["connected_stacks"],
            )
            table = self.create_network_table(network_name)

            self.network_headers[network_name] = header
            self.network_tables[network_name] = table

            if network_name in self.expanded_networks:
                header.expanded = True
                table.styles.display = "block"

            # Create and mount the container immediately unless we're in a batch update
            if not self._is_updating:
                network_container = Container(classes="network-container")
                self.mount(network_container)
                network_container.mount(header)
                network_container.mount(table)
                # Ensure proper display state
                table.styles.display = "block" if header.expanded else "none"

            # Update selected network data if this is the selected network
            if (
                self.selected_item
                and self.selected_item[0] == "network"
                and self.selected_item[1] == network_name
            ):
                self.selected_network_data = network_data
        else:
            header = self.network_headers[network_name]
            was_expanded = header.expanded
            header.driver = network_data["driver"]
            header.scope = network_data["scope"]
            header.subnet = network_data["subnet"]
            header.total_containers = network_data["total_containers"]
            header.connected_stacks = network_data["connected_stacks"]
            header.expanded = was_expanded
            self.network_tables[network_name].styles.display = (
                "block" if was_expanded else "none"
            )
            header._update_content()

            # Update selected network data if this is the selected network
            if (
                self.selected_item
                and self.selected_item[0] == "network"
                and self.selected_item[1] == network_name
            ):
                self.selected_network_data = network_data

    def add_container_to_network(self, network_name: str, container_data: dict) -> None:
        """Add or update a container in its network's table.

        Args:
            network_name: Name of the network the container is connected to
            container_data: Dictionary containing container information
        """
        if network_name not in self.network_tables:
            logger.warning(
                f"Network {network_name} not found when trying to add container"
            )
            return

        table = self.network_tables[network_name]
        container_id = container_data["id"]

        row_data = (
            container_data["id"],
            container_data["name"],
            container_data["stack"],
            container_data["ip"],
        )

        try:
            # Add as a new row
            row_key = table.row_count
            table.add_row(*row_data)
            self.network_rows[f"{network_name}:{container_id}"] = (
                network_name,
                row_key,
            )
        except Exception as e:
            logger.error(
                f"Error adding container {container_id} to network {network_name}: {str(e)}",
                exc_info=True,
            )

    def add_stack(
        self, name: str, config_file: str, running: int, exited: int, total: int
    ) -> None:
        """Add or update a stack section in the container list.

        Args:
            name: Name of the stack
            config_file: Path to the compose configuration file
            running: Number of running containers
            exited: Number of exited containers
            total: Total number of containers
        """
        # Track that this stack exists in the new data
        self._stacks_in_new_data.add(name)

        if name not in self.stack_tables:
            header = StackHeader(name, config_file, running, exited, total)
            table = self.create_stack_table(name)

            self.stack_headers[name] = header
            self.stack_tables[name] = table

            if name in self.expanded_stacks:
                header.expanded = True
                table.styles.display = "block"

            # Create and mount the container immediately unless we're in a batch update
            if not self._is_updating:
                stack_container = Container(classes="stack-container")
                self.mount(stack_container)
                stack_container.mount(header)
                stack_container.mount(table)
                # Ensure proper display state
                table.styles.display = "block" if header.expanded else "none"

            # Update selected stack data if this is the selected stack
            if (
                self.selected_item
                and self.selected_item[0] == "stack"
                and self.selected_item[1] == name
            ):
                self.selected_stack_data = {
                    "name": name,
                    "config_file": config_file,
                    "running": running,
                    "exited": exited,
                    "total": total,
                }
        else:
            header = self.stack_headers[name]
            was_expanded = header.expanded
            header.running = running
            header.exited = exited
            header.total = total
            header.config_file = config_file
            header.expanded = was_expanded
            self.stack_tables[name].styles.display = "block" if was_expanded else "none"
            header._update_content()

            # Update selected stack data if this is the selected stack
            if (
                self.selected_item
                and self.selected_item[0] == "stack"
                and self.selected_item[1] == name
            ):
                self.selected_stack_data = {
                    "name": name,
                    "config_file": config_file,
                    "running": running,
                    "exited": exited,
                    "total": total,
                }

    def add_container_to_stack(self, stack_name: str, container_data: dict) -> None:
        """Add or update a container in its stack's table.

        Args:
            stack_name: Name of the stack the container belongs to
            container_data: Dictionary containing container information
        """
        if stack_name not in self.stack_tables:
            self.add_stack(stack_name, "N/A", 0, 0, 0)

        table = self.stack_tables[stack_name]
        container_id = container_data["id"]

        # Format PIDs to show "N/A" when 0
        pids_display = (
            "N/A" if container_data["pids"] == "0" else container_data["pids"]
        )

        row_data = (
            container_data["id"],
            container_data["name"],
            container_data["status"],
            container_data["cpu"],
            container_data["memory"],
            pids_display,
            container_data["ports"],
        )

        # Update selected container data if this is the selected container
        if (
            self.selected_item
            and self.selected_item[0] == "container"
            and self.selected_item[1] == container_id
        ):
            self.selected_container_data = container_data

        try:
            # Since we clear container_rows at the beginning of each update cycle,
            # we'll always be adding new rows during a refresh
            if self._is_updating:
                # Add as a new row
                row_key = table.row_count
                table.add_row(*row_data)
                self.container_rows[container_id] = (stack_name, row_key)
            else:
                # For individual updates outside of a batch update cycle,
                # check if this container already exists in the table
                if container_id in self.container_rows:
                    existing_stack, existing_row = self.container_rows[container_id]

                    # If the container moved to a different stack, remove it from the old one
                    if (
                        existing_stack != stack_name
                        and existing_stack in self.stack_tables
                    ):
                        old_table = self.stack_tables[existing_stack]
                        try:
                            old_table.remove_row(existing_row)
                            # Update row indices for containers after this one
                            for cid, (cstack, crow) in list(
                                self.container_rows.items()
                            ):
                                if cstack == existing_stack and crow > existing_row:
                                    self.container_rows[cid] = (cstack, crow - 1)
                        except Exception as e:
                            logger.error(
                                f"Error removing container {container_id} from old stack: {str(e)}",
                                exc_info=True,
                            )

                        # Add to the new stack
                        row_key = table.row_count
                        table.add_row(*row_data)
                        self.container_rows[container_id] = (stack_name, row_key)
                    else:
                        # Update the existing row in the same stack
                        try:
                            for col_idx, value in enumerate(row_data):
                                table.update_cell(existing_row, col_idx, value)
                        except Exception as e:
                            logger.error(
                                f"Error updating container {container_id}: {str(e)}",
                                exc_info=True,
                            )
                else:
                    # Add as a new row
                    row_key = table.row_count
                    table.add_row(*row_data)
                    self.container_rows[container_id] = (stack_name, row_key)

        except Exception as e:
            logger.error(
                f"Error adding container {container_id}: {str(e)}", exc_info=True
            )
            return

        if self._is_updating and self._pending_clear:
            try:

                # Ensure section headers exist
                self._ensure_section_headers()

                # Prepare all containers
                network_containers = {}
                for network_name in sorted(self.network_headers.keys()):
                    header = self.network_headers[network_name]
                    table = self.network_tables[network_name]
                    network_container = Container(classes="network-container")
                    network_containers[network_name] = (
                        network_container,
                        header,
                        table,
                    )

                stack_containers = {}
                for stack_name in sorted(self.stack_headers.keys()):
                    header = self.stack_headers[stack_name]
                    table = self.stack_tables[stack_name]
                    stack_container = Container(classes="stack-container")
                    stack_containers[stack_name] = (stack_container, header, table)

                # Mount stacks section
                if stack_containers:
                    self.mount(self.stacks_section_header)
                    for stack_name, (
                        container,
                        header,
                        table,
                    ) in stack_containers.items():
                        self.mount(container)
                        container.mount(header)
                        container.mount(table)
                        table.styles.display = "block" if header.expanded else "none"

                # Mount networks section
                if network_containers:
                    self.mount(self.networks_section_header)
                    for network_name, (
                        container,
                        header,
                        table,
                    ) in network_containers.items():
                        self.mount(container)
                        container.mount(header)
                        container.mount(table)
                        table.styles.display = "block" if header.expanded else "none"

                self._pending_clear = False

                if self.current_focus:
                    # Check if the search input is currently focused
                    # If it is, don't steal focus from it
                    if self.screen and self.screen.focused:
                        focused_widget = self.screen.focused
                        if (
                            hasattr(focused_widget, "id")
                            and focused_widget.id == "search-input"
                        ):
                            pass  # Search input is focused, don't steal focus
                        else:
                            if self.current_focus in self.stack_headers:
                                self.stack_headers[self.current_focus].focus()
                            elif self.current_focus in self.stack_tables:
                                self.stack_tables[self.current_focus].focus()
                    else:
                        if self.current_focus in self.stack_headers:
                            self.stack_headers[self.current_focus].focus()
                        elif self.current_focus in self.stack_tables:
                            self.stack_tables[self.current_focus].focus()
            except Exception as e:
                logger.error(f"Error mounting widgets: {str(e)}", exc_info=True)

    def action_toggle_item(self) -> None:
        """Toggle the visibility of the selected item (network or stack)."""
        # Check if a network header has focus
        for network_name, header in self.network_headers.items():
            if header.has_focus:
                table = self.network_tables[network_name]
                header.toggle()
                table.styles.display = "block" if header.expanded else "none"
                return

        # Check if a stack header has focus
        for stack_name, header in self.stack_headers.items():
            if header.has_focus:
                table = self.stack_tables[stack_name]
                header.toggle()
                table.styles.display = "block" if header.expanded else "none"
                return

    def action_toggle_network(self) -> None:
        """Toggle the visibility of the selected network's container table."""
        for network_name, header in self.network_headers.items():
            if header.has_focus:
                table = self.network_tables[network_name]
                header.toggle()
                table.styles.display = "block" if header.expanded else "none"
                break

    def action_toggle_stack(self) -> None:
        """Toggle the visibility of the selected stack's container table."""
        for stack_name, header in self.stack_headers.items():
            if header.has_focus:
                table = self.stack_tables[stack_name]
                header.toggle()
                table.styles.display = "block" if header.expanded else "none"
                break

    def on_mount(self) -> None:
        """Handle initial widget mount by focusing and expanding the first stack."""
        try:
            # Check if the search input is currently focused
            # If it is, don't steal focus from it
            should_focus = True
            if self.screen and self.screen.focused:
                focused_widget = self.screen.focused
                if (
                    hasattr(focused_widget, "id")
                    and focused_widget.id == "search-input"
                ):
                    should_focus = False

            headers = list(self.stack_headers.values())
            if headers:
                first_header = headers[0]
                if should_focus:
                    first_header.focus()
                first_header.expanded = True
                first_table = self.stack_tables[first_header.stack_name]
                first_table.styles.display = "block"

                # If there are rows in the first table, select the first container
                if first_table.row_count > 0:
                    if should_focus:
                        first_table.focus()
                    first_table.move_cursor(row=0)

                    # Get the container ID from the first row
                    container_id = first_table.get_cell_at((0, 0))
                    if container_id:
                        self.select_container(container_id)
                else:
                    # If no containers, select the stack
                    self.select_stack(first_header.stack_name)
        except Exception as e:
            logger.error(f"Error during ContainerList mount: {str(e)}", exc_info=True)
            raise

    def select_network(self, network_name: str) -> None:
        """Select a network and update the footer.

        Args:
            network_name: Name of the network to select
        """
        if network_name in self.network_headers:
            # Clear any previous selection
            self.selected_item = ("network", network_name)
            self.selected_container_data = None
            self.selected_stack_data = None

            # Store network data for footer display
            header = self.network_headers[network_name]
            self.selected_network_data = {
                "name": network_name,
                "driver": header.driver,
                "scope": header.scope,
                "subnet": header.subnet,
                "total_containers": header.total_containers,
                "connected_stacks": header.connected_stacks,
            }

            # Update the footer and cursor visibility
            self._update_footer_with_selection()
            self._update_cursor_visibility()

            # Post selection change message
            self.post_message(
                SelectionChanged("network", network_name, self.selected_network_data)
            )

    def select_stack(self, stack_name: str) -> None:
        """Select a stack and update the footer.

        Args:
            stack_name: Name of the stack to select
        """
        if stack_name in self.stack_headers:
            # Clear any previous selection
            self.selected_item = ("stack", stack_name)
            self.selected_container_data = None

            # Store stack data for footer display
            header = self.stack_headers[stack_name]
            self.selected_stack_data = {
                "name": stack_name,
                "config_file": header.config_file,
                "running": header.running,
                "exited": header.exited,
                "total": header.total,
            }

            # Update the footer and cursor visibility
            self._update_footer_with_selection()
            self._update_cursor_visibility()

            # Post selection change message
            self.post_message(
                SelectionChanged("stack", stack_name, self.selected_stack_data)
            )

    def select_container(self, container_id: str) -> None:
        """Select a container and update the footer.

        Args:
            container_id: ID of the container to select
        """
        if container_id in self.container_rows:
            # Clear any previous selection
            self.selected_item = ("container", container_id)
            self.selected_stack_data = None

            # Find the container data
            stack_name, row_idx = self.container_rows[container_id]
            table = self.stack_tables[stack_name]

            # Get container data from the table
            container_data = {
                "id": table.get_cell_at((row_idx, 0)),
                "name": table.get_cell_at((row_idx, 1)),
                "status": table.get_cell_at((row_idx, 2)),
                "cpu": table.get_cell_at((row_idx, 3)),
                "memory": table.get_cell_at((row_idx, 4)),
                "pids": table.get_cell_at((row_idx, 5)),
                "ports": table.get_cell_at((row_idx, 6)),
                "stack": stack_name,
            }

            self.selected_container_data = container_data

            # Make sure the stack is expanded
            header = self.stack_headers[stack_name]
            if not header.expanded:
                header.expanded = True
                table.styles.display = "block"
                header._update_content()

            # Check if the search input is currently focused
            # If it is, don't steal focus from it
            if self.screen and self.screen.focused:
                focused_widget = self.screen.focused
                if (
                    hasattr(focused_widget, "id")
                    and focused_widget.id == "search-input"
                ):
                    # Still position the cursor on the selected row without focusing
                    if table.cursor_row != row_idx:
                        table.move_cursor(row=row_idx)
                else:
                    # Focus the table and position the cursor
                    table.focus()
                    # Position the cursor on the selected row
                    if table.cursor_row != row_idx:
                        table.move_cursor(row=row_idx)
            else:
                # Focus the table and position the cursor
                table.focus()
                # Position the cursor on the selected row
                if table.cursor_row != row_idx:
                    table.move_cursor(row=row_idx)

            # Force a refresh of the table to ensure the cursor is visible
            table.refresh()

            # Update the footer with selection
            self._update_footer_with_selection()

            # Post selection change message
            self.post_message(
                SelectionChanged(
                    "container", container_id, self.selected_container_data
                )
            )

            # Log the current state for debugging
        else:
            logger.error(f"Container ID {container_id} not found in container_rows")

    def _update_footer_with_selection(self) -> None:
        """Update the footer with the current selection information."""
        if self.screen is None:
            logger.warning("Cannot update footer: screen is None")
            return

        try:
            status_bar = self.screen.query_one("#status_bar")

            if self.selected_item is None:
                # Clear the status bar
                from rich.style import Style
                from rich.text import Text

                no_selection_text = Text(
                    "No selection", Style(color="white", bold=True)
                )
                status_bar.update(no_selection_text)

                # Post a message to clear log pane selection
                self.post_message(SelectionChanged("none", "", {}))
                return

            item_type, item_id = self.selected_item

            if item_type == "network" and self.selected_network_data:
                network_data = self.selected_network_data
                from rich.style import Style
                from rich.text import Text

                # Create a rich text object with styled components
                selection_text = Text()
                selection_text.append(
                    "Current Selection:", Style(color="black", bgcolor="yellow")
                )
                selection_text.append("  Network: ", Style(color="white"))
                selection_text.append(
                    f"{network_data['name']}", Style(color="cyan", bold=True)
                )
                selection_text.append(" | ", Style(color="white"))
                selection_text.append(f"Driver: ", Style(color="white"))
                selection_text.append(
                    f"{network_data['driver']}", Style(color="blue", bold=True)
                )
                selection_text.append(" | ", Style(color="white"))
                selection_text.append(f"Scope: ", Style(color="white"))
                selection_text.append(
                    f"{network_data['scope']}", Style(color="magenta", bold=True)
                )
                selection_text.append(" | ", Style(color="white"))
                selection_text.append(f"Containers: ", Style(color="white"))
                selection_text.append(
                    f"{network_data['total_containers']}",
                    Style(color="green", bold=True),
                )

                status_bar.update(selection_text)

            elif item_type == "stack" and self.selected_stack_data:
                stack_data = self.selected_stack_data
                from rich.style import Style
                from rich.text import Text

                # Create a rich text object with styled components
                selection_text = Text()
                selection_text.append(
                    "Current Selection:", Style(color="black", bgcolor="yellow")
                )
                selection_text.append("  Stack: ", Style(color="white"))
                selection_text.append(
                    f"{stack_data['name']}", Style(color="white", bold=True)
                )
                selection_text.append(" | ", Style(color="white"))
                selection_text.append(f"Running: ", Style(color="white"))
                selection_text.append(
                    f"{stack_data['running']}", Style(color="green", bold=True)
                )
                selection_text.append(" | ", Style(color="white"))
                selection_text.append(f"Exited: ", Style(color="white"))
                selection_text.append(
                    f"{stack_data['exited']}", Style(color="yellow", bold=True)
                )
                selection_text.append(" | ", Style(color="white"))
                selection_text.append(f"Total: ", Style(color="white"))
                selection_text.append(
                    f"{stack_data['total']}", Style(color="cyan", bold=True)
                )

                status_bar.update(selection_text)

            elif item_type == "container" and self.selected_container_data:
                container_data = self.selected_container_data
                from rich.style import Style
                from rich.text import Text

                # Create a rich text object with styled components
                selection_text = Text()
                selection_text.append(
                    "Current Selection:", Style(color="black", bgcolor="yellow")
                )
                selection_text.append("  Container: ", Style(color="white"))
                selection_text.append(
                    f"{container_data['name']}", Style(color="white", bold=True)
                )
                selection_text.append(" | ", Style(color="white"))
                selection_text.append("Status: ", Style(color="white"))

                # Style status based on value
                status = container_data["status"]
                if "running" in status.lower():
                    status_style = Style(color="green", bold=True)
                elif "exited" in status.lower():
                    status_style = Style(color="yellow", bold=True)
                else:
                    status_style = Style(color="red", bold=True)

                selection_text.append(status, status_style)

                # Add CPU and memory if available
                if "cpu" in container_data and container_data["cpu"]:
                    selection_text.append(" | ", Style(color="white"))
                    selection_text.append("CPU: ", Style(color="white"))
                    selection_text.append(
                        f"{container_data['cpu']}", Style(color="cyan", bold=True)
                    )

                if "memory" in container_data and container_data["memory"]:
                    selection_text.append(" | ", Style(color="white"))
                    selection_text.append("Memory: ", Style(color="white"))
                    selection_text.append(
                        f"{container_data['memory']}", Style(color="magenta", bold=True)
                    )

                status_bar.update(selection_text)

            else:
                # Clear the status bar if no valid selection
                logger.warning(f"Invalid selection: {item_type} - {item_id}")
                from rich.style import Style
                from rich.text import Text

                invalid_selection_text = Text(
                    f"Invalid selection: {item_type} - {item_id}",
                    Style(color="red", bold=True),
                )
                status_bar.update(invalid_selection_text)

        except Exception as e:
            logger.error(f"Error updating status bar: {str(e)}", exc_info=True)

    def _update_cursor_visibility(self) -> None:
        """Update cursor visibility and focus based on current selection.

        Instead of hiding cursors, we focus the table containing the selected container
        and ensure the cursor is positioned on the correct row.
        """
        try:
            # Check if the search input is currently focused
            # If it is, don't steal focus from it
            if self.screen and self.screen.focused:
                focused_widget = self.screen.focused
                # Check if the focused widget is the search input
                if (
                    hasattr(focused_widget, "id")
                    and focused_widget.id == "search-input"
                ):
                    return

            # If a container is selected, focus its table and position the cursor
            if self.selected_item and self.selected_item[0] == "container":
                container_id = self.selected_item[1]
                if container_id in self.container_rows:
                    stack_name, row_idx = self.container_rows[container_id]
                    if stack_name in self.stack_tables:
                        table = self.stack_tables[stack_name]

                        # Focus the table
                        table.focus()

                        # Ensure the cursor is positioned on the correct row
                        if table.cursor_row != row_idx:
                            table.move_cursor(row=row_idx)

            # If a stack is selected, focus its header
            elif self.selected_item and self.selected_item[0] == "stack":
                stack_name = self.selected_item[1]
                if stack_name in self.stack_headers:
                    header = self.stack_headers[stack_name]
                    header.focus()

        except Exception as e:
            logger.error(
                f"Error updating cursor visibility and focus: {str(e)}", exc_info=True
            )

    def on_data_table_row_selected(self, event) -> None:
        """Handle DataTable row selection events."""
        table = event.data_table
        row_key = event.row_key

        # Find which stack this table belongs to
        for stack_name, stack_table in self.stack_tables.items():
            if stack_table == table:
                # Get the container ID from the first column
                try:
                    row = table.get_row_index(row_key)
                    if row is not None and row < table.row_count:
                        container_id = table.get_cell_at((row, 0))

                        # Select the container to update the status bar
                        self.select_container(container_id)
                except Exception as e:
                    logger.error(
                        f"Error handling row selection: {str(e)}", exc_info=True
                    )
                break

    def on_network_header_selected(self, event) -> None:
        """Handle NetworkHeader selection events."""
        header = event.network_header
        self.select_network(header.network_name)

    def on_network_header_clicked(self, event) -> None:
        """Handle NetworkHeader click events."""
        header = event.network_header
        self.select_network(header.network_name)

    def on_stack_header_selected(self, event) -> None:
        """Handle StackHeader selection events."""
        header = event.stack_header
        self.select_stack(header.stack_name)

    def on_stack_header_clicked(self, event) -> None:
        """Handle StackHeader click events."""
        header = event.stack_header
        self.select_stack(header.stack_name)

    def action_cursor_up(self) -> None:
        """Handle up arrow key."""
        current = self.screen.focused

        # Check if the search input is currently focused
        # If it is, don't process navigation
        if hasattr(current, "id") and current.id == "search-input":
            return

        if isinstance(current, DataTable):
            # If we're at the top of the table, focus the header
            if current.cursor_row == 0:
                stack_name = next(
                    name
                    for name, table in self.stack_tables.items()
                    if table == current
                )
                header = self.stack_headers[stack_name]
                header.focus()
                self.select_stack(stack_name)
            else:
                current.action_cursor_up()
                # Update selection based on new cursor position
                row = current.cursor_row
                stack_name = next(
                    name
                    for name, table in self.stack_tables.items()
                    if table == current
                )
                container_id = current.get_cell_at((row, 0))
                self.select_container(container_id)
        elif isinstance(current, StackHeader):
            # Find previous visible widget
            current_idx = list(self.stack_headers.values()).index(current)
            if current_idx > 0:
                prev_header = list(self.stack_headers.values())[current_idx - 1]
                prev_table = self.stack_tables[prev_header.stack_name]
                if prev_header.expanded and prev_table.row_count > 0:
                    prev_table.focus()
                    prev_table.move_cursor(row=prev_table.row_count - 1)
                    # Update selection to the container
                    container_id = prev_table.get_cell_at((prev_table.row_count - 1, 0))
                    self.select_container(container_id)
                else:
                    prev_header.focus()
                    self.select_stack(prev_header.stack_name)

    def action_cursor_down(self) -> None:
        """Handle down arrow key."""
        current = self.screen.focused

        # Check if the search input is currently focused
        # If it is, don't process navigation
        if hasattr(current, "id") and current.id == "search-input":
            return

        if isinstance(current, DataTable):
            # If we're at the bottom of the table, focus the next header
            if current.cursor_row >= current.row_count - 1:
                stack_name = next(
                    name
                    for name, table in self.stack_tables.items()
                    if table == current
                )
                next_header_idx = list(self.stack_headers.keys()).index(stack_name) + 1
                if next_header_idx < len(self.stack_headers):
                    next_header = list(self.stack_headers.values())[next_header_idx]
                    next_header.focus()
                    self.select_stack(list(self.stack_headers.keys())[next_header_idx])
            else:
                current.action_cursor_down()
                # Update selection based on new cursor position
                row = current.cursor_row
                stack_name = next(
                    name
                    for name, table in self.stack_tables.items()
                    if table == current
                )
                container_id = current.get_cell_at((row, 0))
                self.select_container(container_id)
        elif isinstance(current, StackHeader):
            # If expanded and has rows, focus the table
            stack_name = current.stack_name
            table = self.stack_tables[stack_name]
            if current.expanded and table.row_count > 0:
                table.focus()
                table.move_cursor(row=0)
                # Update selection to the first container
                container_id = table.get_cell_at((0, 0))
                self.select_container(container_id)
            else:
                # Focus next header
                current_idx = list(self.stack_headers.values()).index(current)
                if current_idx < len(self.stack_headers) - 1:
                    next_header = list(self.stack_headers.values())[current_idx + 1]
                    next_header.focus()
                    self.select_stack(next_header.stack_name)

    def on_data_table_cursor_moved(self, event) -> None:
        """Handle DataTable cursor movement events to update selection."""
        table = event.sender

        # Find which stack this table belongs to
        for stack_name, stack_table in self.stack_tables.items():
            if stack_table == table:
                # Get the container ID from the first column
                try:
                    row = table.cursor_row
                    if row is not None and row < table.row_count:
                        container_id = table.get_cell_at((row, 0))
                        # Select the container to update the status bar
                        self.select_container(container_id)
                except Exception as e:
                    logger.error(
                        f"Error handling table cursor movement: {str(e)}", exc_info=True
                    )
                break

    def on_data_table_cell_selected(self, event) -> None:
        """Handle DataTable cell selection events."""
        table = event.sender

        # Find which stack this table belongs to
        for stack_name, stack_table in self.stack_tables.items():
            if stack_table == table:
                # Get the container ID from the first column
                try:
                    row = table.cursor_row
                    if row is not None and row < table.row_count:
                        container_id = table.get_cell_at((row, 0))
                        self.select_container(container_id)
                except Exception as e:
                    logger.error(
                        f"Error handling table selection: {str(e)}", exc_info=True
                    )
                break

    def on_data_table_row_highlighted(self, event) -> None:
        """Handle DataTable row highlight events."""
        table = event.data_table
        row_key = event.row_key

        # Find which stack this table belongs to
        for stack_name, stack_table in self.stack_tables.items():
            if stack_table == table:
                # Get the container ID from the first column
                try:
                    row = table.get_row_index(row_key)
                    if row is not None and row < table.row_count:
                        container_id = table.get_cell_at((row, 0))
                        # We don't select the container here, just log for debugging
                except Exception as e:
                    logger.error(
                        f"Error handling row highlight: {str(e)}", exc_info=True
                    )
                break

    def on_data_table_cell_highlighted(self, event) -> None:
        """Handle DataTable cell highlight events."""
        table = event.data_table
        coordinate = event.coordinate

        # Find which stack this table belongs to
        for stack_name, stack_table in self.stack_tables.items():
            if stack_table == table:
                # Get the container ID from the first column
                try:
                    row, _ = coordinate
                    if row is not None and row < table.row_count:
                        container_id = table.get_cell_at((row, 0))
                except Exception as e:
                    logger.error(
                        f"Error handling cell highlight: {str(e)}", exc_info=True
                    )
                break

    def on_data_table_click(self, event) -> None:
        """Handle DataTable click events."""
        table = event.sender

        # Find which stack this table belongs to
        for stack_name, stack_table in self.stack_tables.items():
            if stack_table == table:
                try:
                    # Get the click coordinates
                    if hasattr(event, "coordinate"):
                        row, _ = event.coordinate
                    elif hasattr(event, "y"):
                        # Convert screen y to row index
                        y = event.y - table.screen_y
                        row = y // 1  # Assuming row height is 1
                    else:
                        # Fall back to current cursor position
                        row = table.cursor_row

                    if row is not None and row < table.row_count:
                        # Check if the search input is currently focused
                        # If it is, don't steal focus from it
                        if self.screen and self.screen.focused:
                            focused_widget = self.screen.focused
                            if not (
                                hasattr(focused_widget, "id")
                                and focused_widget.id == "search-input"
                            ):
                                # Focus the table only if search input is not focused
                                table.focus()
                        else:
                            # Focus the table
                            table.focus()

                        # Move the cursor to the clicked row
                        table.move_cursor(row=row)

                        # Get the container ID from the first column
                        container_id = table.get_cell_at((row, 0))

                        # Select the container to update the status bar
                        self.select_container(container_id)
                except Exception as e:
                    logger.error(f"Error handling table click: {str(e)}", exc_info=True)
                break

    def on_data_table_selected(self, event) -> None:
        """Handle DataTable selection events."""
        table = event.sender

        # Find which stack this table belongs to
        for stack_name, stack_table in self.stack_tables.items():
            if stack_table == table:
                try:
                    # Get the selected row
                    row = table.cursor_row
                    if row is not None and row < table.row_count:
                        # Get the container ID from the first column
                        container_id = table.get_cell_at((row, 0))

                        # Select the container to update the status bar
                        self.select_container(container_id)
                except Exception as e:
                    logger.error(
                        f"Error handling DataTable.Selected event: {str(e)}",
                        exc_info=True,
                    )
                break

    def on_data_table_mouse_down(self, event) -> None:
        """Handle mouse down events on the DataTable."""
        table = event.sender

        # Find which stack this table belongs to
        for stack_name, stack_table in self.stack_tables.items():
            if stack_table == table:
                try:
                    # Get the mouse position relative to the table
                    mouse_x, mouse_y = event.x, event.y

                    # Convert to row index
                    # The exact calculation depends on the table's layout
                    # This is a simplified version
                    header_height = 1  # Adjust based on your header height
                    row = (mouse_y - header_height) // 1  # Assuming row height is 1

                    if row >= 0 and row < table.row_count:
                        # Check if the search input is currently focused
                        # If it is, don't steal focus from it
                        if self.screen and self.screen.focused:
                            focused_widget = self.screen.focused
                            if not (
                                hasattr(focused_widget, "id")
                                and focused_widget.id == "search-input"
                            ):
                                # Focus the table only if search input is not focused
                                table.focus()
                        else:
                            # Focus the table
                            table.focus()

                        # Move the cursor to the clicked row
                        table.move_cursor(row=row)

                        # Get the container ID from the first column
                        container_id = table.get_cell_at((row, 0))

                        # Select the container to update the status bar
                        self.select_container(container_id)
                except Exception as e:
                    logger.error(f"Error handling mouse down: {str(e)}", exc_info=True)
                break
