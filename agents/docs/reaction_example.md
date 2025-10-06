# Reaction System Documentation

## Overview

The agent now has the ability to intelligently add emoji reactions to user messages. The LLM makes the decision about when and which reaction to add based on its understanding of the conversation context and the user's personality.

## How It Works

### 1. **LLM Decision Making**
- When the agent receives a message, it processes it with structured output
- The LLM decides whether to add a reaction (`add_reaction: boolean`)
- If yes, it chooses a specific emoji from the available reactions (`reaction_emoji: string`)

### 2. **Available Reactions**
The LLM can choose from these Telegram-supported reactions:
```
👍, 👎, ❤️, 🔥, 🥰, 👏, 😁, 🤔, 🤯, 😱, 🤬, 😢, 🎉, 🤩, 🤮, 💩,
🙏, 👌, 🕊, 🤡, 🥱, 🥴, 😍, 🐳, ❤️‍🔥, 🌚, 🌭, 💯, 🤣, ⚡️, 🍌, 🏆,
💔, 🤨, 😐, 🍓, 🍾, 💋, 🖕, 😈, 😴, 😭, 🤓, 👻, 👨‍💻, 👀, 🎃, 🙈,
😇, 😨, 🤝, ✍️, 🤗, 🫡, 🎅, 🎄, ☃️, 💅, 🤪, 🗿, 🆒, 💘, 🙉, 🦄,
😘, 💊, 🙊, 😎, 🤏
```

### 3. **Flow Control**
```
User Message → Chat Agent (LLM) → Decision Branch
                     ↓                    ↓
           Text Response Generated    Reaction Decision
                     ↓                    ↓
              Send Text Message      Add Reaction (if chosen)
                     ↓                    ↓
                   END  ←────────────────┘
```

## Customization Options

### 1. **Modify Reaction Frequency**
Edit the system prompt in `chat_agent.py` to make the agent more or less reactive:

```python
# More reactive
"Use reactions frequently to show engagement and emotional responses."

# Less reactive  
"Use reactions sparingly and only for significant emotional moments."

# Personality-based
"React in a way that matches your personality - be enthusiastic if that's your character."
```

### 2. **Add/Remove Available Reactions**
Update the `AVAILABLE_REACTIONS` list in `chat_agent.py`:

```python
AVAILABLE_REACTIONS = [
    "👍", "👎", "❤️", "🔥",  # Keep essentials
    # Add new ones or remove unused ones
]
```

### 3. **Contextual Instructions**
Modify the reaction instructions in the system prompt:

```python
f"React to express emotions like: agreement (👍), love (❤️), amazement (🤯), etc."
f"Consider the user's emotional state and respond appropriately."
f"Don't react if the message doesn't warrant an emotional response."
```

### 4. **Validation Rules**
Add custom validation in `ReactionTool.validate_reaction()`:

```python
def validate_reaction(self, reaction: str) -> bool:
    # Custom logic here
    if some_condition:
        return False
    return reaction in self.AVAILABLE_REACTIONS
```

## Example Usage

**User:** "I just got promoted at work! 🎉"
**Agent Response:** 
- Text: "That's amazing! Congratulations! 🎉 Tell me more about your new role!"
- Reaction: 🎉 (added to user's message)

**User:** "I'm feeling really sad today 😢"
**Agent Response:**
- Text: "I'm sorry to hear that. Do you want to talk about what's making you sad?"
- Reaction: 😢 (added to user's message)

**User:** "What's the weather like?"
**Agent Response:**
- Text: "I can't check the weather, but you could try a weather app!"
- Reaction: None (routine question doesn't warrant emotional reaction)

## Benefits

1. **Natural Interaction**: Reactions feel more human-like and immediate
2. **Emotional Intelligence**: LLM decides contextually appropriate reactions
3. **Non-Intrusive**: Reactions don't interrupt the conversation flow
4. **Personality Expression**: Agent can express character through reaction choices
5. **User Engagement**: Visual feedback makes conversations more engaging 