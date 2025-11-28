#!/usr/bin/env python3
"""
Basecamp Task Creator

A Python script that takes a JSON list of tasks and creates them in Basecamp.
Supports Basecamp 3 API with OAuth2 or personal access tokens.

Usage:
    python basecamp_task_creator.py tasks.json
    python basecamp_task_creator.py --stdin < tasks.json
    cat tasks.json | python basecamp_task_creator.py --stdin
"""

import argparse
import json
import os
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional
from urllib.parse import urljoin

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


# ============================================================================
# Configuration
# ============================================================================

@dataclass
class BasecampConfig:
    """Configuration for Basecamp API connection."""
    
    account_id: str
    access_token: str
    project_id: str
    todolist_id: str
    user_agent: str = "Cursor-Basecamp-Sync (your-email@example.com)"
    api_base_url: str = "https://3.basecampapi.com"
    
    @classmethod
    def from_env(cls) -> "BasecampConfig":
        """Load configuration from environment variables."""
        required_vars = [
            "BASECAMP_ACCOUNT_ID",
            "BASECAMP_ACCESS_TOKEN", 
            "BASECAMP_PROJECT_ID",
            "BASECAMP_TODOLIST_ID",
        ]
        
        missing = [var for var in required_vars if not os.getenv(var)]
        if missing:
            raise EnvironmentError(
                f"Missing required environment variables: {', '.join(missing)}\n"
                "Please set them or create a .env file."
            )
        
        return cls(
            account_id=os.getenv("BASECAMP_ACCOUNT_ID"),
            access_token=os.getenv("BASECAMP_ACCESS_TOKEN"),
            project_id=os.getenv("BASECAMP_PROJECT_ID"),
            todolist_id=os.getenv("BASECAMP_TODOLIST_ID"),
            user_agent=os.getenv("BASECAMP_USER_AGENT", cls.user_agent),
        )
    
    @classmethod
    def from_file(cls, filepath: str) -> "BasecampConfig":
        """Load configuration from a JSON file."""
        with open(filepath, "r") as f:
            data = json.load(f)
        return cls(**data)


# ============================================================================
# Task Model
# ============================================================================

@dataclass
class Task:
    """Represents a task to be created in Basecamp."""
    
    content: str  # Required: The task title/description
    description: str = ""  # Optional: Rich text notes (HTML supported)
    due_on: Optional[str] = None  # Optional: Due date (YYYY-MM-DD)
    assignee_ids: list = field(default_factory=list)  # Optional: List of Basecamp user IDs
    notify: bool = False  # Whether to notify assignees
    starts_on: Optional[str] = None  # Optional: Start date (YYYY-MM-DD)
    
    # Metadata (not sent to Basecamp, used for tracking)
    source_file: Optional[str] = None
    source_line: Optional[int] = None
    priority: str = "normal"  # low, normal, high, critical
    category: Optional[str] = None
    
    def to_basecamp_payload(self) -> dict:
        """Convert task to Basecamp API payload."""
        payload = {
            "content": self.content,
            "description": self.description,
        }
        
        if self.due_on:
            payload["due_on"] = self.due_on
        
        if self.assignee_ids:
            payload["assignee_ids"] = self.assignee_ids
            
        if self.notify:
            payload["notify"] = self.notify
            
        if self.starts_on:
            payload["starts_on"] = self.starts_on
            
        return payload
    
    @classmethod
    def from_dict(cls, data: dict) -> "Task":
        """Create a Task from a dictionary."""
        # Handle both snake_case and camelCase keys
        return cls(
            content=data.get("content") or data.get("title", ""),
            description=data.get("description", ""),
            due_on=data.get("due_on") or data.get("dueOn"),
            assignee_ids=data.get("assignee_ids") or data.get("assigneeIds", []),
            notify=data.get("notify", False),
            starts_on=data.get("starts_on") or data.get("startsOn"),
            source_file=data.get("source_file") or data.get("sourceFile"),
            source_line=data.get("source_line") or data.get("sourceLine"),
            priority=data.get("priority", "normal"),
            category=data.get("category"),
        )


# ============================================================================
# Basecamp API Client
# ============================================================================

class BasecampClient:
    """Client for interacting with the Basecamp 3 API."""
    
    def __init__(self, config: BasecampConfig):
        self.config = config
        self.session = self._create_session()
        self._request_count = 0
        self._last_request_time = 0
        
    def _create_session(self) -> requests.Session:
        """Create a requests session with retry logic."""
        session = requests.Session()
        
        # Set default headers
        session.headers.update({
            "Authorization": f"Bearer {self.config.access_token}",
            "Content-Type": "application/json",
            "User-Agent": self.config.user_agent,
        })
        
        # Configure retry strategy
        retry_strategy = Retry(
            total=3,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["HEAD", "GET", "POST", "PUT", "DELETE"],
        )
        
        adapter = HTTPAdapter(max_retries=retry_strategy)
        session.mount("https://", adapter)
        session.mount("http://", adapter)
        
        return session
    
    def _get_base_url(self) -> str:
        """Get the base URL for API requests."""
        return f"{self.config.api_base_url}/{self.config.account_id}"
    
    def _rate_limit(self):
        """Implement rate limiting to respect Basecamp's limits (~50 req/10s)."""
        current_time = time.time()
        time_since_last = current_time - self._last_request_time
        
        # If we've made many requests recently, slow down
        if self._request_count >= 45 and time_since_last < 10:
            sleep_time = 10 - time_since_last
            print(f"  ⏳ Rate limiting: sleeping {sleep_time:.1f}s...")
            time.sleep(sleep_time)
            self._request_count = 0
        
        self._last_request_time = time.time()
        self._request_count += 1
    
    def _make_request(self, method: str, endpoint: str, **kwargs) -> requests.Response:
        """Make an API request with error handling."""
        self._rate_limit()
        
        url = f"{self._get_base_url()}/{endpoint}"
        
        try:
            response = self.session.request(method, url, **kwargs)
            response.raise_for_status()
            return response
        except requests.exceptions.HTTPError as e:
            error_msg = f"HTTP Error: {e.response.status_code}"
            try:
                error_detail = e.response.json()
                error_msg += f" - {error_detail}"
            except (ValueError, KeyError):
                error_msg += f" - {e.response.text}"
            raise BasecampAPIError(error_msg) from e
        except requests.exceptions.RequestException as e:
            raise BasecampAPIError(f"Request failed: {e}") from e
    
    def get_projects(self) -> list:
        """Get all projects in the Basecamp account."""
        response = self._make_request("GET", "projects.json")
        return response.json()
    
    def get_todolists(self, project_id: str) -> list:
        """Get all todo lists in a project."""
        response = self._make_request(
            "GET", 
            f"buckets/{project_id}/todosets.json"
        )
        todoset = response.json()
        
        # Get the actual todolists from the todoset
        todolists_url = todoset.get("todolists_url", "")
        if todolists_url:
            response = self.session.get(todolists_url)
            response.raise_for_status()
            return response.json()
        return []
    
    def get_todos(self, project_id: str, todolist_id: str) -> list:
        """Get all todos in a todolist."""
        response = self._make_request(
            "GET",
            f"buckets/{project_id}/todolists/{todolist_id}/todos.json"
        )
        return response.json()
    
    def create_todo(self, task: Task, project_id: str = None, todolist_id: str = None) -> dict:
        """Create a new todo in Basecamp."""
        project_id = project_id or self.config.project_id
        todolist_id = todolist_id or self.config.todolist_id
        
        payload = task.to_basecamp_payload()
        
        response = self._make_request(
            "POST",
            f"buckets/{project_id}/todolists/{todolist_id}/todos.json",
            json=payload
        )
        
        return response.json()
    
    def check_todo_exists(self, content: str, project_id: str = None, todolist_id: str = None) -> bool:
        """Check if a todo with the same content already exists."""
        project_id = project_id or self.config.project_id
        todolist_id = todolist_id or self.config.todolist_id
        
        try:
            todos = self.get_todos(project_id, todolist_id)
            return any(todo.get("content", "").strip() == content.strip() for todo in todos)
        except BasecampAPIError:
            return False
    
    def test_connection(self) -> bool:
        """Test the API connection."""
        try:
            self.get_projects()
            return True
        except BasecampAPIError:
            return False


class BasecampAPIError(Exception):
    """Custom exception for Basecamp API errors."""
    pass


# ============================================================================
# Task Processor
# ============================================================================

class TaskProcessor:
    """Processes and creates tasks in Basecamp."""
    
    def __init__(self, client: BasecampClient, dry_run: bool = False, skip_duplicates: bool = True):
        self.client = client
        self.dry_run = dry_run
        self.skip_duplicates = skip_duplicates
        self.stats = {
            "total": 0,
            "created": 0,
            "skipped": 0,
            "failed": 0,
        }
    
    def process_tasks(self, tasks: list[Task]) -> list[dict]:
        """Process a list of tasks and create them in Basecamp."""
        results = []
        self.stats["total"] = len(tasks)
        
        print(f"\n{'='*60}")
        print(f"Processing {len(tasks)} task(s)...")
        if self.dry_run:
            print("🔍 DRY RUN MODE - No tasks will be created")
        print(f"{'='*60}\n")
        
        for i, task in enumerate(tasks, 1):
            result = self._process_single_task(task, i, len(tasks))
            results.append(result)
        
        self._print_summary()
        return results
    
    def _process_single_task(self, task: Task, index: int, total: int) -> dict:
        """Process a single task."""
        result = {
            "task": task.content,
            "status": "pending",
            "basecamp_id": None,
            "error": None,
        }
        
        print(f"[{index}/{total}] {task.content[:50]}{'...' if len(task.content) > 50 else ''}")
        
        # Check for duplicates
        if self.skip_duplicates and not self.dry_run:
            if self.client.check_todo_exists(task.content):
                print(f"  ⏭️  Skipped (duplicate)")
                result["status"] = "skipped"
                self.stats["skipped"] += 1
                return result
        
        # Create the task
        if self.dry_run:
            print(f"  🔍 Would create task")
            if task.due_on:
                print(f"      Due: {task.due_on}")
            if task.description:
                print(f"      Description: {task.description[:50]}...")
            result["status"] = "dry_run"
            self.stats["created"] += 1
            return result
        
        try:
            response = self.client.create_todo(task)
            result["status"] = "created"
            result["basecamp_id"] = response.get("id")
            result["url"] = response.get("app_url")
            print(f"  ✅ Created (ID: {result['basecamp_id']})")
            self.stats["created"] += 1
        except BasecampAPIError as e:
            result["status"] = "failed"
            result["error"] = str(e)
            print(f"  ❌ Failed: {e}")
            self.stats["failed"] += 1
        
        return result
    
    def _print_summary(self):
        """Print processing summary."""
        print(f"\n{'='*60}")
        print("Summary")
        print(f"{'='*60}")
        print(f"  Total tasks:   {self.stats['total']}")
        print(f"  ✅ Created:    {self.stats['created']}")
        print(f"  ⏭️  Skipped:    {self.stats['skipped']}")
        print(f"  ❌ Failed:     {self.stats['failed']}")
        print(f"{'='*60}\n")


# ============================================================================
# JSON Input Handler
# ============================================================================

def load_tasks_from_json(source: str | dict | list) -> list[Task]:
    """
    Load tasks from various JSON sources.
    
    Args:
        source: Can be a file path, JSON string, dict, or list
        
    Returns:
        List of Task objects
    """
    data = None
    
    if isinstance(source, list):
        data = source
    elif isinstance(source, dict):
        # Single task as dict
        data = [source]
    elif isinstance(source, str):
        # Try to parse as JSON string first
        try:
            data = json.loads(source)
        except json.JSONDecodeError:
            # Assume it's a file path
            if os.path.exists(source):
                with open(source, "r") as f:
                    data = json.load(f)
            else:
                raise FileNotFoundError(f"File not found: {source}")
    
    if data is None:
        raise ValueError("Could not parse tasks from source")
    
    # Ensure data is a list
    if isinstance(data, dict):
        # Check if it's a wrapper object with a "tasks" key
        if "tasks" in data:
            data = data["tasks"]
        else:
            data = [data]
    
    # Convert to Task objects
    tasks = []
    for item in data:
        if isinstance(item, dict):
            tasks.append(Task.from_dict(item))
        elif isinstance(item, str):
            # Simple string becomes task content
            tasks.append(Task(content=item))
    
    return tasks


def load_tasks_from_stdin() -> list[Task]:
    """Load tasks from stdin."""
    if sys.stdin.isatty():
        raise ValueError("No input provided via stdin")
    
    content = sys.stdin.read()
    return load_tasks_from_json(content)


# ============================================================================
# CLI Interface
# ============================================================================

def create_parser() -> argparse.ArgumentParser:
    """Create the argument parser."""
    parser = argparse.ArgumentParser(
        description="Create Basecamp tasks from a JSON list",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s tasks.json
  %(prog)s tasks.json --dry-run
  %(prog)s --stdin < tasks.json
  cat tasks.json | %(prog)s --stdin
  %(prog)s tasks.json --config basecamp_config.json
  
JSON Format:
  [
    {
      "content": "Task title (required)",
      "description": "Optional description (HTML supported)",
      "due_on": "2024-12-31",
      "priority": "high",
      "category": "backend"
    },
    "Simple task as string"
  ]

Environment Variables:
  BASECAMP_ACCOUNT_ID    - Your Basecamp account ID
  BASECAMP_ACCESS_TOKEN  - OAuth2 access token
  BASECAMP_PROJECT_ID    - Target project ID
  BASECAMP_TODOLIST_ID   - Target todolist ID
  BASECAMP_USER_AGENT    - Custom User-Agent (optional)
        """
    )
    
    # Input source
    input_group = parser.add_mutually_exclusive_group(required=True)
    input_group.add_argument(
        "json_file",
        nargs="?",
        help="Path to JSON file containing tasks"
    )
    input_group.add_argument(
        "--stdin",
        action="store_true",
        help="Read JSON from stdin"
    )
    
    # Configuration
    parser.add_argument(
        "--config",
        "-c",
        help="Path to JSON config file (alternative to env vars)"
    )
    parser.add_argument(
        "--project-id",
        help="Override Basecamp project ID"
    )
    parser.add_argument(
        "--todolist-id",
        help="Override Basecamp todolist ID"
    )
    
    # Behavior options
    parser.add_argument(
        "--dry-run",
        "-n",
        action="store_true",
        help="Preview tasks without creating them"
    )
    parser.add_argument(
        "--allow-duplicates",
        action="store_true",
        help="Create tasks even if they already exist"
    )
    parser.add_argument(
        "--output",
        "-o",
        help="Write results to JSON file"
    )
    
    # Utility options
    parser.add_argument(
        "--list-projects",
        action="store_true",
        help="List all available projects and exit"
    )
    parser.add_argument(
        "--list-todolists",
        action="store_true",
        help="List all todolists in the configured project"
    )
    parser.add_argument(
        "--test-connection",
        action="store_true",
        help="Test API connection and exit"
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable verbose output"
    )
    
    return parser


def main():
    """Main entry point."""
    parser = create_parser()
    args = parser.parse_args()
    
    # Load configuration
    try:
        if args.config:
            config = BasecampConfig.from_file(args.config)
        else:
            # Try to load .env file if python-dotenv is available
            try:
                from dotenv import load_dotenv
                load_dotenv()
            except ImportError:
                pass
            config = BasecampConfig.from_env()
    except (EnvironmentError, FileNotFoundError) as e:
        # For utility commands that don't need full config
        if not (args.list_projects or args.list_todolists or args.test_connection):
            if args.dry_run:
                print(f"⚠️  Warning: {e}")
                print("Running in dry-run mode without API connection.\n")
                config = None
            else:
                print(f"❌ Configuration Error: {e}")
                sys.exit(1)
        else:
            print(f"❌ Configuration Error: {e}")
            sys.exit(1)
    
    # Override config with CLI arguments
    if config:
        if args.project_id:
            config.project_id = args.project_id
        if args.todolist_id:
            config.todolist_id = args.todolist_id
    
    # Create client
    client = BasecampClient(config) if config else None
    
    # Handle utility commands
    if args.test_connection:
        print("Testing Basecamp API connection...")
        if client and client.test_connection():
            print("✅ Connection successful!")
            sys.exit(0)
        else:
            print("❌ Connection failed!")
            sys.exit(1)
    
    if args.list_projects:
        print("Fetching projects...")
        projects = client.get_projects()
        print(f"\nFound {len(projects)} project(s):\n")
        for p in projects:
            print(f"  ID: {p['id']}")
            print(f"  Name: {p['name']}")
            print(f"  URL: {p.get('app_url', 'N/A')}")
            print()
        sys.exit(0)
    
    if args.list_todolists:
        print(f"Fetching todolists for project {config.project_id}...")
        todolists = client.get_todolists(config.project_id)
        print(f"\nFound {len(todolists)} todolist(s):\n")
        for tl in todolists:
            print(f"  ID: {tl['id']}")
            print(f"  Name: {tl['name']}")
            print(f"  Count: {tl.get('todos_count', 'N/A')} todos")
            print()
        sys.exit(0)
    
    # Load tasks
    try:
        if args.stdin:
            tasks = load_tasks_from_stdin()
        else:
            tasks = load_tasks_from_json(args.json_file)
    except (FileNotFoundError, ValueError, json.JSONDecodeError) as e:
        print(f"❌ Error loading tasks: {e}")
        sys.exit(1)
    
    if not tasks:
        print("⚠️  No tasks found in input")
        sys.exit(0)
    
    # Process tasks
    processor = TaskProcessor(
        client=client,
        dry_run=args.dry_run or client is None,
        skip_duplicates=not args.allow_duplicates
    )
    
    results = processor.process_tasks(tasks)
    
    # Write results if requested
    if args.output:
        output_data = {
            "timestamp": datetime.now().isoformat(),
            "stats": processor.stats,
            "results": [
                {
                    "task": r["task"],
                    "status": r["status"],
                    "basecamp_id": r.get("basecamp_id"),
                    "url": r.get("url"),
                    "error": r.get("error"),
                }
                for r in results
            ]
        }
        with open(args.output, "w") as f:
            json.dump(output_data, f, indent=2)
        print(f"📄 Results written to {args.output}")
    
    # Exit with appropriate code
    if processor.stats["failed"] > 0:
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
