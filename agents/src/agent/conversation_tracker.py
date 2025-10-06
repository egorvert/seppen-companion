import asyncio
import logging
from datetime import datetime, timedelta
from typing import Dict, Optional
from mem0 import MemoryClient
import os

logger = logging.getLogger(__name__)

class ConversationTracker:
    """Tracks conversation activity to avoid interrupting active chats."""
    
    def __init__(self):
        self.mem0 = MemoryClient(api_key=os.getenv("MEM0_API_KEY"))
        self.last_user_message: Dict[str, datetime] = {}
        self.conversation_timeout_minutes = 30
    
    def update_user_activity(self, user_id: str):
        """Update the last activity timestamp for a user."""
        self.last_user_message[user_id] = datetime.now()
        
        # Also store in memory for persistence across bot restarts
        asyncio.create_task(self._store_activity_in_memory(user_id))
    
    async def _store_activity_in_memory(self, user_id: str):
        """Store user activity timestamp in memory."""
        try:
            timestamp = datetime.now().isoformat()
            # Use system role for metadata
            messages = [{"role": "system", "content": f"Last user message timestamp: {timestamp}"}]
            self.mem0.add(messages=messages, user_id=user_id)
        except Exception as e:
            logger.error(f"Error storing activity timestamp for user {user_id}: {e}")
    
    async def is_conversation_active(self, user_id: str) -> bool:
        """Check if user is currently in an active conversation."""
        # First check in-memory tracker
        if user_id in self.last_user_message:
            time_since_last = datetime.now() - self.last_user_message[user_id]
            if time_since_last.total_seconds() < (self.conversation_timeout_minutes * 60):
                return True
        
        # Fallback: check memory for persistent tracking
        try:
            memories = self.mem0.search(query="Last user message timestamp", user_id=user_id, limit=1)
            if memories and memories[0].get('memory'):
                memory_text = memories[0]['memory']
                if "timestamp:" in memory_text:
                    timestamp_str = memory_text.split("timestamp:")[-1].strip()
                    try:
                        last_message_time = datetime.fromisoformat(timestamp_str)
                        time_since_last = datetime.now() - last_message_time
                        return time_since_last.total_seconds() < (self.conversation_timeout_minutes * 60)
                    except ValueError:
                        pass
        except Exception as e:
            logger.error(f"Error checking conversation activity for user {user_id}: {e}")
        
        return False
    
    async def get_time_since_last_message(self, user_id: str) -> Optional[timedelta]:
        """Get the time elapsed since the user's last message."""
        # Check in-memory first
        if user_id in self.last_user_message:
            return datetime.now() - self.last_user_message[user_id]
        
        # Check memory
        try:
            memories = self.mem0.search(query="Last user message timestamp", user_id=user_id, limit=1)
            if memories and memories[0].get('memory'):
                memory_text = memories[0]['memory']
                if "timestamp:" in memory_text:
                    timestamp_str = memory_text.split("timestamp:")[-1].strip()
                    try:
                        last_message_time = datetime.fromisoformat(timestamp_str)
                        return datetime.now() - last_message_time
                    except ValueError:
                        pass
        except Exception as e:
            logger.error(f"Error getting last message time for user {user_id}: {e}")
        
        return None
    
    def cleanup_old_activities(self):
        """Clean up old activity records to prevent memory leaks."""
        cutoff_time = datetime.now() - timedelta(hours=24)
        users_to_remove = []
        
        for user_id, last_time in self.last_user_message.items():
            if last_time < cutoff_time:
                users_to_remove.append(user_id)
        
        for user_id in users_to_remove:
            del self.last_user_message[user_id]

# Global conversation tracker instance
conversation_tracker = ConversationTracker() 