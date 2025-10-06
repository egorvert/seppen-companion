# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a LangGraph-based AI companion chatbot built for Telegram. The bot features:
- Conversational chat with personality-driven responses
- Integration with Mem0 for long-term memory
- Proactive messaging system that initiates conversations
- Emoji reactions to user messages
- Image understanding capabilities
- Timezone-aware scheduling

## Development Commands

### Running the Bot
```bash
# Start the Telegram bot
python src/telegram_bot.py
```

### LangGraph Development
```bash
# Start LangGraph development server (with hot reload)
langgraph dev

# Install dependencies
pip install -e . "langgraph-cli[inmem]"
```

### Testing
```bash
# Run unit tests
make test
# or
python -m pytest tests/unit_tests/

# Run integration tests
make integration_tests
# or
python -m pytest tests/integration_tests

# Run tests in watch mode
make test_watch

# Run specific test file
make test TEST_FILE=tests/unit_tests/test_specific.py
```

### Linting and Formatting
```bash
# Format code
make format
# or
ruff format .
ruff check --select I --fix .

# Run linters (includes ruff, mypy)
make lint
# or
ruff check .
mypy --strict src/
```

## Architecture

### Core Components

**Two Primary Graphs:**
1. **`companion_agent_graph`** (`src/agent/graph.py`) - Main conversation flow
   - Entry: `chat_agent` → decides to use tools or check reactions
   - If tools needed: `tools` → `chat_agent_after_tools` → `check_reaction`
   - If no tools: directly to `check_reaction`
   - Final: optionally `add_reaction` → END

2. **`proactive_message_graph`** (`src/agent/proactive_graph.py`) - Proactive messaging
   - Entry: `proactive_agent` → generates proactive message → END

**Key Nodes:**
- `chat_agent_node` (`src/agent/chat_agent.py`) - Main conversational logic, loads personality, retrieves Mem0 memories, generates response with structured output (includes reaction decision)
- `proactive_agent_node` (`src/agent/proactive_agent.py`) - Generates conversation starters based on time and context
- `add_reaction_node` (`src/agent/reaction_node.py`) - Adds Telegram emoji reactions to user messages
- Tool nodes for timezone lookup

**Scheduler System:**
- `scheduler_agent` (`src/agent/scheduler_agent.py`) - Determines when/what to send proactively, manages user timezone, frequency preferences, DND hours (7 AM - 11 PM in user's timezone)
- `BackgroundScheduler` (`src/agent/background_scheduler.py`) - APScheduler-based system that triggers proactive messages, tracks ignore counts, persists user registrations to Mem0
- `conversation_tracker` (`src/agent/conversation_tracker.py`) - Tracks active conversations to avoid interrupting users

**Bot Entry Point:**
- `telegram_bot.py` - Telegram bot handlers, message buffering (3-5s delay before processing), onboarding flow (name → timezone), proactive messaging toggle via `ENABLE_PROACTIVE_MESSAGING` env var

### State Management

**Chat State Fields:**
```python
messages: List[BaseMessage]  # Conversation history (managed by LangGraph thread persistence)
mem0_user_id: str  # User ID for Mem0 memory storage
telegram_context: Dict  # Contains chat_id, message_id, bot instance (passed via config)
llm_wants_to_react: bool  # LLM decision to add reaction
llm_chosen_reaction: Optional[str]  # Chosen emoji
reaction_result: Optional[Dict]  # Result of reaction attempt
```

**Proactive State Fields:**
```python
mem0_user_id: str
telegram_context: Dict  # Contains chat_id
message_type: str  # "morning_check", "afternoon_thought", "evening_reflection", "spontaneous"
prompt_config: Dict  # Prompt configuration from scheduler
is_proactive: bool  # Flag for proactive messages
```

### Personality System

Personalities are defined in JSON files (`personalities/lena.json`). Structure:
- Basic info: name, age, gender, temperament, MBTI
- Big 5 personality traits with facets (0-1 scale)
- Speech style: openers, filler words, emoji palette, tone ratios
- Behavioral tendencies: strengths, flaws, motivations, stressors
- Daily schedule config: preferred times, frequency settings, conversation prompts, spontaneous intervals

The personality JSON is loaded by agents to shape system prompts and behavior.

### Memory Integration (Mem0)

- User-specific memories stored with `mem0_user_id`
- Semantic search retrieves relevant context for each conversation turn
- Stores: conversation history, user timezone, frequency preferences, daily message markers, proactive message timestamps
- Role-based message format: `{"role": "user/assistant/system", "content": "..."}`

### Timezone Handling

1. Users provide location during onboarding or in conversation
2. `get_timezone_from_location` tool (uses `timezonefinder` + `geopy`) converts location → IANA timezone
3. Timezone stored in Mem0: "User timezone is America/New_York"
4. Scheduler uses timezone for DND hours and time-appropriate messaging

### Proactive Messaging Flow

1. `BackgroundScheduler` registers users and schedules checks
2. Periodic checks (every 30 min) + scheduled checks at specific times
3. `scheduler_agent.should_send_proactive_message()` validates:
   - Appropriate time (7 AM - 11 PM user local time)
   - Frequency constraints (min 4 hours between messages by default)
   - Not during active conversation
   - User hasn't ignored recent messages (2+ ignored = special message)
   - Not already sent this message type today
4. If conditions met: `proactive_message_graph` generates message
5. Message sent via Telegram bot with natural delays
6. Ignore check scheduled for 2 hours later

### Message Processing

Text messages are buffered with 3-5 second delay before processing. If user sends multiple messages within this window, they're combined into a single turn. This prevents rapid back-and-forth and allows the agent to respond to complete thoughts.

Photo messages bypass buffering and are processed immediately. Images are sent to the LLM using OpenAI's vision capabilities.

## Configuration Files

- `.env` - API keys (TELEGRAM_BOT_TOKEN, OPENAI_API_KEY, MEM0_API_KEY), feature flags (ENABLE_PROACTIVE_MESSAGING)
- `langgraph.json` - Defines graph entry point for LangGraph server
- `pyproject.toml` - Python dependencies and tool configs (ruff, mypy)
- `personalities/lena.json` - Primary personality configuration

## Important Implementation Details

### LangGraph State Updates
LangGraph only updates state fields that are explicitly returned. When returning partial state updates, include ALL fields that should be preserved (especially `telegram_context`).

### Structured Output with Tools
The chat agent uses TWO different LLM configurations:
- `llm_with_tools` - For tool calling (timezone lookup)
- `structured_llm` - For normal responses (includes reaction decision)

Tool calling and structured output are mutually exclusive in OpenAI's API. The agent detects timezone-related keywords and routes to tool calling first, then falls back to structured output.

### Reaction System
The LLM decides whether to add reactions in its structured output. Reactions are added via Telegram's `set_message_reaction` API. Available reactions are defined in `AVAILABLE_REACTIONS` list in `chat_agent.py`.

### Background Task Management
User messages create async tasks that are cancelled and rescheduled if new messages arrive. The `active_task` reference tracks the current processing task per user.

### Proactive Message Persistence
User registrations are persisted to Mem0 with a system user ID (`PROACTIVE_SCHEDULER_SYSTEM`). This allows the scheduler to restore subscriptions after bot restarts.

## Model Configuration

- Chat Agent: GPT-4.1 (temperature 0.7)
- Proactive Agent: GPT-4o-mini (temperature 0.8, higher for creativity)
- Both use LangChain's `ChatOpenAI` wrapper
