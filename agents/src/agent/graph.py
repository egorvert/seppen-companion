"""LangGraph graph for the chat agent.

This graph manages the conversation flow, integrating with Mem0 for memory
and loading a personality for the AI companion.
"""

from __future__ import annotations

import logging
from typing import List, TypedDict, Annotated, Optional, Dict, Any

from langchain_core.messages import BaseMessage, ToolMessage
from langgraph.graph import StateGraph, END
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode

from .chat_agent import chat_agent_node
from .reaction_node import should_add_reaction, add_reaction_node
from .tools import ALL_TOOLS

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

def should_use_tools(state: Dict[str, Any]) -> str:
    """Check if the last message has tool calls."""
    messages = state.get("messages", [])
    if messages and hasattr(messages[-1], 'tool_calls') and messages[-1].tool_calls:
        return "tools"
    return "check_reaction"

def should_check_tools_after_response(state: Dict[str, Any]) -> str:
    """After tools, always check for reactions."""
    return "check_reaction"

# Create tool node for handling tool calls
tool_node = ToolNode(ALL_TOOLS)

graph_builder = StateGraph(State)

# Add nodes
graph_builder.add_node("chat_agent", chat_agent_node)
graph_builder.add_node("tools", tool_node)
graph_builder.add_node("chat_agent_after_tools", chat_agent_node)  # Same function, different node for flow control
graph_builder.add_node("add_reaction", add_reaction_node)

# Set entry point
graph_builder.set_entry_point("chat_agent")

# Add conditional edge from chat_agent to check for tools first
graph_builder.add_conditional_edges(
    "chat_agent",
    should_use_tools,
    {
        "tools": "tools",
        "check_reaction": "check_reaction"
    }
)

# After tools, go to a separate chat_agent node for final response
graph_builder.add_edge("tools", "chat_agent_after_tools")

# After the post-tool chat agent, always check for reactions
graph_builder.add_edge("chat_agent_after_tools", "check_reaction")

# Add a separate node for the reaction check after tool handling
def check_reaction(state: Dict[str, Any]) -> Dict[str, Any]:
    """Pass-through node for reaction checking."""
    return state

graph_builder.add_node("check_reaction", check_reaction)

# Add conditional edge from reaction check to either add_reaction or END
graph_builder.add_conditional_edges(
    "check_reaction",
    should_add_reaction,
    {
        "add_reaction": "add_reaction",
        "end": END
    }
)

# After adding reaction, end the conversation
graph_builder.add_edge("add_reaction", END)

companion_agent_graph = graph_builder.compile(name="AICompanionChat")
