import os
import asyncio
import logging
import random # Added for random delay
from dotenv import load_dotenv

# --- Load .env file FIRST --- #
# This ensures that environment variables are available when other modules are imported
# and initialize their clients (like OpenAI or Mem0).
DOTENV_PATH = os.path.join(os.path.dirname(__file__), '..', '.env')
if os.path.exists(DOTENV_PATH):
    load_dotenv(DOTENV_PATH)
else:
    # Fallback if .env is not in agents/.env but perhaps in agents/src/.env
    # Or you can log a more specific error if it must be in agents/.env
    DOTENV_PATH_SRC = os.path.join(os.path.dirname(__file__), '.env')
    if os.path.exists(DOTENV_PATH_SRC):
        load_dotenv(DOTENV_PATH_SRC)
    else:
        print(f"Warning: .env file not found at {DOTENV_PATH} or {DOTENV_PATH_SRC}. Ensure API keys are set in your environment.")
# --- End .env loading --- #

from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

from langchain_core.messages import HumanMessage, AIMessage

# Now import your project modules, which might rely on the loaded env vars
from agent import companion_agent_graph # Import from the agent package directly
from agent.background_scheduler import BackgroundScheduler
from agent.conversation_tracker import conversation_tracker
from agent.scheduler_agent import scheduler_agent

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
MEM0_API_KEY = os.getenv("MEM0_API_KEY")
ENABLE_PROACTIVE_MESSAGING = os.getenv("ENABLE_PROACTIVE_MESSAGING", "true").lower() == "true"

# ANSI color codes for better logging visibility
class Colors:
    RED = '\033[91m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    MAGENTA = '\033[95m'
    CYAN = '\033[96m'
    WHITE = '\033[97m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'
    RESET = '\033[0m'

# Custom formatter with colors
class ColoredFormatter(logging.Formatter):
    def format(self, record):
        if record.levelname == 'INFO':
            record.levelname = f"{Colors.GREEN}INFO{Colors.RESET}"
        elif record.levelname == 'WARNING':
            record.levelname = f"{Colors.YELLOW}WARN{Colors.RESET}"
        elif record.levelname == 'ERROR':
            record.levelname = f"{Colors.RED}ERROR{Colors.RESET}"
        elif record.levelname == 'DEBUG':
            record.levelname = f"{Colors.CYAN}DEBUG{Colors.RESET}"
        return super().format(record)

# Configure logging with colored formatter (avoid duplicate handlers)
logger = logging.getLogger() # Get the root logger
logger.handlers.clear() # Clear any existing handlers

handler = logging.StreamHandler()
handler.setFormatter(ColoredFormatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s"))
logger.addHandler(handler)
logger.setLevel(logging.INFO)

# Reduce noise from other libraries
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("telegram.ext").setLevel(logging.WARNING)
logging.getLogger("telegram").setLevel(logging.WARNING)
logging.getLogger("apscheduler").setLevel(logging.WARNING)  # Reduce scheduler noise

# Set up logging for agent modules
logging.getLogger("agent.chat_agent").setLevel(logging.INFO)
logging.getLogger("agent.reaction_node").setLevel(logging.INFO)
logging.getLogger("agent.tools.reaction_tool").setLevel(logging.INFO)

if not TELEGRAM_BOT_TOKEN:
    logger.error("TELEGRAM_BOT_TOKEN not found! Check .env or environment variables.")
    exit()
# We can be a bit more lenient with OpenAI/Mem0 keys here as chat_agent.py might also check
# or the error will be caught during client initialization anyway, but good to warn.
if not OPENAI_API_KEY:
    logger.warning("OPENAI_API_KEY not found. The agent might not work if not set elsewhere.")
if not MEM0_API_KEY:
    logger.warning("MEM0_API_KEY not found. Mem0 integration might fail if not set elsewhere.")


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Sends a casual, natural welcome message when the /start command is issued."""
    user = update.effective_user
    logger.info(f"{Colors.YELLOW}🚀 BOT STARTED{Colors.RESET} by user {Colors.BOLD}{user.id}{Colors.RESET} ({user.username or 'No username'})")
    
    mem0_user_id = str(user.id)
    chat_id = update.effective_chat.id
    
    # Initialize user data with onboarding state
    if mem0_user_id not in context.user_data:
        context.user_data[mem0_user_id] = {
            'buffer': [], 
            'active_task': None, 
            'chat_id': chat_id,
            'onboarding_step': 'waiting_for_name'  # Track onboarding progress
        }
    else:
        context.user_data[mem0_user_id]['onboarding_step'] = 'waiting_for_name'
        
    try:
        # Send a casual, natural introduction asking for their name
        intro_messages = [
            "Hey! I'm Lena 😊",
            "What should I call you?"
        ]
        
        for i, message in enumerate(intro_messages):
            is_last = (i == len(intro_messages) - 1)
            await send_message_with_delay(context.bot, chat_id, message, is_last_message=is_last)

    except Exception as e:
        logger.error(f"Error during start command for user {user.id}: {e}", exc_info=True)
        await update.message.reply_text("Hey there! I'm Lena. What should I call you?")

async def process_user_messages(user_id: str, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Processes buffered messages for a user after a delay. Sends the response directly without placeholder."""
    user_data = context.user_data.get(user_id)
    
    if not user_data:
        logger.warning(f"User data not found for user {user_id} in process_user_messages. Aborting.")
        return

    current_task_object = asyncio.current_task()

    try:
        await asyncio.sleep(random.uniform(3, 5)) # Wait for 3-5 seconds

        # Make a copy of messages to process and then clear the buffer for this user
        # This ensures new messages arriving during agent processing aren't included in *this* turn.
        messages_to_process = list(user_data.get('buffer', []))
        if 'buffer' in user_data:
            user_data['buffer'].clear()

        if not messages_to_process:
            logger.debug(f"No messages to process for user {user_id} after delay")
            return # Return early, finally will clear task

        # Create HumanMessage objects for each buffered message
        new_human_messages = []
        for message_text in messages_to_process:
            new_human_messages.append(HumanMessage(content=message_text))

        combined_message = "\\n".join(messages_to_process)
        logger.info(f"{Colors.MAGENTA}🧠 AGENT PROCESSING{Colors.RESET} [{user_id}]: {Colors.BOLD}{combined_message[:100]}...{Colors.RESET}")

        graph_config = {
            "configurable": {
                "thread_id": user_id,
                "telegram_bot": context.bot  # Pass bot through config instead of state
            }
        }
        
        # Build input state that appends new messages to existing conversation
        # LangGraph will automatically merge this with the existing thread state
        current_turn_input = {
            "messages": new_human_messages,  # Only new messages - LangGraph will merge with existing thread
            "mem0_user_id": user_id,
            "telegram_context": {
                "chat_id": user_data.get('chat_id'),
                "message_id": user_data.get('last_message_id')
            },
            "llm_wants_to_react": False,
            "llm_chosen_reaction": None,
            "reaction_result": None
        }
        
        # DEBUG: Log the telegram_context being passed to graph
        telegram_ctx = current_turn_input["telegram_context"]
        bot_in_config = graph_config["configurable"].get("telegram_bot")
        logger.info(f"🔧 GRAPH INPUT: telegram_context={bool(telegram_ctx)}, bot_in_config={bool(bot_in_config)}, chat_id={telegram_ctx.get('chat_id')}, message_id={telegram_ctx.get('message_id')}")
        logger.info(f"🔧 NEW MESSAGES COUNT: {len(new_human_messages)}")
        
        # Execute the graph and get the final state
        final_state = await companion_agent_graph.ainvoke(current_turn_input, config=graph_config)
        
        # Extract the AI message from the final state
        ai_messages = [msg for msg in final_state.get("messages", []) if isinstance(msg, AIMessage)]
        if ai_messages:
            final_response_message = ai_messages[-1].content
            # Normalize newlines (e.g. \r\n to \n) before splitting
            normalized_message = final_response_message.strip().replace('\r\n', '\n')
            paragraphs = [p.strip() for p in normalized_message.split('\n\n') if p.strip()]

            if not paragraphs: # Handle case where message was only whitespace or empty after split
                await context.bot.send_message(chat_id=user_data.get('chat_id'), text="I received an empty response. Could you try rephrasing?")
            else:
                # Send all paragraphs as separate messages with delays
                for i, para_text in enumerate(paragraphs):
                    try:
                        is_last = (i == len(paragraphs) - 1)
                        await send_message_with_delay(context.bot, user_data.get('chat_id'), para_text, is_last_message=is_last)
                        logger.info(f"{Colors.GREEN}💬 AGENT REPLY{Colors.RESET} [{user_id}] ({i+1}/{len(paragraphs)}): {Colors.BOLD}{para_text[:100]}{'...' if len(para_text) > 100 else ''}{Colors.RESET}")
                    except Exception as e_send:
                        logger.error(f"Error sending paragraph to user {user_id}: {e_send}")
        else:
            await context.bot.send_message(chat_id=user_data.get('chat_id'), text="I don't have a response for that right now. Could you try something else?")
    except asyncio.CancelledError:
        logger.info(f"Message processing task for user {user_id} (task: {current_task_object.get_name()}) was cancelled.")
        # Do not try to edit placeholder or clear placeholder_info, a new task/placeholder is managing interactions.
        raise # Re-raise to allow asyncio to handle the cancellation.
    except Exception as e:
        logger.error(f"Error processing message for user {user_id} in background task (task: {current_task_object.get_name()}): {e}", exc_info=True)
        try:
            await context.bot.send_message(chat_id=user_data.get('chat_id'), text="Oh dear, I seem to be having a bit of a muddle. Could you try that again?")
        except Exception as e_inner:
            logger.error(f"Error sending error message to user {user_id} from background task (task: {current_task_object.get_name()}): {e_inner}")
    finally:
        # Clear the active_task reference ONLY if this task is still the one stored.
        # This prevents a cancelled task from clearing a newer, rescheduled task.
        if user_data and user_data.get('active_task') is current_task_object:
            user_data['active_task'] = None
            logger.info(f"Task {current_task_object.get_name()} for user {user_id} finished and cleared its active_task reference.")
        elif user_data and user_data.get('active_task') is not None:
             logger.info(f"Task {current_task_object.get_name()} for user {user_id} finished, but active_task was already {user_data.get('active_task').get_name() if user_data.get('active_task') else 'None'}. Not clearing.")


async def handle_photo_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles incoming photo messages, sends them to the agent, and replies."""
    user = update.effective_user
    user_id = str(user.id)
    chat_id = update.effective_chat.id

    logger.info(f"{Colors.CYAN}📸 PHOTO MESSAGE{Colors.RESET} [{user_id}]: {Colors.BOLD}{update.message.caption or 'No caption'}{Colors.RESET}")

    # Track user activity and reset ignore count
    conversation_tracker.update_user_activity(user_id)
    await scheduler_agent.reset_ignored_count(user_id)

    if user_id not in context.user_data: # Ensure user_data initialized
        context.user_data[user_id] = {'buffer': [], 'active_task': None, 'chat_id': chat_id}
    
    user_data = context.user_data[user_id]
    user_data['chat_id'] = chat_id  # Store chat_id for later use
    
    # Check if user is still in onboarding
    onboarding_step = user_data.get('onboarding_step')
    if onboarding_step in ['waiting_for_name', 'waiting_for_timezone']:
        if onboarding_step == 'waiting_for_name':
            await update.message.reply_text("Nice photo! But first, what should I call you? 😊")
        else:  # waiting_for_timezone
            await update.message.reply_text("Cool pic! But could you tell me what city you're in first?")
        return
    
    # Cancel any existing text processing task for this user, as photo takes precedence.
    active_task = user_data.get('active_task')
    if active_task and not active_task.done():
        try:
            active_task.cancel()
            logger.info(f"Cancelled text processing task {active_task.get_name()} for user {user_id} due to new photo message.")
        except Exception as e:
            logger.error(f"Error cancelling previous task for user {user_id}: {e}")
        user_data['active_task'] = None # Clear it

    try:
        photo_file = await context.bot.get_file(update.message.photo[-1].file_id)
        # Assuming photo_file.file_path is the full downloadable URL as per observed logs
        image_url = photo_file.file_path 
        
        content_list = []
        if update.message.caption:
            content_list.append({"type": "text", "text": update.message.caption})
        content_list.append({"type": "image_url", "image_url": {"url": image_url}})
        
        human_message_with_image = HumanMessage(content=content_list)
        
        logger.info(f"Constructed HumanMessage for user {user_id} with image. Content: {content_list}")

        graph_config = {
            "configurable": {
                "thread_id": user_id,
                "telegram_bot": context.bot  # Pass bot through config instead of state
            }
        }
        # Ensure messages list always starts with the current HumanMessage for the agent node
        current_turn_input = {
            "messages": [human_message_with_image], 
            "mem0_user_id": user_id,
            "telegram_context": {
                "chat_id": chat_id,
                "message_id": update.message.message_id
            },
            "llm_wants_to_react": False,
            "llm_chosen_reaction": None,
            "reaction_result": None
        }
        
        # DEBUG: Log the telegram_context being passed to graph for photos
        telegram_ctx = current_turn_input["telegram_context"]
        bot_in_config = graph_config["configurable"].get("telegram_bot")
        logger.info(f"🔧 PHOTO GRAPH INPUT: telegram_context={bool(telegram_ctx)}, bot_in_config={bool(bot_in_config)}, chat_id={telegram_ctx.get('chat_id')}, message_id={telegram_ctx.get('message_id')}")
        
        # Execute the graph and get the final state
        final_state = await companion_agent_graph.ainvoke(current_turn_input, config=graph_config)
        
        # Extract the AI message from the final state
        ai_messages = [msg for msg in final_state.get("messages", []) if isinstance(msg, AIMessage)]
        if ai_messages:
            final_response_message = ai_messages[-1].content
            normalized_message = final_response_message.strip().replace('\\r\\n', '\\n')
            paragraphs = [p.strip() for p in normalized_message.split('\\n\\n') if p.strip()]

            if not paragraphs:
                await update.message.reply_text("I saw the picture, but I'm not sure what to say!")
            else:
                for i, para_text in enumerate(paragraphs):
                    is_last = (i == len(paragraphs) - 1)
                    await send_message_with_delay(context.bot, chat_id, para_text, is_last_message=is_last)
                    logger.info(f"{Colors.GREEN}🖼️ PHOTO REPLY{Colors.RESET} [{user_id}] ({i+1}/{len(paragraphs)}): {Colors.BOLD}{para_text[:100]}{'...' if len(para_text) > 100 else ''}{Colors.RESET}")
        else:
            await update.message.reply_text("I saw your picture, but I'm speechless right now!")

    except Exception as e:
        logger.error(f"Error processing photo for user {user_id}: {e}", exc_info=True)
        await update.message.reply_text("I had a little trouble looking at that picture. Could you try sending it again?")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles incoming text messages, buffers them, and schedules/reschedules processing."""
    user_message_text = update.message.text
    user_id = str(update.effective_user.id)
    chat_id = update.effective_chat.id

    logger.info(f"{Colors.BLUE}📨 USER MESSAGE{Colors.RESET} [{user_id}]: {Colors.BOLD}{user_message_text}{Colors.RESET}")

    # Track user activity and reset ignore count
    conversation_tracker.update_user_activity(user_id)
    await scheduler_agent.reset_ignored_count(user_id)
    
    # Initialize user data if needed
    if user_id not in context.user_data:
        context.user_data[user_id] = {'buffer': [], 'active_task': None, 'chat_id': chat_id}
    
    user_data = context.user_data[user_id]
    user_data['chat_id'] = chat_id
    
    # Handle onboarding flow
    onboarding_step = user_data.get('onboarding_step')
    
    if onboarding_step == 'waiting_for_name':
        # User just provided their name
        user_data['user_name'] = user_message_text.strip()
        user_data['onboarding_step'] = 'waiting_for_timezone'
        
        # Save their name in memory
        # Use assistant role since it's information the bot is remembering
        messages = [{"role": "assistant", "content": f"User's name is {user_message_text.strip()}"}]
        scheduler_agent.mem0.add(messages=messages, user_id=user_id)
        
        timezone_messages = [
            f"Nice to meet you, {user_message_text.strip()}! 👋",
            "Just so I know when to reach out to you, what city are you in right now?"
        ]
        
        for i, message in enumerate(timezone_messages):
            is_last = (i == len(timezone_messages) - 1)
            await send_message_with_delay(context.bot, chat_id, message, is_last_message=is_last)
        return
        
    elif onboarding_step == 'waiting_for_timezone':
        # User provided their location/timezone
        location = user_message_text.strip()
        
        # Try to get timezone from location
        try:
            from agent.tools.timezone_tool import get_timezone_from_location
            timezone = get_timezone_from_location(location)
            
            if "Could not determine" not in timezone:
                # Successfully found timezone
                await scheduler_agent.save_user_timezone(user_id, timezone)
                user_data['onboarding_step'] = 'complete'
                
                # Register user for proactive messaging now that we have their timezone
                background_scheduler = context.application.bot_data.get('background_scheduler')
                if background_scheduler:
                    background_scheduler.register_user(user_id, chat_id)
                
                response_messages = [
                    f"Perfect! Got you down as being in {location} 📍",
                    "Alright, we're all set! What's on your mind?"
                ]
                
                for i, message in enumerate(response_messages):
                    is_last = (i == len(response_messages) - 1)
                    await send_message_with_delay(context.bot, chat_id, message, is_last_message=is_last)
                return
            else:
                # Couldn't determine timezone, ask for clarification
                await update.message.reply_text("Hmm, I'm not sure where that is. Could you try a major city name like 'London' or 'New York'?")
                return
                
        except Exception as e:
            logger.error(f"Error processing timezone for user {user_id}: {e}")
            await update.message.reply_text("I had trouble with that location. Could you try a major city name?")
            return
    
    # Handle timezone validation if user didn't go through onboarding
    background_scheduler = context.application.bot_data.get('background_scheduler')
    if background_scheduler:
        # Check if user has a timezone stored. If not, maybe the message is the timezone.
        if not await scheduler_agent.get_user_timezone(user_id):
            try:
                import pytz
                pytz.timezone(user_message_text)
                await scheduler_agent.save_user_timezone(user_id, user_message_text)
                await update.message.reply_text(f"Great, I've set your timezone to {user_message_text}. Thanks!")
                # Don't process this message as a regular chat message
                return
            except pytz.UnknownTimeZoneError:
                # It's not a valid timezone, so process as a regular message
                pass
        
        background_scheduler.register_user(user_id, chat_id)

    # Regular message processing continues below
    user_data['last_message_id'] = update.message.message_id  # Store message ID for reactions
    user_data['buffer'].append(user_message_text)

    # If there's an existing task, cancel it.
    active_task = user_data.get('active_task')
    if active_task and not active_task.done():
        try:
            active_task.cancel()
            logger.info(f"Cancelled previous task {active_task.get_name()} for user {user_id} due to new message.")
        except Exception as e:
            logger.error(f"Error cancelling previous task for user {user_id}: {e}")
    
    # Create a new task for processing messages
    try:
        new_task = asyncio.create_task(
            process_user_messages(user_id, context),
            name=f"ProcessMsg_User{user_id}_Msg{len(user_data['buffer'])}" # Name for easier debugging
        )
        user_data['active_task'] = new_task
        
        # Add a callback to log if the task fails unexpectedly (not due to cancellation)
        def _task_done_callback(task: asyncio.Task, user_id_cb: str):
            try:
                task.result() # Access result to raise exception if one occurred
            except asyncio.CancelledError:
                logger.info(f"Task {task.get_name()} for user {user_id_cb} was cancelled (logged in callback).")
            except Exception as e_cb:
                logger.error(f"Task {task.get_name()} for user {user_id_cb} raised an unhandled exception: {e_cb}", exc_info=e_cb)

        new_task.add_done_callback(lambda t: _task_done_callback(t, user_id))
        logger.debug(f"⏰ Scheduled processing task for user {user_id}")

    except Exception as e:
        logger.error(f"Error initiating message processing for user {user_id}: {e}", exc_info=True)
        await update.message.reply_text("Sorry, I couldn't start processing your message right now.")
        # Ensure task reference is cleared if placeholder/task creation failed critically
        if user_data: # Should exist
             user_data['active_task'] = None


async def send_message_with_delay(bot, chat_id: str, text: str, is_last_message: bool = False) -> None:
    """
    Sends a message and adds a delay based on message length.
    
    Args:
        bot: Telegram bot instance
        chat_id: Chat ID to send message to
        text: Message text to send
        is_last_message: Whether this is the last message in a sequence (no delay after)
    """
    # Send the message
    await bot.send_message(chat_id=chat_id, text=text)
    
    # Don't add delay after the last message
    if is_last_message:
        logger.debug(f"💤 No delay added - this is the last message in sequence")
        return
    
    # Calculate delay based on message length
    message_length = len(text)
    
    # Base delay: 2-4 seconds (minimum 2 seconds as requested)
    base_delay = random.uniform(2.0, 4.0)
    
    # Add extra delay for longer messages
    # For every 100 characters, add 0.5-1.5 seconds
    length_factor = (message_length // 100) * random.uniform(0.5, 1.5)
    
    # Total delay: base + length factor, capped at 8 seconds to avoid excessive delays
    total_delay = min(base_delay + length_factor, 8.0)
    
    logger.debug(f"💤 Adding delay: {total_delay:.1f}s (message: {message_length} chars, base: {base_delay:.1f}s, length factor: {length_factor:.1f}s)")
    await asyncio.sleep(total_delay)


async def main() -> None:
    """Starts the Telegram bot."""
    logger.info(f"{Colors.BOLD}{Colors.GREEN}🤖 STARTING AI COMPANION BOT{Colors.RESET}")

    # Build feature list based on configuration
    features = ["Text messages", "Photos", "Reactions"]
    if ENABLE_PROACTIVE_MESSAGING:
        features.append("Proactive Messaging")
    logger.info(f"{Colors.CYAN}📋 Features enabled: {', '.join(features)}{Colors.RESET}")

    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    # Initialize background scheduler only if proactive messaging is enabled
    background_scheduler = None
    if ENABLE_PROACTIVE_MESSAGING:
        background_scheduler = BackgroundScheduler(application.bot)
        # Store scheduler reference in bot_data
        application.bot_data['background_scheduler'] = background_scheduler
    else:
        logger.info(f"{Colors.YELLOW}⏸️ Proactive messaging is DISABLED (ENABLE_PROACTIVE_MESSAGING=false){Colors.RESET}")
        application.bot_data['background_scheduler'] = None
    
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    application.add_handler(MessageHandler(filters.PHOTO, handle_photo_message))

    logger.info(f"{Colors.BOLD}{Colors.BLUE}🔄 BOT IS LIVE - Listening for messages...{Colors.RESET}")
    
    # Use async methods to avoid deprecation warnings
    async with application:
        await application.initialize()
        await application.start()
        
        # Start the background scheduler (now async) if enabled
        if background_scheduler:
            await background_scheduler.start()
        
        await application.updater.start_polling()
        
        try:
            # Keep the bot running
            await asyncio.Event().wait()
        except KeyboardInterrupt:
            logger.info(f"{Colors.YELLOW}🛑 Bot stopping gracefully...{Colors.RESET}")
        finally:
            # Stop the background scheduler if it exists
            if background_scheduler:
                background_scheduler.stop()
            await application.updater.stop()
            await application.stop()
            await application.shutdown()

if __name__ == "__main__":
    asyncio.run(main())
