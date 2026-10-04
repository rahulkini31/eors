"""Configuration settings for the Multi-Agent Framework and MCP Servers."""

import os
from typing import Dict

# MCP Server Base URLs (Azure Container Apps live endpoints)
MCP_SERVERS: Dict[str, Dict[str, str]] = {
    "ERP": {
        "name": "mcp_db_01",
        "domain": "Enterprise Resource Planning (Commercial / Orders)",
        "base_url": os.environ.get(
            "MCP_ERP_URL",
            "https://mcp-db-01.agreeablemeadow-194f1f73.southeastasia.azurecontainerapps.io"
        ),
        "sse_endpoint": "/sse",
        "health_endpoint": "/health"
    },
    "WMS": {
        "name": "mcp_db_02",
        "domain": "Warehouse Management System (Physical Execution / Bins)",
        "base_url": os.environ.get(
            "MCP_WMS_URL",
            "https://mcp-db-02.agreeablemeadow-194f1f73.southeastasia.azurecontainerapps.io"
        ),
        "sse_endpoint": "/sse",
        "health_endpoint": "/health"
    },
    "TMS": {
        "name": "mcp_db_03",
        "domain": "Transportation Management System (Freight / Carriers)",
        "base_url": os.environ.get(
            "MCP_TMS_URL",
            "https://mcp-db-03.agreeablemeadow-194f1f73.southeastasia.azurecontainerapps.io"
        ),
        "sse_endpoint": "/sse",
        "health_endpoint": "/health"
    }
}

# Google Gemini Model Configuration
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY", "")
GEMINI_MODEL_ID = os.environ.get("GEMINI_MODEL_ID", "gemini-2.5-flash")
