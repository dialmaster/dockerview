"""Confirmation modal dialog for destructive operations."""

from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Center, Container, Horizontal, Middle, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Checkbox, Label, Static


class ConfirmModal(ModalScreen[bool]):
    """A reusable confirmation modal with optional checkbox.

    This modal follows Textual best practices by:
    - Extending ModalScreen with a return type hint
    - Using CSS for styling
    - Providing a clean API for the caller
    """

    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
    ]

    DEFAULT_CSS = """
    ConfirmModal {
        align: center middle;
        background: rgba(0, 0, 0, 0.5);
    }

    ConfirmModal > Container {
        background: $surface;
        border: solid $primary;
        width: 70;
        height: auto;
        min-height: 16;
        max-height: 16;
        padding-top: 0;
        padding-bottom: 1;
        padding-left: 1;
        padding-right: 1;
    }

    ConfirmModal .modal-header {
        height: 2;
        max-height: 2;
        width: 100%;
    }

    ConfirmModal Static.modal-title {
        text-style: bold;
        color: $warning;
        width: 1fr;
        height: 1;
    }

    ConfirmModal .close-button {
        width: 3;
        min-width: 3;
        height: 1;
        background: transparent;
        border: none;
        color: $text-muted;
        text-align: center;
        padding: 0;
    }

    ConfirmModal .close-button:hover {
        color: $text;
        background: $boost;
    }

    ConfirmModal .modal-body {
        width: 100%;
        height: 8;
        margin-top: 1;
        min-height: 8;
        padding: 0;
    }

    ConfirmModal Static.modal-message {
        width: 100%;
        text-align: left;
        margin-bottom: 1;
        height: auto;
        min-height: 3;
    }

    ConfirmModal Checkbox {
        margin-top: 1;
        margin-bottom: 1;
        width: 100%;
        height: auto;
        min-height: 3;
    }

    ConfirmModal .button-container {
        dock: bottom;
        align: center middle;
        height: 3;
        max-height: 3;
        width: 100%;
        margin-top: 9;
    }

    ConfirmModal Button {
        margin: 0 1;
        min-width: 14;
        height: 3;
    }

    ConfirmModal .danger-button {
        background: $error;
        color: $text;
    }

    ConfirmModal .danger-button:hover {
        background: $error-darken-1;
    }
    """

    def __init__(
        self,
        title: str,
        message: str,
        checkbox_label: str = None,
        checkbox_default: bool = False,
        confirm_label: str = "Confirm",
        cancel_label: str = "Cancel",
        dangerous: bool = True,
    ):
        """Initialize the confirmation modal.

        Args:
            title: The title of the modal
            message: The confirmation message to display
            checkbox_label: Optional label for a checkbox (None to hide checkbox)
            checkbox_default: Default state of the checkbox
            confirm_label: Label for the confirm button
            cancel_label: Label for the cancel button
            dangerous: Whether the confirm button should be styled as dangerous
        """
        super().__init__()
        self.title = title
        self.message = message
        self.checkbox_label = checkbox_label
        self.checkbox_default = checkbox_default
        self.confirm_label = confirm_label
        self.cancel_label = cancel_label
        self.dangerous = dangerous
        self.checkbox = None

    def compose(self) -> ComposeResult:
        """Compose the modal UI."""
        with Container():

            # Header with title and close button
            with Horizontal(classes="modal-header"):
                yield Static(self.title, classes="modal-title")
                yield Button("✕", id="close", classes="close-button")

            # Body content
            with Vertical(classes="modal-body"):
                # Message
                yield Static(self.message, classes="modal-message")

                # Optional checkbox
                if self.checkbox_label:
                    self.checkbox = Checkbox(
                        self.checkbox_label, value=self.checkbox_default
                    )
                    yield self.checkbox

            # Buttons
            with Horizontal(classes="button-container"):
                yield Button(self.cancel_label, id="cancel", variant="default")
                yield Button(
                    self.confirm_label,
                    id="confirm",
                    variant="error" if self.dangerous else "primary",
                    classes="danger-button" if self.dangerous else "",
                )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button press events."""
        if event.button.id == "confirm":
            # Return True to indicate confirmation
            self.dismiss(True)
        else:
            # Return False to indicate cancellation (for both cancel and close)
            self.dismiss(False)

    def action_cancel(self) -> None:
        """Handle the cancel action from escape key."""
        self.dismiss(False)

    @property
    def checkbox_checked(self) -> bool:
        """Get the checkbox state.

        Returns:
            bool: True if checkbox is checked, False otherwise (or if no checkbox)
        """
        return self.checkbox.value if self.checkbox else False


class ComposeDownModal(ConfirmModal):
    """Specialized modal for docker-compose down confirmation."""

    def __init__(self, stack_name: str):
        """Initialize the compose down confirmation modal.

        Args:
            stack_name: Name of the stack to be taken down
        """
        super().__init__(
            title="Confirm Stack Down",
            message=f"Are you sure you want to take down the stack '{stack_name}'? This will stop and remove all containers in the stack.",
            checkbox_label="Also remove volumes",
            checkbox_default=False,
            confirm_label="Take Down",
            cancel_label="Cancel",
            dangerous=True,
        )
        self.stack_name = stack_name
