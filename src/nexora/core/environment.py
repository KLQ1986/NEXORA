"""Environment check: what the adapters report about the tools on this machine (design v4.0, section 23.3)."""
from nexora.core.adapter import AdapterRegistry


def report(adapters: AdapterRegistry) -> dict:
    out = {"adapters": [{"name": c.name, "operations": list(c.operations), "runs": c.runs} for c in adapters.describe()]}
    for name, probe in adapters.environment().items():
        out[name] = probe
    return out
