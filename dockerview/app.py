import logging
from typing import Iterable, Union

from textual.app import App, ComposeResult, SystemCommand
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.timer import Timer
from textual.widgets import Footer, Header
from textual.worker import Worker

from dockerview.config import config
from dockerview.docker_mgmt.manager import DockerManager
from dockerview.ui.actions.docker_actions import DockerActions
from dockerview.ui.actions.refresh_actions import RefreshActions
from dockerview.ui.containers import ContainerList, SelectionChanged
from dockerview.ui.dialogs.confirm import (
    ComposeDownModal,
    RemoveImageModal,
    RemoveUnusedImagesModal,
)
from dockerview.ui.viewers.log_pane import LogPane
from dockerview.ui.widgets.status import ErrorDisplay, StatusBar
from dockerview.utils.logging import setup_logging

# Initialize logging
log_file = setup_logging()
logger = logging.getLogger("dockerview")
if log_file:  # Only log if debug mode is enabled
    logger.info(f"Logging initialized. Log file: {log_file}")


class DockerViewApp(App, DockerActions, RefreshActions):
    """A Textual TUI application for monitoring Docker containers and stacks."""

    # Ensure command palette is enabled
    ENABLE_COMMAND_PALETTE = True

    CSS = """
    /* Remove generic container styling that might affect command palette */

    #left-pane {
        width: 50%;
        height: 100%;
        padding: 0 1;
    }

    /* Only apply to Vertical containers inside left-pane */
    #left-pane Vertical {
        height: auto;
        width: 100%;
        padding: 0 1;
    }

    /* Ensure ContainerList fills available space and scrolls independently */
    ContainerList {
        height: 100%;
    }

    DataTable {
        background: $surface;
        border: none;
    }

    DataTable > .datatable--header {
        background: $surface;
        color: $text;
        text-style: bold;
        border-bottom: solid $primary-darken-2;
    }

    DataTable > .datatable--cursor {
        background: $primary-darken-3;
        color: $text;
    }

    DataTable:focus > .datatable--cursor {
        background: $primary-darken-2;
        color: $text;
    }

    Header {
        background: $surface-darken-2;
        color: $primary-lighten-2;
        border-bottom: solid $primary-darken-3;
        text-style: bold;
        height: 3;
        padding: 0 1;
    }

    Footer {
        background: $primary-darken-2;
        color: $primary-lighten-2;
        border-top: solid $primary-darken-3;
        text-style: bold;
        height: 2;
        padding: 0 0;
    }
    """

    BINDINGS = [
        Binding("q", "quit", "Quit", show=True),
        Binding("s", "start", "Start Selected", show=True),
        Binding("t", "stop", "Stop Selected", show=True),
        Binding("e", "restart", "Restart Selected", show=True),
        Binding("u", "recreate", "Recreate Selected", show=True),
        Binding("d", "down", "Down Selected Stack", show=True),
        Binding("r", "remove_image", "Remove Selected Image", show=True),
        Binding("R", "remove_unused_images", "Remove All Unused Images", show=True),
    ]

    def __init__(self):
        """Initialize the application and Docker manager."""
        try:
            super().__init__()
            DockerActions.__init__(self)
            RefreshActions.__init__(self)
            self.docker = DockerManager()
            self.container_list: ContainerList | None = None
            self.log_pane: LogPane | None = None
            self.error_display: ErrorDisplay | None = None
            self.refresh_timer: Timer | None = None
            self._current_worker: Worker | None = None
            self.footer: Footer | None = None
            self.status_bar: StatusBar | None = None
            # Track current selection type for dynamic bindings
            self._current_selection_type = "none"
        except Exception as e:
            logger.error(f"Error during initialization: {str(e)}", exc_info=True)
            raise

    def get_system_commands(self, screen: Screen) -> Iterable[SystemCommand]:
        """Add system commands to the command palette.

        Args:
            screen: The current screen

        Returns:
            Iterable[SystemCommand]: The system commands
        """
        try:
            logger.info("get_system_commands called")

            # Yield default system commands
            for cmd in super().get_system_commands(screen):
                logger.info(f"Yielding default command: {cmd.title}")
                yield cmd

            # Yield custom commands
            custom_commands = [
                (
                    "Start Selected",
                    "Start the selected container or stack",
                    self.action_start,
                ),
                (
                    "Stop Selected",
                    "Stop the selected container or stack",
                    self.action_stop,
                ),
                (
                    "Restart Selected",
                    "Restart the selected container or stack",
                    self.action_restart,
                ),
                (
                    "Recreate Selected",
                    "Recreate the selected container/stack (docker compose up -d)",
                    self.action_recreate,
                ),
                (
                    "Down Selected Stack",
                    "Take down the selected stack (docker compose down)",
                    self.action_down,
                ),
                (
                    "Remove Selected Image",
                    "Remove the selected unused Docker image",
                    self.action_remove_image,
                ),
                (
                    "Remove All Unused Images",
                    "Remove all unused Docker images",
                    self.action_remove_unused_images,
                ),
            ]

            for title, help_text, callback in custom_commands:
                logger.info(f"Yielding custom command: {title}")
                yield SystemCommand(title, help_text, callback)

        except Exception as e:
            logger.error(f"Error in get_system_commands: {str(e)}", exc_info=True)
            # Re-raise to ensure Textual sees the error
            raise

    def compose(self) -> ComposeResult:
        """Create the application's widget hierarchy.

        Returns:
            ComposeResult: The composed widget tree
        """
        try:
            yield Header()
            with Horizontal():
                with Vertical(id="left-pane"):
                    error = ErrorDisplay()
                    error.id = "error"
                    yield error
                    container_list = ContainerList()
                    container_list.id = "containers"
                    yield container_list
                log_pane = LogPane()
                yield log_pane
            status_bar = StatusBar()
            status_bar.id = "status_bar"
            yield status_bar
            footer = Footer()
            footer.id = "footer"
            yield footer
        except Exception as e:
            logger.error(f"Error during composition: {str(e)}", exc_info=True)
            raise

    def on_mount(self) -> None:
        """Set up the application after widgets are mounted.

        Initializes the container list, error display, and starts the auto-refresh timer.
        """
        try:
            self.title = "Docker Container Monitor"
            # Get references to our widgets after they're mounted using IDs
            self.container_list = self.query_one("#containers", ContainerList)
            self.log_pane = self.query_one("#log-pane", LogPane)
            self.error_display = self.query_one("#error", ErrorDisplay)
            self.footer = self.query_one("#footer", Footer)
            self.status_bar = self.query_one("#status_bar", StatusBar)

            # Start the auto-refresh timer with interval from config
            refresh_interval = config.get("app.refresh_interval", 5.0)
            self.refresh_timer = self.set_interval(
                refresh_interval, self.action_refresh
            )
            # Trigger initial refresh immediately
            self.call_after_refresh(self.action_refresh)
        except Exception as e:
            logger.error(f"Error during mount: {str(e)}", exc_info=True)
            raise

    def action_quit(self) -> None:
        """Handle the quit action by stopping the refresh timer and exiting."""
        if self.refresh_timer:
            self.refresh_timer.stop()
        self.exit()

    def action_refresh(self) -> None:
        """Trigger an asynchronous refresh of the container list."""
        try:
            # Use call_after_refresh to ensure we're in the right context
            self.call_after_refresh(self.refresh_containers)
        except Exception as e:
            logger.error(f"Error scheduling refresh: {str(e)}", exc_info=True)

    def action_start(self) -> None:
        """Start the selected container or stack."""
        if not self.is_action_applicable("start"):
            return
        self.execute_docker_command("start")

    def action_stop(self) -> None:
        """Stop the selected container or stack."""
        if not self.is_action_applicable("stop"):
            return
        self.execute_docker_command("stop")

    def action_restart(self) -> None:
        """Restart the selected container or stack."""
        if not self.is_action_applicable("restart"):
            return
        self.execute_docker_command("restart")

    def action_recreate(self) -> None:
        """Recreate the selected container or stack using docker compose up -d."""
        if not self.is_action_applicable("recreate"):
            return
        self.execute_docker_command("recreate")

    def action_down(self) -> None:
        """Take down the selected stack with confirmation dialog."""
        if not self.is_action_applicable("down"):
            return

        item_type, item_id = self.container_list.selected_item

        # Get stack name for the modal
        stack_name = "unknown"
        if self.container_list.selected_stack_data:
            stack_name = self.container_list.selected_stack_data.get("name", "unknown")

        # Create the modal
        modal = ComposeDownModal(stack_name)

        # Push the confirmation modal
        def handle_down_confirmation(confirmed: bool) -> None:
            """Handle the result from the confirmation modal."""
            if confirmed:
                # Get checkbox state from the modal instance
                remove_volumes = modal.checkbox_checked

                # Build command with volume flag if needed
                command = "down"
                if remove_volumes:
                    command = "down:remove_volumes"

                self.execute_docker_command(command)

        self.push_screen(modal, handle_down_confirmation)

    def action_remove_image(self) -> None:
        """Remove the selected unused image with confirmation dialog."""
        if not self.container_list or not self.container_list.selected_item:
            self.error_display.update("No image selected")
            return

        item_type, item_id = self.container_list.selected_item
        if item_type != "image":
            self.error_display.update("Selected item is not an image")
            return

        image_data = self.container_list.image_manager.selected_image_data
        if not image_data:
            self.error_display.update("No image data available")
            return

        container_names = image_data.get("container_names", [])
        if container_names:
            self.error_display.update(
                f"Cannot remove image: in use by {len(container_names)} container(s)"
            )
            return

        modal = RemoveImageModal(image_data)

        def handle_remove_confirmation(confirmed: bool) -> None:
            """Handle the result from the confirmation modal."""
            if confirmed:
                self.execute_image_command("remove_image")

        self.push_screen(modal, handle_remove_confirmation)

    def action_remove_unused_images(self) -> None:
        """Remove all unused images with confirmation dialog."""
        unused_images = self.docker.get_unused_images()
        unused_count = len(unused_images)

        if unused_count == 0:
            self.error_display.update("No unused images found")
            return

        modal = RemoveUnusedImagesModal(unused_count)

        def handle_remove_all_confirmation(confirmed: bool) -> None:
            """Handle the result from the confirmation modal."""
            if confirmed:
                self.execute_image_command("remove_unused_images")

        self.push_screen(modal, handle_remove_all_confirmation)

    def check_action(self, action: str, parameters: tuple) -> Union[bool, None]:
        """Check if an action should be enabled.

        Returns:
            True: Show the key and allow the action
            False: Hide the key from the footer
            None: Show the key as disabled (dimmed) in the footer
        """
        SELECTION_ACTIONS = {
            "container": ["start", "stop", "restart", "recreate"],
            "service": ["start", "stop", "restart", "recreate"],
            "stack": ["start", "stop", "restart", "recreate", "down"],
            "network": [],
            "image": ["remove_image", "remove_unused_images"],
            "volume": [],
            "none": [],
        }

        # Always allow system actions
        if action in ("quit", "command_palette"):
            return True

        # For Docker-specific actions, check if they apply to current selection
        selection_type = self._current_selection_type

        if not selection_type or selection_type not in SELECTION_ACTIONS:
            return False

        available_actions = SELECTION_ACTIONS[selection_type]
        return action in available_actions

    def on_selection_changed(self, event: SelectionChanged) -> None:
        """Handle selection changes from the container list.

        Args:
            event: The SelectionChanged event containing selection information
        """
        if not self.log_pane:
            return

        if event.item_type == "none":
            self.log_pane.clear_selection()
            self.container_list._update_footer_with_selection()
            self.status_bar.refresh()
        else:
            self.log_pane.update_selection(
                event.item_type, event.item_id, event.item_data
            )
            self.container_list._update_footer_with_selection()
            self.status_bar.refresh()
        self._current_selection_type = event.item_type
        self.refresh_bindings()


def main():
    """Run the Docker container monitoring application."""
    try:
        app = DockerViewApp()
        app.run()
    except Exception as e:
        logger.error(f"Error running app: {str(e)}", exc_info=True)
        raise


__all__ = ["main", "DockerViewApp"]
