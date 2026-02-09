"""
Multi-Agent PR Review System using Google ADK

This module provides a multi-agent system for reviewing GitHub Pull Requests
with specialist agents (PO, Senior Engineer, Security, DevOps, QA) and a 
Tech Lead orchestrator.
"""

import os
import sys
import asyncio
import json
import logging
from typing import List, Dict, Any, AsyncGenerator
from dataclasses import dataclass
from enum import Enum
from datetime import datetime

from dotenv import load_dotenv
from google.adk.agents import LlmAgent, BaseAgent, ParallelAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.tools.mcp_tool.mcp_toolset import McpToolset
from google.adk.tools.mcp_tool.mcp_session_manager import StreamableHTTPConnectionParams
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.adk.events import Event
from google.genai import types

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

# Configuration from environment
GCP_PROJECT_ID = os.getenv("GCP_PROJECT_ID")
GCP_LOCATION = os.getenv("GCP_LOCATION") or "us-central1"
GITHUB_TOKEN = os.getenv("GITHUB_PERSONAL_ACCESS_TOKEN")

# Set environment variables for Google ADK Vertex AI
if GCP_PROJECT_ID:
    os.environ["GOOGLE_CLOUD_PROJECT"] = GCP_PROJECT_ID
    os.environ["GOOGLE_CLOUD_LOCATION"] = GCP_LOCATION
    os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "true"

# Constants
APP_NAME = "multi_agent_pr_reviewer"
DEFAULT_MODEL = "gemini-2.5-pro"  # Use Gemini 2.5 Pro for best quality


class Severity(Enum):
    """Severity levels for review findings"""
    CRITICAL = "🔴 Critical"
    HIGH = "🟠 High"
    MEDIUM = "🟡 Medium"
    LOW = "🟢 Low"


@dataclass
class ReviewResult:
    """Structured review result from an agent"""
    agent_name: str
    agent_role: str
    summary: str
    findings: List[Dict]
    recommendation: str
    full_review: str
    
    def to_dict(self) -> Dict:
        return {
            "agent": self.agent_name,
            "role": self.agent_role,
            "summary": self.summary,
            "findings_count": len(self.findings),
            "recommendation": self.recommendation
        }


def get_github_mcp_tools() -> McpToolset:
    """Create GitHub MCP toolset using Streamable HTTP transport"""
    if not GITHUB_TOKEN:
        raise ValueError("GITHUB_PERSONAL_ACCESS_TOKEN not set")
    
    toolset = McpToolset(
        connection_params=StreamableHTTPConnectionParams(
            url="https://api.githubcopilot.com/mcp/",
            headers={
                "Authorization": f"Bearer {GITHUB_TOKEN}"
            }
        )
    )
    return toolset


async def discover_mcp_tools() -> List[str]:
    """Discover available MCP tools and log them"""
    logger.info("Discovering available MCP tools...")
    try:
        toolset = get_github_mcp_tools()
        # Get tools from the toolset
        tools = await toolset.get_tools()
        tool_names = [t.name for t in tools]
        logger.info(f"Available MCP tools ({len(tool_names)}): {tool_names}")
        return tool_names
    except Exception as e:
        logger.error(f"Failed to discover MCP tools: {e}")
        return []


def create_specialist_agent(
    name: str,
    role: str,
    focus_areas: List[str],
    owner: str,
    repo: str,
    pr_number: int
) -> LlmAgent:
    """Factory function to create specialist review agents"""
    
    focus_list = "\n".join([f"- {area}" for area in focus_areas])
    
    instruction = f"""You are a {role} reviewing PR #{pr_number} in repository {owner}/{repo}.

**MANDATORY: You MUST use these tools BEFORE writing any review:**

Step 1 - Get PR info:
Call tool `get_pull_request` with parameters:
- owner: "{owner}"
- repo: "{repo}" 
- pull_number: {pr_number}

Step 2 - Get changed files:
Call tool `get_pull_request_files` with parameters:
- owner: "{owner}"
- repo: "{repo}"
- pull_number: {pr_number}

Step 3 - For each file, get the content:
Call tool `get_file_contents` with:
- owner: "{owner}"
- repo: "{repo}"
- path: "<file_path_from_step_2>"

**STOP! If you cannot execute these tools or they return errors, you MUST respond:**
```json
{{
  "agent_name": "{name}",
  "agent_role": "{role}",
  "pr_accessed": false,
  "error": "Could not access PR data - tool call failed",
  "files_in_diff": [],
  "findings": [],
  "recommendation": "COMMENT"
}}
```

**Your Focus Areas:**
{focus_list}

**After successfully getting PR data, output this JSON:**
```json
{{
  "agent_name": "{name}",
  "agent_role": "{role}",
  "pr_accessed": true,
  "repository": "{owner}/{repo}",
  "pr_number": {pr_number},
  "files_in_diff": ["exact file paths from get_pull_request_files response"],
  "summary": "Summary based on ACTUAL file contents you retrieved",
  "score": 1-10,
  "findings": [
    {{
      "severity": "CRITICAL|HIGH|MEDIUM|LOW",
      "category": "Category",
      "file": "path/from/get_pull_request_files.py",
      "line": 42,
      "issue": "Issue found in the ACTUAL code you retrieved",
      "current_code": "actual code from get_file_contents",
      "suggested_code": "```python\\nimproved code\\n```",
      "recommendation": "How to fix"
    }}
  ],
  "recommendation": "APPROVE|REQUEST_CHANGES|COMMENT",
  "rationale": "Based on actual code review"
}}
```

**Rules:**
- files_in_diff MUST contain the exact paths from get_pull_request_files
- If files_in_diff is empty, you did NOT use the tools correctly
- If you find NO issues, recommend APPROVE with empty findings
- Every finding MUST reference actual code you retrieved"""

    return LlmAgent(
        name=name,
        model=DEFAULT_MODEL,
        description=f"{role} - Reviews PRs for {', '.join(focus_areas[:2])}",
        instruction=instruction,
        output_key=f"{name.lower()}_review",
        tools=[get_github_mcp_tools()]
    )


def create_tech_lead_agent(
    owner: str,
    repo: str,
    pr_number: int
) -> LlmAgent:
    """Create Tech Lead synthesis agent"""
    
    instruction = f"""You are a Tech Lead synthesizing reviews for PR #{pr_number} in {owner}/{repo}.

**Your Task:**
Read all specialist reviews from session state:
- productowner_review
- seniorengineer_review  
- securityengineer_review
- devopsengineer_review
- qaengineer_review

**CRITICAL: Check if specialists actually accessed PR data:**
- Look for "pr_accessed": true in each review
- Look for non-empty "files_in_diff" arrays
- If any specialist has "pr_accessed": false or empty files_in_diff, note this as data_access_status: "partial_failure"

**DECISION LOGIC:**
1. If ALL specialists have empty findings AND pr_accessed=true → auto_approve = true, final_decision = "APPROVE"
2. If any specialist has CRITICAL findings → auto_approve = false, final_decision = "REQUEST_CHANGES"
3. If only MEDIUM/LOW findings → auto_approve = false, final_decision = "COMMENT"
4. If specialists couldn't access data (pr_accessed=false) → auto_approve = false

**Output JSON:**
```json
{{
  "repository": "{owner}/{repo}",
  "pr_number": {pr_number},
  "summary": "Executive summary",
  "overall_score": 1-10,
  "auto_approve": true,
  "congratulations_message": "🎉 Excellent work! Clean code, no issues found. Keep it up! 🚀✨",
  "data_access_status": "all_success|partial_failure|all_failed",
  "files_reviewed": ["list of files from specialist reviews"],
  "critical_blockers": [],
  "important_improvements": [],
  "optional_suggestions": [],
  "inline_comments": [
    {{
      "path": "file/path.py",
      "line": 42,
      "side": "RIGHT",
      "body": "**🔴 CRITICAL**\\n\\nIssue description\\n\\n**Current:**\\n```python\\nbad_code()\\n```\\n\\n**Fix:**\\n```python\\ngood_code()\\n```\\n\\n*— AgentName*"
    }}
  ],
  "specialist_reviews": [
    {{
      "agent": "AgentName",
      "role": "Role",
      "pr_accessed": true,
      "files_reviewed": ["files"],
      "score": 8,
      "recommendation": "APPROVE",
      "findings_count": 0,
      "key_findings": []
    }}
  ],
  "final_decision": "APPROVE|REQUEST_CHANGES|COMMENT",
  "rationale": "Explanation",
  "next_steps": []
}}
```

**If auto_approve is true:**
- congratulations_message should be celebratory with emojis
- inline_comments should be empty
- Celebrate the PR author's good work!"""

    return LlmAgent(
        name="TechLead",
        model=DEFAULT_MODEL,
        description="Tech Lead - Synthesizes reviews and makes final decision",
        instruction=instruction,
        output_key="tech_lead_synthesis",
        tools=[get_github_mcp_tools()]
    )


class PRReviewOrchestrator(BaseAgent):
    """
    Custom orchestrator agent for multi-agent PR review.
    
    Coordinates specialist agents and tech lead synthesis
    following ADK best practices.
    """
    
    # Pydantic field declarations
    specialist_agents: List[LlmAgent]
    tech_lead: LlmAgent
    parallel_review: ParallelAgent
    
    model_config = {"arbitrary_types_allowed": True}
    
    def __init__(
        self,
        owner: str,
        repo: str,
        pr_number: int
    ):
        """Initialize the PR Review Orchestrator"""
        
        # Create specialist agents
        specialists = [
            create_specialist_agent(
                name="ProductOwner",
                role="Product Owner",
                focus_areas=[
                    "PR alignment with linked issues",
                    "Acceptance criteria validation",
                    "Business value verification",
                    "Breaking changes impact"
                ],
                owner=owner, repo=repo, pr_number=pr_number
            ),
            create_specialist_agent(
                name="SeniorEngineer",
                role="Senior Software Engineer",
                focus_areas=[
                    "Code quality and readability",
                    "Architecture and design patterns",
                    "Performance implications",
                    "Error handling and edge cases"
                ],
                owner=owner, repo=repo, pr_number=pr_number
            ),
            create_specialist_agent(
                name="SecurityEngineer",
                role="Security Engineer",
                focus_areas=[
                    "Security vulnerabilities (OWASP Top 10)",
                    "Authentication/authorization",
                    "Input validation",
                    "Secrets exposure"
                ],
                owner=owner, repo=repo, pr_number=pr_number
            ),
            create_specialist_agent(
                name="DevOpsEngineer",
                role="DevOps Engineer",
                focus_areas=[
                    "CI/CD configuration",
                    "Infrastructure as Code",
                    "Deployment risks",
                    "Monitoring and logging"
                ],
                owner=owner, repo=repo, pr_number=pr_number
            ),
            create_specialist_agent(
                name="QAEngineer",
                role="QA Engineer",
                focus_areas=[
                    "Test coverage",
                    "Test quality",
                    "Edge cases",
                    "Regression risks"
                ],
                owner=owner, repo=repo, pr_number=pr_number
            ),
        ]
        
        # Create parallel agent for concurrent specialist reviews
        parallel_review = ParallelAgent(
            name="ParallelSpecialistReview",
            sub_agents=specialists
        )
        
        # Create tech lead agent
        tech_lead = create_tech_lead_agent(owner, repo, pr_number)
        
        # Initialize base agent with sub_agents
        super().__init__(
            name="PRReviewOrchestrator",
            specialist_agents=specialists,
            tech_lead=tech_lead,
            parallel_review=parallel_review,
            sub_agents=[parallel_review, tech_lead]
        )
    
    async def _run_async_impl(
        self,
        ctx: InvocationContext
    ) -> AsyncGenerator[Event, None]:
        """
        Orchestrate the multi-agent PR review workflow.
        
        Phase 1: Run all specialist agents in parallel
        Phase 2: Tech Lead synthesizes all reviews
        """
        logger.info(f"[{self.name}] Starting PR review workflow")
        
        # Phase 1: Parallel specialist reviews
        logger.info(f"[{self.name}] Phase 1: Running specialist reviews in parallel...")
        async for event in self.parallel_review.run_async(ctx):
            logger.debug(f"[{self.name}] Event from ParallelReview: {event}")
            yield event
        
        # Log specialist results
        for agent in self.specialist_agents:
            review_key = f"{agent.name.lower()}_review"
            if review_key in ctx.session.state:
                logger.info(f"[{self.name}] {agent.name} completed review")
        
        # Phase 2: Tech Lead synthesis
        logger.info(f"[{self.name}] Phase 2: Tech Lead synthesizing reviews...")
        async for event in self.tech_lead.run_async(ctx):
            logger.debug(f"[{self.name}] Event from TechLead: {event}")
            yield event
        
        logger.info(f"[{self.name}] PR review workflow completed")


def parse_json_response(text: str) -> Dict:
    """Extract and parse JSON from agent response"""
    try:
        json_start = text.find('{')
        json_end = text.rfind('}') + 1
        
        if json_start >= 0 and json_end > json_start:
            json_str = text[json_start:json_end]
            return json.loads(json_str)
    except json.JSONDecodeError as e:
        logger.warning(f"Failed to parse JSON: {e}")
    
    return {"summary": text, "findings": [], "recommendation": "COMMENT"}


async def run_review(owner: str, repo: str, pr_number: int) -> Dict[str, Any]:
    """
    Run the multi-agent PR review.
    
    Args:
        owner: Repository owner
        repo: Repository name
        pr_number: Pull request number
    
    Returns:
        Complete review results dictionary
    """
    logger.info(f"Starting multi-agent review for {owner}/{repo}#{pr_number}")
    
    # Create session service
    session_service = InMemorySessionService()
    
    # Create orchestrator agent
    orchestrator = PRReviewOrchestrator(
        owner=owner,
        repo=repo,
        pr_number=pr_number
    )
    
    # Create runner
    runner = Runner(
        agent=orchestrator,
        app_name=APP_NAME,
        session_service=session_service
    )
    
    # Create session with initial state
    user_id = "pr_reviewer"
    session_id = f"review_{owner}_{repo}_{pr_number}"
    
    await session_service.create_session(
        app_name=APP_NAME,
        user_id=user_id,
        session_id=session_id,
        state={
            "owner": owner,
            "repo": repo,
            "pr_number": pr_number
        }
    )
    
    # Run the review
    message = types.Content(
        role='user',
        parts=[types.Part(text=f"Review PR #{pr_number} in {owner}/{repo}")]
    )
    
    final_response = ""
    async for event in runner.run_async(
        user_id=user_id,
        session_id=session_id,
        new_message=message
    ):
        if event.is_final_response() and event.content and event.content.parts:
            final_response = event.content.parts[0].text
    
    # Get final session state
    session = await session_service.get_session(
        app_name=APP_NAME,
        user_id=user_id,
        session_id=session_id
    )
    
    # Build results from session state
    specialist_results = []
    all_files_reviewed = set()
    data_access_issues = []
    
    for agent in orchestrator.specialist_agents:
        review_key = f"{agent.name.lower()}_review"
        review_text = session.state.get(review_key, "")
        logger.info(f"[{agent.name}] Raw review length: {len(review_text)} chars")
        
        if review_text:
            parsed = parse_json_response(review_text)
            
            # Check if agent accessed PR data
            pr_accessed = parsed.get("pr_accessed", True)
            files_in_diff = parsed.get("files_in_diff", parsed.get("files_reviewed", []))
            
            if not pr_accessed:
                data_access_issues.append(f"{agent.name}: Could not access PR data")
                logger.warning(f"[{agent.name}] Could not access PR data")
            else:
                all_files_reviewed.update(files_in_diff)
                logger.info(f"[{agent.name}] Reviewed files: {files_in_diff}")
            
            specialist_results.append({
                "agent": agent.name,
                "role": parsed.get("agent_role", agent.description),
                "pr_accessed": pr_accessed,
                "repository": parsed.get("repository", f"{owner}/{repo}"),
                "pr_number": parsed.get("pr_number", pr_number),
                "summary": parsed.get("summary", ""),
                "score": parsed.get("score", 0),
                "files_reviewed": files_in_diff,
                "recommendation": parsed.get("recommendation", "COMMENT"),
                "rationale": parsed.get("rationale", ""),
                "findings": parsed.get("findings", []),
                "findings_count": len(parsed.get("findings", []))
            })
        else:
            logger.warning(f"[{agent.name}] No review output found")
            data_access_issues.append(f"{agent.name}: No review output")
    
    # Get tech lead synthesis
    tech_lead_text = session.state.get("tech_lead_synthesis", final_response)
    tech_lead_parsed = parse_json_response(tech_lead_text)
    
    # Determine data access status
    if len(data_access_issues) == 0:
        data_status = "all_success"
    elif len(data_access_issues) == len(orchestrator.specialist_agents):
        data_status = "all_failed"
    else:
        data_status = "partial_failure"
    
    # Check for auto-approve
    auto_approve = tech_lead_parsed.get("auto_approve", False)
    final_decision = tech_lead_parsed.get("final_decision", "COMMENT")
    
    # If no issues found by any specialist, auto-approve
    total_findings = sum(len(r.get("findings", [])) for r in specialist_results)
    if total_findings == 0 and data_status == "all_success":
        auto_approve = True
        final_decision = "APPROVE"
        logger.info("No issues found - setting auto_approve=True")
    
    return {
        "pr": f"{owner}/{repo}#{pr_number}",
        "repository": f"{owner}/{repo}",
        "pr_number": pr_number,
        "timestamp": datetime.now().isoformat(),
        "data_access_status": data_status,
        "data_access_issues": data_access_issues,
        "files_reviewed": list(all_files_reviewed),
        "summary": tech_lead_parsed.get("summary", "Review completed"),
        "overall_score": tech_lead_parsed.get("overall_score", 0),
        "auto_approve": auto_approve,
        "congratulations_message": tech_lead_parsed.get("congratulations_message", "🎉 Great work! This PR looks clean and well-structured. Keep it up! 🚀✨"),
        "final_decision": final_decision,
        "critical_blockers": tech_lead_parsed.get("critical_blockers", []),
        "important_improvements": tech_lead_parsed.get("important_improvements", []),
        "optional_suggestions": tech_lead_parsed.get("optional_suggestions", []),
        "inline_comments": tech_lead_parsed.get("inline_comments", []),
        "specialist_reviews": specialist_results,
        "rationale": tech_lead_parsed.get("rationale", ""),
        "next_steps": tech_lead_parsed.get("next_steps", [])
    }


async def main():
    """Main entry point for CLI and GitHub Actions"""
    
    print(f"\n{'='*80}")
    print("🚀 Multi-Agent PR Review System")
    print(f"{'='*80}")
    
    # Validate configuration
    if not GCP_PROJECT_ID:
        print("❌ Error: GCP_PROJECT_ID not set")
        print("\nRequired environment variables:")
        print("  - GCP_PROJECT_ID: Your GCP project ID")
        print("  - GOOGLE_APPLICATION_CREDENTIALS: Path to service account JSON")
        print("  - GITHUB_PERSONAL_ACCESS_TOKEN: GitHub PAT")
        return 1
    
    if not GITHUB_TOKEN:
        print("❌ Error: GITHUB_PERSONAL_ACCESS_TOKEN not set")
        return 1
    
    # Discover available MCP tools
    print("\n🔧 Discovering available MCP tools...")
    try:
        available_tools = await discover_mcp_tools()
        print(f"✅ Found {len(available_tools)} tools: {available_tools[:10]}...")
    except Exception as e:
        print(f"⚠️ Could not discover tools: {e}")
        available_tools = []
    
    # Get PR details from environment
    owner = os.getenv("REPO_OWNER")
    repo = os.getenv("REPO_NAME")
    pr_number = os.getenv("PR_NUMBER")
    
    if not all([owner, repo, pr_number]):
        print("⚠️  Using test values (set REPO_OWNER, REPO_NAME, PR_NUMBER)")
        owner = owner or "test-owner"
        repo = repo or "test-repo"
        pr_number = pr_number or "1"
    
    pr_number = int(pr_number)
    
    print(f"\n📋 Repository: {owner}/{repo}")
    print(f"🔢 PR Number: #{pr_number}")
    print(f"☁️  GCP Project: {GCP_PROJECT_ID}")
    print(f"📍 Location: {GCP_LOCATION}")
    print(f"⏰ Time: {datetime.now().isoformat()}")
    print(f"{'='*80}\n")
    
    try:
        # Run review
        results = await run_review(owner, repo, pr_number)
        
        # Save results
        output_file = "review_results.json"
        with open(output_file, 'w') as f:
            json.dump(results, f, indent=2, default=str)
        
        print(f"\n📄 Results saved to {output_file}")
        
        # Print detailed summary for logging
        print(f"\n{'='*80}")
        print("📋 REVIEW SUMMARY")
        print(f"{'='*80}")
        print(f"📦 Repository: {results.get('repository', 'N/A')}")
        print(f"🔢 PR Number: #{results.get('pr_number', 'N/A')}")
        print(f"📊 Overall Score: {results.get('overall_score', 'N/A')}/10")
        print(f"🎯 Decision: {results['final_decision']}")
        print(f"📁 Data Access: {results.get('data_access_status', 'unknown')}")
        
        # Show files reviewed
        files_reviewed = results.get('files_reviewed', [])
        print(f"\n📂 Files Reviewed ({len(files_reviewed)}):")
        if files_reviewed:
            for f in files_reviewed[:20]:  # Show first 20
                print(f"   - {f}")
            if len(files_reviewed) > 20:
                print(f"   ... and {len(files_reviewed) - 20} more files")
        else:
            print("   ⚠️ No files found in diff or could not access PR data")
        
        # Show data access issues if any
        if results.get('data_access_issues'):
            print(f"\n⚠️ Data Access Issues:")
            for issue in results['data_access_issues']:
                print(f"   - {issue}")
        
        print(f"\n📝 Summary:\n{results['summary']}")
        
        if results.get('critical_blockers'):
            print(f"\n🚫 Critical Blockers:")
            for blocker in results['critical_blockers']:
                print(f"  - {blocker}")
        
        if results.get('important_improvements'):
            print(f"\n⚠️ Important Improvements:")
            for imp in results['important_improvements']:
                print(f"  - {imp}")
        
        # Detailed specialist reviews for logging
        print(f"\n{'='*80}")
        print("👥 DETAILED SPECIALIST REVIEWS")
        print(f"{'='*80}")
        for review in results['specialist_reviews']:
            icon = "✅" if review['recommendation'] == "APPROVE" else "⚠️" if review['recommendation'] == "REQUEST_CHANGES" else "💬"
            access_icon = "🔗" if review.get('pr_accessed', True) else "❌"
            
            print(f"\n{'-'*60}")
            print(f"{icon} {review['agent']} - {review.get('role', 'Specialist')}")
            print(f"{'-'*60}")
            print(f"   {access_icon} PR Accessed: {review.get('pr_accessed', 'unknown')}")
            print(f"   📊 Score: {review.get('score', 'N/A')}/10")
            print(f"   🎯 Recommendation: {review['recommendation']}")
            
            agent_files = review.get('files_reviewed', [])
            print(f"   📁 Files Reviewed ({len(agent_files)}):")
            for f in agent_files[:10]:
                print(f"      - {f}")
            if len(agent_files) > 10:
                print(f"      ... and {len(agent_files) - 10} more")
            
            print(f"\n   📝 Summary: {review.get('summary', 'N/A')}")
            print(f"   💡 Rationale: {review.get('rationale', 'N/A')}")
            
            findings = review.get('findings', [])
            if findings:
                print(f"\n   🔍 Findings ({len(findings)}):")
                for i, finding in enumerate(findings, 1):
                    severity = finding.get('severity', 'N/A')
                    severity_icon = "🔴" if severity == "CRITICAL" else "🟠" if severity == "HIGH" else "🟡" if severity == "MEDIUM" else "🟢"
                    print(f"\n   {i}. {severity_icon} [{severity}] {finding.get('category', 'General')}")
                    print(f"      📄 File: {finding.get('file', 'N/A')}")
                    print(f"      📍 Line: {finding.get('line', 'N/A')}")
                    print(f"      ❗ Issue: {finding.get('issue', 'N/A')}")
                    if finding.get('code_snippet'):
                        code = finding['code_snippet'][:200]
                        print(f"      💻 Code: {code}...")
                    print(f"      💡 Fix: {finding.get('recommendation', 'N/A')}")
            else:
                print(f"\n   ✅ No issues found in focus areas")
        
        if results.get('next_steps'):
            print(f"\n📋 Next Steps:")
            for step in results['next_steps']:
                print(f"  - {step}")
        
        print(f"\n{'='*80}")
        print("✅ Review Complete!")
        print(f"{'='*80}\n")
        
        return 0
        
    except Exception as e:
        logger.error(f"Review failed: {e}", exc_info=True)
        print(f"\n❌ Error: {e}")
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
