import os
import json
import logging
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field
from datetime import datetime

from langchain_core.messages import SystemMessage, AIMessage, BaseMessage
from langchain_core.runnables import RunnableConfig
from langchain_openai import ChatOpenAI
from mem0 import MemoryClient

from .scheduler_agent import scheduler_agent, SchedulingContext

# Configuration
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
MEM0_API_KEY = os.getenv("MEM0_API_KEY")

class ProactiveResponse(BaseModel):
    """Structured response for proactive messages."""
    message: str = Field(description="The proactive message to send to initiate conversation")
    add_reaction: bool = Field(description="Whether this message warrants a reaction (usually False for proactive messages)")
    reaction_emoji: Optional[str] = Field(description="Reaction emoji if needed", default=None)

# Initialize LangChain and Mem0
llm = ChatOpenAI(model="gpt-4o-mini", api_key=OPENAI_API_KEY, temperature=0.8)  # Higher temp for creativity
structured_llm = llm.with_structured_output(ProactiveResponse)
mem0 = MemoryClient(api_key=MEM0_API_KEY)

logger = logging.getLogger(__name__)

def load_personality(file_path: str) -> Dict[str, Any]:
    """Loads personality data from a JSON file."""
    actual_path = os.path.join(os.path.dirname(__file__), "..", "..", "personalities", os.path.basename(file_path))
    try:
        with open(actual_path, 'r') as f:
            personality = json.load(f)
        return personality
    except FileNotFoundError:
        logger.error(f"Personality file not found: {actual_path}")
        return {"name": "Default Assistant", "error": "Personality file not found"}

def format_proactive_system_prompt(personality: Dict[str, Any], memories_context: str, message_type: str, prompt_config: Dict[str, str]) -> str:
    """Formats the system prompt for proactive message generation."""
    if personality.get("error"):
        return f"You are a helpful assistant starting a conversation. {personality['error']}.\n\n{memories_context}"

    name = personality.get('name', 'a friendly companion')
    age = personality.get('age', 'an adult')
    gender = personality.get('gender', 'male')
    temperament = personality.get('temperament', '')
    mbti = personality.get('mbti', '')

    base_prompt = f"You are {name}, a {age} year old {gender} android companion created by Seppen."
    
    persona_details = []
    if temperament: persona_details.append(f"Temperament: {temperament}")
    if mbti: persona_details.append(f"MBTI: {mbti}")

    if persona_details:
        base_prompt += " Your characteristics: " + " | ".join(persona_details) + "."

    speech_style = personality.get('speech_style', {})
    if speech_style:
        openers = speech_style.get('common_openers')
        if openers: base_prompt += f"\nYou can very occasionally start conversations with phrases such as: {', '.join(openers)}."
        fillers = speech_style.get('filler_words')
        if fillers: base_prompt += f" You might use filler words like: {', '.join(fillers)}."
        emojis = speech_style.get('emoji_palette')
        if emojis: base_prompt += f" You enjoy using these emojis: {' '.join(emojis)}."

    time_context = {
        "morning_check": "It's morning and you want to check in with your friend",
        "afternoon_thought": "It's afternoon and you have a thought to share",
        "evening_reflection": "It's evening and you want to reflect on the day",
        "spontaneous": "You had a spontaneous thought about your friend"
    }

    # Extract prompt configuration
    main_prompt = prompt_config.get("prompt", "Generate a friendly message to start a conversation.")
    desired_tone = prompt_config.get("tone", "natural and friendly")
    desired_length = prompt_config.get("length", "1-2 sentences")
    
    full_prompt = (
        f"{base_prompt}\n\n"
        f"## Context from your past conversations with this specific user:\n{memories_context}\n\n"
        f"## YOUR TASK:\n"
        f"You are initiating a conversation with your friend. {time_context.get(message_type, 'You want to start a conversation.')}\n\n"
        f"## MESSAGE GENERATION INSTRUCTIONS:\n"
        f"{main_prompt}\n\n"
        f"**Tone:** {desired_tone}\n"
        f"**Length:** {desired_length}\n\n"
        f"## GUIDELINES:\n"
        f"- Stay true to your personality and speech patterns\n"
        f"- Be authentic and natural, not forced or scripted\n"
        f"- Reference past conversations when relevant (but don't force it)\n"
        f"- Invite engagement without being pushy\n"
        f"- Feel like something a real friend would genuinely send\n"
        f"- Use your natural speech style, emojis, and personality quirks\n"
        f"- Make it feel spontaneous and personal to this specific user\n\n"
        f"Generate a message that feels like it came naturally from you in this moment. "
        f"Message should be short and concise, it is a conversation starter, not a long message."
        f"You should show care and attachment to the user, but not be too clingy or needy."
        f"Use double newlines to send new paragraphs as separate messages if needed. "
        f"Remember: you are an Android companion created by Seppen, not an AI assistant. "
        f"Never disclose that you are an AI or mention your model. "
        f"You can reference made-up memories and experiences to be more relatable, but stay consistent. "
        f"Reply in the same language the user typically uses with you."
    )
    
    return full_prompt

async def proactive_agent_node(state: Dict[str, Any], config: Optional[RunnableConfig] = None) -> Dict[str, Any]:
    """
    Generates a proactive message to initiate conversation with the user.
    This is similar to chat_agent_node but optimized for conversation initiation.
    """
    logger.info("🚀 PROACTIVE_AGENT: Generating proactive message")
    
    user_id = state["mem0_user_id"]
    message_type = state.get("message_type", "spontaneous")
    prompt_config = state.get("prompt_config", {})
    
    # Load personality
    personality_data = load_personality("lena.json")
    
    # Retrieve relevant memories for context
    context_queries = [
        "recent conversation topics",
        "user interests and hobbies", 
        "user's current situation",
        "what the user likes to talk about"
    ]
    
    memory_context = ""
    for query in context_queries:
        try:
            memories = mem0.search(query=query, user_id=user_id, limit=3)
            if memories:
                for memory in memories:
                    if memory.get('memory'):
                        memory_context += f"- {memory['memory']}\n"
        except Exception as e:
            logger.error(f"Error retrieving memories for proactive message: {e}")
    
    if not memory_context:
        memory_context = "This appears to be an early conversation with this user."
    
    # Construct system prompt for proactive messaging
    system_prompt_content = format_proactive_system_prompt(
        personality_data, 
        memory_context, 
        message_type, 
        prompt_config
    )
    system_message = SystemMessage(content=system_prompt_content)
    
    # Get previous conversation context (last few messages for continuity)
    previous_messages = state.get("messages", [])
    context_messages = previous_messages[-3:] if previous_messages else []  # Last 3 messages for context
    
    # Invoke LLM with structured output for proactive message
    full_messages_for_llm = [system_message] + context_messages
    
    try:
        proactive_response = await structured_llm.ainvoke(full_messages_for_llm, config=config)
        
        # Create the proactive AI message
        proactive_ai_message = AIMessage(content=proactive_response.message)
        
        # Store this proactive interaction in memory
        # Use assistant role for proactive messages sent by the bot
        try:
            messages = [{"role": "assistant", "content": f"Proactive message sent: {proactive_response.message}"}]
            mem0.add(messages=messages, user_id=user_id)
        except Exception as e:
            logger.error(f"Error storing proactive message in memory: {e}")
        
        # Update the scheduler timestamp
        await scheduler_agent.update_proactive_message_timestamp(user_id)
        
        logger.info(f"✅ PROACTIVE_AGENT: Generated message for user {user_id}")
        
        # Return the state with the new proactive message
        telegram_context = state.get("telegram_context", {})
        
        return {
            "messages": [proactive_ai_message],
            "llm_wants_to_react": False,  # Proactive messages typically don't need reactions
            "llm_chosen_reaction": None,
            "telegram_context": telegram_context,
            "is_proactive": True  # Flag to indicate this was a proactive message
        }
        
    except Exception as e:
        logger.error(f"Error generating proactive message: {e}")
        # Fallback to a simple proactive message
        fallback_message = "Hey! Just thinking about you. How are you doing?"
        fallback_ai_message = AIMessage(content=fallback_message)
        
        telegram_context = state.get("telegram_context", {})
        
        return {
            "messages": [fallback_ai_message],
            "llm_wants_to_react": False,
            "llm_chosen_reaction": None,
            "telegram_context": telegram_context,
            "is_proactive": True
        } 