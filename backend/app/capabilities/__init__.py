"""Capability registry, dependency resolution and the Capability Center service (W1-REG)."""

from app.capabilities.registry import REGISTRY, REGISTRY_BY_ID, REGISTRY_IDS, CapabilityDef, get_capability

__all__ = ["REGISTRY", "REGISTRY_BY_ID", "REGISTRY_IDS", "CapabilityDef", "get_capability"]
