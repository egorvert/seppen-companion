"""LangGraph graph for the chat agent.

This graph manages the conversation flow, integrating with Mem0 for memory
and loading a personality for the AI companion.
"""

from __future__ import annotations

import logging
from typing import List, TypedDict, Annotated, Optional, Dict, Any

from langchain_core.messages import BaseMessage
from langgraph.graph import StateGraph, END
from langgraph.graph.message import add_messages

from .chat_agent import chat_agent_node
from .reaction_node import should_add_reaction, add_reaction_node

# Set up logging for this module
logger = logging.getLogger(__name__)

class RequiredState(TypedDict):
    """Required fields for the graph state."""
    messages: Annotated[List[BaseMessage], add_messages]
    mem0_user_id: str

class OptionalState(TypedDict, total=False):
    """Optional fields for the graph state."""
    telegram_context: Optional[Dict[str, Any]]  # Contains chat_id, message_id, etc. (bot passed via config)
    llm_wants_to_react: bool  # Whether LLM decided to add a reaction
    llm_chosen_reaction: Optional[str]  # Which reaction LLM chose
    reaction_result: Optional[Dict[str, Any]]  # Result of reaction attempt

class State(RequiredState, OptionalState):
    """Shared state for the graph - combines required and optional fields."""
    pass

graph_builder = StateGraph(State)

# Add nodes
graph_builder.add_node("chat_agent", chat_agent_node)
graph_builder.add_node("add_reaction", add_reaction_node)

# Set entry point
graph_builder.set_entry_point("chat_agent")

# Add conditional edge from chat_agent to either add_reaction or END
graph_builder.add_conditional_edges(
    "chat_agent",
    should_add_reaction,
    {
        "add_reaction": "add_reaction",
        "end": END
    }
)

# After adding reaction, end the conversation
graph_builder.add_edge("add_reaction", END)

companion_agent_graph = graph_builder.compile(name="AICompanionChat")
