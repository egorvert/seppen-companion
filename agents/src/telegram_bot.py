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

from langchain_core.messages import HumanMessage

# Now import your project modules, which might rely on the loaded env vars
from agent import companion_agent_graph # Import from the agent package directly

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY") 
MEM0_API_KEY = os.getenv("MEM0_API_KEY")

# Basic logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

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
    logger.info(f"User {user.id} ({user.username}) started the bot.")
    
    mem0_user_id = str(user.id)
    graph_config = {"configurable": {"thread_id": mem0_user_id}}
    initial_state = {"messages": [], "mem0_user_id": mem0_user_id}

    full_response_message = "" # Accumulate full response here
    placeholder_message = await update.message.reply_text("Lena is thinking...")
    
    try:
        async for event in companion_agent_graph.astream_events(initial_state, config=graph_config, version="v2"):
            if event["event"] == "on_chat_model_stream":
                chunk = event["data"].get("chunk")
                if chunk and hasattr(chunk, 'content') and chunk.content:
                    full_response_message += chunk.content
        
        if full_response_message:
            await context.bot.edit_message_text(chat_id=update.effective_chat.id, 
                                                message_id=placeholder_message.message_id, 
                                                text=full_response_message)
        else:
            await context.bot.edit_message_text(chat_id=update.effective_chat.id, 
                                                message_id=placeholder_message.message_id, 
                                                text="Hi! I'm Lena, nice to meet you.")

    except Exception as e:
        logger.error(f"Error during start command for user {user.id}: {e}", exc_info=True)
        await context.bot.edit_message_text(chat_id=update.effective_chat.id, 
                                            message_id=placeholder_message.message_id, 
                                            text="Sorry, I had a little trouble starting up. Could you try sending a message?")

async def process_user_messages(user_id: str, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Processes buffered messages for a user after a delay. Edits the placeholder tied to the latest message."""
    user_data = context.user_data.get(user_id)
    
    if not user_data or 'placeholder_info' not in user_data or not user_data['placeholder_info']:
        logger.warning(f"User data or placeholder_info not found for user {user_id} in process_user_messages. Aborting.")
        # Ensure task reference is cleared if it somehow still points here
        if user_data and user_data.get('active_task') is asyncio.current_task():
            user_data['active_task'] = None
        return

    placeholder_info = user_data['placeholder_info']
    placeholder_message_id = placeholder_info['message_id']
    chat_id = placeholder_info['chat_id']
    
    current_task_object = asyncio.current_task()

    try:
        await asyncio.sleep(random.uniform(3, 5)) # Wait for 3-5 seconds

        # Make a copy of messages to process and then clear the buffer for this user
        # This ensures new messages arriving during agent processing aren't included in *this* turn.
        messages_to_process = list(user_data.get('buffer', []))
        if 'buffer' in user_data:
            user_data['buffer'].clear()

        if not messages_to_process:
            logger.info(f"No messages to process for user {user_id} after delay (task: {current_task_object.get_name()}).")
            try:
                await context.bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=placeholder_message_id,
                    text="I'm ready when you are! Send me a message."
                )
            except Exception as e:
                logger.error(f"Error updating placeholder for empty buffer for user {user_id} (task: {current_task_object.get_name()}): {e}")
            return # Return early, finally will clear task

        combined_message = "\\n".join(messages_to_process)
        logger.info(f"Processing combined message for user {user_id} (task: {current_task_object.get_name()}): {combined_message[:200]}...")

        graph_config = {"configurable": {"thread_id": user_id}}
        current_turn_input = {"messages": [HumanMessage(content=combined_message)], "mem0_user_id": user_id}
        
        final_response_message = ""
        async for event in companion_agent_graph.astream_events(current_turn_input, config=graph_config, version="v2"):
            if event["event"] == "on_chat_model_stream":
                chunk = event["data"].get("chunk")
                if chunk and hasattr(chunk, 'content') and chunk.content:
                    final_response_message += chunk.content
        
        if final_response_message:
            # Normalize newlines (e.g. \r\n to \n) before splitting
            normalized_message = final_response_message.strip().replace('\r\n', '\n')
            paragraphs = [p.strip() for p in normalized_message.split('\n\n') if p.strip()]

            if not paragraphs: # Handle case where message was only whitespace or empty after split
                await context.bot.edit_message_text(chat_id=chat_id,
                                                    message_id=placeholder_message_id,
                                                    text="I received an empty response. Could you try rephrasing?")
                user_data['placeholder_info'] = None # Placeholder consumed
            else:
                # Send the first paragraph by editing the placeholder
                first_paragraph = paragraphs.pop(0)
                await context.bot.edit_message_text(chat_id=chat_id,
                                                    message_id=placeholder_message_id,
                                                    text=first_paragraph)
                user_data['placeholder_info'] = None # Placeholder consumed by the first paragraph

                # Send subsequent paragraphs as new messages
                for para_text in paragraphs:
                    try:
                        await context.bot.send_message(chat_id=chat_id, text=para_text)
                    except Exception as e_send:
                        logger.error(f"Error sending subsequent paragraph to user {user_id} (task: {current_task_object.get_name()}): {e_send}")
        else:
            await context.bot.edit_message_text(chat_id=chat_id,
                                                message_id=placeholder_message_id,
                                                text="I don't have a response for that right now. Could you try something else?")
            user_data['placeholder_info'] = None # Placeholder consumed
    except asyncio.CancelledError:
        logger.info(f"Message processing task for user {user_id} (task: {current_task_object.get_name()}) was cancelled.")
        # Do not try to edit placeholder or clear placeholder_info, a new task/placeholder is managing interactions.
        raise # Re-raise to allow asyncio to handle the cancellation.
    except Exception as e:
        logger.error(f"Error processing message for user {user_id} in background task (task: {current_task_object.get_name()}): {e}", exc_info=True)
        try:
            await context.bot.edit_message_text(chat_id=chat_id,
                                                message_id=placeholder_message_id,
                                                text="Oh dear, I seem to be having a bit of a muddle. Could you try that again?")
            user_data['placeholder_info'] = None # Placeholder consumed by error message
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


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles incoming text messages, buffers them, and schedules/reschedules processing."""
    user_message_text = update.message.text
    user_id = str(update.effective_user.id)

    logger.info(f"Received message from user {user_id}: '{user_message_text}'")

    if user_id not in context.user_data:
        context.user_data[user_id] = {'buffer': [], 'active_task': None, 'placeholder_info': None}
    
    user_data = context.user_data[user_id]
    user_data['buffer'].append(user_message_text)

    # Store old placeholder info for potential deletion
    old_placeholder_info = user_data.get('placeholder_info')

    # If there's an existing task, cancel it.
    active_task = user_data.get('active_task')
    if active_task and not active_task.done():
        try:
            active_task.cancel()
            logger.info(f"Cancelled previous task {active_task.get_name()} for user {user_id} due to new message.")
        except Exception as e:
            logger.error(f"Error cancelling previous task for user {user_id}: {e}")
    
    # Attempt to delete the old placeholder message if it existed
    if old_placeholder_info:
        try:
            await context.bot.delete_message(chat_id=old_placeholder_info['chat_id'], message_id=old_placeholder_info['message_id'])
            logger.info(f"Deleted old placeholder message {old_placeholder_info['message_id']} for user {user_id}.")
        except Exception as e:
            logger.warning(f"Could not delete old placeholder message {old_placeholder_info.get('message_id', 'N/A')} for user {user_id}: {e}")

    # Always create a new placeholder and a new task for the latest message.
    try:
        placeholder = await update.message.reply_text("Lena is typing...")
        user_data['placeholder_info'] = {'message_id': placeholder.message_id, 'chat_id': placeholder.chat_id}
        
        new_task = asyncio.create_task(
            process_user_messages(user_id, context),
            name=f"ProcessMsg_User{user_id}_Msg{placeholder.message_id}" # Name for easier debugging
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
        logger.info(f"Scheduled new task {new_task.get_name()} for user {user_id} with new placeholder {placeholder.message_id}.")

    except Exception as e:
        logger.error(f"Error initiating message processing for user {user_id}: {e}", exc_info=True)
        await update.message.reply_text("Sorry, I couldn't start processing your message right now.")
        # Ensure task reference is cleared if placeholder/task creation failed critically
        if user_data: # Should exist
             user_data['active_task'] = None
             user_data['placeholder_info'] = None


def main() -> None:
    """Starts the Telegram bot."""
    logger.info("Starting Telegram bot...")

    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info("Telegram bot polling...")
    application.run_polling()

if __name__ == "__main__":
    main() 