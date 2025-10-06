import os
import json
import random
import logging
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List, Tuple
from dataclasses import dataclass

import pytz
from mem0 import MemoryClient

# Configuration
MEM0_API_KEY = os.getenv("MEM0_API_KEY")
mem0 = MemoryClient(api_key=MEM0_API_KEY)

logger = logging.getLogger(__name__)

@dataclass
class SchedulingContext:
    """Context information for scheduling decisions."""
    user_id: str
    last_proactive_message: Optional[datetime]
    last_user_response: Optional[datetime]
    current_time: datetime
    user_timezone: str = "UTC"  # Default to UTC
    user_frequency_preference: Optional[str] = None  # From memory: "more", "less", "normal"

class SchedulerAgent:
    """Agent responsible for determining when and what to send for proactive messaging."""

    def __init__(self, personality_file: str = "lena.json"):
        self.personality = self._load_personality(personality_file)
        self.schedule_config = self.personality.get("daily_schedule", {})
        self.mem0 = mem0  # Expose the mem0 client as an instance attribute
        
    def _load_personality(self, file_path: str) -> Dict[str, Any]:
        """Loads personality data from a JSON file."""
        actual_path = os.path.join(os.path.dirname(__file__), "..", "..", "personalities", os.path.basename(file_path))
        try:
            with open(actual_path, 'r') as f:
                personality = json.load(f)
            return personality
        except FileNotFoundError:
            logger.error(f"Personality file not found: {actual_path}")
            return {"name": "Default Assistant", "error": "Personality file not found"}
    
    def should_send_proactive_message(self, context: SchedulingContext) -> Tuple[bool, Optional[str]]:
        """
        Determines if a proactive message should be sent and what type.
        Returns (should_send, message_type)
        """
        if not self.schedule_config:
            return False, None
            
        # Check basic timing constraints
        if not self._is_appropriate_time(context):
            return False, None
            
        # Check frequency constraints
        if not self._meets_frequency_requirements(context):
            return False, None
            
        # Determine message type based on time and context
        message_type = self._determine_message_type(context)
        
        return True, message_type
    
    def _is_appropriate_time(self, context: SchedulingContext) -> bool:
        """Check if current time is appropriate for messaging in the user's timezone."""
        try:
            user_tz = pytz.timezone(context.user_timezone)
        except pytz.UnknownTimeZoneError:
            logger.warning(f"Unknown timezone '{context.user_timezone}' for user {context.user_id}. Defaulting to UTC.")
            user_tz = pytz.utc

        current_time_user_tz = datetime.now(user_tz)
        current_hour = current_time_user_tz.hour
        
        # Basic "do not disturb" hours (late night/early morning)
        # 7 AM to 11 PM (23:00 is not allowed, only up to 22:59)
        if current_hour < 7 or current_hour >= 23:
            logger.info(f"Skipping proactive message for user {context.user_id} due to DND hours in their timezone ({context.user_timezone}). Current hour: {current_hour}")
            return False
            
        return True
    
    def _meets_frequency_requirements(self, context: SchedulingContext) -> bool:
        """Check if enough time has passed since last proactive message."""
        if not context.last_proactive_message:
            return True  # No previous message, okay to send
            
        default_freq = self.schedule_config.get("default_frequency", {})
        min_hours = default_freq.get("min_hours_between", 4)
        max_hours = default_freq.get("max_hours_between", 12)
        
        # Adjust based on user preference from memory
        if context.user_frequency_preference == "more":
            min_hours = max(1, min_hours - 2)  # More frequent, but not spam
        elif context.user_frequency_preference == "less":
            min_hours = min_hours + 4  # Less frequent
            
        time_since_last = context.current_time - context.last_proactive_message
        hours_since_last = time_since_last.total_seconds() / 3600
        
        return hours_since_last >= min_hours
    
    def _determine_message_type(self, context: SchedulingContext) -> str:
        """Determine the type of message to send based on the user's local time."""
        try:
            user_tz = pytz.timezone(context.user_timezone)
        except pytz.UnknownTimeZoneError:
            user_tz = pytz.utc

        current_time_user_tz = datetime.now(user_tz)
        current_hour = current_time_user_tz.hour
        
        logger.info(f"Determining message type for user {context.user_id} in timezone {context.user_timezone}. Current local hour: {current_hour}")

        # Time-based triggers
        if 7 <= current_hour < 12:
            return "morning_check"
        elif 12 <= current_hour < 17:
            return "afternoon_thought"
        elif 17 <= current_hour <= 22:
            return "evening_reflection"
        else:
            return "spontaneous"
    
    def get_proactive_message_prompt(self, message_type: str, context: SchedulingContext) -> Dict[str, str]:
        """Get the prompt configuration for generating a proactive message."""
        prompts = self.schedule_config.get("conversation_prompts", {})
        prompt_config = prompts.get(message_type, prompts.get("spontaneous", {}))
        
        if not prompt_config:
            # Fallback prompt configuration
            return {
                "prompt": "Generate a friendly, natural message to check in with the user. Be genuine and caring.",
                "tone": "friendly, genuine",
                "length": "1-2 sentences"
            }
            
        # Always return the appropriate prompt for the message type
        # Spontaneity now affects scheduling additional messages, not prompt selection
        return prompt_config
    
    async def get_user_timezone(self, user_id: str) -> Optional[str]:
        """Get user's timezone from memory."""
        try:
            memories = mem0.search(query="user timezone is", user_id=user_id, limit=1)
            if memories and memories[0].get('memory'):
                memory_text = memories[0]['memory']
                # Extract timezone from "User timezone is America/New_York"
                return memory_text.split("is")[-1].strip()
            return None
        except Exception as e:
            logger.error(f"Error retrieving timezone for user {user_id}: {e}")
            return None

    async def save_user_timezone(self, user_id: str, timezone: str):
        """Save user's timezone to memory."""
        try:
            # Use assistant role for user information the bot remembers
            messages = [{"role": "assistant", "content": f"User timezone is {timezone}"}]
            mem0.add(messages=messages, user_id=user_id)
            logger.info(f"Saved timezone for user {user_id}: {timezone}")
        except Exception as e:
            logger.error(f"Error saving timezone for user {user_id}: {e}")

    async def get_user_frequency_preference(self, user_id: str) -> Optional[str]:
        """Extract user's frequency preference from memories."""
        try:
            # Search for memories about messaging frequency
            frequency_queries = [
                "message me more often",
                "message me less often", 
                "too many messages",
                "not enough messages",
                "message frequency",
                "contact me more",
                "contact me less",
                "you're too clingy",
                "I want to hear from you more"
            ]
            
            for query in frequency_queries:
                memories = mem0.search(query=query, user_id=user_id)
                if memories:
                    for memory in memories:
                        memory_text = memory.get('memory', '').lower()
                        
                        # Look for frequency indicators
                        if any(phrase in memory_text for phrase in ["more often", "more frequently", "contact me more"]):
                            return "more"
                        elif any(phrase in memory_text for phrase in ["less often", "less frequently", "too many", "contact me less"]):
                            return "less"
                            
            return None  # No preference found
            
        except Exception as e:
            logger.error(f"Error retrieving frequency preference for user {user_id}: {e}")
            return None
    
    async def is_conversation_active(self, user_id: str) -> bool:
        """Check if user is currently in an active conversation (last message < 30 min ago)."""
        try:
            # Search for recent user messages
            memories = mem0.search(query="User:", user_id=user_id, limit=1)
            if memories and memories[0].get('memory'):
                memory_text = memories[0]['memory']
                # This is a simplified check - in practice, you'd want to track timestamps more precisely
                # For now, we'll assume if there's recent memory, conversation might be active
                # You could enhance this by storing precise timestamps
                return False  # For now, assume conversation is not active
            return False
        except Exception as e:
            logger.error(f"Error checking conversation activity for user {user_id}: {e}")
            return False
    
    async def get_ignored_message_count(self, user_id: str) -> int:
        """Get the count of consecutive ignored proactive messages."""
        try:
            memories = mem0.search(query="consecutive ignored proactive messages", user_id=user_id, limit=1)
            if memories and memories[0].get('memory'):
                memory_text = memories[0]['memory']
                # Extract count from memory text like "User has ignored 2 consecutive proactive messages"
                import re
                match = re.search(r'ignored (\d+) consecutive', memory_text)
                if match:
                    return int(match.group(1))
            return 0
        except Exception as e:
            logger.error(f"Error retrieving ignored message count for user {user_id}: {e}")
            return 0
    
    async def increment_ignored_count(self, user_id: str):
        """Increment the count of consecutive ignored proactive messages."""
        try:
            current_count = await self.get_ignored_message_count(user_id)
            new_count = current_count + 1
            # Use system role for tracking metadata
            messages = [{"role": "system", "content": f"User has ignored {new_count} consecutive proactive messages without responding"}]
            mem0.add(messages=messages, user_id=user_id)
            logger.info(f"User {user_id} ignored count increased to {new_count}")
        except Exception as e:
            logger.error(f"Error incrementing ignored count for user {user_id}: {e}")
    
    async def reset_ignored_count(self, user_id: str):
        """Reset the ignored message count when user responds."""
        try:
            # Use system role for tracking metadata
            messages = [{"role": "system", "content": "User has ignored 0 consecutive proactive messages - they are responsive"}]
            mem0.add(messages=messages, user_id=user_id)
            logger.info(f"Reset ignored count for user {user_id}")
        except Exception as e:
            logger.error(f"Error resetting ignored count for user {user_id}: {e}")
    
    async def should_send_ignore_message(self, user_id: str) -> bool:
        """Check if we should send a special message about being ignored."""
        ignored_count = await self.get_ignored_message_count(user_id)
        return ignored_count >= 2
    
    async def has_sent_daily_message(self, user_id: str, message_type: str) -> bool:
        """Check if we've already sent a specific type of message today."""
        try:
            from datetime import date
            today = date.today().isoformat()
            # Use a very specific marker to avoid false positives from semantic search
            marker = f"DAILY_MESSAGE_SENT_{message_type.upper()}_{today}"
            search_query = marker
            
            memories = mem0.search(query=search_query, user_id=user_id, limit=3)
            if memories:
                for memory in memories:
                    memory_text = memory.get('memory', '')
                    # Require exact match of our marker in the memory text
                    if marker in memory_text:
                        logger.debug(f"Found marker for {message_type} for user {user_id} today.")
                        return True
            logger.debug(f"No marker found for {message_type} for user {user_id} today.")
            return False
        except Exception as e:
            logger.error(f"Error checking daily message status for user {user_id}: {e}")
            return False

    async def has_sent_spontaneous_in_interval(self, user_id: str, interval_name: str) -> bool:
        """Check if we've already sent a spontaneous message in this time interval today."""
        try:
            from datetime import date
            today = date.today().isoformat()
            # Use a very specific marker to avoid false positives from semantic search
            marker = f"SPONTANEOUS_INTERVAL_SENT_{interval_name}_{today}"
            search_query = marker
            
            memories = mem0.search(query=search_query, user_id=user_id, limit=3)
            if memories:
                for memory in memories:
                    memory_text = memory.get('memory', '')
                    # Require exact match of our marker in the memory text
                    if marker in memory_text:
                        return True
            return False
        except Exception as e:
            logger.error(f"Error checking spontaneous interval status for user {user_id}: {e}")
            return False

    async def mark_spontaneous_sent_in_interval(self, user_id: str, interval_name: str):
        """Mark that we've sent a spontaneous message in this time interval today."""
        try:
            from datetime import date
            today = date.today().isoformat()
            # Use a specific marker that won't be confused with other memories
            marker = f"SPONTANEOUS_INTERVAL_SENT_{interval_name}_{today}"
            memory_text = f"{marker} - Spontaneous message completed for {interval_name} interval on {today}"
            # Use system role for tracking metadata
            messages = [{"role": "system", "content": memory_text}]
            mem0.add(messages=messages, user_id=user_id)
        except Exception as e:
            logger.error(f"Error marking spontaneous interval sent for user {user_id}: {e}")
    
    def get_current_spontaneous_interval(self, current_time: datetime) -> Optional[str]:
        """Determine which spontaneous interval we're currently in."""
        current_hour = current_time.hour
        intervals = self.schedule_config.get("spontaneous_intervals", [])
        
        for interval in intervals:
            start_hour = interval.get("start_hour")
            end_hour = interval.get("end_hour")
            if start_hour <= current_hour < end_hour:
                return interval.get("name")
        
        return None
    
    async def mark_daily_message_sent(self, user_id: str, message_type: str):
        """Mark that we've sent a daily message of this type."""
        try:
            from datetime import date
            today = date.today().isoformat()
            # Use a specific marker that won't be confused with other memories
            marker = f"DAILY_MESSAGE_SENT_{message_type.upper()}_{today}"
            memory_text = f"{marker} - Daily message '{message_type}' completed for {today}"
            # Use system role for tracking metadata
            messages = [{"role": "system", "content": memory_text}]
            mem0.add(messages=messages, user_id=user_id)
            logger.info(f"Marked daily message {message_type} as sent for user {user_id}")
        except Exception as e:
            logger.error(f"Error marking daily message sent for user {user_id}: {e}")
    
    async def update_proactive_message_timestamp(self, user_id: str):
        """Store timestamp of sent proactive message in memory."""
        try:
            # Use system role for tracking metadata
            messages = [{"role": "system", "content": f"Last proactive message sent at {datetime.now().isoformat()}"}]
            mem0.add(messages=messages, user_id=user_id)
        except Exception as e:
            logger.error(f"Error storing proactive message timestamp for user {user_id}: {e}")
    
    def get_next_scheduled_time(self, context: SchedulingContext, message_type: Optional[str] = None) -> Optional[datetime]:
        """Calculate when the next proactive message should be sent."""
        if not self.schedule_config:
            return None
            
        preferred_times = self.schedule_config.get("preferred_times", [])
        current_time = context.current_time
        
        # If this is for a spontaneous message, schedule it randomly
        if message_type == "spontaneous":
            return self._get_next_spontaneous_time(context)
        
        # Find next preferred time today or tomorrow with random offset
        for time_config in preferred_times:
            time_str = time_config.get("time", "")
            try:
                hour, minute = map(int, time_str.split(":"))
                base_scheduled_time = current_time.replace(hour=hour, minute=minute, second=0, microsecond=0)
                
                # Add random offset: ±30 minutes
                offset_minutes = random.randint(-30, 30)
                scheduled_time = base_scheduled_time + timedelta(minutes=offset_minutes)
                
                # If time has passed today, try tomorrow (with new random offset)
                if scheduled_time <= current_time:
                    base_scheduled_time += timedelta(days=1)
                    offset_minutes = random.randint(-30, 30)
                    scheduled_time = base_scheduled_time + timedelta(minutes=offset_minutes)
                    
                # Check if this meets frequency requirements
                test_context = SchedulingContext(
                    user_id=context.user_id,
                    last_proactive_message=context.last_proactive_message,
                    last_user_response=context.last_user_response,
                    current_time=scheduled_time,
                    user_frequency_preference=context.user_frequency_preference
                )
                
                if self._meets_frequency_requirements(test_context):
                    return scheduled_time
                    
            except ValueError:
                continue
                
        # Fallback: schedule based on frequency settings
        default_freq = self.schedule_config.get("default_frequency", {})
        min_hours = default_freq.get("min_hours_between", 4)
        
        if context.user_frequency_preference == "more":
            min_hours = max(1, min_hours - 2)
        elif context.user_frequency_preference == "less":
            min_hours = min_hours + 4
            
        base_time = context.last_proactive_message or current_time
        return base_time + timedelta(hours=min_hours)
    
    def _get_next_spontaneous_time(self, context: SchedulingContext) -> datetime:
        """Calculate when the next spontaneous message should be sent."""
        current_time = context.current_time
        
        # Schedule spontaneous messages at random times during appropriate hours
        # Avoid late night/early morning (7 AM to 11 PM)
        min_hours_from_now = 1  # At least 1 hour from now
        max_hours_from_now = 8  # At most 8 hours from now
        
        # Adjust based on user frequency preference
        if context.user_frequency_preference == "more":
            max_hours_from_now = 4  # More frequent spontaneous messages
        elif context.user_frequency_preference == "less":
            min_hours_from_now = 4  # Less frequent spontaneous messages
            max_hours_from_now = 12
        
        # Generate random time within the range
        random_hours = random.uniform(min_hours_from_now, max_hours_from_now)
        proposed_time = current_time + timedelta(hours=random_hours)
        
        # Ensure it's during appropriate hours (7 AM to 11 PM)
        if proposed_time.hour < 7:
            # Too early, move to 7-11 AM
            proposed_time = proposed_time.replace(hour=random.randint(7, 11))
        elif proposed_time.hour >= 23:
            # Too late, move to next day 7-11 AM
            proposed_time = proposed_time.replace(hour=random.randint(7, 11)) + timedelta(days=1)
            
        return proposed_time
    
    def should_schedule_spontaneous_message(self, context: SchedulingContext) -> bool:
        """Determine if we should schedule additional spontaneous messages."""
        spontaneity = self.schedule_config.get("scheduling_personality", {}).get("spontaneity_factor", 0.3)
        
        # Use spontaneity factor to determine if we should schedule spontaneous messages
        # Higher spontaneity = more likely to schedule additional random messages
        return random.random() < spontaneity

# Global instance
scheduler_agent = SchedulerAgent() 