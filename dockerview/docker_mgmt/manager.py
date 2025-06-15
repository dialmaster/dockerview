import json
import logging
import os
import subprocess
import threading
import time
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional

import docker

logger = logging.getLogger("dockerview.docker_mgmt")


class DockerManager:
    """Manages Docker interactions."""

    def __init__(self):
        """Initialize the Docker client connection."""
        try:
            self.client = docker.from_env()
            self.last_error = None
        except Exception as e:
            logger.error(f"Failed to initialize Docker client: {str(e)}", exc_info=True)
            raise

    def _check_compose_file_accessible(self, config_file_path: str) -> bool:
        """Check if a Docker Compose config file is accessible.

        Args:
            config_file_path: Path to the compose config file(s) (comma-separated if multiple)

        Returns:
            bool: True if at least one compose file is accessible, False otherwise
        """
        if not config_file_path or config_file_path == "N/A":
            return False

        try:
            # Config files can be comma-separated
            config_files = [f.strip() for f in config_file_path.split(",")]

            # Check if at least one file is accessible
            for config_file in config_files:
                if Path(config_file).is_file():
                    logger.debug(f"Compose file accessible: {config_file}")
                    return True

            logger.debug(f"No accessible compose files found in: {config_file_path}")
            return False

        except Exception as e:
            logger.error(
                f"Error checking compose file accessibility: {str(e)}", exc_info=True
            )
            return False

    def get_compose_stacks(self) -> Dict[str, Dict]:
        """Retrieve all Docker Compose stacks and their containers.

        Returns:
            Dict[str, Dict]: A dictionary mapping stack names to their details including:
                - name: Stack name
                - config_file: Path to compose config file
                - containers: List of container objects
                - running: Count of running containers
                - exited: Count of exited containers
                - total: Total container count
                - can_recreate: Whether the stack can be recreated (compose file accessible)
                - has_compose_file: Whether a compose file path is defined
        """
        stacks = defaultdict(
            lambda: {
                "name": "",
                "config_file": "",
                "containers": [],
                "running": 0,
                "exited": 0,
                "total": 0,
                "can_recreate": False,
                "has_compose_file": False,
            }
        )

        try:
            containers = self.client.containers.list(all=True)

            for container in containers:
                try:
                    project = container.labels.get(
                        "com.docker.compose.project", "ungrouped"
                    )
                    config_file = container.labels.get(
                        "com.docker.compose.project.config_files", "N/A"
                    )

                    if project not in stacks:
                        stacks[project]["name"] = project
                        stacks[project]["config_file"] = config_file
                        stacks[project]["has_compose_file"] = config_file != "N/A"
                        stacks[project]["can_recreate"] = (
                            self._check_compose_file_accessible(config_file)
                        )

                    stacks[project]["containers"].append(container)
                    stacks[project]["total"] += 1
                    if container.status == "running":
                        stacks[project]["running"] += 1
                    elif "exited" in container.status:
                        stacks[project]["exited"] += 1

                except Exception as container_error:
                    logger.error(
                        f"Error processing container {container.name}: {str(container_error)}",
                        exc_info=True,
                    )
                    continue

        except Exception as e:
            error_msg = f"Error getting compose stacks: {str(e)}"
            logger.error(error_msg, exc_info=True)
            self.last_error = error_msg
            return {}

        return dict(stacks)

    def get_all_container_stats(self) -> Dict[str, Dict[str, str]]:
        """Retrieve stats for all containers in a single operation.

        Returns:
            Dict[str, Dict[str, str]]: A dictionary mapping container IDs to their stats including:
                - cpu: CPU usage percentage
                - memory: Memory usage and limit
                - memory_percent: Memory usage percentage
                - pids: Number of processes

        PERFORMANCE NOTE: This method uses the Docker SDK with concurrent stats collection
        to efficiently retrieve stats for all containers. We use threading to parallelize
        the stats collection while maintaining good performance with many containers.
        """
        stats_dict = {}
        try:
            logger.debug("Starting Docker SDK stats collection")
            collection_start = time.time()

            # Get all running containers
            containers = self.client.containers.list(filters={"status": "running"})
            logger.debug(f"Found {len(containers)} running containers")

            if not containers:
                return {}

            # Use threading to collect stats concurrently
            stats_lock = threading.Lock()
            threads = []

            def collect_container_stats(container):
                """Collect stats for a single container."""
                try:
                    # Get stats without streaming (single snapshot)
                    stats = container.stats(stream=False)

                    # Calculate CPU percentage
                    cpu_delta = (
                        stats["cpu_stats"]["cpu_usage"]["total_usage"]
                        - stats["precpu_stats"]["cpu_usage"]["total_usage"]
                    )
                    system_delta = (
                        stats["cpu_stats"]["system_cpu_usage"]
                        - stats["precpu_stats"]["system_cpu_usage"]
                    )
                    cpu_count = len(
                        stats["cpu_stats"]["cpu_usage"].get("percpu_usage", [None])
                    )

                    if system_delta > 0:
                        cpu_percent = (cpu_delta / system_delta) * cpu_count * 100.0
                    else:
                        cpu_percent = 0.0

                    # Calculate memory usage
                    mem_stats = stats["memory_stats"]
                    mem_usage = mem_stats.get("usage", 0)
                    mem_limit = mem_stats.get("limit", 0)

                    # Account for cache in memory usage (same as docker stats CLI)
                    cache = mem_stats.get("stats", {}).get("cache", 0)
                    mem_usage = mem_usage - cache if mem_usage > cache else mem_usage

                    mem_percent = (
                        (mem_usage / mem_limit * 100.0) if mem_limit > 0 else 0.0
                    )

                    # Format memory strings
                    def format_bytes(bytes_val):
                        """Format bytes to human readable format."""
                        for unit in ["B", "KiB", "MiB", "GiB", "TiB"]:
                            if bytes_val < 1024.0:
                                return f"{bytes_val:.1f}{unit}"
                            bytes_val /= 1024.0
                        return f"{bytes_val:.1f}PiB"

                    mem_usage_str = format_bytes(mem_usage)
                    mem_limit_str = format_bytes(mem_limit)

                    # Get PIDs count
                    pids_stats = stats.get("pids_stats", {})
                    pids_current = pids_stats.get("current", 0)

                    # Store the stats
                    with stats_lock:
                        stats_dict[container.short_id] = {
                            "cpu": f"{cpu_percent:.2f}%",
                            "memory": f"{mem_usage_str} / {mem_limit_str}",
                            "memory_percent": f"{mem_percent:.2f}",
                            "pids": str(pids_current),
                        }

                except Exception as e:
                    logger.error(
                        f"Error collecting stats for container {container.short_id}: {str(e)}",
                        exc_info=True,
                    )
                    # Provide default values on error
                    with stats_lock:
                        stats_dict[container.short_id] = {
                            "cpu": "0%",
                            "memory": "0B / 0B",
                            "memory_percent": "0",
                            "pids": "0",
                        }

            # Create and start threads for each container
            for container in containers:
                thread = threading.Thread(
                    target=collect_container_stats, args=(container,)
                )
                thread.daemon = True
                threads.append(thread)
                thread.start()

            # Wait for all threads to complete with a timeout
            timeout = 5.0  # 5 second timeout for stats collection
            for thread in threads:
                thread.join(timeout=timeout)

            collection_end = time.time()
            logger.debug(
                f"Collected stats for {len(stats_dict)} containers in {collection_end - collection_start:.3f}s"
            )

        except Exception as e:
            error_msg = f"Error getting container stats: {str(e)}"
            logger.error(error_msg, exc_info=True)
            return {}

        return stats_dict

    def get_containers(self) -> List[Dict]:
        """Retrieve all containers with their current stats.

        Returns:
            List[Dict]: A list of container information dictionaries including:
                - id: Container short ID
                - name: Container name
                - status: Current status
                - cpu: CPU usage percentage
                - memory: Memory usage
                - pids: Number of processes
                - stack: Docker Compose stack name
                - ports: Container port mappings
        """
        containers = []
        try:
            # Get all container stats in a single call first (this is the most time-consuming operation)
            all_stats = self.get_all_container_stats()

            # Then get the stacks information
            stacks = self.get_compose_stacks()

            # Process the containers with their stats
            for stack_name, stack_info in stacks.items():
                for container in stack_info["containers"]:
                    try:
                        stats = all_stats.get(
                            container.short_id,
                            {
                                "cpu": "0%",
                                "memory": "0B / 0B",
                                "memory_percent": "0",
                                "pids": "0",
                            },
                        )

                        container_info = {
                            "id": container.short_id,
                            "name": container.name,
                            "status": container.status,
                            "cpu": stats["cpu"],
                            "memory": stats["memory"],
                            "pids": stats["pids"],
                            "stack": stack_name,
                            "ports": self._format_ports(container),
                        }
                        containers.append(container_info)
                    except Exception as container_error:
                        logger.error(
                            f"Error processing container {container.name}: {str(container_error)}",
                            exc_info=True,
                        )
                        continue

        except Exception as e:
            error_msg = f"Error getting container stats: {str(e)}"
            logger.error(error_msg, exc_info=True)
            self.last_error = error_msg
            return []

        return containers

    def _format_ports(self, container) -> str:
        """Format container port mappings for display.

        Args:
            container: Docker container object

        Returns:
            str: Formatted string of port mappings (e.g. "8080->80, 443->443")
        """
        try:
            ports = set()  # Use a set to eliminate duplicates
            for port in container.ports.items():
                if port[1]:
                    # Extract the container port without the protocol suffix
                    container_port = port[0].split("/")[0]
                    for binding in port[1]:
                        ports.add(f"{binding['HostPort']}->{container_port}")
            return ", ".join(sorted(ports)) if ports else ""
        except Exception as e:
            logger.error(
                f"Error formatting ports for container {container.short_id}: {str(e)}",
                exc_info=True,
            )
            return ""

    def execute_container_command(self, container_id: str, command: str) -> bool:
        """Execute a command on a specific container.

        Args:
            container_id: ID of the container to operate on
            command: Command to execute (start, stop, restart, recreate)

        Returns:
            bool: True if successful, False otherwise
        """
        try:
            if command == "recreate":
                # For recreate, we need to get the service name and stack name
                container = self.client.containers.get(container_id)
                stack_name = container.labels.get("com.docker.compose.project")
                service_name = container.labels.get("com.docker.compose.service")

                if not stack_name or not service_name:
                    error_msg = "Cannot recreate container: missing compose project or service labels"
                    logger.error(error_msg)
                    self.last_error = error_msg
                    return False

                # Get the compose config file(s)
                config_files = container.labels.get(
                    "com.docker.compose.project.config_files", ""
                )

                # Check if compose file is accessible
                if not self._check_compose_file_accessible(config_files):
                    error_msg = (
                        f"Cannot recreate container: compose file not accessible"
                    )
                    logger.error(error_msg)
                    self.last_error = error_msg
                    return False

                cmd = ["docker", "compose", "-p", stack_name]

                # Add config file(s) if available
                if config_files and config_files != "N/A":
                    # Config files are comma-separated
                    for config_file in config_files.split(","):
                        cmd.extend(["-f", config_file.strip()])

                cmd.extend(["up", "-d", service_name])
                logger.info(f"Executing recreate command: {' '.join(cmd)}")

                # Use Popen to run the command in the background
                process = subprocess.Popen(
                    cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
                )

                # We don't wait for the process to complete to keep the UI responsive
                return True
            else:
                logger.info(
                    f"Executing container command: {command} on container {container_id}"
                )

                def run_container_command():
                    try:
                        container = self.client.containers.get(container_id)

                        if command == "start":
                            container.start()
                        elif command == "stop":
                            container.stop()
                        elif command == "restart":
                            container.restart()
                        else:
                            error_msg = f"Unknown container command: {command}"
                            logger.error(error_msg)
                            self.last_error = error_msg
                    except Exception as e:
                        logger.error(
                            f"Error in container command thread: {str(e)}",
                            exc_info=True,
                        )

                # Run the command in a separate thread to avoid blocking
                thread = threading.Thread(target=run_container_command)
                thread.daemon = True
                thread.start()

            return True
        except Exception as e:
            error_msg = f"Error executing container command: {str(e)}"
            logger.error(error_msg, exc_info=True)
            self.last_error = error_msg
            return False

    def get_networks(self) -> Dict[str, Dict]:
        """Retrieve all Docker networks with their connected containers and stacks.

        Returns:
            Dict[str, Dict]: A dictionary mapping network names to their details including:
                - id: Network short ID
                - name: Network name
                - driver: Network driver (bridge, overlay, host, etc.)
                - scope: Network scope (local, swarm)
                - subnet: Network subnet/IP range
                - connected_containers: List of connected container info
                - connected_stacks: Set of stack names using this network
                - total_containers: Total number of connected containers
        """
        networks = {}
        try:
            docker_networks = self.client.networks.list()

            for network in docker_networks:
                try:
                    # Reload the network to get detailed information including containers
                    network.reload()

                    # Get network configuration details
                    config = network.attrs.get("IPAM", {}).get("Config", [])
                    subnet = config[0].get("Subnet", "N/A") if config else "N/A"

                    # Get connected containers
                    connected_containers = []
                    connected_stacks = set()

                    containers = network.attrs.get("Containers", {})
                    logger.debug(
                        f"Network {network.name} has {len(containers)} connected containers"
                    )

                    for container_id, container_info in containers.items():
                        try:
                            # Get the actual container object to access labels
                            container_obj = self.client.containers.get(container_id)
                            container_name = container_info.get(
                                "Name", container_obj.name
                            )

                            # Determine stack from container labels
                            stack_name = container_obj.labels.get(
                                "com.docker.compose.project", "ungrouped"
                            )
                            connected_stacks.add(stack_name)

                            container_data = {
                                "id": container_id[:12],
                                "name": container_name,
                                "stack": stack_name,
                                "ip": (
                                    container_info.get("IPv4Address", "").split("/")[0]
                                    if container_info.get("IPv4Address")
                                    else "N/A"
                                ),
                            }
                            connected_containers.append(container_data)
                            logger.debug(
                                f"Added container to network {network.name}: {container_data}"
                            )
                        except Exception as container_error:
                            logger.error(
                                f"Error processing connected container {container_id}: {str(container_error)}",
                                exc_info=True,
                            )
                            continue

                    networks[network.name] = {
                        "id": network.short_id,
                        "name": network.name,
                        "driver": network.attrs.get("Driver", "unknown"),
                        "scope": network.attrs.get("Scope", "local"),
                        "subnet": subnet,
                        "connected_containers": connected_containers,
                        "connected_stacks": connected_stacks,
                        "total_containers": len(connected_containers),
                    }

                except Exception as network_error:
                    logger.error(
                        f"Error processing network {network.name}: {str(network_error)}",
                        exc_info=True,
                    )
                    continue

        except Exception as e:
            error_msg = f"Error getting networks: {str(e)}"
            logger.error(error_msg, exc_info=True)
            self.last_error = error_msg
            return {}

        return networks

    def execute_stack_command(
        self, stack_name: str, config_file: str, command: str
    ) -> bool:
        """Execute a command on a Docker Compose stack.

        Args:
            stack_name: Name of the stack to operate on
            config_file: Path to the compose configuration file
            command: Command to execute (start, stop, restart, recreate)

        Returns:
            bool: True if successful, False otherwise
        """
        try:
            # For start/stop/restart, use SDK to operate on all containers in the stack
            if command in ["start", "stop", "restart"]:
                logger.info(
                    f"Executing {command} on all containers in stack: {stack_name}"
                )

                # Get all containers for this stack
                stacks = self.get_compose_stacks()
                stack_info = stacks.get(stack_name)

                if not stack_info:
                    error_msg = f"Stack '{stack_name}' not found"
                    logger.error(error_msg)
                    self.last_error = error_msg
                    return False

                # Use threading to execute commands on all containers concurrently
                def run_stack_command():
                    try:
                        threads = []
                        errors = []

                        def execute_on_container(container):
                            try:
                                if command == "start":
                                    container.start()
                                elif command == "stop":
                                    container.stop()
                                elif command == "restart":
                                    container.restart()
                                logger.debug(
                                    f"Successfully {command}ed container {container.name}"
                                )
                            except Exception as e:
                                error_msg = f"Error {command}ing container {container.name}: {str(e)}"
                                logger.error(error_msg)
                                errors.append(error_msg)

                        # Create threads for each container
                        for container in stack_info["containers"]:
                            thread = threading.Thread(
                                target=execute_on_container, args=(container,)
                            )
                            thread.daemon = True
                            threads.append(thread)
                            thread.start()

                        # Wait for all threads to complete
                        for thread in threads:
                            thread.join(timeout=10.0)

                        if errors:
                            self.last_error = "; ".join(errors)
                            logger.error(
                                f"Errors during stack {command}: {self.last_error}"
                            )

                    except Exception as e:
                        logger.error(
                            f"Error in stack command thread: {str(e)}", exc_info=True
                        )

                # Run the command in a separate thread to avoid blocking
                thread = threading.Thread(target=run_stack_command)
                thread.daemon = True
                thread.start()

                return True

            # For recreate, use subprocess but only if compose file is accessible
            elif command == "recreate":
                # Check if we can recreate this stack
                if not self._check_compose_file_accessible(config_file):
                    error_msg = f"Cannot recreate stack '{stack_name}': compose file not accessible"
                    logger.error(error_msg)
                    self.last_error = error_msg
                    return False

                cmd = ["docker", "compose", "-p", stack_name]

                # Add config file(s) if provided and not 'N/A'
                if config_file and config_file != "N/A":
                    # Config files are comma-separated
                    for cf in config_file.split(","):
                        cmd.extend(["-f", cf.strip()])

                cmd.extend(["up", "-d"])
                logger.info(f"Executing stack recreate command: {' '.join(cmd)}")

                # Use Popen to run the command in the background
                process = subprocess.Popen(
                    cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
                )

                # We don't wait for the process to complete to keep the UI responsive
                return True
            else:
                error_msg = f"Unknown stack command: {command}"
                logger.error(error_msg)
                self.last_error = error_msg
                return False

        except Exception as e:
            error_msg = f"Error executing stack command: {str(e)}"
            logger.error(error_msg, exc_info=True)
            self.last_error = error_msg
            return False
