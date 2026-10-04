import unittest
from mcp_servers.common.validator import TableQueryInput, ReadQueryInput


class TestMCPValidation(unittest.TestCase):
    def test_table_name_validation(self):
        # Valid table names
        self.assertEqual(TableQueryInput(table_name="users").table_name, "users")
        self.assertEqual(TableQueryInput(table_name="orders_2026").table_name, "orders_2026")
        self.assertIsNone(TableQueryInput(table_name=None).table_name)
        self.assertIsNone(TableQueryInput(table_name="   ").table_name)

        # Invalid table names
        with self.assertRaises(Exception):
            TableQueryInput(table_name="users; DROP TABLE users;")

        with self.assertRaises(Exception):
            TableQueryInput(table_name="orders--comment")

    def test_read_only_query_allowed(self):
        valid_queries = [
            "SELECT * FROM customers",
            "SELECT id, name, created_at FROM orders WHERE status = 'COMPLETED'",
            "WITH RankedOrders AS (SELECT id, ROW_NUMBER() OVER (ORDER BY id) as rn FROM orders) SELECT * FROM RankedOrders WHERE rn <= 10",
            "select count(1) from inventory",
        ]
        for q in valid_queries:
            validated = ReadQueryInput(query=q)
            self.assertIsNotNone(validated.query)

    def test_mutating_queries_forbidden(self):
        blocked_queries = [
            "INSERT INTO users (name) VALUES ('hacker')",
            "UPDATE users SET role = 'admin'",
            "DELETE FROM users WHERE id = 1",
            "DROP TABLE users",
            "ALTER TABLE users ADD COLUMN is_admin bit",
            "CREATE TABLE test (id int)",
            "TRUNCATE TABLE logs",
            "EXEC sp_executesql N'SELECT 1'",
            "EXECUTE xp_cmdshell 'dir'",
            "SELECT * INTO new_table FROM old_table",
            "GRANT ALL PRIVILEGES ON users TO public",
            "MERGE INTO target USING source ON target.id = source.id WHEN MATCHED THEN UPDATE SET target.val = source.val",
            "SELECT * FROM users; DROP TABLE users;",
        ]
        for q in blocked_queries:
            with self.assertRaises(Exception):
                ReadQueryInput(query=q)


if __name__ == "__main__":
    unittest.main()
