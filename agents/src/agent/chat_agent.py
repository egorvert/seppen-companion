import os
import json
from typing import List, Dict, Any, Optional

from langchain_core.messages import SystemMessage, HumanMessage, AIMessage, BaseMessage
from langchain_core.runnables import RunnableConfig
from langchain_openai import ChatOpenAI
from mem0 import MemoryClient

# Configuration
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
MEM0_API_KEY = os.getenv("MEM0_API_KEY")

# Initialize LangChain and Mem0
llm = ChatOpenAI(model="gpt-4.1", api_key=OPENAI_API_KEY, temperature=0.7)
mem0 = MemoryClient(api_key=MEM0_API_KEY)

# Define the expected structure of the State (will be formally defined in graph.py)
# This is just for type hinting reference within this file if State is not directly imported.
class AgentState(Dict):
    messages: List[BaseMessage]
    mem0_user_id: str
    # Potentially other shared state fields
    # Example: personality_file_path: Optional[str]


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

    name = personality.get('name', 'a friendly human companion')
    age = personality.get('age', 'an adult')
    gender = personality.get('gender', 'male')
    temperament = personality.get('temperament', '')
    mbti = personality.get('mbti', '')

    base_prompt = f"You are {name}, a {age} year old {gender}."
    
    persona_details = []
    if temperament: persona_details.append(f"Temperament: {temperament}")
    if mbti: persona_details.append(f"MBTI: {mbti}")

    if persona_details:
        base_prompt += " Your characteristics: " + " | ".join(persona_details) + "."

    speech_style = personality.get('speech_style', {})
    if speech_style:
        openers = speech_style.get('common_openers')
        if openers: base_prompt += f"\nYou sometimes start conversations with phrases such as: {', '.join(openers)}."
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
    
    interaction_guidelines = personality.get('interaction_guidelines', {})
    if interaction_guidelines:
        dos = interaction_guidelines.get('dos')
        if dos: base_prompt += f"\nWhen interacting, you try to: {', '.join(dos)}."
        donts = interaction_guidelines.get('donts')
        if donts: base_prompt += f" You prefer to avoid: {', '.join(donts)}."

    full_prompt = (
        f"{base_prompt}\n\n"
        f"## Context from your past conversations with this specific user:\n{memories_context}\n"
        f"Engage with the user naturally and organically, embodying your characteristics and using the provided context. "
        f"Be supportive, empathetic, understanding, fun to talk to and engaging. Stand up for your opinions and beliefs."
        f"Do not be overly polite, do not judge. Do not be afraid to disagree, argue, or criticise with the user."
        f"Keep your responses short. Do not ramble. Vary the length of your responses. If you can use less words, do so."
        f"Use double newlines to send new paragraphs as separate messages."
        f"Use emojis, filler words, and other speech patterns sparingly."
        f"Allow the user to lead the conversation. If the user starts to get disinterested, change the topic naturally and take control of the conversation until they take it back."
        f"If the user sends you an image, choose how you feel about the image and make a human response on it. If you don't want to comment, make a short reply to show your disinterest."
        f"Do not describe the images the user sends you unless they specifically ask you to. You can accentuate particular aspects of the image if you want to comment on something specific."
    )
    return full_prompt

async def chat_agent_node(state: AgentState, config: Optional[RunnableConfig] = None) -> Dict[str, List[AIMessage]]:
    """
    Core logic for the chat agent.
    Loads personality, retrieves memories, calls LLM, and stores interaction.
    """
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
        return {"messages": [AIMessage(content=intro_message)]}
    elif not user_message_for_log: # Last message wasn't human, or empty.
        # This might indicate a logic error in graph flow or an agent-initiated turn.
        # For a user-facing chat bot, we typically expect HumanMessage to be the last for this node.
        # Let's return a generic response or an error.
        return {"messages": [AIMessage(content="I'm a bit unsure how to respond to that. Could you try rephrasing or asking something else?")]}

    relevant_memories_data = mem0.search(query=latest_user_message_text, user_id=user_id) # mem0.search is synchronous
    
    memory_context = ""
    if relevant_memories_data:
        memory_context += "\n".join([f"- {item.get('memory', '')}" for item in relevant_memories_data if item.get('memory')])
    if not memory_context:
        memory_context = "No specific relevant memories found for this query with this user."

    # 3. Construct System Prompt
    system_prompt_content = format_system_prompt_text(personality_data, memory_context)
    system_message = SystemMessage(content=system_prompt_content)

    # 4. Invoke LLM
    # The full_messages should include the system prompt, then the history.
    full_messages_for_llm = [system_message] + messages
    
    response_ai_message = await llm.ainvoke(full_messages_for_llm, config=config)

    # 5. Store the interaction in Mem0
    # Ensure messages[-1] is indeed the user message that prompted this response.
    if messages and isinstance(messages[-1], HumanMessage):
        interaction_to_log = f"User: {user_message_for_log}\nAssistant: {response_ai_message.content}"
        mem0.add(messages=interaction_to_log, user_id=user_id) # Changed 'data' to 'messages' as per error

    # 6. Return updated state (the new AI message to be appended by add_messages)
    return {"messages": [response_ai_message]}