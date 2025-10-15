import os
import subprocess
import tempfile
from typing import Optional

from agents import function_tool


@function_tool
def execute_applescript(code_snippet: str, timeout: Optional[int] = 60) -> str:
    """
    Execute AppleScript code to interact with Mac applications and system features.

    This tool provides comprehensive access to macOS applications and system functionality through AppleScript.
    It can interact with and manipulate data across the entire Apple ecosystem on Mac.

    **Primary Capabilities:**

    📝 **Apple Notes Integration:**
    - Create, read, modify, and organize notes
    - Search notes by content, title, or folder
    - Manage note folders and organization
    - Export notes to various formats

    📅 **Calendar & Events:**
    - Access calendar events and appointments
    - Create new calendar entries with details
    - Modify existing events (time, location, attendees)
    - Search events by date range or keywords
    - Manage multiple calendars

    👥 **Contacts Management:**
    - Retrieve contact information (names, phones, emails, addresses)
    - Add new contacts with complete details
    - Update existing contact information
    - Search contacts by various criteria
    - Organize contacts into groups

    🔍 **Finder & File System:**
    - Navigate and search files using Spotlight
    - Create, move, copy, and organize files and folders
    - Get file properties (size, creation date, permissions)
    - Manage desktop and downloads folder
    - Access recent files and favorites

    💻 **System Information:**
    - Check battery status and power settings
    - Monitor disk space and storage usage
    - Get network connectivity and WiFi information
    - Access system preferences and settings
    - Retrieve hardware information (RAM, CPU, etc.)

    🌐 **Safari & Web Browsing:**
    - Read and organize browser bookmarks
    - Access browsing history
    - Control tabs and windows
    - Extract webpage content
    - Manage reading list

    📧 **Mail & Communications:**
    - Read, compose, and send emails
    - Access mailbox folders and organization
    - Search emails by sender, subject, or content
    - Manage email accounts and signatures
    - Process attachments

    💬 **Messages & Communication:**
    - Send and receive text messages
    - Access message history
    - Manage conversation threads
    - Send media attachments via Messages

    🎵 **Media & Entertainment:**
    - Control Music/iTunes playback
    - Access music library and playlists
    - Control volume and audio settings
    - Manage Photos library and albums

    ⚙️ **Application Control:**
    - Launch, quit, and control any Mac application
    - Interact with application menus and dialogs
    - Automate repetitive tasks across applications
    - Manage window positioning and organization

    🔧 **System Control:**
    - Execute shell commands and capture output
    - Control system sleep, restart, and shutdown
    - Manage user accounts and permissions
    - Access and modify system preferences
    - Control accessibility features

    **Security Note:** This tool operates with the same permissions as the user running it.
    It can access any data and perform any actions that the user account has permissions for.

    **Usage Examples:**

    Simple note creation:
    ```applescript
    tell application "Notes"
        make new note at folder "Notes" with properties {name:"My Note", body:"Note content"}
    end tell
    ```

    Get calendar events:
    ```applescript
    tell application "Calendar"
        set today to current date
        set todayEvents to events of calendar "Calendar" whose start date ≥ today and start date < today + days
        return todayEvents
    end tell
    ```

    System information:
    ```applescript
    set batteryInfo to do shell script "pmset -g batt"
    set diskSpace to do shell script "df -h /"
    return "Battery: " & batteryInfo & return & "Disk: " & diskSpace
    ```

    Args:
        code_snippet: Multi-line AppleScript code to execute. Should be valid AppleScript syntax.
        timeout: Maximum execution time in seconds (default: 60). Prevents hanging on long operations.

    Returns:
        String containing the output from the AppleScript execution, or error message if execution fails.

    Raises:
        No exceptions are raised - all errors are returned as descriptive error messages in the output string.
    """
    if not code_snippet or not code_snippet.strip():
        return "Error: code_snippet cannot be empty"

    # Create temporary file for the AppleScript
    with tempfile.NamedTemporaryFile(mode="w", suffix=".scpt", delete=False, encoding="utf-8") as temp_file:
        temp_path = temp_file.name
        try:
            # Write the AppleScript to the temp file
            temp_file.write(code_snippet)
            temp_file.flush()

            # Execute the AppleScript using osascript
            cmd = ["/usr/bin/osascript", temp_path]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, encoding="utf-8")

            if result.returncode != 0:
                error_message = (
                    f"AppleScript execution failed (return code {result.returncode}): {result.stderr.strip()}"
                )
                return error_message

            # Return the output, or a success message if no output
            output = result.stdout.strip()
            return output if output else "AppleScript executed successfully (no output)"

        except subprocess.TimeoutExpired:
            return f"AppleScript execution timed out after {timeout} seconds"
        except FileNotFoundError:
            return "Error: osascript command not found. This tool only works on macOS systems."
        except PermissionError:
            return "Error: Permission denied executing AppleScript. Check system permissions."
        except Exception as e:
            return f"Error executing AppleScript: {str(e)}"
        finally:
            # Clean up the temporary file
            try:
                os.unlink(temp_path)
            except OSError:
                pass  # Ignore cleanup errors
