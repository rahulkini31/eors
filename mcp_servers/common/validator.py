"""Input validation and strict protocol-level read-only query guardrails using Pydantic v2."""

import re
from typing import Optional
from pydantic import BaseModel, Field, field_validator


class TableQueryInput(BaseModel):
    """Schema for querying table metadata."""
    table_name: Optional[str] = Field(
        default=None,
        description="Optional table name to filter schema. Must contain only alphanumeric characters or underscores.",
        max_length=128
    )

    @field_validator("table_name")
    @classmethod
    def validate_table_name(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            v = v.strip()
            if not v:
                return None
            if not re.match(r"^[A-Za-z0-9_]+$", v):
                raise ValueError("Invalid table name. Only alphanumeric characters and underscores are allowed.")
        return v


class ReadQueryInput(BaseModel):
    """Schema for executing read-only SQL queries."""
    query: str = Field(
        ...,
        description="SQL SELECT query to execute.",
        min_length=1,
        max_length=10000
    )
    max_rows: int = Field(
        default=100,
        description="Maximum number of rows to return (between 1 and 1000).",
        ge=1,
        le=1000
    )

    @field_validator("query")
    @classmethod
    def validate_read_only_query(cls, v: str) -> str:
        cleaned = v.strip()
        if not cleaned:
            raise ValueError("Query cannot be empty.")

        # Strip standard SQL comments to prevent evasion
        cleaned_no_comments = re.sub(r"--[^\n]*", "", cleaned)
        cleaned_no_comments = re.sub(r"/\*[\s\S]*?\*/", "", cleaned_no_comments).strip()

        if not cleaned_no_comments:
            raise ValueError("Query contains no executable statements.")

        # Multiple statements check (semicolon followed by non-whitespace)
        statements = [s.strip() for s in cleaned_no_comments.split(";") if s.strip()]
        if len(statements) > 1:
            raise ValueError("Multiple SQL statements in a single query are forbidden.")

        single_query = statements[0]

        # Check that query starts with SELECT or WITH
        if not re.match(r"^(SELECT|WITH)\b", single_query, re.IGNORECASE):
            raise ValueError("Protocol restriction: Only SELECT or CTE (WITH ... SELECT) queries are allowed.")

        # Prohibited mutating / DDL / DML / administrative keywords
        forbidden_patterns = [
            r"\bINSERT\b",
            r"\bUPDATE\b",
            r"\bDELETE\b",
            r"\bDROP\b",
            r"\bALTER\b",
            r"\bCREATE\b",
            r"\bTRUNCATE\b",
            r"\bEXEC\b",
            r"\bEXECUTE\b",
            r"\bGRANT\b",
            r"\bREVOKE\b",
            r"\bDENY\b",
            r"\bMERGE\b",
            r"\bBACKUP\b",
            r"\bRESTORE\b",
            r"\bSHUTDOWN\b",
            r"\bINTO\b",           # Prevents SELECT INTO table
            r"\bBULK\b",
            r"\bOPENROWSET\b",
            r"\bOPENDATASOURCE\b",
            r"\bXP_\w+",
            r"\bSP_\w+",
        ]

        for pattern in forbidden_patterns:
            if re.search(pattern, single_query, re.IGNORECASE):
                matched = re.search(pattern, single_query, re.IGNORECASE).group()
                raise ValueError(f"Protocol restriction: Prohibited keyword or command detected ('{matched}'). Only read queries are permitted.")

        return single_query
