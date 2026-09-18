"""CloudOps Sentinel: Enterprise SRE & FinOps Multi-Agent System built with Google ADK."""

from sentinel_agent.agent.adk_agent import app, root_agent, sub_agents
from sentinel_agent.agent.core import CloudOpsSentinelOrchestrator, StrategicModelRouter

__version__ = "1.0.0"

__all__ = [
    "CloudOpsSentinelOrchestrator",
    "StrategicModelRouter",
    "__version__",
    "app",
    "root_agent",
    "sub_agents",
]
