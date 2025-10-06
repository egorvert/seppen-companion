import asyncio
import logging
import random
from datetime import datetime, timedelta
from typing import Dict, Set, Optional
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.date import DateTrigger
from apscheduler.triggers.interval import IntervalTrigger

from telegram import Bot
from telegram.error import TelegramError
from langchain_core.messages import AIMessage
from mem0 import MemoryClient
import os

from .scheduler_agent import scheduler_agent, SchedulingContext
from .proactive_graph import proactive_message_graph
from .conversation_tracker import conversation_tracker

logger = logging.getLogger(__name__)

class BackgroundScheduler:
    """Manages background scheduling for proactive messages."""
    
    def __init__(self, telegram_bot: Bot):
        self.scheduler = AsyncIOScheduler()
        self.telegram_bot = telegram_bot
        self.active_users: Set[str] = set()  # Track users who have active schedules
        self.user_chat_mapping: Dict[str, int] = {}  # user_id -> chat_id mapping
        
        # Initialize Mem0 client for persistence
        self.mem0 = MemoryClient(api_key=os.getenv("MEM0_API_KEY"))
        
    async def start(self):
        """Start the background scheduler and restore previous user registrations."""
        # First restore previous user registrations from Mem0
        await self._restore_user_registrations()
        
        self.scheduler.start()
        
        # Schedule periodic check for new proactive messages (every 30 minutes)
        self.scheduler.add_job(
            self._periodic_proactive_check,
            IntervalTrigger(minutes=30),
            id="periodic_proactive_check",
            replace_existing=True
        )
        
        logger.info(f"🕐 Background scheduler started with {len(self.active_users)} restored users")
    
    def stop(self):
        """Stop the background scheduler."""
        self.scheduler.shutdown()
        logger.info("🛑 Background scheduler stopped")
    
    async def _restore_user_registrations(self):
        """Restore user registrations from Mem0 after bot restart."""
        try:
            # Search for all user registration records using a system user ID
            # We'll use a special system user ID to store global registration data
            system_user_id = "PROACTIVE_SCHEDULER_SYSTEM"
            memories = self.mem0.search(query="PROACTIVE_SCHEDULER_REGISTRATION", user_id=system_user_id, limit=100)
            
            restored_count = 0
            collected_user_data = {}  # Dict to collect user_id -> chat_id mappings from separate memories
            
            for memory in memories:
                memory_text = memory.get('memory', '')
                logger.debug(f"Processing memory: {memory_text}")
                
                # Handle both possible formats:
                # Original format: "PROACTIVE_SCHEDULER_REGISTRATION user_id:{user_id} chat_id:{chat_id} registered_at:{timestamp}"
                # Mem0 transformed format: "Registered proactive scheduler with user_id {user_id} and chat_id {chat_id} at {timestamp}"
                
                user_id = None
                chat_id = None
                
                try:
                    if "user_id" in memory_text and "chat_id" in memory_text:
                        # Try original format first
                        if "user_id:" in memory_text and "chat_id:" in memory_text:
                            parts = memory_text.split()
                            for part in parts:
                                if part.startswith("user_id:"):
                                    user_id = part.split(":", 1)[1]
                                elif part.startswith("chat_id:"):
                                    chat_id = int(part.split(":", 1)[1])
                        # Try Mem0 transformed format
                        elif "user_id " in memory_text and "chat_id " in memory_text:
                            import re
                            # Extract using regex: "user_id 123456789 and chat_id 123456789"
                            user_id_match = re.search(r'user_id\s+(\d+)', memory_text)
                            chat_id_match = re.search(r'chat_id\s+(\d+)', memory_text)
                            
                            if user_id_match:
                                user_id = user_id_match.group(1)
                            if chat_id_match:
                                chat_id = int(chat_id_match.group(1))
                    
                    if user_id and chat_id:
                        self.active_users.add(user_id)
                        self.user_chat_mapping[user_id] = chat_id
                        
                        # Reschedule the user for proactive messaging
                        await self._reschedule_user_proactive_messages(user_id)
                        
                        restored_count += 1
                        logger.debug(f"Restored user registration: {user_id} -> chat {chat_id}")
                    else:
                        logger.debug(f"Could not extract user_id or chat_id from: {memory_text}")
                        
                except (ValueError, IndexError) as e:
                    logger.warning(f"Failed to parse registration memory: {memory_text}, error: {e}")
                    continue
            
            # Additional pass: Look for separate "User ID is X" and "Chat ID is X" memories
            logger.debug("Searching for separate user ID and chat ID memories...")
            try:
                # Search for memories containing user IDs and chat IDs separately
                user_id_memories = self.mem0.search(query="User ID is", user_id=system_user_id, limit=50)
                chat_id_memories = self.mem0.search(query="Chat ID is", user_id=system_user_id, limit=50)
                
                # Extract user IDs
                import re
                for memory in user_id_memories:
                    memory_text = memory.get('memory', '')
                    if "User ID is" in memory_text:
                        match = re.search(r'User ID is\s+(\d+)', memory_text)
                        if match:
                            user_id = match.group(1)
                            if user_id not in collected_user_data:
                                collected_user_data[user_id] = {}
                            collected_user_data[user_id]['user_id'] = user_id
                            
                # Extract chat IDs and match them to user IDs
                for memory in chat_id_memories:
                    memory_text = memory.get('memory', '')
                    if "Chat ID is" in memory_text:
                        match = re.search(r'Chat ID is\s+(\d+)', memory_text)
                        if match:
                            chat_id = int(match.group(1))
                            # Find a user_id that matches this chat_id (assuming they're the same for direct messages)
                            for user_id in collected_user_data:
                                if 'chat_id' not in collected_user_data[user_id]:
                                    # For Telegram direct messages, user_id often equals chat_id
                                    if user_id == str(chat_id):
                                        collected_user_data[user_id]['chat_id'] = chat_id
                                        break
                            # Also check if this chat_id has a corresponding user_id
                            chat_id_str = str(chat_id)
                            if chat_id_str in collected_user_data and 'chat_id' not in collected_user_data[chat_id_str]:
                                collected_user_data[chat_id_str]['chat_id'] = chat_id
                
                # Process collected data
                for user_id, data in collected_user_data.items():
                    if 'user_id' in data and 'chat_id' in data and user_id not in self.active_users:
                        self.active_users.add(user_id)
                        self.user_chat_mapping[user_id] = data['chat_id']
                        
                        # Reschedule the user for proactive messaging
                        await self._reschedule_user_proactive_messages(user_id)
                        
                        restored_count += 1
                        logger.debug(f"Restored user registration from separate memories: {user_id} -> chat {data['chat_id']}")
                        
            except Exception as e:
                logger.warning(f"Error processing separate user/chat ID memories: {e}")
            
            if restored_count > 0:
                logger.info(f"📋 Restored {restored_count} user registrations from persistent storage")
                logger.info(f"📋 Active users after restore: {list(self.active_users)}")
            else:
                logger.info("📋 No previous user registrations found")
                
        except Exception as e:
            logger.error(f"Error restoring user registrations: {e}")
    
    async def _reschedule_user_proactive_messages(self, user_id: str):
        """Reschedule proactive messages for a restored user."""
        try:
            # Schedule initial check for regular messages (in 1 hour to avoid spam on restart)
            initial_check_time = datetime.now() + timedelta(hours=1)
            self._schedule_user_check(user_id, initial_check_time, "regular")
            
            # Also schedule potential spontaneous messages
            self._schedule_spontaneous_messages(user_id)
            
            logger.debug(f"Rescheduled proactive messages for restored user {user_id}")
        except Exception as e:
            logger.error(f"Error rescheduling messages for user {user_id}: {e}")
    
    async def _save_user_registration(self, user_id: str, chat_id: int):
        """Save user registration to Mem0 for persistence."""
        try:
            timestamp = datetime.now().isoformat()
            memory_text = f"PROACTIVE_SCHEDULER_REGISTRATION user_id:{user_id} chat_id:{chat_id} registered_at:{timestamp}"
            
            # Store using a system user ID so we can retrieve all registrations
            system_user_id = "PROACTIVE_SCHEDULER_SYSTEM"
            
            # First, remove any existing registration for this user to avoid duplicates
            # But don't await it to avoid blocking - just do a quick check
            try:
                existing_memories = self.mem0.search(query=f"user_id:{user_id}", user_id=system_user_id, limit=5)
                for memory in existing_memories:
                    if f"user_id:{user_id}" in memory.get('memory', ''):
                        memory_id = memory.get('id')
                        if memory_id:
                            self.mem0.delete(memory_id=memory_id)
                            break
            except Exception as remove_error:
                logger.debug(f"Could not remove existing registration for {user_id}: {remove_error}")
            
            # Save the new registration
            # Use system role for scheduler metadata
            messages = [{"role": "system", "content": memory_text}]
            self.mem0.add(messages=messages, user_id=system_user_id)
            logger.info(f"💾 Saved user registration to persistent storage: {user_id}")
        except Exception as e:
            logger.error(f"Error saving user registration for {user_id}: {e}")
    
    async def _remove_user_registration(self, user_id: str):
        """Remove user registration from Mem0."""
        try:
            # Search for this user's registration record and delete it
            system_user_id = "PROACTIVE_SCHEDULER_SYSTEM"
            memories = self.mem0.search(query=f"PROACTIVE_SCHEDULER_REGISTRATION user_id:{user_id}", user_id=system_user_id, limit=10)
            
            for memory in memories:
                memory_text = memory.get('memory', '')
                if f"user_id:{user_id}" in memory_text and "PROACTIVE_SCHEDULER_REGISTRATION" in memory_text:
                    # Delete this memory record
                    memory_id = memory.get('id')
                    if memory_id:
                        self.mem0.delete(memory_id=memory_id)
                        logger.debug(f"Removed user registration from persistent storage: {user_id}")
                        break
        except Exception as e:
            logger.error(f"Error removing user registration for {user_id}: {e}")
    
    def register_user(self, user_id: str, chat_id: int):
        """Register a user for proactive messaging."""
        # Check if user is already registered
        if user_id in self.active_users:
            logger.info(f"📝 User {user_id} already registered for proactive messaging")
            return
        
        self.user_chat_mapping[user_id] = chat_id
        self.active_users.add(user_id)
        
        # Save to persistent storage immediately (blocking)
        logger.info(f"🔄 Attempting to save registration for user {user_id} to persistent storage")
        try:
            # Create an event loop if we're not in an async context
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # If we're already in an async context, schedule the task
                task = asyncio.create_task(self._save_user_registration(user_id, chat_id))
                logger.debug(f"Created async task for saving user {user_id} registration")
            else:
                # If no event loop is running, run it synchronously
                loop.run_until_complete(self._save_user_registration(user_id, chat_id))
                logger.debug(f"Ran save operation synchronously for user {user_id}")
        except RuntimeError:
            # If no event loop exists, create one and run the save operation
            asyncio.run(self._save_user_registration(user_id, chat_id))
            logger.debug(f"Created new event loop for saving user {user_id} registration")
        
        # Schedule initial check for regular messages (in 1 hour)
        initial_check_time = datetime.now() + timedelta(hours=1)
        self._schedule_user_check(user_id, initial_check_time, "regular")
        
        # Also schedule potential spontaneous messages
        self._schedule_spontaneous_messages(user_id)
        
        logger.info(f"📝 Registered user {user_id} for proactive messaging")
    
    def unregister_user(self, user_id: str):
        """Unregister a user from proactive messaging."""
        self.active_users.discard(user_id)
        self.user_chat_mapping.pop(user_id, None)
        
        # Remove from persistent storage immediately (blocking)
        try:
            # Create an event loop if we're not in an async context
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # If we're already in an async context, schedule the task
                asyncio.create_task(self._remove_user_registration(user_id))
            else:
                # If no event loop is running, run it synchronously
                loop.run_until_complete(self._remove_user_registration(user_id))
        except RuntimeError:
            # If no event loop exists, create one and run the remove operation
            asyncio.run(self._remove_user_registration(user_id))
        
        # Remove any scheduled jobs for this user
        try:
            self.scheduler.remove_job(f"proactive_check_{user_id}")
            self.scheduler.remove_job(f"spontaneous_check_{user_id}")
        except:
            pass  # Jobs might not exist
            
        logger.info(f"❌ Unregistered user {user_id} from proactive messaging")
    
    def _schedule_user_check(self, user_id: str, check_time: datetime, check_type: str = "regular"):
        """Schedule a proactive message check for a specific user."""
        if check_type == "spontaneous":
            job_id = f"spontaneous_check_{user_id}"
            method = self._check_and_send_spontaneous_message
        else:
            job_id = f"proactive_check_{user_id}"
            method = self._check_and_send_proactive_message
        
        self.scheduler.add_job(
            method,
            DateTrigger(run_date=check_time),
            args=[user_id],
            id=job_id,
            replace_existing=True
        )
        
        logger.debug(f"⏰ Scheduled {check_type} check for user {user_id} at {check_time}")
    
    async def _periodic_proactive_check(self):
        """Periodic check for all active users to see if they need proactive messages."""
        logger.debug("🔄 Running periodic proactive message check")
        
        for user_id in list(self.active_users):  # Copy to avoid modification during iteration
            try:
                await self._check_and_send_proactive_message(user_id, is_periodic=True)
            except Exception as e:
                logger.error(f"Error in periodic check for user {user_id}: {e}")
    
    async def _check_and_send_proactive_message(self, user_id: str, is_periodic: bool = False):
        """Check if a proactive message should be sent to a user and send it if appropriate."""
        try:
            # Check if conversation is currently active
            conversation_active = await conversation_tracker.is_conversation_active(user_id)
            if conversation_active:
                logger.info(f"⏸️ Conversation active for user {user_id}, postponing proactive message")
                # Reschedule for 15 minutes later
                postponed_time = datetime.now() + timedelta(minutes=15)
                self._schedule_user_check(user_id, postponed_time, "regular")
                return
            
            # Check if user has been ignoring messages
            should_send_ignore_msg = await scheduler_agent.should_send_ignore_message(user_id)
            if should_send_ignore_msg:
                logger.info(f"🤐 User {user_id} has been ignoring messages, sending ignore message")
                await self._generate_and_send_proactive_message(user_id, "ignored")
                # Don't schedule any more messages until user responds
                return
            
            # Get user's frequency preference from memory
            frequency_preference = await scheduler_agent.get_user_frequency_preference(user_id)
            
            # Get user's timezone from memory
            user_timezone = await scheduler_agent.get_user_timezone(user_id)
            if not user_timezone:
                logger.warning(f"No timezone found for user {user_id}. Defaulting to UTC.")
                user_timezone = "UTC"

            # Get last proactive message timestamp from memory
            last_proactive = await self._get_last_proactive_timestamp(user_id)
            
            # Create scheduling context
            context = SchedulingContext(
                user_id=user_id,
                last_proactive_message=last_proactive,
                last_user_response=None,  # We could track this if needed
                current_time=datetime.now(),
                user_timezone=user_timezone,
                user_frequency_preference=frequency_preference
            )
            
            # Check if we should send a proactive message
            should_send, message_type = scheduler_agent.should_send_proactive_message(context)
            
            if should_send:
                # Check if we've already sent this type of message today
                already_sent_today = await scheduler_agent.has_sent_daily_message(user_id, message_type)
                if already_sent_today:
                    logger.info(f"📅 Already sent {message_type} message today for user {user_id}, skipping")
                    # Schedule next regular check for tomorrow
                    next_check = scheduler_agent.get_next_scheduled_time(context)
                    if next_check:
                        self._schedule_user_check(user_id, next_check, "regular")
                    return
                
                # Try to generate and send the message
                message_sent_successfully = await self._generate_and_send_proactive_message(user_id, message_type)
                
                # Only mark as sent if the message was actually delivered
                if message_sent_successfully:
                    await scheduler_agent.mark_daily_message_sent(user_id, message_type)
                    logger.info(f"✅ Successfully sent and marked {message_type} message for user {user_id}")
                else:
                    logger.warning(f"⚠️ Failed to send {message_type} message for user {user_id}, not marking as sent")
                
                # Schedule next regular check
                next_check = scheduler_agent.get_next_scheduled_time(context)
                if next_check:
                    self._schedule_user_check(user_id, next_check, "regular")
            elif not is_periodic:
                # If this was a scheduled check but we're not sending, reschedule for later
                next_check = scheduler_agent.get_next_scheduled_time(context)
                if next_check:
                    self._schedule_user_check(user_id, next_check, "regular")
                    
        except Exception as e:
            logger.error(f"Error checking proactive message for user {user_id}: {e}")
    
    async def _generate_and_send_proactive_message(self, user_id: str, message_type: str) -> bool:
        """Generate and send a proactive message to the user. Returns True if successful."""
        try:
            chat_id = self.user_chat_mapping.get(user_id)
            if not chat_id:
                logger.warning(f"No chat_id found for user {user_id}")
                return False
            
            # Get prompt configuration from scheduler
            context = SchedulingContext(
                user_id=user_id,
                last_proactive_message=None,
                last_user_response=None,
                current_time=datetime.now()
            )
            prompt_config = scheduler_agent.get_proactive_message_prompt(message_type, context)
            
            # Build state for proactive message graph
            proactive_state = {
                "mem0_user_id": user_id,
                "telegram_context": {
                    "chat_id": chat_id
                },
                "message_type": message_type,
                "prompt_config": prompt_config,
                "messages": [],  # Empty for proactive messages
                "is_proactive": True
            }
            
            # Generate the proactive message using the graph
            graph_config = {
                "configurable": {
                    "thread_id": user_id,
                    "telegram_bot": self.telegram_bot
                }
            }
            
            final_state = await proactive_message_graph.ainvoke(proactive_state, config=graph_config)
            
            # Extract and send the generated message
            ai_messages = [msg for msg in final_state.get("messages", []) if isinstance(msg, AIMessage)]
            if ai_messages:
                message_content = ai_messages[-1].content
                
                # Send the message using the same delay logic as normal messages
                normalized_message = message_content.strip().replace('\r\n', '\n')
                paragraphs = [p.strip() for p in normalized_message.split('\n\n') if p.strip()]
                
                if paragraphs:
                    for i, para_text in enumerate(paragraphs):
                        is_last = (i == len(paragraphs) - 1)
                        await self._send_message_with_delay(chat_id, para_text, is_last_message=is_last)
                    
                    logger.info(f"📤 Sent proactive message to user {user_id}: {message_content[:50]}...")
                    
                    # Track this proactive message for ignore detection (unless it's an ignore message)
                    if message_type != "ignored":
                        await self._schedule_ignore_check(user_id)
                    
                    return True  # Message sent successfully
                else:
                    logger.warning(f"Generated empty proactive message for user {user_id}")
                    return False  # Empty message generated
            else:
                logger.warning(f"No AI message generated for proactive message to user {user_id}")
                return False  # No message generated
                
        except TelegramError as e:
            logger.error(f"Telegram error sending proactive message to user {user_id}: {e}")
            # If user blocked the bot or chat doesn't exist, unregister them
            if "blocked by the user" in str(e).lower() or "chat not found" in str(e).lower():
                self.unregister_user(user_id)
            return False  # Telegram error
        except Exception as e:
            logger.error(f"Error generating/sending proactive message for user {user_id}: {e}")
            return False  # General error
    
    async def _get_last_proactive_timestamp(self, user_id: str) -> Optional[datetime]:
        """Get the timestamp of the last proactive message from memory."""
        try:
            memories = self.mem0.search(query="Last proactive message sent at", user_id=user_id, limit=1)
            if memories and memories[0].get('memory'):
                memory_text = memories[0]['memory']
                # Extract timestamp from memory text
                if "sent at" in memory_text:
                    timestamp_str = memory_text.split("sent at")[-1].strip()
                    try:
                        return datetime.fromisoformat(timestamp_str)
                    except ValueError:
                        pass
            return None
        except Exception as e:
            logger.error(f"Error retrieving last proactive timestamp for user {user_id}: {e}")
            return None
    
    async def _send_message_with_delay(self, chat_id: int, text: str, is_last_message: bool = False):
        """Send a message with appropriate delay between messages."""
        import random
        
        # Send the message
        await self.telegram_bot.send_message(chat_id=chat_id, text=text)
        
        # Don't add delay after the last message
        if is_last_message:
            return
        
        # Calculate delay based on message length (same logic as main bot)
        message_length = len(text)
        base_delay = random.uniform(2.0, 4.0)
        length_factor = (message_length // 100) * random.uniform(0.5, 1.5)
        total_delay = min(base_delay + length_factor, 8.0)
        
        await asyncio.sleep(total_delay)
    
    async def _schedule_ignore_check(self, user_id: str):
        """Schedule a check to see if the user ignored the proactive message (after 2 hours)."""
        check_time = datetime.now() + timedelta(hours=2)
        job_id = f"ignore_check_{user_id}_{int(check_time.timestamp())}"
        
        self.scheduler.add_job(
            self._check_if_message_ignored,
            DateTrigger(run_date=check_time),
            args=[user_id, check_time],
            id=job_id,
            replace_existing=False  # Allow multiple ignore checks
        )
        
        logger.debug(f"⏰ Scheduled ignore check for user {user_id} at {check_time}")
    
    async def _check_if_message_ignored(self, user_id: str, message_time: datetime):
        """Check if user has responded since the proactive message was sent."""
        try:
            # Check if user has sent any message since the proactive message
            time_since_message = await conversation_tracker.get_time_since_last_message(user_id)
            
            if time_since_message is None or (datetime.now() - message_time) <= time_since_message:
                # User hasn't responded since the proactive message was sent
                await scheduler_agent.increment_ignored_count(user_id)
                logger.info(f"📵 User {user_id} ignored proactive message sent at {message_time}")
            else:
                # User has responded, reset ignore count
                await scheduler_agent.reset_ignored_count(user_id)
                logger.debug(f"✅ User {user_id} has been responsive")
                
        except Exception as e:
            logger.error(f"Error checking if message was ignored for user {user_id}: {e}")
    
    def _schedule_spontaneous_messages(self, user_id: str):
        """Schedule potential spontaneous messages for a user in all intervals."""
        try:
            current_time = datetime.now()
            intervals = scheduler_agent.schedule_config.get("spontaneous_intervals", [])
            
            for interval in intervals:
                interval_name = interval.get("name")
                start_hour = interval.get("start_hour")
                end_hour = interval.get("end_hour")
                
                # Schedule a check for this interval if we haven't already
                self._schedule_interval_spontaneous_check(user_id, interval_name, start_hour, end_hour, current_time)
                    
        except Exception as e:
            logger.error(f"Error scheduling spontaneous messages for user {user_id}: {e}")
    
    def _schedule_interval_spontaneous_check(self, user_id: str, interval_name: str, start_hour: int, end_hour: int, current_time: datetime):
        """Schedule a spontaneous message check for a specific interval."""
        try:
            # Calculate when this interval starts today
            interval_start = current_time.replace(hour=start_hour, minute=0, second=0, microsecond=0)
            interval_end = current_time.replace(hour=end_hour, minute=0, second=0, microsecond=0)
            
            # If the interval has already passed today, schedule for tomorrow
            if interval_end <= current_time:
                interval_start += timedelta(days=1)
                interval_end += timedelta(days=1)
            
            # If we're currently in the interval, schedule a check soon
            if interval_start <= current_time <= interval_end:
                check_time = current_time + timedelta(minutes=random.randint(5, 30))
            else:
                # Schedule check for random time within the interval
                interval_duration_minutes = (interval_end - interval_start).total_seconds() / 60
                random_offset_minutes = random.randint(0, int(interval_duration_minutes))
                check_time = interval_start + timedelta(minutes=random_offset_minutes)
            
            job_id = f"spontaneous_interval_{interval_name}_{user_id}"
            
            self.scheduler.add_job(
                self._check_and_send_interval_spontaneous_message,
                DateTrigger(run_date=check_time),
                args=[user_id, interval_name],
                id=job_id,
                replace_existing=True
            )
            
            logger.debug(f"⏰ Scheduled {interval_name} spontaneous check for user {user_id} at {check_time}")
            
        except Exception as e:
            logger.error(f"Error scheduling interval {interval_name} for user {user_id}: {e}")
    
    async def _check_and_send_interval_spontaneous_message(self, user_id: str, interval_name: str):
        """Check and send a spontaneous message for a specific time interval."""
        try:
            current_time = datetime.now()
            
            # Check if we're still in the correct interval
            current_interval = scheduler_agent.get_current_spontaneous_interval(current_time)
            if current_interval != interval_name:
                logger.info(f"⏰ No longer in {interval_name} interval for user {user_id}, skipping")
                return
            
            # Check if conversation is currently active
            conversation_active = await conversation_tracker.is_conversation_active(user_id)
            if conversation_active:
                logger.info(f"⏸️ Conversation active for user {user_id}, skipping {interval_name} spontaneous message")
                return
            
            # Check if user has been ignoring messages
            should_send_ignore_msg = await scheduler_agent.should_send_ignore_message(user_id)
            if should_send_ignore_msg:
                logger.info(f"🤐 User {user_id} ignoring messages, skipping {interval_name} spontaneous message")
                return
            
            # Check if we've already sent a spontaneous message in this interval today
            already_sent_in_interval = await scheduler_agent.has_sent_spontaneous_in_interval(user_id, interval_name)
            if already_sent_in_interval:
                logger.info(f"📅 Already sent spontaneous message in {interval_name} today for user {user_id}, skipping")
                return
            
            # 40% chance to send a spontaneous message
            if random.random() < scheduler_agent.schedule_config.get("scheduling_personality", {}).get("spontaneity_factor", 0.4):
                logger.info(f"🎲 Sending spontaneous message in {interval_name} for user {user_id}")
                
                # Send spontaneous message
                message_sent = await self._generate_and_send_proactive_message(user_id, "spontaneous")
                
                if message_sent:
                    # Mark spontaneous message as sent for this interval
                    await scheduler_agent.mark_spontaneous_sent_in_interval(user_id, interval_name)
                    logger.info(f"✅ Successfully sent {interval_name} spontaneous message for user {user_id}")
                else:
                    logger.warning(f"⚠️ Failed to send {interval_name} spontaneous message for user {user_id}")
            else:
                logger.info(f"🎲 No spontaneous message for {interval_name} for user {user_id} (chance not met)")
            
        except Exception as e:
            logger.error(f"Error in {interval_name} spontaneous message check for user {user_id}: {e}")

    async def _check_and_send_spontaneous_message(self, user_id: str):
        """Legacy method - keeping for compatibility but not used in new system."""
        logger.warning(f"Legacy spontaneous message method called for user {user_id} - this should not happen with new interval system")

# Global scheduler instance (will be initialized in telegram_bot.py)
background_scheduler: Optional[BackgroundScheduler] = None 