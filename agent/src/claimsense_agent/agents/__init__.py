"""The four ClaimSense agents, run by pipeline code in this order:

    reader → coverage → risk → drafter

Each agent has its own OBO token and reaches data only through the MCP server. `mock` holds
deterministic stand-ins that call the real tools but replace the model with simple rules.
"""
