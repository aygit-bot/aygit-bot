# 🤖 Multi-Agent AI PR Reviewer

AI-powered code review system using Google Gemini 2.5 Pro with 5 specialist agents.

## ✨ Features

- 🎯 **5 Specialist AI Agents** - Each reviews from a different perspective
- 💬 **Inline Code Comments** - Direct suggestions on specific lines
- ✅ **Auto-Approve** - Automatically approves clean PRs
- 🎉 **Emoji Reactions** - Visual feedback on PR quality
- 📊 **Detailed Reports** - Severity-based issue tracking

## 🤖 AI Agents

| Agent | Focus |
|-------|-------|
| 🎯 Product Owner | Requirements, user stories, acceptance criteria |
| 👨‍💻 Senior Engineer | Code quality, design patterns, performance |
| 🔒 Security Engineer | OWASP Top 10, input validation, secrets |
| 🔧 DevOps Engineer | CI/CD, infrastructure, deployment |
| 🧪 QA Engineer | Test coverage, edge cases, regression |

**Tech Lead** synthesizes all reviews and makes the final decision.

## 🚀 Quick Setup

### 1. GCP Setup

```bash
# Create service account
gcloud iam service-accounts create github-pr-reviewer \
  --display-name="GitHub PR Reviewer"

# Grant Vertex AI access
gcloud projects add-iam-policy-binding YOUR_PROJECT \
  --member="serviceAccount:github-pr-reviewer@YOUR_PROJECT.iam.gserviceaccount.com" \
  --role="roles/aiplatform.user"

# Create key
gcloud iam service-accounts keys create key.json \
  --iam-account=github-pr-reviewer@YOUR_PROJECT.iam.gserviceaccount.com

# Enable API
gcloud services enable aiplatform.googleapis.com
```

### 2. GitHub Secrets

Add these secrets to this repository:

| Secret | Value |
|--------|-------|
| `GCP_SA_KEY` | Contents of `key.json` |
| `GCP_PROJECT_ID` | Your GCP project ID |
| `GH_PAT` | GitHub PAT with repo/PR access |

### 3. Trigger Review

Go to **Actions** → **AI PR Review** → **Run workflow**

Enter:
- `target_repo`: `owner/repo-name`
- `pr_number`: PR number to review

## 📋 Output Example

```
🤖 Multi-Agent PR Review Summary

| Metric | Value |
|--------|-------|
| Score | 8/10 |
| Files Reviewed | 3 |
| 🔴 Critical | 0 |
| 🟠 High | 1 |
| 🟡 Medium | 2 |

👥 Specialist Votes
| Agent | Score | Decision |
|-------|-------|----------|
| ProductOwner | 10/10 | ✅ APPROVE |
| SeniorEngineer | 7/10 | ⚠️ REQUEST_CHANGES |
| SecurityEngineer | 8/10 | 💬 COMMENT |
```

## 🔧 Local Development

```bash
# Install dependencies
pip install -r requirements.txt

# Set environment variables
export GCP_PROJECT_ID=your-project
export GITHUB_PERSONAL_ACCESS_TOKEN=ghp_xxx
export GOOGLE_APPLICATION_CREDENTIALS=key.json

# Run
python multi_agent_reviewer.py
```

## 📄 License

MIT
