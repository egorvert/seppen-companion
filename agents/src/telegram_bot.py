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

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY") 
MEM0_API_KEY = os.getenv("MEM0_API_KEY")

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
    """Sends a welcome message when the /start command is issued."""
    user = update.effective_user
    logger.info(f"{Colors.YELLOW}🚀 BOT STARTED{Colors.RESET} by user {Colors.BOLD}{user.id}{Colors.RESET} ({user.username or 'No username'})")
    
    mem0_user_id = str(user.id)
    graph_config = {
        "configurable": {
            "thread_id": mem0_user_id,
            "telegram_bot": context.bot  # Pass bot through config instead of state
        }
    }
    initial_state = {
        "messages": [], 
        "mem0_user_id": mem0_user_id,
        "telegram_context": {
            "chat_id": update.effective_chat.id,
            "message_id": update.message.message_id
        },
        "llm_wants_to_react": False,
        "llm_chosen_reaction": None,
        "reaction_result": None
    }

    try:
        # Execute the graph and get the final state
        final_state = await companion_agent_graph.ainvoke(initial_state, config=graph_config)
        
        # Extract the AI message from the final state
        ai_messages = [msg for msg in final_state.get("messages", []) if isinstance(msg, AIMessage)]
        if ai_messages:
            await update.message.reply_text(ai_messages[-1].content)
        else:
            await update.message.reply_text("Hi! I'm Lena, nice to meet you.")

    except Exception as e:
        logger.error(f"Error during start command for user {user.id}: {e}", exc_info=True)
        await update.message.reply_text("Sorry, I had a little trouble starting up. Could you try sending a message?")

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

        combined_message = "\\n".join(messages_to_process)
        logger.info(f"{Colors.MAGENTA}🧠 AGENT PROCESSING{Colors.RESET} [{user_id}]: {Colors.BOLD}{combined_message[:100]}...{Colors.RESET}")

        graph_config = {
            "configurable": {
                "thread_id": user_id,
                "telegram_bot": context.bot  # Pass bot through config instead of state
            }
        }
        current_turn_input = {
            "messages": [HumanMessage(content=combined_message)], 
            "mem0_user_id": user_id,
            "telegram_context": {
                "chat_id": user_data.get('chat_id'),
                "message_id": user_data.get('last_message_id')  # We'll need to track this
            },
            "llm_wants_to_react": False,
            "llm_chosen_reaction": None,
            "reaction_result": None
        }
        
        # DEBUG: Log the telegram_context being passed to graph
        telegram_ctx = current_turn_input["telegram_context"]
        bot_in_config = graph_config["configurable"].get("telegram_bot")
        logger.info(f"🔧 GRAPH INPUT: telegram_context={bool(telegram_ctx)}, bot_in_config={bool(bot_in_config)}, chat_id={telegram_ctx.get('chat_id')}, message_id={telegram_ctx.get('message_id')}")
        
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
                # Send all paragraphs as separate messages
                for i, para_text in enumerate(paragraphs):
                    try:
                        await context.bot.send_message(chat_id=user_data.get('chat_id'), text=para_text)
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

    if user_id not in context.user_data: # Ensure user_data initialized
        context.user_data[user_id] = {'buffer': [], 'active_task': None, 'chat_id': chat_id}
    
    # Cancel any existing text processing task for this user, as photo takes precedence.
    user_data = context.user_data[user_id]
    user_data['chat_id'] = chat_id  # Store chat_id for later use
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
                    await context.bot.send_message(chat_id=chat_id, text=para_text)
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

    if user_id not in context.user_data:
        context.user_data[user_id] = {'buffer': [], 'active_task': None, 'chat_id': chat_id}
    
    user_data = context.user_data[user_id]
    user_data['chat_id'] = chat_id  # Store chat_id for later use
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


async def main() -> None:
    """Starts the Telegram bot."""
    logger.info(f"{Colors.BOLD}{Colors.GREEN}🤖 STARTING AI COMPANION BOT{Colors.RESET}")
    logger.info(f"{Colors.CYAN}📋 Features enabled: Text messages, Photos, Reactions{Colors.RESET}")

    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    application.add_handler(MessageHandler(filters.PHOTO, handle_photo_message))

    logger.info(f"{Colors.BOLD}{Colors.BLUE}🔄 BOT IS LIVE - Listening for messages...{Colors.RESET}")
    
    # Use async methods to avoid deprecation warnings
    async with application:
        await application.initialize()
        await application.start()
        await application.updater.start_polling()
        
        try:
            # Keep the bot running
            await asyncio.Event().wait()
        except KeyboardInterrupt:
            logger.info(f"{Colors.YELLOW}🛑 Bot stopping gracefully...{Colors.RESET}")
        finally:
            await application.updater.stop()
            await application.stop()
            await application.shutdown()

if __name__ == "__main__":
    asyncio.run(main())