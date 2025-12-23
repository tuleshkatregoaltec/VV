"""MCP Tool Registry Service - Exposes API endpoints as LLM tools using FastMCP."""

from fastmcp import FastMCP
from typing import List, Dict, Any, Optional
import logging
import json

logger = logging.getLogger(__name__)


class MCPToolRegistry:
    """Registry for MCP tools exposing existing API endpoints"""

    def __init__(self):
        self.mcp = FastMCP("ViteVue Real Estate Tools")
        self._register_tools()

    def _register_tools(self):
        """Register all API endpoints as MCP tools"""

        # Analytics Tools
        @self.mcp.tool()
        async def get_sales_analytics(
            property_usage: str = "Residential",
            timeframe_days: Optional[int] = None,
            start_date: Optional[str] = None,
            end_date: Optional[str] = None,
            master_project: Optional[str] = None,
            property_type: Optional[str] = None,
            rooms: Optional[str] = None,
            reg_type: Optional[str] = None,
            price_bucket: Optional[str] = None,
            area_bucket: Optional[str] = None,
        ) -> Dict[str, Any]:
            """Get comprehensive sales analytics with trends, KPIs, and dimensional breakdowns.

            Returns detailed market insights including:
            - Summary metrics (total volume, transaction count, average prices, price/sqft)
            - Period-over-period change percentages
            - Daily trend data for time series analysis
            - Breakdowns by property type, rooms, registration type, and master project

            Use custom date ranges for specific periods, or timeframe_days for recent data.
            Apply filters to drill down into specific market segments.

            Args:
                property_usage: Type of property - "Residential" or "Commercial" (default: "Residential")
                timeframe_days: Days to look back (7, 30, 90, 180, 365). Ignored if start_date/end_date provided.
                start_date: Custom start date in YYYY-MM-DD format (e.g., "2024-01-01")
                end_date: Custom end date in YYYY-MM-DD format (e.g., "2024-12-31")
                master_project: Filter by master project name (e.g., "Dubai Marina", "Downtown Dubai")
                property_type: Filter by property type (e.g., "Unit", "Villa", "Building", "Land")
                rooms: Filter by room count (e.g., "Studio", "1 B/R", "2 B/R", "3 B/R", "4 B/R", "5 B/R", "6 B/R+")
                reg_type: Filter by registration type - "Ready" or "Offplan"
                price_bucket: Filter by price range (e.g., "<500K", "500K-1M", "1M-2M", "2M-5M", "5M-10M", "10M-25M", ">25M")
                area_bucket: Filter by area range in sqft (e.g., "<500", "500-1K", "1K-2K", "2K-3K", "3K-5K", ">5K")
            """
            from backend.app.services.analytics_service import fetch_sales_analytics
            from backend.app.db.session import async_session
            from datetime import datetime

            async with async_session() as session:
                # Convert date strings to date objects if provided
                parsed_start_date = None
                parsed_end_date = None
                if start_date:
                    parsed_start_date = datetime.strptime(start_date, "%Y-%m-%d").date()
                if end_date:
                    parsed_end_date = datetime.strptime(end_date, "%Y-%m-%d").date()

                result = await fetch_sales_analytics(
                    db=session,
                    property_usage=property_usage,
                    timeframe_days=timeframe_days,
                    start_date=parsed_start_date,
                    end_date=parsed_end_date,
                    master_project=master_project,
                    property_type=property_type,
                    rooms=rooms,
                    reg_type=reg_type,
                    price_bucket=price_bucket,
                    area_bucket=area_bucket,
                )
                return result.model_dump()

        @self.mcp.tool()
        async def get_rental_analytics(
            property_usage: str = "Residential",
            timeframe_days: Optional[int] = None,
            start_date: Optional[str] = None,
            end_date: Optional[str] = None,
            master_project: Optional[str] = None,
            property_type: Optional[str] = None,
            rent_bucket: Optional[str] = None,
            area_bucket: Optional[str] = None,
        ) -> Dict[str, Any]:
            """Get comprehensive rental analytics with trends, KPIs, and dimensional breakdowns.

            Returns detailed rental market insights including:
            - Summary metrics (total annual value, contract count, average rent, rent/sqft)
            - Period-over-period change percentages
            - Daily trend data for time series analysis
            - Breakdowns by property type and master project

            IMPORTANT: This aggregated analytics does NOT include bedroom-specific breakdowns. For bedroom-specific
            rental data, use search_rental_contracts with property_sub_type filter (e.g., "2 bed rooms+hall").

            Use custom date ranges for specific periods, or timeframe_days for recent data.
            Apply filters to drill down into specific rental market segments.

            Args:
                property_usage: Type of property - "Residential" or "Commercial" (default: "Residential")
                timeframe_days: Days to look back (7, 30, 90, 180, 365). Ignored if start_date/end_date provided.
                start_date: Custom start date in YYYY-MM-DD format (e.g., "2024-01-01")
                end_date: Custom end date in YYYY-MM-DD format (e.g., "2024-12-31")
                master_project: Filter by master project name (e.g., "Dubai Marina", "Downtown Dubai", "Mulberry")
                property_type: Filter by general property type (e.g., "Flat", "Villa", "Building")
                rent_bucket: Filter by annual rent range (e.g., "<50K", "50K-100K", "100K-200K", "200K-500K", "500K-1M", ">1M")
                area_bucket: Filter by area range in sqft (e.g., "<500", "500-1K", "1K-2K", "2K-3K", "3K-5K", ">5K")
            """
            from backend.app.services.analytics_service import fetch_rental_analytics
            from backend.app.db.session import async_session
            from datetime import datetime

            async with async_session() as session:
                # Convert date strings to date objects if provided
                parsed_start_date = None
                parsed_end_date = None
                if start_date:
                    parsed_start_date = datetime.strptime(start_date, "%Y-%m-%d").date()
                if end_date:
                    parsed_end_date = datetime.strptime(end_date, "%Y-%m-%d").date()

                result = await fetch_rental_analytics(
                    db=session,
                    property_usage=property_usage,
                    timeframe_days=timeframe_days,
                    start_date=parsed_start_date,
                    end_date=parsed_end_date,
                    master_project=master_project,
                    property_type=property_type,
                    rent_bucket=rent_bucket,
                    area_bucket=area_bucket,
                )
                return result.model_dump()

        # Transaction Tools
        @self.mcp.tool()
        async def search_sales_transactions(
            limit: int = 50,
            offset: int = 0,
            master_project: Optional[str] = None,
            property_type: Optional[str] = None,
            rooms: Optional[str] = None,
            area_min: Optional[float] = None,
            area_max: Optional[float] = None,
            price_min: Optional[float] = None,
            price_max: Optional[float] = None,
        ) -> Dict[str, Any]:
            """Search sales transactions with filters. Returns paginated list of sales transactions with details like project, building, price, area, etc.

            Args:
                limit: Number of results to return (max 500)
                offset: Pagination offset
                master_project: Filter by master project name
                property_type: Filter by property type
                rooms: Filter by number of rooms
                area_min: Minimum property area in sqft
                area_max: Maximum property area in sqft
                price_min: Minimum sale price in AED
                price_max: Maximum sale price in AED
            """
            from backend.app.services.transactions_service import (
                fetch_sales_transactions,
            )
            from backend.app.db.session import async_session

            async with async_session() as session:
                result = await fetch_sales_transactions(
                    db=session,
                    limit=limit,
                    offset=offset,
                    master_project=master_project,
                    property_type=property_type,
                    rooms=rooms,
                    area_min=area_min,
                    area_max=area_max,
                    price_min=price_min,
                    price_max=price_max,
                )
                return result.model_dump()

        @self.mcp.tool()
        async def search_rental_contracts(
            limit: int = 50,
            offset: int = 0,
            master_project: Optional[str] = None,
            property_type: Optional[str] = None,
            property_sub_type: Optional[str] = None,
            area_min: Optional[float] = None,
            area_max: Optional[float] = None,
            rent_min: Optional[float] = None,
            rent_max: Optional[float] = None,
        ) -> Dict[str, Any]:
            """Search rental contracts with filters. Returns paginated list of rental contracts with details like project, rent amount, area, bedroom count, etc.

            Rental bedroom data is stored in the property_sub_type field with formats like:
            - "1bed room+Hall", "2 bed rooms+hall", "3 bed rooms+hall", "4 bed rooms+hall", etc.
            - "Studio" for studio apartments

            Use property_sub_type to filter by specific bedroom counts (e.g., "2 bed rooms+hall" for 2BR units).

            Args:
                limit: Number of results to return (max 500)
                offset: Pagination offset
                master_project: Filter by master project name (e.g., "Mulberry", "Dubai Marina")
                property_type: Filter by general property type (e.g., "Flat", "Villa")
                property_sub_type: Filter by bedroom count (e.g., "2 bed rooms+hall", "3 bed rooms+hall", "Studio")
                area_min: Minimum property area in sqft
                area_max: Maximum property area in sqft
                rent_min: Minimum annual rent in AED
                rent_max: Maximum annual rent in AED
            """
            from backend.app.services.transactions_service import fetch_rental_contracts
            from backend.app.db.session import async_session

            async with async_session() as session:
                result = await fetch_rental_contracts(
                    db=session,
                    limit=limit,
                    offset=offset,
                    master_project=master_project,
                    property_type=property_type,
                    property_sub_type=property_sub_type,
                    area_min=area_min,
                    area_max=area_max,
                    rent_min=rent_min,
                    rent_max=rent_max,
                )
                return result.model_dump()

        # Supply Tools
        @self.mcp.tool()
        async def get_developers(
            sort_by: str = "projects", limit: int = 50, offset: int = 0
        ) -> Dict[str, Any]:
            """Get list of developers with their projects and statistics.

            Args:
                sort_by: Sort by 'projects', 'transactions', or 'avg_price'
                limit: Number of results to return
                offset: Pagination offset
            """
            from backend.app.services.supply_service import (
                get_all_developers,
                get_developer_stats_bulk,
            )
            from backend.app.db.session import async_session

            async with async_session() as session:
                developers = await get_all_developers(session, sort_by, limit, offset)
                dev_ids = [d.developer_id for d in developers]
                stats_map = await get_developer_stats_bulk(session, dev_ids)

                result = []
                for dev in developers:
                    stats = stats_map.get(dev.developer_id, {})
                    result.append(
                        {
                            "developer_id": dev.developer_id,
                            "developer_name": dev.developer_name_en,
                            "phone": dev.phone,
                            "webpage": dev.webpage,
                            **stats,
                        }
                    )
                return {"developers": result, "total": len(result)}

        @self.mcp.tool()
        async def get_project_details(project_id: int) -> Dict[str, Any]:
            """Get detailed information about a specific real estate project.

            Args:
                project_id: The project ID to look up
            """
            from backend.app.services.supply_service import get_project_by_id
            from backend.app.db.session import async_session

            async with async_session() as session:
                project = await get_project_by_id(session, project_id)
                if not project:
                    return {"error": "Project not found"}
                return project.model_dump()

        # Filter Tools
        @self.mcp.tool()
        async def get_available_master_projects() -> List[str]:
            """Get list of all available master projects for filtering. Useful for understanding what master projects exist in the database."""
            from backend.app.services.filters_service import get_distinct_values
            from backend.app.db.models.transactions import Transaction
            from backend.app.db.session import async_session

            async with async_session() as session:
                return await get_distinct_values(
                    session, Transaction.master_project_en, []
                )

        @self.mcp.tool()
        async def get_sales_filter_options(
            master_project: Optional[str] = None, property_type: Optional[str] = None
        ) -> Dict[str, Any]:
            """Get available filter options for sales transactions based on current filters. Returns lists of available property types, rooms, buildings, etc. Useful for building dynamic filter UIs or understanding data distribution.

            Args:
                master_project: Filter context by master project
                property_type: Filter context by property type
            """
            from backend.app.services.filters_service import fetch_sales_filter_options
            from backend.app.db.session import async_session

            async with async_session() as session:
                result = await fetch_sales_filter_options(
                    session=session,
                    master_project=master_project,
                    property_type=property_type,
                )
                return result.model_dump()

    async def get_tools_for_llm(self) -> List[Dict[str, Any]]:
        """Convert MCP tools to OpenAI function calling format"""
        tools = []
        mcp_tools = await self.mcp.get_tools()
        # get_tools() returns a dict of {tool_name: FunctionTool}
        for tool_name, tool in mcp_tools.items():
            tools.append(
                {
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": tool.description,
                        "parameters": tool.parameters,
                    },
                }
            )
        return tools

    async def execute_tool(
        self, tool_name: str, arguments: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Execute a tool by name with given arguments"""
        try:
            tool = await self.mcp.get_tool(tool_name)
            if not tool:
                return {"success": False, "error": f"Tool not found: {tool_name}"}

            result = await tool.run(arguments)

            # Extract content from ToolResult
            # ToolResult.content is a list of TextContent objects
            if result.content and len(result.content) > 0:
                text_content = result.content[0].text
                # The text is a JSON string, parse it
                parsed_result = json.loads(text_content)
                return {"success": True, "result": parsed_result}
            else:
                return {"success": False, "error": "No content in tool result"}
        except Exception as e:
            logger.exception(f"Tool execution failed: {tool_name}")
            return {"success": False, "error": str(e)}


# Global registry instance
mcp_registry = MCPToolRegistry()
