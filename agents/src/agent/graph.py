"""LangGraph graph for the chat agent.

This graph manages the conversation flow, integrating with Mem0 for memory
and loading a personality for the AI companion.
"""

from __future__ import annotations

from typing import List, TypedDict, Annotated

from langchain_core.messages import BaseMessage
from langgraph.graph import StateGraph, END
from langgraph.graph.message import add_messages

from .chat_agent import chat_agent_node

class State(TypedDict):
    """Shared state for the graph."""
    messages: Annotated[List[BaseMessage], add_messages]
    mem0_user_id: str

graph_builder = StateGraph(State)

graph_builder.add_node("chat_agent", chat_agent_node)

graph_builder.set_entry_point("chat_agent")

graph_builder.add_edge("chat_agent", END)

companion_agent_graph = graph_builder.compile(name="AICompanionChat")
