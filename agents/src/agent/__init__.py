"""New LangGraph Agent.

This module defines a custom graph.
"""

# Make the compiled graph available when importing the 'agent' package
from .graph import companion_agent_graph
from .proactive_graph import proactive_message_graph
from .tools import ReactionTool

__all__ = ["companion_agent_graph", "proactive_message_graph", "ReactionTool"]
