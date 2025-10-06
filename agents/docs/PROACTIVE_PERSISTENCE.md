# Proactive Messaging Persistence

## Overview

The bot now persists user registrations for proactive messaging across restarts. When the bot restarts, previously registered users will automatically be restored and continue receiving proactive messages.

## How It Works

### Storage Mechanism
- User registrations are stored in Mem0 using a special format: `PROACTIVE_SCHEDULER_REGISTRATION user_id:{user_id} chat_id:{chat_id} registered_at:{timestamp}`
- This data is stored in global memory (not user-specific) so it can be retrieved during startup

### Startup Process
1. When the `BackgroundScheduler` starts, it calls `_restore_user_registrations()`
2. This method searches Mem0 for all registration records
3. Each valid registration is parsed to extract user_id and chat_id
4. Users are added back to `active_users` and `user_chat_mapping`
5. Proactive message scheduling is resumed for each restored user

### Registration Management
- **Register**: When a user is registered, their data is saved to Mem0
- **Unregister**: When a user is unregistered, their data is removed from Mem0
- **Duplicate Prevention**: Before saving a new registration, any existing registration for that user is removed

### Scheduling After Restore
- Restored users get an initial proactive message check scheduled for 1 hour after restart
- This prevents spam immediately after bot restart
- Spontaneous messages are also rescheduled normally

## Technical Details

### Key Methods Added
- `_restore_user_registrations()`: Loads existing registrations from Mem0
- `_save_user_registration()`: Saves a registration to Mem0
- `_remove_user_registration()`: Removes a registration from Mem0
- `_reschedule_user_proactive_messages()`: Reschedules messaging for restored users

### Error Handling
- Graceful handling of malformed registration data
- Logging of restoration success/failure
- Fallback behavior if Mem0 is unavailable

### Performance Considerations
- Registration data is loaded once at startup
- Mem0 operations are async to avoid blocking
- Limited search results (100 registrations max) to prevent memory issues

## Benefits

1. **Continuity**: Users don't lose their proactive messaging registration when the bot restarts
2. **User Experience**: No need to re-register or restart conversations
3. **Reliability**: Bot restarts (for updates, crashes, etc.) don't affect service
4. **Scalability**: Can handle restoration of many users efficiently

## Testing

A test script `test_persistence.py` is available to verify the persistence functionality works correctly. 