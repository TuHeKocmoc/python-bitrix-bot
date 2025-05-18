import os
from prometheus_client import Counter, start_http_server

# Counter for executed commands
command_counter = Counter(
    'bot_commands_total',
    'Total number of executed bot commands',
    ['command']
)

# Counter for created tasks
tasks_created_counter = Counter(
    'bot_tasks_created_total',
    'Total number of tasks created via the bot'
)


def setup_metrics() -> None:
    """Start Prometheus metrics HTTP server."""
    port = int(os.getenv('METRICS_PORT', '8000'))
    start_http_server(port)


def observe_command(command: str) -> None:
    """Increment counter for a specific command."""
    command_counter.labels(command=command).inc()


def observe_task_created() -> None:
    """Increment counter for created tasks."""
    tasks_created_counter.inc()
