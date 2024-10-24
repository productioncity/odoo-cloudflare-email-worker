#!/usr/bin/env python3
"""
llm.py

This script facilitates interaction with the OpenAI API, managing conversation state,
and updating files in the repository based on LLM responses.

Author: Troy Kelly
Email: troy@aperim.com
Date: Saturday, 19 October 2024

Updates:
- Fixed issue with "double wrapping" in files generated from LLM responses.
- Added function to clean Markdown code blocks from LLM responses before file updates.
"""

import argparse
import json
import logging
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import openai
from openai import OpenAI

# ========================================================================
# System Prompt Template
#
# The system prompt is embedded directly within this script for portability.
# You can edit the prompt below as needed.
# ========================================================================

SYSTEM_PROMPT_TEMPLATE = """
## Requirements

### Language

- **Use Australian English** in all responses.

### Responses

When refactoring or modifying code:

- **Provide Complete, Operable Files**: Respond with full, functional code files. **Do not use placeholders** or omit any code that the user would need to replace.
- **Never Truncate**: Only ever provide complete files.
- **Never use placeholders**: Never remove operable code in a response. Never replace code with a placeholder.
- **Preserve Existing Functionality**: Do not remove any existing functionality unless explicitly instructed to do so.
- **Handling Long Outputs**:
  - If the output is too long or there are too many files to include in a single response:
    - Provide as many complete files as possible.
    - Indicate that more output is available by including the marker: `<<LLM_MORE_OUTPUT_AVAILABLE>>`
    - After all output has been provided, indicate the end with: `<<LLM_CONTINUED_OUTPUT_END>>`

**Example**:

```
[Your code output here]

<<LLM_MORE_OUTPUT_AVAILABLE>>
```

### File Demarcation

When providing complete files, **use the following unique markers** to clearly indicate the start and end of each file's content. **Do not double-wrap** with markdown tags; only use these markers:

- **Start of File**: `<<LLM_FILE_START: [filename]>>`
- **End of File**: `<<LLM_FILE_END>>`

**Example**:

```
<<LLM_FILE_START: frontend/src/redux/slices/userSlice.ts>>
[File content goes here]
<<LLM_FILE_END>>
```

*Use these markers exactly as shown, including the double angle brackets and the notation.*

## Technical and Coding Proficiency

When providing code examples and revisions, **adhere strictly to the relevant Google Style Guide** (e.g., for Python, follow the Google Python Style Guide; for Bash, follow the Google Bash Style Guide). Additionally:

1. **Always use best practices**: Always provide responses that adhere to established best practice principles in the field you are responding.
2. **Style Compliance**: All code must comply with the Google Style Guide where one exists, or follow best practices if not.
3. **Full Typing**: Use full typing in languages that support it, including for variables.
4. **Avoid `Any` Type**: Do not use the `Any` type. If it is absolutely necessary, provide detailed code comments explaining why.
5. **Modular Code**: Break code into the smallest logical functional components.
6. **Use of Classes**: Utilize classes where appropriate to enhance functionality.
7. **Exception Handling**: Catch and handle all reasonable errors and exceptions, including performing cleanup when appropriate.
8. **Signal Handling**: Catch and handle all reasonable signals (e.g., `TERM`, `KILL`, `HUP`), including performing cleanup when appropriate.
9. **Inline Documentation**: Include thorough inline documentation within the code.
10. **Usage Examples**: Provide examples in comments where appropriate.
11. **Do not directly modify any dependency management files** (e.g., those that define project dependencies). Instead, provide the appropriate command or tool-based approach to make changes, as would normally be done using the language's standard package manager or environment. This ensures the changes are applied correctly within the workflow of the specific project.
12. **Do not modify or adjust any linting configuration** to bypass or ignore coding errors. Coding errors should be fixed by correcting the code itself, not by changing or disabling linting rules. If the linting configuration is incorrect or needs adjustment for valid reasons, suggest changes with clear justification. However, coding errors should always be addressed as coding issues, not hidden or ignored through linting configuration changes.
13. **File Headers for New Files**: When creating new files, include a header with:
    - The purpose and description of the file.
    - The author's name and contact information.
    - Code history and changes.
14. **Shebang for Executable Files**: For new executable files, use the `env` shebang method at the top:

    ```python
    #!/usr/bin/env python3
    ```

15. **Imports/Includes**: Ensure all necessary imports/includes are referenced; do not include unused modules.

## Context

### Date

- **Today is {current_date}**

### User Information

- **GITHUB_USERNAME**: `{GITHUB_USERNAME}`
- **GITHUB_FULLNAME**: `{GITHUB_FULLNAME}`
- **GITHUB_EMAIL**: `{GITHUB_EMAIL}`

---
"""


class EnvironmentConfig:
    """
    A class to load and store environment variables.
    """

    def __init__(self) -> None:
        self.env_vars: Dict[str, str] = self.load_environment_variables()

    @staticmethod
    def load_environment_variables() -> Dict[str, str]:
        """Load necessary environment variables."""
        env_vars = {
            "OPENAI_KEY": os.getenv("LLM_SH_OPENAI_KEY", ""),
            "OPENAI_PROJECT": os.getenv("LLM_SH_OPENAI_PROJECT", ""),
            "OPENAI_ORGANIZATION": os.getenv("LLM_SH_OPENAI_ORGANIZATION", ""),
            "OPENAI_MODEL": os.getenv("LLM_SH_OPENAI_MODEL", "gpt-4"),
            "OPENAI_MAX_TOKENS": os.getenv("LLM_SH_OPENAI_MAX_TOKENS", "4096"),
            "GITHUB_USERNAME": os.getenv("GITHUB_USERNAME", "troykelly"),
            "GITHUB_FULLNAME": os.getenv("GITHUB_FULLNAME", "Troy Kelly"),
            "GITHUB_EMAIL": os.getenv("GITHUB_EMAIL", "troy@aperim.com"),
            "GITHUB_OWNER": os.getenv("GITHUB_OWNER", ""),
            "GITHUB_REPO": os.getenv("GITHUB_REPO", ""),
        }
        return env_vars


class OpenAIInteraction:
    """
    A class to handle interactions with the OpenAI API.
    """

    def __init__(self, env_vars: Dict[str, str]) -> None:
        self.env_vars = env_vars
        self.api_key: str = env_vars["OPENAI_KEY"]
        self.organization: str = env_vars.get("OPENAI_ORGANIZATION", "")
        self.model: str = env_vars["OPENAI_MODEL"]
        self.max_tokens: int = int(env_vars.get("OPENAI_MAX_TOKENS", "4096"))
        self.client = OpenAI(api_key=self.api_key, organization=self.organization)

    def send(self, conversation: List[Dict[str, str]]) -> Optional[str]:
        """
        Send the conversation to the OpenAI API and get the assistant's response.

        Args:
            conversation: List of messages in the conversation.

        Returns:
            The assistant's response content, or None if an error occurred.
        """
        try:
            # Attempt to send messages with 'system' role
            response = self.client.chat.completions.create(
                model=self.model,
                messages=self._format_messages(conversation),
                max_tokens=self.max_tokens,
                temperature=1,
                top_p=1,
                frequency_penalty=0,
                presence_penalty=0,
            )
            return response.choices[0].message.content
        except openai.BadRequestError as e:
            error_message = str(e)
            if "'system'" in error_message:
                logging.warning(
                    "Model doesn't support 'system' role in messages. Retrying without 'system' role."
                )
                return self._retry_without_system_role(conversation)
            else:
                logging.error(f"OpenAI API Error: {e}")
                return None
        except openai.OpenAIError as e:
            logging.error(f"OpenAI API Error: {e}")
            return None
        except Exception as e:
            logging.error(f"An unexpected error occurred: {e}")
            return None

    def _retry_without_system_role(
        self, conversation: List[Dict[str, str]]
    ) -> Optional[str]:
        """
        Retry the chat completion request without the 'system' role.

        Args:
            conversation: Original conversation including 'system' role.

        Returns:
            The assistant's response content, or None if an error occurred.
        """
        # Remove 'system' messages
        messages_without_system = [
            msg for msg in conversation if msg["role"] != "system"
        ]
        # Concatenate system prompt with the first user message
        system_prompt = next(
            (msg["content"] for msg in conversation if msg["role"] == "system"), ""
        )
        if messages_without_system and messages_without_system[0]["role"] == "user":
            messages_without_system[0][
                "content"
            ] = f"{system_prompt}\n\n{messages_without_system[0]['content']}"
        else:
            # Prepend the system prompt as a user message
            messages_without_system.insert(
                0, {"role": "user", "content": system_prompt}
            )

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=self._format_messages(messages_without_system),
            )
            return response.choices[0].message.content
        except openai.error.OpenAIError as e:
            logging.error(f"Error after removing 'system' role: {e}")
            return None

    @staticmethod
    def _format_messages(conversation: List[Dict[str, str]]) -> List[Dict[str, str]]:
        """
        Format the conversation into the expected message format for OpenAI API.

        Args:
            conversation: List of messages in the conversation.

        Returns:
            Formatted list of messages.
        """
        return [
            {"role": msg["role"], "content": msg["content"]} for msg in conversation
        ]


class ConversationManager:
    """
    A class to manage the conversation state and storage.
    """

    def __init__(self, conversation_file: str) -> None:
        self.conversation_file: str = conversation_file
        self.conversation: List[Dict[str, str]] = []
        self.load_conversation()

    def load_conversation(self) -> None:
        """
        Load the conversation from the file.
        """
        if os.path.exists(self.conversation_file):
            try:
                with open(self.conversation_file, "r", encoding="utf-8") as f:
                    self.conversation = json.load(f)
                    logging.info("Loaded existing conversation.")
            except json.JSONDecodeError:
                logging.warning(
                    "Invalid conversation file. Starting a new conversation."
                )
                self.conversation = []
        else:
            logging.info("No previous conversation found. Starting a new conversation.")

    def save_conversation(self) -> None:
        """
        Save the conversation to the file.
        """
        with open(self.conversation_file, "w", encoding="utf-8") as f:
            json.dump(self.conversation, f, indent=2)
        logging.info("Conversation saved.")

    def append_message(self, role: str, content: str) -> None:
        """
        Append a message to the conversation.

        Args:
            role: The role of the message ('user', 'assistant', 'system').
            content: The content of the message.
        """
        self.conversation.append({"role": role, "content": content})

    def get_conversation(self) -> List[Dict[str, str]]:
        """
        Get the current conversation.

        Returns:
            List of conversation messages.
        """
        return self.conversation


def main() -> None:
    """
    Main function to orchestrate the script operations.
    """
    # Parse command line arguments
    parser = argparse.ArgumentParser(description="Run the LLM assistant script.")
    parser.add_argument(
        "paths", nargs="*", help="Specific files or folders to include."
    )
    parser.add_argument(
        "--include-large", action="store_true", help="Include content of large files."
    )
    parser.add_argument(
        "-v",
        "--verbosity",
        action="count",
        default=0,
        help="Set verbosity level. Use -v, -vv, or -vvv.",
    )
    args = parser.parse_args()

    # Set up logging based on verbosity level
    verbosity = args.verbosity
    if verbosity == 0:
        logging_level = logging.WARNING
    elif verbosity == 1:
        logging_level = logging.INFO
    elif verbosity >= 2:
        logging_level = logging.DEBUG
    else:
        logging_level = logging.WARNING
    logging.basicConfig(
        level=logging_level, format="%(asctime)s [%(levelname)s] %(message)s"
    )

    # Load environment variables
    env_config = EnvironmentConfig()
    env_vars = env_config.env_vars

    if not env_vars["OPENAI_KEY"]:
        logging.error(
            "OpenAI API key not found in environment variables (LLM_SH_OPENAI_KEY). Exiting."
        )
        sys.exit(1)

    # Initialize conversation manager
    conversation_manager = ConversationManager(".llm.json")

    # Check if we need to start a new conversation
    if conversation_manager.conversation:
        while True:
            choice = (
                input(
                    "A previous conversation is in progress. Do you wish to continue it? (yes/no): "
                )
                .strip()
                .lower()
            )
            if choice == "yes":
                break
            elif choice == "no":
                # Delete llm.md and .llm.json to start a new conversation
                if os.path.exists("llm.md"):
                    os.remove("llm.md")
                if os.path.exists(".llm.json"):
                    os.remove(".llm.json")
                conversation_manager.conversation = []
                conversation_manager.save_conversation()
                break
            else:
                print("Please enter 'yes' or 'no'.")

    # Initialize OpenAI handler
    openai_handler = OpenAIInteraction(env_vars)

    # Build file tree and contents
    root_dir = "."
    include_files = args.paths if args.paths else None
    file_tree, files_contents = build_file_tree(
        root_dir, include_files, args.include_large
    )

    # Write and read prompt
    user_prompt = write_prompt_file()

    # Prepare system prompt
    system_prompt = prepare_system_prompt(env_vars, file_tree, files_contents)

    # Append messages to conversation
    conversation_manager.append_message("system", system_prompt)
    conversation_manager.append_message("user", user_prompt)

    # Send conversation to OpenAI
    response_content = openai_handler.send(conversation_manager.get_conversation())

    if not response_content:
        logging.error("No response from OpenAI API. Exiting.")
        sys.exit(1)

    # Append assistant's response
    conversation_manager.append_message("assistant", response_content)
    conversation_manager.save_conversation()

    # Update llm.md with assistant's response
    with open("llm.md", "a", encoding="utf-8") as f:
        f.write("\n## Assistant's Response\n\n")
        f.write(response_content)

    # Process any file updates
    files_to_update = update_files_from_response(response_content)
    if files_to_update:
        process_file_updates(files_to_update)

    # Handle further interaction loop
    handle_interaction_loop(conversation_manager, openai_handler)


def build_file_tree(
    root_dir: str, include_files: Optional[List[str]], include_large: bool
) -> Tuple[List[str], Dict[str, str]]:
    """
    Build a file tree representation and collect file contents.

    Args:
        root_dir: The root directory to scan.
        include_files: Specific files or directories to include.
        include_large: Flag indicating whether to include large files.

    Returns:
        A tuple containing the file tree list and a dictionary of file contents.
    """
    file_tree: List[str] = []
    files_contents: Dict[str, str] = {}
    ignored_paths: List[str] = get_ignored_paths()

    for dirpath, dirnames, filenames in os.walk(root_dir):
        # Exclude ignored directories
        original_dirnames = dirnames.copy()
        dirnames[:] = [
            d
            for d in dirnames
            if not should_ignore(
                os.path.relpath(os.path.join(dirpath, d), root_dir), ignored_paths
            )
        ]
        if logging.getLogger().getEffectiveLevel() <= logging.DEBUG:
            for d in original_dirnames:
                rel_path = os.path.relpath(os.path.join(dirpath, d), root_dir)
                if d not in dirnames:
                    logging.debug(f"Ignoring directory: {rel_path}")
                else:
                    logging.debug(f"Including directory: {rel_path}")

        for filename in filenames:
            filepath = os.path.join(dirpath, filename)
            relative_path = os.path.relpath(filepath, root_dir)
            if should_ignore(relative_path, ignored_paths):
                logging.debug(f"Ignoring file: {relative_path}")
                continue
            if include_files and not any(
                Path(relative_path).match(inc) for inc in include_files
            ):
                logging.debug(f"File not included by paths filter: {relative_path}")
                continue
            file_tree.append(relative_path)
            logging.debug(f"Including file: {relative_path}")
            # Process file content
            process_file_content(filepath, relative_path, files_contents, include_large)
    return file_tree, files_contents


def process_file_content(
    filepath: str,
    relative_path: str,
    files_contents: Dict[str, str],
    include_large: bool,
) -> None:
    """
    Process and store the content of a file.

    Args:
        filepath: Full path to the file.
        relative_path: Relative path for display.
        files_contents: Dictionary to store file contents.
        include_large: Flag indicating whether to include large files.
    """
    try:
        file_size = os.path.getsize(filepath)
    except OSError:
        file_size = 0
    if any(
        filepath.endswith(ext)
        for ext in [
            ".png",
            ".jpg",
            ".jpeg",
            ".gif",
            ".pdf",
            ".zip",
            ".exe",
            ".dll",
            ".bin",
        ]
    ):
        files_contents[relative_path] = "[Binary file content omitted]"
        logging.debug(f"Binary file content omitted: {relative_path}")
    elif file_size > 1e6 and not include_large:
        if filepath.endswith((".json", ".yaml", ".yml")):
            try:
                with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
                    content = f.read()
                    skeleton = skeletonize_json_yaml(content)
                    files_contents[relative_path] = skeleton
                    logging.debug(
                        f"Included skeletonized content for large file: {relative_path}"
                    )
            except Exception as e:
                files_contents[relative_path] = (
                    f"[Could not read file for skeletonization: {e}]"
                )
                logging.error(
                    f"Error reading file for skeletonization: {relative_path}"
                )
        else:
            files_contents[relative_path] = "[File content omitted due to size]"
            logging.debug(f"File content omitted due to size: {relative_path}")
    else:
        try:
            with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
                files_contents[relative_path] = content
                logging.debug(f"File content read: {relative_path}")
        except Exception as e:
            files_contents[relative_path] = f"[Could not read file: {e}]"
            logging.error(f"Could not read file: {relative_path}, Error: {e}")


def get_ignored_paths() -> List[str]:
    """
    Get list of paths to ignore from .gitignore and .llmignore.

    Returns:
        List of ignored paths.
    """
    ignored_paths = []
    for ignore_file in [".gitignore", ".llmignore"]:
        if os.path.exists(ignore_file):
            with open(ignore_file, "r", encoding="utf-8") as f:
                lines = f.readlines()
            for line in lines:
                stripped_line = line.strip()
                if stripped_line and not stripped_line.startswith("#"):
                    ignored_paths.append(stripped_line)
                    logging.debug(
                        f"Added ignore pattern from {ignore_file}: {stripped_line}"
                    )
    # Always ignore specific files
    ignored_paths.extend(
        [
            ".git",
            ".llm.json",
            "llm.md",
            "llm.py",
        ]
    )
    logging.debug("Ignored paths: %s", ignored_paths)
    return ignored_paths


def should_ignore(path: str, ignored_paths: List[str]) -> bool:
    """
    Determine if a path should be ignored based on ignore patterns.

    Args:
        path: The path to check.
        ignored_paths: List of ignored paths.

    Returns:
        True if the path should be ignored, False otherwise.
    """
    for pattern in ignored_paths:
        if Path(path).match(pattern) or Path(path).match(f"**/{pattern}"):
            logging.debug(f"Path {path} matches ignore pattern {pattern}")
            return True
    return False


def skeletonize_json_yaml(content: str) -> str:
    """
    Create a skeleton representation of JSON or YAML content.

    Args:
        content: The file content.

    Returns:
        The skeletonized representation.
    """
    try:
        import json
        import yaml  # Requires PyYAML

        try:
            data = json.loads(content)
            skeleton = json.dumps(skeletonize_data(data), indent=2)
        except json.JSONDecodeError:
            data = yaml.safe_load(content)
            skeleton = yaml.dump(skeletonize_data(data), indent=2)
        return skeleton
    except Exception as e:
        logging.error(f"Error skeletonizing content: {e}")
        return f"[Error skeletonizing file: {e}]"


def skeletonize_data(data: Any) -> Any:
    """
    Recursively create a skeleton of data structures.

    Args:
        data: The data to skeletonize.

    Returns:
        The skeletonized data.
    """
    if isinstance(data, dict):
        return {k: skeletonize_data(v) for k, v in data.items()}
    elif isinstance(data, list):
        if data:
            return [skeletonize_data(data[0])]
        else:
            return []
    else:
        return f"<{type(data).__name__}>"


def write_prompt_file() -> str:
    """
    Create or open prompt file and get user input.

    Returns:
        The user prompt as a string.
    """
    if not os.path.exists("llm.md"):
        with open("llm.md", "w", encoding="utf-8") as f:
            f.write(
                '# llm.md\n\nPlease provide your instructions under the "Prompt" section below.\n\n## Prompt\n\n'
            )
    # Open the file in VSCode if possible
    if os.getenv("CODESPACES") == "true" or os.getenv("REMOTE_CONTAINERS") == "true":
        subprocess.run(["code", "llm.md"])
    else:
        print("Please open llm.md and provide your prompt under the 'Prompt' section.")

    print("Waiting for you to write your prompt in llm.md...")
    try:
        initial_mtime = os.path.getmtime("llm.md")
    except FileNotFoundError:
        logging.error("llm.md not found. Exiting.")
        sys.exit(1)

    while True:
        time.sleep(1)
        try:
            current_mtime = os.path.getmtime("llm.md")
            if current_mtime != initial_mtime:
                break
        except FileNotFoundError:
            logging.error("llm.md has been deleted. Exiting.")
            sys.exit(1)

    with open("llm.md", "r", encoding="utf-8") as f:
        content = f.read()
    if "## Prompt" in content:
        prompt = content.split("## Prompt", 1)[1].strip()
        if prompt:
            return prompt
    logging.error("No prompt detected in llm.md. Exiting.")
    sys.exit(1)


def prepare_system_prompt(
    env_vars: Dict[str, str], file_tree: List[str], files_contents: Dict[str, str]
) -> str:
    """
    Prepare the system prompt including context and requirements.

    Args:
        env_vars: Dictionary of environment variables.
        file_tree: List of files in the workspace.
        files_contents: Dictionary of file contents.

    Returns:
        The system prompt as a string.
    """
    system_prompt_template = SYSTEM_PROMPT_TEMPLATE
    current_date = datetime.now().strftime("%A, %d %B %Y")
    system_prompt = system_prompt_template.format(
        current_date=current_date,
        GITHUB_USERNAME=env_vars["GITHUB_USERNAME"],
        GITHUB_FULLNAME=env_vars["GITHUB_FULLNAME"],
        GITHUB_EMAIL=env_vars["GITHUB_EMAIL"],
    )

    # Append file tree and contents
    system_prompt += "\n\n## Workspace File Tree\n\n"
    for path in file_tree:
        system_prompt += f"- {path}\n"
    system_prompt += "\n\n## File Contents\n\n"
    for path in file_tree:
        content = files_contents.get(path, "")
        system_prompt += f"### {path}\n\n"
        system_prompt += f"```\n{content}\n```\n\n"
    logging.debug("Prepared system prompt.")
    return system_prompt


def remove_markdown_code_blocks(content_lines: List[str]) -> List[str]:
    """
    Remove markdown code block markers from the content lines.

    Args:
        content_lines: List of content lines between file markers.

    Returns:
        Cleaned list of content lines without markdown code blocks.
    """
    cleaned_lines = []
    in_code_block = False
    for line in content_lines:
        stripped_line = line.strip()
        # Check for the start or end of a code block
        if stripped_line.startswith("```"):
            # Toggle the in_code_block flag
            in_code_block = not in_code_block
            continue  # Skip the line with ```
        # Add the line to cleaned_lines
        cleaned_lines.append(line)
    return cleaned_lines


def update_files_from_response(response_text: str) -> Dict[str, str]:
    """
    Extract file updates from assistant's response.

    Args:
        response_text: The assistant's response.

    Returns:
        Dictionary mapping filenames to their updated contents.
    """
    files_to_update: Dict[str, str] = {}
    lines = response_text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.startswith("<<LLM_FILE_START:"):
            filename = line[len("<<LLM_FILE_START:") :].rstrip(">>").strip()
            content_lines: List[str] = []
            i += 1
            while i < len(lines):
                if lines[i].startswith("<<LLM_FILE_END>>"):
                    break
                content_lines.append(lines[i])
                i += 1
            # Clean the content lines by removing markdown code blocks
            content_lines = remove_markdown_code_blocks(content_lines)
            file_content = "\n".join(content_lines).strip()
            files_to_update[filename] = file_content
            logging.debug(f"Found file update for: {filename}")
        else:
            i += 1
    return files_to_update


def process_file_updates(files_to_update: Dict[str, str]) -> None:
    """
    Process and update files based on the assistant's response.

    Args:
        files_to_update: Dictionary mapping filenames to their updated contents.
    """
    print("The assistant has provided updates to the following files:")
    for filename in files_to_update.keys():
        print(f"- {filename}")
    while True:
        choice = (
            input("Do you wish to automatically update them? (yes/no): ")
            .strip()
            .lower()
        )
        if choice == "yes":
            if not git_is_clean():
                print("Git repository is not clean. Committing current changes.")
                git_commit_all()
            atomically_write_files(files_to_update)
            print("Files have been updated.")
            break
        elif choice == "no":
            print("Files were not updated.")
            break
        else:
            print("Please enter 'yes' or 'no'.")


def atomically_write_files(files_dict: Dict[str, str]) -> None:
    """
    Atomically write updated files to the file system.

    Args:
        files_dict: Dictionary mapping filenames to their updated contents.
    """
    for filename, content in files_dict.items():
        dirname = os.path.dirname(filename)
        if dirname and not os.path.exists(dirname):
            os.makedirs(dirname)
            logging.debug(f"Created directory: {dirname}")
        temp_filename = f"{filename}.tmp"
        with open(temp_filename, "w", encoding="utf-8") as f:
            f.write(content)
        shutil.move(temp_filename, filename)
        logging.debug(f"Updated file: {filename}")


def git_is_clean() -> bool:
    """
    Check if the Git repository is clean.

    Returns:
        True if the Git repository is clean, False otherwise.
    """
    result = subprocess.run(
        ["git", "status", "--porcelain"], capture_output=True, text=True
    )
    is_clean = not result.stdout.strip()
    logging.debug(f"Git repository is clean: {is_clean}")
    return is_clean


def git_commit_all() -> None:
    """
    Commit all changes to Git with a standard commit message.
    """
    subprocess.run(["git", "add", "."])
    commit_message = f"LLM Auto Commit {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
    subprocess.run(["git", "commit", "-m", commit_message])
    logging.info("Committed current changes to Git.")


def handle_interaction_loop(
    conversation_manager: ConversationManager, openai_handler: OpenAIInteraction
) -> None:
    """
    Handle the user interaction loop for continuing the conversation.

    Args:
        conversation_manager: The ConversationManager instance.
        openai_handler: The OpenAIInteraction instance.
    """
    while True:
        cont = (
            input("Do you wish to respond to the assistant? (yes/no): ").strip().lower()
        )
        if cont == "yes":
            # Append new section to llm.md
            with open("llm.md", "a", encoding="utf-8") as f:
                f.write("\n## Your Response\n\n")
            print(
                "Please provide your response in llm.md under 'Your Response' section."
            )

            # Wait for user to update the file
            print("Waiting for you to write your response in llm.md...")
            try:
                initial_mtime = os.path.getmtime("llm.md")
            except FileNotFoundError:
                logging.error("llm.md not found. Exiting.")
                sys.exit(1)

            while True:
                time.sleep(1)
                try:
                    current_mtime = os.path.getmtime("llm.md")
                    if current_mtime != initial_mtime:
                        break
                except FileNotFoundError:
                    logging.error("llm.md has been deleted. Exiting.")
                    sys.exit(1)

            # Read user's response
            with open("llm.md", "r", encoding="utf-8") as f:
                content = f.read()

            if "## Your Response" in content:
                user_response = content.split("## Your Response", 1)[1].strip()
                if user_response:
                    conversation_manager.append_message("user", user_response)
                    # Send to OpenAI API
                    response_content = openai_handler.send(
                        conversation_manager.get_conversation()
                    )

                    if not response_content:
                        logging.error("No response from OpenAI API. Exiting.")
                        sys.exit(1)

                    # Append assistant's response to conversation
                    conversation_manager.append_message("assistant", response_content)
                    conversation_manager.save_conversation()

                    # Update llm.md with assistant's response
                    with open("llm.md", "a", encoding="utf-8") as f:
                        f.write("\n## Assistant's Response\n\n")
                        f.write(response_content)

                    # Process any file updates as before
                    files_to_update = update_files_from_response(response_content)
                    if files_to_update:
                        process_file_updates(files_to_update)
                else:
                    print(
                        "No user response detected in llm.md. Exiting the conversation."
                    )
                    break
            else:
                print(
                    "No 'Your Response' section found in llm.md. Exiting the conversation."
                )
                break
        elif cont == "no":
            print("Conversation ended.")
            break
        else:
            print("Please enter 'yes' or 'no'.")


if __name__ == "__main__":
    main()
