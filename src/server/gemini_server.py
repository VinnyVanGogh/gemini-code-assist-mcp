"""
Main FastMCP server for Gemini integration.

This module implements the MCP server that provides tools for interacting
with Google Gemini CLI for development assistance.
"""

import json
from typing import Any

from mcp.server.fastmcp import Context, FastMCP
from pydantic import BaseModel, Field

from ..core.config import ConfigManager
from ..core.gemini_client import GeminiCLIClient


class CodeReviewRequest(BaseModel):
    """Request model for code review."""

    code: str = Field(description="Code to review")
    language: str | None = Field(default=None, description="Programming language")
    focus: str | None = Field(
        default="general",
        description="Focus area: general, security, performance, style, or bugs"
    )


class CodeReviewResponse(BaseModel):
    """Response model for code review."""

    summary: str = Field(description="Overall assessment summary")
    issues: list[dict[str, Any]] = Field(description="List of identified issues")
    suggestions: list[str] = Field(description="Improvement suggestions")
    rating: str = Field(description="Overall code quality rating")
    input_prompt: str = Field(description="The prompt sent to Gemini")
    gemini_response: str = Field(description="The raw response from Gemini")


class GeminiToolResponse(BaseModel):
    """Generic response model for Gemini tools with input/output transparency."""
    
    result: str = Field(description="The processed result")
    input_prompt: str = Field(description="The prompt sent to Gemini")
    gemini_response: str = Field(description="The raw response from Gemini")
    metadata: dict[str, Any] = Field(default_factory=dict, description="Additional metadata")


class FeaturePlanRequest(BaseModel):
    """Request model for feature plan review."""

    feature_plan: str = Field(description="Feature plan document")
    context: str | None = Field(default="", description="Project context")
    focus_areas: str | None = Field(
        default="completeness,feasibility,clarity",
        description="Areas to focus on"
    )


class BugAnalysisRequest(BaseModel):
    """Request model for bug analysis."""

    bug_description: str = Field(description="Description of the bug")
    code_context: str | None = Field(default="", description="Relevant code snippets")
    error_logs: str | None = Field(default="", description="Error messages and logs")
    environment: str | None = Field(default="", description="Environment details")
    reproduction_steps: str | None = Field(default="", description="Steps to reproduce")
    language: str | None = Field(default="", description="Programming language")


class CodeExplanationRequest(BaseModel):
    """Request model for code explanation."""

    code: str = Field(description="Code to explain")
    language: str | None = Field(default=None, description="Programming language")
    detail_level: str | None = Field(
        default="intermediate",
        description="Detail level: basic, intermediate, or advanced"
    )
    questions: str | None = Field(default="", description="Specific questions about the code")


def create_server() -> FastMCP:
    """
    Create and configure the Gemini MCP server.
    
    Returns:
        Configured FastMCP server instance
    """
    # Initialize configuration
    config_manager = ConfigManager()
    server_config = config_manager.config

    # Create FastMCP server
    mcp = FastMCP(
        name=server_config.name,
        # Enable stateless HTTP for Claude Code compatibility
        stateless_http=True
    )

    # Initialize Gemini client
    gemini_client = GeminiCLIClient(server_config.gemini_options)

    @mcp.tool()
    async def gemini_review_code(
        request: CodeReviewRequest,
        ctx: Context
    ) -> CodeReviewResponse:
        """
        Analyze code quality, style, and potential issues using Gemini.
        
        Provides comprehensive code review including bug detection,
        security analysis, performance optimization suggestions, and
        best practice recommendations.
        """
        await ctx.info(f"Starting code review for {len(request.code)} characters of code")

        try:
            # Get template and format prompt
            template = config_manager.get_template("code_review")
            if not template:
                raise ValueError("Code review template not found")

            # Determine language if not provided
            language = request.language or "auto-detect"

            # Create focus instruction
            focus_map = {
                "security": "Focus specifically on security vulnerabilities and potential exploits.",
                "performance": "Focus on performance optimizations and bottlenecks.",
                "style": "Focus on code style, formatting, and best practices.",
                "bugs": "Focus on potential bugs and logical errors.",
                "general": "Provide a comprehensive review covering all aspects."
            }
            focus_instruction = focus_map.get(request.focus, focus_map["general"])

            # Format template
            system_prompt, user_prompt = template.format(
                language=language,
                code=request.code,
                focus_instruction=focus_instruction
            )

            # Call Gemini
            response = await gemini_client.call_with_structured_prompt(
                system_prompt=system_prompt,
                user_prompt=user_prompt
            )

            if not response.success:
                raise ValueError(f"Gemini call failed: {response.error}")

            # Parse structured response
            try:
                # Try to extract JSON from response
                content = response.content
                if "```json" in content:
                    # Extract JSON block
                    start = content.find("```json") + 7
                    end = content.find("```", start)
                    if end != -1:
                        json_content = content[start:end].strip()
                        parsed = json.loads(json_content)
                    else:
                        # Fallback to simple parsing
                        parsed = {"summary": content, "issues": [], "suggestions": []}
                else:
                    # Create structured response from text
                    parsed = {
                        "summary": content[:500] + "..." if len(content) > 500 else content,
                        "issues": [],
                        "suggestions": content.split('\n') if content else []
                    }

                return CodeReviewResponse(
                    summary=parsed.get("summary", "Code review completed"),
                    issues=parsed.get("issues", []),
                    suggestions=parsed.get("suggestions", []),
                    rating=parsed.get("rating", "Review completed"),
                    input_prompt=response.input_prompt,
                    gemini_response=response.content
                )

            except json.JSONDecodeError:
                # Fallback to simple text response
                return CodeReviewResponse(
                    summary=response.content[:200] + "..." if len(response.content) > 200 else response.content,
                    issues=[],
                    suggestions=[response.content],
                    rating="Review completed (text format)",
                    input_prompt=response.input_prompt,
                    gemini_response=response.content
                )

        except Exception as e:
            await ctx.error(f"Code review failed: {str(e)}")
            return CodeReviewResponse(
                summary=f"Error during review: {str(e)}",
                issues=[],
                suggestions=[],
                rating="Failed",
                input_prompt="Error occurred before prompt creation",
                gemini_response=f"Error: {str(e)}"
            )

    @mcp.tool()
    async def gemini_proofread_feature_plan(
        request: FeaturePlanRequest,
        ctx: Context
    ) -> GeminiToolResponse:
        """
        Review and improve feature plans and specifications using Gemini.
        
        Analyzes feature plans for completeness, clarity, technical feasibility,
        and provides suggestions for improvement.
        """
        await ctx.info("Starting feature plan review")

        try:
            # Get template
            template = config_manager.get_template("feature_plan_review")
            if not template:
                raise ValueError("Feature plan review template not found")

            # Format template
            system_prompt, user_prompt = template.format(
                feature_plan=request.feature_plan,
                context=request.context,
                focus_areas=request.focus_areas
            )

            # Call Gemini
            response = await gemini_client.call_with_structured_prompt(
                system_prompt=system_prompt,
                user_prompt=user_prompt
            )

            if not response.success:
                raise ValueError(f"Gemini call failed: {response.error}")

            return GeminiToolResponse(
                result=response.content,
                input_prompt=response.input_prompt,
                gemini_response=response.content
            )

        except Exception as e:
            await ctx.error(f"Feature plan review failed: {str(e)}")
            return GeminiToolResponse(
                result=f"Error during feature plan review: {str(e)}",
                input_prompt="Error occurred before prompt creation",
                gemini_response=f"Error: {str(e)}"
            )

    @mcp.tool()
    async def gemini_analyze_bug(
        request: BugAnalysisRequest,
        ctx: Context
    ) -> GeminiToolResponse:
        """
        Analyze bugs and suggest fixes using Gemini.
        
        Provides root cause analysis, fix suggestions, and preventive measures
        for reported bugs.
        """
        await ctx.info("Starting bug analysis")

        try:
            # Get template
            template = config_manager.get_template("bug_analysis")
            if not template:
                raise ValueError("Bug analysis template not found")

            # Format template
            system_prompt, user_prompt = template.format(
                bug_description=request.bug_description,
                error_logs=request.error_logs,
                code_context=request.code_context,
                language=request.language or "unknown",
                environment=request.environment,
                reproduction_steps=request.reproduction_steps
            )

            # Call Gemini
            response = await gemini_client.call_with_structured_prompt(
                system_prompt=system_prompt,
                user_prompt=user_prompt
            )

            if not response.success:
                raise ValueError(f"Gemini call failed: {response.error}")

            return GeminiToolResponse(
                result=response.content,
                input_prompt=response.input_prompt,
                gemini_response=response.content
            )

        except Exception as e:
            await ctx.error(f"Bug analysis failed: {str(e)}")
            return GeminiToolResponse(
                result=f"Error during bug analysis: {str(e)}",
                input_prompt="Error occurred before prompt creation",
                gemini_response=f"Error: {str(e)}"
            )

    @mcp.tool()
    async def gemini_explain_code(
        request: CodeExplanationRequest,
        ctx: Context
    ) -> GeminiToolResponse:
        """
        Explain code functionality and implementation using Gemini.
        
        Provides clear, educational explanations of code with varying
        levels of detail based on the target audience.
        """
        await ctx.info(f"Starting code explanation ({request.detail_level} level)")

        try:
            # Get template
            template = config_manager.get_template("code_explanation")
            if not template:
                raise ValueError("Code explanation template not found")

            # Determine language if not provided
            language = request.language or "auto-detect"

            # Format template
            system_prompt, user_prompt = template.format(
                language=language,
                code=request.code,
                detail_level=request.detail_level,
                questions=request.questions
            )

            # Call Gemini
            response = await gemini_client.call_with_structured_prompt(
                system_prompt=system_prompt,
                user_prompt=user_prompt
            )

            if not response.success:
                raise ValueError(f"Gemini call failed: {response.error}")

            return GeminiToolResponse(
                result=response.content,
                input_prompt=response.input_prompt,
                gemini_response=response.content
            )

        except Exception as e:
            await ctx.error(f"Code explanation failed: {str(e)}")
            return GeminiToolResponse(
                result=f"Error during code explanation: {str(e)}",
                input_prompt="Error occurred before prompt creation",
                gemini_response=f"Error: {str(e)}"
            )

    # Add resources for configuration and status
    @mcp.resource("gemini://config")
    def get_config() -> str:
        """Get current Gemini MCP server configuration."""
        config_dict = config_manager.get_config_dict()
        return json.dumps(config_dict, indent=2)

    @mcp.resource("gemini://templates")
    def list_templates() -> str:
        """List available prompt templates."""
        templates = config_manager.list_templates()
        return json.dumps(templates, indent=2)

    @mcp.resource("gemini://status")
    async def get_status() -> str:
        """Get Gemini CLI status and authentication info."""
        try:
            # Test authentication
            auth_valid = await gemini_client.verify_authentication()
            status = {
                "authenticated": auth_valid,
                "model": config_manager.config.gemini_options.model,
                "cli_available": True
            }
        except Exception as e:
            status = {
                "authenticated": False,
                "error": str(e),
                "cli_available": False
            }

        return json.dumps(status, indent=2)

    return mcp
