"""CloudOps Sentinel: Enterprise SRE & FinOps Multi-Agent System built with Google ADK."""

from sentinel_agent.agent.adk_agent import app, root_agent, sub_agents
from sentinel_agent.agent.core import CloudOpsSentinelOrchestrator, StrategicModelRouter
from sentinel_agent.infrastructure_iac import (
    TERRAFORM_MAIN_HCL,
    TERRAFORM_OUTPUTS_HCL,
    TERRAFORM_VARIABLES_HCL,
    build_terraform_json_manifest,
)

__version__ = "1.0.0"

__all__ = [
    "TERRAFORM_MAIN_HCL",
    "TERRAFORM_OUTPUTS_HCL",
    "TERRAFORM_VARIABLES_HCL",
    "CloudOpsSentinelOrchestrator",
    "StrategicModelRouter",
    "__version__",
    "app",
    "build_terraform_json_manifest",
    "root_agent",
    "sub_agents",
]
