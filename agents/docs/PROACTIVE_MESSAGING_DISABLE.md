# Proactive Messaging Disable/Enable Documentation

## Current Status
Proactive messaging has been **TEMPORARILY DISABLED** by setting `ENABLE_PROACTIVE_MESSAGING=false` in the `.env` file.

## How It Works

### Disable Mechanism
The proactive messaging system is disabled at the initialization level:

1. **Environment Variable**: `ENABLE_PROACTIVE_MESSAGING=false` in `.env`
2. **Bot Initialization**: `src/telegram_bot.py` checks this flag and conditionally initializes the `BackgroundScheduler`
3. **User Registration**: All calls to `background_scheduler.register_user()` are protected with null checks
4. **Scheduler Operations**: Start/stop operations check if scheduler exists before executing

### Files Modified

#### `.env`
- Added `ENABLE_PROACTIVE_MESSAGING=false` configuration flag

#### `src/telegram_bot.py`
- Added `ENABLE_PROACTIVE_MESSAGING` environment variable reading
- Modified startup message to show feature status
- Conditionally initialize `BackgroundScheduler` based on flag
- Added null checks for scheduler start/stop operations
- Existing null checks for `register_user()` calls were already in place

#### No changes needed to:
- `src/agent/background_scheduler.py` - operates normally when initialized
- `src/agent/proactive_agent.py` - operates normally when called
- `src/agent/scheduler_agent.py` - operates normally when called
- `src/agent/proactive_graph.py` - operates normally when called

## How to Re-enable Proactive Messaging

### Option 1: Change Environment Variable
1. Edit `.env` file
2. Change `ENABLE_PROACTIVE_MESSAGING=false` to `ENABLE_PROACTIVE_MESSAGING=true`
3. Restart the bot

### Option 2: Remove Environment Variable
1. Remove the `ENABLE_PROACTIVE_MESSAGING` line from `.env` (defaults to true)
2. Restart the bot

## Verification

When proactive messaging is **disabled**, you should see:
```
🤖 STARTING AI COMPANION BOT
📋 Features enabled: Text messages, Photos, Reactions
⏸️ Proactive messaging is DISABLED (ENABLE_PROACTIVE_MESSAGING=false)
```

When proactive messaging is **enabled**, you should see:
```
🤖 STARTING AI COMPANION BOT
📋 Features enabled: Text messages, Photos, Reactions, Proactive Messaging
🕐 Background scheduler started with X restored users
```

## What's Preserved

All proactive messaging code is **completely intact**:
- ✅ All scheduling logic
- ✅ All proactive message generation
- ✅ All user timezone handling
- ✅ All conversation tracking
- ✅ All background jobs and intervals
- ✅ All persistence functionality

Only the **initialization** is disabled - no functionality has been removed or broken.