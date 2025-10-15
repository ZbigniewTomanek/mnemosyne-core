# Telegram File API Usage Guide

This document explains how to use Telegram's file handling capabilities in the bot, specifically for environment variable management with file support.

## Overview

The Telegram Bot API provides robust file handling capabilities that allow bots to:
- Send files to users as downloadable documents
- Receive file uploads from users
- Handle various file types and sizes

## File Size Limits

- **Maximum downloadable file size**: 20 MB
- **Maximum uploadable file size**: 20 MB (via Bot API)
- **File download links**: Valid for at least 1 hour

## Sending Files to Users

### Using `reply_document()`

```python
import io
from telegram import Update
from telegram.ext import CallbackContext

async def send_file_example(update: Update, context: CallbackContext):
    # Create file content
    content = "This is the file content"
    file_bytes = content.encode('utf-8')
    
    # Create a BytesIO object
    file_obj = io.BytesIO(file_bytes)
    file_obj.name = "example.txt"  # Set filename
    
    # Send as document
    await update.message.reply_document(
        document=file_obj,
        filename="example.txt",
        caption="📄 Here's your file!\n\n💾 Size: {len(file_bytes)} bytes"
    )
```

### Key Parameters for `reply_document()`

- `document`: File object, file path, or file URL
- `filename`: Name for the downloaded file
- `caption`: Optional description text (supports Markdown)
- `parse_mode`: Text formatting (e.g., `ParseMode.MARKDOWN`)

## Receiving Files from Users

### Document Message Handler

```python
from telegram import Document, Update
from telegram.ext import MessageHandler, filters

# Handler for document uploads
async def handle_document(update: Update, context: CallbackContext):
    document: Document = update.message.document
    
    # Validate file size
    if document.file_size > 20 * 1024 * 1024:  # 20MB
        await update.message.reply_text("❌ File too large (max 20MB)")
        return
    
    # Download file
    file = await document.get_file()
    file_content = await file.download_as_bytearray()
    
    # Process content
    try:
        text_content = file_content.decode('utf-8')
        # Process the text content...
    except UnicodeDecodeError:
        await update.message.reply_text("❌ File must contain valid UTF-8 text")
        return

# Register the handler
app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
```

### Document Object Properties

- `file_id`: Unique identifier for the file
- `file_unique_id`: Consistent identifier across bots
- `file_name`: Original filename from sender
- `mime_type`: MIME type of the file
- `file_size`: File size in bytes
- `thumbnail`: Optional thumbnail for the document

## Environment Variable File Handlers

### Reading Environment Variables as Files

The bot provides `/read_env_file VARIABLE_NAME` command that:

1. **Checks variable length**: If >4000 characters, sends as file
2. **Creates downloadable file**: Uses `io.BytesIO` to create in-memory file
3. **Sends with metadata**: Includes file size and variable name in caption

```python
# Example: Reading a large JSON configuration
# Command: /read_env_file CONFIG_JSON
# Result: Downloads "CONFIG_JSON.txt" with the full JSON content
```

### Setting Environment Variables from Files

The bot provides `/set_env_file VARIABLE_NAME` conversation that:

1. **Prompts for file upload**: Guides user through file upload process
2. **Validates file**: Checks size, encoding, and format
3. **Processes content**: Handles JSON formatting if needed
4. **Updates .env file**: Safely writes to environment file

```python
# Example conversation flow:
# 1. User: /set_env_file API_CONFIG
# 2. Bot: "Please upload a text file..."
# 3. User: [uploads config.json]
# 4. Bot: "✅ Environment variable updated successfully!"
```

## Conversation States

File-based operations use conversation handlers with these states:

```python
# State definitions
WAITING_FOR_FILE = 1

# Conversation flow
ConversationHandler(
    entry_points=[CommandHandler("set_env_file", start_handler)],
    states={
        WAITING_FOR_FILE: [
            MessageHandler(filters.Document.ALL, file_handler),
        ],
    },
    fallbacks=[CommandHandler("cancel", cancel_handler)],
)
```

## Error Handling

### Common Error Cases

1. **File too large**: Check `document.file_size` before processing
2. **Invalid encoding**: Handle `UnicodeDecodeError` for text files
3. **Invalid JSON**: Use `json.loads()` with try/catch for JSON files
4. **Network issues**: Handle file download failures gracefully

### Example Error Handling

```python
try:
    # Download and process file
    file = await document.get_file()
    content = await file.download_as_bytearray()
    text = content.decode('utf-8')
    
    # Validate JSON if needed
    if filename.endswith('.json'):
        json.loads(text)  # Validate JSON format
        
except UnicodeDecodeError:
    await update.message.reply_text("❌ File must contain valid UTF-8 text")
except json.JSONDecodeError as e:
    await update.message.reply_text(f"❌ Invalid JSON format: {str(e)}")
except Exception as e:
    await update.message.reply_text(f"❌ Error processing file: {str(e)}")
```

## Best Practices

### File Validation

- Always check file size before processing
- Validate file encoding for text files
- Verify file format for structured data (JSON, XML, etc.)
- Sanitize filenames to prevent path injection

### User Experience

- Provide clear instructions for file uploads
- Show progress indicators for large files
- Include helpful error messages
- Offer fallback options for failed operations

### Security Considerations

- Never execute uploaded files
- Validate file types and content
- Limit file sizes appropriately
- Scan for malicious content when necessary

### Performance

- Use streaming for large files when possible
- Implement timeouts for file operations
- Clean up temporary files promptly
- Consider file caching for frequently accessed files

## Available Commands

| Command | Description | Usage |
|---------|-------------|-------|
| `/read_env VAR` | Read short env variables | Text response |
| `/read_env_file VAR` | Download large env variables | File download |
| `/set_env VAR value` | Set short env variables | Command with args |
| `/set_env_file VAR` | Upload file to set env variable | Conversation flow |

## Implementation Files

- `telegram_bot/handlers/conversations/env_file_conversation.py`: File-based handlers
- `telegram_bot/handlers/commands/env_commands.py`: Command-based handlers
- `telegram_bot/main.py`: Handler registration

This implementation provides a robust, user-friendly way to handle large environment variables while maintaining the simplicity of text-based commands for smaller values.