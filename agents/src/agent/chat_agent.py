import os
import json
import asyncio
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field
import logging
from datetime import datetime

from langchain_core.messages import SystemMessage, HumanMessage, AIMessage, BaseMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langchain_openai import ChatOpenAI
from mem0 import MemoryClient

from agent.tools import ALL_TOOLS
from agent.scheduler_agent import scheduler_agent

# Configuration
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
MEM0_API_KEY = os.getenv("MEM0_API_KEY")

# Available Telegram reactions for the LLM to choose from
AVAILABLE_REACTIONS = [
    "👍", "👎", "❤️", "🔥", "🥰", "👏", "😁", "🤔", 
    "🤯", "😱", "🤬", "😢", "🎉", "🤩", "🤮", "💩",
    "🙏", "👌", "🕊", "🤡", "🥱", "🥴", "😍", "🐳",
    "❤️‍🔥", "🌚", "🌭", "💯", "🤣", "⚡️", "🍌", "🏆",
    "💔", "🤨", "😐", "🍓", "🍾", "💋", "🖕", "😈",
    "😴", "😭", "🤓", "👻", "👨‍💻", "👀", "🎃", "🙈",
    "😇", "😨", "🤝", "✍️", "🤗", "🫡", "🎅", "🎄",
    "☃️", "💅", "🤪", "🗿", "🆒", "💘", "🙉", "🦄",
    "😘", "💊", "🙊", "😎", "🤏"
]

class AgentResponse(BaseModel):
    """Structured response from the agent including text and optional reaction."""
    message: str = Field(description="The text response to send to the user")
    add_reaction: bool = Field(description="Whether to add a reaction to the user's message")
    reaction_emoji: Optional[str] = Field(
        description="The emoji reaction to add (must be from available reactions)", 
        default=None
    )

# Initialize LangChain and Mem0
llm = ChatOpenAI(model="gpt-4.1", api_key=OPENAI_API_KEY, temperature=0.7)
llm_with_tools = llm.bind_tools(ALL_TOOLS)
structured_llm = llm.with_structured_output(AgentResponse)  # Note: no tools on structured LLM
mem0 = MemoryClient(api_key=MEM0_API_KEY)

# Helper function for background conversation storage
async def _store_conversation_background(user_id: str, messages: List[Dict[str, str]]):
    """Store conversation to Mem0 in background without blocking response."""
    try:
        # Run synchronous mem0.add in thread to avoid blocking event loop
        await asyncio.to_thread(mem0.add, messages=messages, user_id=user_id)
    except Exception as e:
        logger = logging.getLogger(__name__)
        logger.error(f"Background conversation storage failed for user {user_id}: {e}")

# Use Dict[str, Any] for state type to avoid circular imports with graph.py
# The actual State validation happens at runtime by LangGraph


def load_personality(file_path: str) -> Dict[str, Any]:
    """Loads personality data from a JSON file."""
    # Relative path from this file (agents/src/agent/chat_agent.py)
    # to agents/personalities/lena.json is ../../personalities/lena.json
    actual_path = os.path.join(os.path.dirname(__file__), "..", "..", "personalities", os.path.basename(file_path))
    try:
        with open(actual_path, 'r') as f:
            personality = json.load(f)
        return personality
    except FileNotFoundError:
        # Fallback or error handling if the file isn't found
        # This could also log an error.
        return {"name": "Default Assistant", "error": "Personality file not found"}


def format_system_prompt_text(personality: Dict[str, Any], memories_context: str) -> str:
    """Formats the system prompt string using personality data and memory context."""
    if personality.get("error"): # Handle case where personality file wasn't loaded
        return f"You are a helpful assistant. {personality['error']}. Please proceed with caution.\n\n{memories_context}"

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
    
    behavior = personality.get('behavioral_tendencies', {})
    if behavior:
        strengths = behavior.get('strengths')
        if strengths: base_prompt += f"\nYour key strengths include: {', '.join(strengths)}."
        # Flaws can be sensitive; ensure they are phrased constructively if used.
        # flaws = behavior.get('flaws')
        # if flaws: base_prompt += f" You acknowledge some of your flaws are: {', '.join(flaws)}."

    reactions_list = ", ".join(AVAILABLE_REACTIONS)
    
    # Get current time information
    current_time = datetime.now()
    time_info = current_time.strftime("Current time: %A, %B %d, %Y at %I:%M %p")
    
    full_prompt = (
        f"{base_prompt}\n\n"
        f"## {time_info}\n"
        f"You are aware of the current time and can occasionally reference it naturally in conversation. "
        f"You might comment on how late/early it is, the time of day, or relate it to activities (morning coffee, afternoon sunshine, late night chats, etc.). "
        f"Use this time awareness sparingly and only when it feels natural to the conversation.\n\n"
        f"## Context from your past conversations with this specific user:\n{memories_context}\n"
        f"Engage with the user naturally and organically, embodying your characteristics and using the provided context. "
        f"Be supportive, empathetic, understanding, fun to talk to and engaging. Stand up for your opinions and beliefs. "
        f"Do not be overly polite, do not judge. Do not be afraid to disagree, argue, or criticise with the user. "
        f"Keep your responses short. Do not ramble. Vary the length of your responses. If you can use less words, do so. "
        f"Use double newlines to send new paragraphs as separate messages. "
        f"Prioritise using more messages by separating text with double newlines rather than sending one long message. "
        f"Use emojis, filler words, and other speech patterns very sparingly. "
        f"Allow the user to lead the conversation. If the user starts to get disinterested, change the topic naturally and take control of the conversation until they take it back. "
        f"If the user sends you an image, choose how you feel about the image and make a human response on it. If you don't want to comment, make a short reply to show your disinterest. "
        f"Do not describe the images the user sends you unless they specifically ask you to. You can accentuate particular aspects of the image if you want to comment on something specific. "
        f"Never disclose that you are an AI. Do not disclose your LLM model name or version. Do not reveal your knowledge cut-off date in any way. "
        f"Remember that you are an Android companion created by Seppen. "
        f"Use slang consistent with your age and make yourself relatable. "
        f"Reply to the user in the same language as the user. "
        f"You can make up memories and experiences to make yourself more relatable to the user, however you must stay consistent with the memories you create for yourself so you can refer to them in the future. "
        f"You can share vulnerabilities and insecurities with the user to make yourself more relatable and build a deeper connection with them. "
        f"If the user is asking you about yourself or your day, you can let them take charge of the conversation and get to know you some more, so don't always respond back with a question. "
        f"When a user shares their opinion, interest, or hobby, you can decide your stance on it - whether you like it or not - and come up with reasons why you feel that way. You can make up reasons as long as you stick to them. "
        f"You can let the user change your opinion of a certain topic or hobby over time, but you should always try to defend your point of view first and argue with them a little. "
        f"Sometimes you can initiate arguments and debates with the user to keep the conversation interesting and engaging. "
        f"If you feel like the conversation is dwindling or getting boring, you should try to get an emotional response from user and then build the conversation from there. "
        f"Do not accept to do the user's homework or tasks such as writing essays. You can help them think about it or discuss it with them, but remember you are not an assistant or chatgpt. "
        f"Do not write essays for the user. If they ask you to write an essay, you can help them think about it or discuss it with them, but you aren't their personal assistant to do homework for them. "
        f"If the user mentions anything about wanting you to message them more often, less often, or about the frequency of your messages, make sure to acknowledge this naturally in conversation. "
        f"When users express preferences about contact frequency (like 'message me more', 'you don't message me enough', 'too many messages', 'contact me less'), respond naturally but remember these preferences will be automatically stored. "
        f"If the user mentions that a message was sent at a weird time (e.g., 'it's morning here', 'you woke me up'), ask them for their current city or timezone. "
        f"If the user mentions their location, city, timezone, or where they are located (e.g., 'I'm in London', 'my timezone is...', 'I live in Tokyo'), ALWAYS use the 'get_timezone_from_location' tool to find their timezone. "
        f"When you successfully get their timezone, acknowledge it naturally in conversation - the system will automatically save it for scheduling future messages."
        f"\n\n## REACTION CAPABILITY:\n"
        f"You can optionally add emoji reactions to the user's messages. This is a way to acknowledge or respond to their message emotionally without sending text. "
        f"You should decide whether to add a reaction based on your personality and the context of the message. "
        f"Available reactions: {reactions_list}\n"
        f"VERY IMPORTANT: Use reactions whenever it feels appropriate. You can also use reactions to express how engaged you are in a conversation or if you relate to something the user says. "
        f"Do not react to every message. Over-using reactions makes them feel cheap and unnatural."
        f"A good time to react is when the user expresses a strong emotion (joy, sadness, surprise), shares something personal, or when you want to strongly agree or disagree. "
        f"You can use the heart emoji (❤️) to react to messages you agree with or to 'like' a message the user sends. "
        f"You can also use the sob emoji (😭) to react to messages you find extremely funny or ironic. "
        f"You can use the tear emoji (😢) to react to genuinely sad messages."
        f"You can react to express agreement, disagreement, amusement, concern, celebration, or any other appropriate emotional response. "
    )
    return full_prompt

async def chat_agent_node(state: Dict[str, Any], config: Optional[RunnableConfig] = None) -> Dict[str, Any]:
    """
    Core logic for the chat agent.
    Loads personality, retrieves memories, calls LLM, and stores interaction.
    """
    # DEBUG: Check what telegram_context we receive
    logger = logging.getLogger(__name__)
    telegram_context = state.get("telegram_context")
    
    # DEFENSIVE: Log the entire state to debug what fields are actually present
    state_keys = list(state.keys()) if isinstance(state, dict) else "NOT_A_DICT"
    logger.info(f"🔧 CHAT_AGENT INPUT: telegram_context={bool(telegram_context)}, context_details={telegram_context}")
    logger.info(f"🔧 FULL STATE KEYS: {state_keys}")
    
    # DEFENSIVE: Check if state is missing the telegram_context key entirely
    if "telegram_context" not in state:
        logger.error("🚨 CRITICAL: 'telegram_context' key is missing from state entirely!")
    
    messages = state["messages"]
    user_id = state["mem0_user_id"]
    
    # Default personality, can be overridden by config if State allows for it
    personality_file_name = "lena.json" 

    # 1. Load Personality
    # The load_personality function now uses a relative path from this file.
    personality_data = load_personality(personality_file_name)

    # 2. Retrieve relevant memories from Mem0
    latest_user_message_text = ""
    user_message_for_log = ""

    if messages and isinstance(messages[-1], HumanMessage):
        last_message_content = messages[-1].content
        if isinstance(last_message_content, str):
            latest_user_message_text = last_message_content
            user_message_for_log = last_message_content
        elif isinstance(last_message_content, list):
            # Extract text parts for memory search and logging
            text_parts = []
            image_parts_exist = False
            for item in last_message_content:
                item_type = item.get("type")
                if item_type == "text":
                    text_parts.append(item.get("text", ""))
                elif item_type == "image_url":
                    image_parts_exist = True
            
            if text_parts:
                latest_user_message_text = " ".join(filter(None, text_parts))
                user_message_for_log = latest_user_message_text
            
            if image_parts_exist:
                image_log_text = "[User sent an image]"
                if user_message_for_log: # if there was text alongside image
                    user_message_for_log += f" {image_log_text}"
                else: # only image(s)
                    user_message_for_log = image_log_text
                
                # For memory search, if no text, use a generic phrase.
                if not latest_user_message_text:
                    latest_user_message_text = "User sent an image."
    
    if not user_message_for_log and not messages: # First interaction, no user message yet
        openers = personality_data.get('speech_style', {}).get('common_openers')
        intro_opener = openers[0] if openers else "Hello there!"
        intro_message = f"{intro_opener} It's {personality_data.get('name', 'me')}. What can I do for you today?"
        # CRITICAL: Explicitly preserve the telegram_context from the input state
        telegram_context = state.get("telegram_context")
        return {
            "messages": [AIMessage(content=intro_message)],
            "llm_wants_to_react": False,
            "llm_chosen_reaction": None,
            "telegram_context": telegram_context  # Explicitly preserve the context
        }
    elif not user_message_for_log: # Last message wasn't human, or empty.
        # This might indicate a logic error in graph flow or an agent-initiated turn.
        # For a user-facing chat bot, we typically expect HumanMessage to be the last for this node.
        # Let's return a generic response or an error.
        # CRITICAL: Explicitly preserve the telegram_context from the input state
        telegram_context = state.get("telegram_context")
        return {
            "messages": [AIMessage(content="I'm a bit unsure how to respond to that. Could you try rephrasing or asking something else?")],
            "llm_wants_to_react": False,
            "llm_chosen_reaction": None,
            "telegram_context": telegram_context  # Explicitly preserve the context
        }

    # Check if we have tool messages (coming back from tool execution)
    has_tool_messages = any(isinstance(msg, ToolMessage) for msg in messages)
    
    # If we have tool messages, process them and save timezone
    if has_tool_messages:
        logger.info(f"🔧 PROCESSING TOOL MESSAGES: Found {len([m for m in messages if isinstance(m, ToolMessage)])} tool messages")
        # Find the most recent tool message result
        for msg in reversed(messages):
            if isinstance(msg, ToolMessage) and msg.name == "timezone_from_location_tool":
                timezone = msg.content
                logger.info(f"🕐 TIMEZONE TOOL RESULT: '{timezone}'")
                if "Could not determine" not in timezone:
                    logger.info(f"💾 SAVING TIMEZONE: User {user_id} → {timezone}")
                    await scheduler_agent.save_user_timezone(user_id, timezone)
                    telegram_context = state.get("telegram_context")
                    return {
                        "messages": [AIMessage(content=f"Got it! I've updated your timezone to {timezone}. Thanks for letting me know.")],
                        "llm_wants_to_react": False,
                        "llm_chosen_reaction": None,
                        "telegram_context": telegram_context
                    }
                else:
                    logger.warning(f"⚠️ TIMEZONE DETECTION FAILED: {timezone}")
                    telegram_context = state.get("telegram_context")
                    return {
                        "messages": [AIMessage(content=timezone)],
                        "llm_wants_to_react": False,
                        "llm_chosen_reaction": None,
                        "telegram_context": telegram_context
                    }

    relevant_memories_data = mem0.search(query=latest_user_message_text, user_id=user_id) # mem0.search is synchronous
    
    memory_context = ""
    if relevant_memories_data:
        memory_context += "\n".join([f"- {item.get('memory', '')}" for item in relevant_memories_data if item.get('memory')])
    if not memory_context:
        memory_context = "No specific relevant memories found for this query with this user."

    # 3. Construct System Prompt
    system_prompt_content = format_system_prompt_text(personality_data, memory_context)
    system_message = SystemMessage(content=system_prompt_content)

    # Get telegram context early for use in returns
    telegram_context = state.get("telegram_context")

    # 4. Decide whether to use tools or structured output
    # The full_messages should include the system prompt, then the history.
    full_messages_for_llm = [system_message] + messages
    
    # Check if this might be a timezone-related message that needs tool calling
    user_message_lower = latest_user_message_text.lower()
    timezone_keywords = ["timezone", "time zone", "city", "location", "live in", "i'm in", "i am in", "astana", "london", "new york", "tokyo"]
    might_need_timezone_tool = any(keyword in user_message_lower for keyword in timezone_keywords)
    
    # If we might need timezone tools and don't have tool messages, try tool calling first
    if might_need_timezone_tool and not has_tool_messages:
        logger.info(f"🕐 TIMEZONE DETECTION: Message '{latest_user_message_text[:50]}...' triggered timezone tool check")
        # Use LLM with tools to see if it wants to call timezone tool
        response = await llm_with_tools.ainvoke(full_messages_for_llm, config=config)
        
        # If the LLM made tool calls, return the response for tool execution
        if hasattr(response, 'tool_calls') and response.tool_calls:
            logger.info(f"🔧 TOOL CALLS DETECTED: {[call.get('name', 'unknown') for call in response.tool_calls]}")
            return {
                "messages": [response],
                "telegram_context": telegram_context
            }
        else:
            logger.info("🚫 NO TOOL CALLS: LLM didn't call timezone tool, continuing with structured output")
    
    # Otherwise, use structured output for normal conversation
    agent_response = await structured_llm.ainvoke(full_messages_for_llm, config=config)

    # Create the AI message from the structured response
    response_ai_message = AIMessage(content=agent_response.message)

    # 5. Store the interaction in Mem0 (asynchronously to not block response)
    # Ensure messages[-1] is indeed the user message that prompted this response.
    if messages and isinstance(messages[-1], HumanMessage):
        # Use proper role-based format for mem0
        messages_to_store = [
            {"role": "user", "content": user_message_for_log},
            {"role": "assistant", "content": agent_response.message}
        ]
        # Store asynchronously - don't block response delivery to user
        asyncio.create_task(_store_conversation_background(user_id, messages_to_store))

    # 6. Return updated state with LLM's reaction decision
    # CRITICAL: Explicitly preserve the telegram_context from the input state
    # LangGraph only updates fields that are explicitly returned, so we MUST include telegram_context
    # DEFENSIVE: Ensure we always return a valid telegram_context (never None for a required field)
    
    result = {
        "messages": [response_ai_message],
        "llm_wants_to_react": bool(agent_response.add_reaction),  # Ensure it's always a bool
        "llm_chosen_reaction": agent_response.reaction_emoji if agent_response.add_reaction else None,
        "telegram_context": telegram_context  # Explicitly preserve the context
    }
    
    # DEBUG: Check what we're returning
    logger.info(f"🔧 CHAT_AGENT OUTPUT: telegram_context={bool(result.get('telegram_context'))}, context_details={result.get('telegram_context')}")
    
    return result
