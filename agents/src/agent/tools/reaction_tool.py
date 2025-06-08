"""Reaction tool for adding emoji reactions to messages.

This tool allows the agent to add reactions to Telegram messages to express
emotions or responses without sending text messages.
"""

import logging
from typing import Dict, Any, Optional, List
from telegram import Bot
from telegram.error import TelegramError

logger = logging.getLogger(__name__)

class ReactionTool:
    """Tool for adding reactions to Telegram messages."""
    
    # Common reaction emojis that work well in Telegram
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
    
    def __init__(self):
        """Initialize the reaction tool."""
        self.name = "add_reaction"
        self.description = "Add an emoji reaction to the user's message to express emotion or response"
        
    async def execute(self, bot: Bot, chat_id: int, message_id: int, reaction: str) -> Dict[str, Any]:
        """
        Add a reaction to a specific message.
        
        Args:
            bot: Telegram bot instance
            chat_id: Chat ID where the message is located
            message_id: ID of the message to react to
            reaction: Emoji reaction to add
            
        Returns:
            Dict with success status and details
        """
        try:
            logger.info(f"🎯 ATTEMPTING REACTION: '{reaction}' → message {message_id} in chat {chat_id}")
            
            # Validate reaction
            if not self.validate_reaction(reaction):
                logger.warning(f"Reaction '{reaction}' not in available reactions. Using closest match.")
                # Find a similar reaction or default to thumbs up
                reaction = self._get_similar_reaction(reaction)
                logger.info(f"🔄 USING REPLACEMENT REACTION: '{reaction}'")
            
            # Add the reaction using Telegram Bot API
            # Import ReactionTypeEmoji for proper reaction format
            from telegram import ReactionTypeEmoji
            logger.debug(f"📞 Calling bot.set_message_reaction with ReactionTypeEmoji(emoji='{reaction}')")
            
            await bot.set_message_reaction(
                chat_id=chat_id,
                message_id=message_id,
                reaction=[ReactionTypeEmoji(emoji=reaction)]
            )
            
            logger.info(f"🎉 REACTION ADDED: '{reaction}' → message {message_id} in chat {chat_id}")
            
            return {
                "success": True,
                "reaction": reaction,
                "message": f"Added reaction {reaction}",
                "chat_id": chat_id,
                "message_id": message_id
            }
            
        except TelegramError as e:
            logger.error(f"Telegram error adding reaction: {e}")
            return {
                "success": False,
                "error": f"Telegram error: {str(e)}",
                "reaction": reaction
            }
        except Exception as e:
            logger.error(f"Unexpected error adding reaction: {e}")
            return {
                "success": False,
                "error": f"Unexpected error: {str(e)}",
                "reaction": reaction
            }
    
    def _get_similar_reaction(self, requested_reaction: str) -> str:
        """
        Get a similar reaction if the requested one is not available.
        
        Args:
            requested_reaction: The reaction that was requested
            
        Returns:
            A similar available reaction
        """
        # Simple mapping for common cases
        reaction_mapping = {
            "😀": "😁", "😊": "🥰", "😂": "🤣", "😍": "🥰",
            "😘": "💋", "🙂": "👍", "😉": "😁", "😋": "😁",
            "🤗": "🤗", "🤔": "🤔", "😏": "🤨", "😒": "🙄",
            "😞": "😢", "😭": "😭", "😡": "🤬", "🤯": "🤯",
            "🥳": "🎉", "😴": "😴", "🤤": "🤤", "🙄": "🙄"
        }
        
        if requested_reaction in reaction_mapping:
            return reaction_mapping[requested_reaction]
        
        # Default fallbacks based on sentiment
        positive_reactions = ["👍", "❤️", "😁", "🎉", "👏"]
        negative_reactions = ["👎", "😢", "🤔", "😐"]
        
        # Very basic sentiment analysis based on unicode categories
        if requested_reaction in ["😀", "😃", "😄", "😁", "😆", "😂", "🤣", "😊", "😇", "🥰", "😍", "🤩", "😘", "😗", "😚", "😙", "😋", "😛", "😜", "🤪", "😝", "🤑", "🤗", "🤭", "🤫", "🤔", "🤐", "🤨", "😐", "😑", "😶", "😏", "😒", "🙄", "😬", "🤥", "😌", "😔", "😪", "🤤", "😴", "😷", "🤒", "🤕", "🤢", "🤮", "🤧", "🥵", "🥶", "🥴", "😵", "🤯", "🤠", "🥳"]:
            return positive_reactions[0]  # Default to thumbs up
        else:
            return "👍"  # Safe default
    
    def validate_reaction(self, reaction: str) -> bool:
        """
        Validate if a reaction is available in Telegram.
        
        Args:
            reaction: The emoji reaction to validate
            
        Returns:
            True if the reaction is available
        """
        return reaction in self.AVAILABLE_REACTIONS 