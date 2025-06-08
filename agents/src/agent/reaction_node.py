"""Reaction node for the agent graph.

This module contains the logic for determining when to add reactions
and executing the reaction tool.
"""

import logging
from typing import Dict, List, Any, Optional
from langchain_core.messages import HumanMessage, BaseMessage

from .tools import ReactionTool

logger = logging.getLogger(__name__)

# Initialize the reaction tool
reaction_tool = ReactionTool()

def should_add_reaction(state: Dict[str, Any]) -> str:
    """
    Determine whether the agent should add a reaction based on LLM's decision.
    
    This is a conditional edge function that decides the next node in the graph.
    
    Args:
        state: The current state of the conversation
        
    Returns:
        "add_reaction" if LLM decided to react, "end" if not
    """
    telegram_context = state.get("telegram_context")
    llm_wants_to_react = state.get("llm_wants_to_react", False)
    llm_chosen_reaction = state.get("llm_chosen_reaction")
    
    logger.info(f"🔎 REACTION CHECK: telegram_context={bool(telegram_context)}, llm_wants_to_react={llm_wants_to_react}, llm_chosen_reaction={llm_chosen_reaction}")
    
    # Only consider reacting if we have Telegram context
    if not telegram_context:
        logger.warning("No Telegram context available, skipping reaction")
        return "end"
    
    # Check if LLM decided to react and provided a valid reaction
    if llm_wants_to_react and llm_chosen_reaction:
        logger.info(f"🎯 REACTION DECISION: LLM chose to react with {llm_chosen_reaction}")
        return "add_reaction"
    else:
        if llm_wants_to_react and not llm_chosen_reaction:
            logger.warning("⚠️ LLM wanted to react but didn't provide a valid reaction emoji")
        else:
            logger.debug("🚫 LLM decided not to add a reaction")
        return "end"

async def add_reaction_node(state: Dict[str, Any], config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Add a reaction to the user's message using the LLM's chosen reaction.
    
    Args:
        state: The current state of the conversation
        config: Configuration containing the telegram bot instance
        
    Returns:
        Updated state with reaction result
    """
    telegram_context = state.get("telegram_context", {})
    llm_chosen_reaction = state.get("llm_chosen_reaction")
    
    if not llm_chosen_reaction:
        logger.warning("No reaction chosen by LLM")
        return {"reaction_result": {"success": False, "error": "No reaction chosen by LLM"}}
    
    # Extract Telegram context from state and bot from config
    bot = config.get("configurable", {}).get("telegram_bot") if config else None
    chat_id = telegram_context.get("chat_id")
    message_id = telegram_context.get("message_id")
    
    if not all([bot, chat_id, message_id]):
        logger.error(f"Missing Telegram context for reaction: bot={bool(bot)}, chat_id={chat_id}, message_id={message_id}")
        return {
            "reaction_result": {
                "success": False, 
                "error": f"Missing Telegram context: bot={bool(bot)}, chat_id={chat_id}, message_id={message_id}"
            }
        }
    
    # Execute the reaction with the LLM's chosen emoji
    try:
        logger.info(f"⚡ EXECUTING REACTION: Adding {llm_chosen_reaction} to message {message_id}")
        result = await reaction_tool.execute(bot, chat_id, message_id, llm_chosen_reaction)
        if result.get("success"):
            logger.info(f"✅ REACTION SUCCESS: {llm_chosen_reaction} added successfully")
        else:
            logger.warning(f"❌ REACTION FAILED: {result.get('error', 'Unknown error')}")
        return {"reaction_result": result}
    except Exception as e:
        logger.error(f"💥 REACTION ERROR: {e}")
        return {
            "reaction_result": {
                "success": False,
                "error": f"Error executing reaction: {str(e)}"
            }
        } 