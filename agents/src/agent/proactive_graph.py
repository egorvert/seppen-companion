"""LangGraph graph for proactive messaging.

This graph manages proactive message generation, using the scheduler agent
to determine timing and the proactive agent to generate appropriate content.
"""

from __future__ import annotations

import logging
from typing import List, TypedDict, Annotated, Optional, Dict, Any

from langchain_core.messages import BaseMessage
from langgraph.graph import StateGraph, END
from langgraph.graph.message import add_messages

from .proactive_agent import proactive_agent_node

# Set up logging for this module
logger = logging.getLogger(__name__)

class ProactiveRequiredState(TypedDict):
    """Required fields for the proactive graph state."""
    mem0_user_id: str

class ProactiveOptionalState(TypedDict, total=False):
    """Optional fields for the proactive graph state."""
    messages: Annotated[List[BaseMessage], add_messages]
    telegram_context: Optional[Dict[str, Any]]  # Contains chat_id for sending
    message_type: str  # Type of proactive message (morning_check, etc.)
    prompt_config: Dict[str, str]  # Prompt configuration from scheduler
    is_proactive: bool  # Flag indicating this is a proactive message
    llm_wants_to_react: bool
    llm_chosen_reaction: Optional[str]

class ProactiveState(ProactiveRequiredState, ProactiveOptionalState):
    """Shared state for the proactive message graph."""
    pass

# Build the proactive message graph
proactive_graph_builder = StateGraph(ProactiveState)

# Add the proactive agent node
proactive_graph_builder.add_node("proactive_agent", proactive_agent_node)

# Set entry point to proactive agent
proactive_graph_builder.set_entry_point("proactive_agent")

# After generating proactive message, end the workflow
proactive_graph_builder.add_edge("proactive_agent", END)

# Compile the proactive message graph
proactive_message_graph = proactive_graph_builder.compile(name="ProactiveMessageGeneration") 