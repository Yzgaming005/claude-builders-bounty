# 📬 n8n + Claude API — Weekly Dev Summary

Auto-generate a narrative weekly development summary for any GitHub repo, delivered to your team's Discord/Slack.

## How It Works

1. **Schedule:** Fires every Friday at 5PM UTC
2. **Fetch:** Collects commits, closed issues, and merged PRs from the past 7 days via GitHub API
3. **Summarize:** Sends the raw data to Claude API (`claude-sonnet-4-20250514`) for a human-readable narrative
4. **Deliver:** Posts the final summary to your Discord channel (configurable to Slack webhook or email)

## Setup (5 Steps)

### 1. Import the Workflow
- In n8n, go to **Workflows → Add Workflow → Import from File**
- Select `Weekly_Dev_Summary.workflow.json`

### 2. Configure Variables
Open the **Config (Set Variables)** node and update:

| Variable | Description | Example |
|----------|-------------|---------|
| `owner` | GitHub org/user | `your-org` |
| `repo` | Repository name | `your-repo` |
| `language` | Output language | `EN` or `FR` |
| `webhookUrl` | Discord webhook URL | `https://discord.com/api/webhooks/...` |
| `deliveryMethod` | Delivery channel | `discord` (see below for alternatives) |

### 3. Set Up Credentials
n8n will prompt for:

- **GitHub API** — a [GitHub PAT](https://github.com/settings/tokens) with `repo` scope
- **Claude API** — an [Anthropic API key](https://console.anthropic.com/) with access to `claude-sonnet-4-20250514`

### 4. Test the Workflow
Click **Execute Workflow** in n8n. A test summary should appear in your configured channel.

### 5. Activate
Toggle the workflow to **Active**. It runs every Friday at 5PM UTC automatically.

## Alternative Delivery

### Slack Webhook
Replace the **Send to Discord** node with an HTTP Request to `https://hooks.slack.com/services/...` or use n8n's built-in Slack node.

### Email
Replace the **Send to Discord** node with n8n's **Email** node (SMTP). Requires an SMTP credential.

## Example Output

```
📬 Weekly Dev Summary

Repository: vercel/next.js
Week ending: 2026-03-20

📊 Stats
- Commits: 47
- Issues closed: 12
- PRs merged: 8

📝 Generated Summary
This week saw significant progress on the Turbopack integration...
```

---

*Built with n8n + Claude API · Bounty #5 at Claude Builders Bounty*
