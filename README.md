# Basecamp Task Creator

A Python tool to automatically create Basecamp tasks from a JSON list. Perfect for syncing TODO comments, code analysis results, or any structured task list to Basecamp.

## Features

- ✅ Create tasks from JSON files or stdin
- ✅ Automatic duplicate detection
- ✅ Dry-run mode for previewing changes
- ✅ Rate limiting to respect Basecamp API limits
- ✅ Retry logic for transient failures
- ✅ Support for task metadata (due dates, descriptions, assignees)
- ✅ Flexible input formats (detailed objects or simple strings)
- ✅ Utility commands to list projects and todolists

## Installation

```bash
# Clone or navigate to the project
cd /path/to/project

# Install dependencies
pip install -r requirements.txt
```

## Configuration

### Option 1: Environment Variables (Recommended)

```bash
# Copy the example file
cp .env.example .env

# Edit with your values
nano .env
```

Required environment variables:
- `BASECAMP_ACCOUNT_ID` - Your Basecamp account ID (from URL)
- `BASECAMP_ACCESS_TOKEN` - OAuth2 or personal access token
- `BASECAMP_PROJECT_ID` - Target project ID
- `BASECAMP_TODOLIST_ID` - Target todolist ID

### Option 2: Config File

```bash
# Copy the example file
cp basecamp_config.example.json basecamp_config.json

# Edit with your values
nano basecamp_config.json
```

Then use with `--config`:
```bash
python basecamp_task_creator.py tasks.json --config basecamp_config.json
```

### Getting Your Basecamp Credentials

1. **Account ID**: Found in your Basecamp URL: `https://3.basecamp.com/ACCOUNT_ID/...`

2. **Access Token**: 
   - Go to [https://launchpad.37signals.com/integrations](https://launchpad.37signals.com/integrations)
   - Create a new integration
   - Follow OAuth2 flow or use personal access token

3. **Project ID**: Use `--list-projects` to find it:
   ```bash
   python basecamp_task_creator.py --list-projects
   ```

4. **Todolist ID**: Use `--list-todolists` to find it:
   ```bash
   python basecamp_task_creator.py --list-todolists
   ```

## Usage

### Basic Usage

```bash
# Create tasks from a JSON file
python basecamp_task_creator.py tasks.json

# Preview without creating (dry-run)
python basecamp_task_creator.py tasks.json --dry-run

# Read from stdin
cat tasks.json | python basecamp_task_creator.py --stdin

# With pipe from another command
./extract_todos.sh | python basecamp_task_creator.py --stdin
```

### Advanced Options

```bash
# Allow duplicate tasks
python basecamp_task_creator.py tasks.json --allow-duplicates

# Override project/todolist
python basecamp_task_creator.py tasks.json --project-id 12345 --todolist-id 67890

# Save results to file
python basecamp_task_creator.py tasks.json --output results.json

# Verbose output
python basecamp_task_creator.py tasks.json --verbose
```

### Utility Commands

```bash
# Test API connection
python basecamp_task_creator.py --test-connection

# List all projects
python basecamp_task_creator.py --list-projects

# List todolists in configured project
python basecamp_task_creator.py --list-todolists
```

## JSON Format

### Full Format

```json
{
  "tasks": [
    {
      "content": "Task title (required)",
      "description": "Optional description with <strong>HTML</strong> support",
      "due_on": "2024-12-31",
      "starts_on": "2024-12-01",
      "assignee_ids": [12345, 67890],
      "notify": true,
      "priority": "high",
      "category": "backend",
      "source_file": "src/api/users.py",
      "source_line": 42
    }
  ]
}
```

### Simple Format

```json
[
  {
    "content": "First task"
  },
  "Second task as simple string",
  "Third task"
]
```

### Task Fields

| Field | Required | Description |
|-------|----------|-------------|
| `content` | Yes | Task title/description |
| `description` | No | Rich text notes (HTML supported) |
| `due_on` | No | Due date (YYYY-MM-DD) |
| `starts_on` | No | Start date (YYYY-MM-DD) |
| `assignee_ids` | No | List of Basecamp user IDs |
| `notify` | No | Notify assignees (default: false) |
| `priority` | No | Metadata: low, normal, high, critical |
| `category` | No | Metadata: custom category |
| `source_file` | No | Metadata: originating file |
| `source_line` | No | Metadata: line number in source |

> Note: `priority`, `category`, `source_file`, and `source_line` are metadata fields stored locally and not sent to Basecamp.

## Examples

### Example 1: From Code Analysis

```bash
# Generate tasks from TODO comments
grep -rn "TODO:" src/ | python -c "
import sys, json
tasks = []
for line in sys.stdin:
    parts = line.split(':', 2)
    if len(parts) >= 3:
        tasks.append({
            'content': parts[2].replace('TODO:', '').strip(),
            'source_file': parts[0],
            'source_line': int(parts[1])
        })
print(json.dumps(tasks))
" | python basecamp_task_creator.py --stdin
```

### Example 2: CI/CD Integration

```yaml
# .github/workflows/sync-todos.yml
name: Sync TODOs to Basecamp

on:
  push:
    branches: [main]

jobs:
  sync:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      
      - name: Setup Python
        uses: actions/setup-python@v4
        with:
          python-version: '3.11'
          
      - name: Install dependencies
        run: pip install -r requirements.txt
        
      - name: Extract and sync TODOs
        env:
          BASECAMP_ACCOUNT_ID: ${{ secrets.BASECAMP_ACCOUNT_ID }}
          BASECAMP_ACCESS_TOKEN: ${{ secrets.BASECAMP_ACCESS_TOKEN }}
          BASECAMP_PROJECT_ID: ${{ secrets.BASECAMP_PROJECT_ID }}
          BASECAMP_TODOLIST_ID: ${{ secrets.BASECAMP_TODOLIST_ID }}
        run: |
          python extract_todos.py | python basecamp_task_creator.py --stdin
```

### Example 3: Manual Task Entry

```bash
# Quick task creation
echo '[{"content": "Review PR #123"}, {"content": "Update dependencies"}]' | \
  python basecamp_task_creator.py --stdin
```

## Output

### Console Output

```
============================================================
Processing 3 task(s)...
============================================================

[1/3] Implement user authentication flow
  ✅ Created (ID: 1234567890)
[2/3] Fix memory leak in dashboard component
  ⏭️  Skipped (duplicate)
[3/3] Add unit tests for payment service
  ✅ Created (ID: 1234567891)

============================================================
Summary
============================================================
  Total tasks:   3
  ✅ Created:    2
  ⏭️  Skipped:    1
  ❌ Failed:     0
============================================================
```

### Results File (--output)

```json
{
  "timestamp": "2024-11-28T10:30:00.000000",
  "stats": {
    "total": 3,
    "created": 2,
    "skipped": 1,
    "failed": 0
  },
  "results": [
    {
      "task": "Implement user authentication flow",
      "status": "created",
      "basecamp_id": 1234567890,
      "url": "https://3.basecamp.com/...",
      "error": null
    }
  ]
}
```

## Troubleshooting

### Common Issues

**"Missing required environment variables"**
- Ensure all required env vars are set
- Check for typos in `.env` file
- Verify `.env` file is in the current directory

**"HTTP Error: 401"**
- Access token is invalid or expired
- Regenerate token at launchpad.37signals.com

**"HTTP Error: 404"**
- Project ID or Todolist ID is incorrect
- Use `--list-projects` and `--list-todolists` to verify

**"Rate limiting"**
- Normal behavior when creating many tasks
- Script automatically handles this with delays

## License

MIT License - Use freely in your projects.
