-- ============================================================================
-- Migration: db_01_erp.sql
-- Database: db-01-dev (ERP - Enterprise Resource Planning)
-- Target Server: eosr-db-server.database.windows.net
-- Domain: Commercial System of Record, Financial Asset Valuation, Order Entry
-- Conventions: Legacy tbl_* prefixes, PascalCase/Hungarian columns, text statuses
-- Decoupling: Autonomous database. NO cross-database foreign keys.
-- ============================================================================

-- ----------------------------------------------------------------------------
-- 1. Idempotent Teardown (Child to Parent)
-- ----------------------------------------------------------------------------
IF OBJECT_ID('dbo.tbl_OrderLineItems', 'U') IS NOT NULL
    DROP TABLE dbo.tbl_OrderLineItems;
GO

IF OBJECT_ID('dbo.tbl_SalesOrders', 'U') IS NOT NULL
    DROP TABLE dbo.tbl_SalesOrders;
GO

IF OBJECT_ID('dbo.tbl_Inventory_Master', 'U') IS NOT NULL
    DROP TABLE dbo.tbl_Inventory_Master;
GO

IF OBJECT_ID('dbo.tbl_Customers', 'U') IS NOT NULL
    DROP TABLE dbo.tbl_Customers;
GO

-- ----------------------------------------------------------------------------
-- 2. DDL Schema Definition
-- ----------------------------------------------------------------------------

-- Table 1: Customers Master
CREATE TABLE dbo.tbl_Customers (
    Cust_ID VARCHAR(20) NOT NULL PRIMARY KEY,
    Cust_Name NVARCHAR(100) NOT NULL,
    Account_Type VARCHAR(30) NOT NULL,          -- 'ENTERPRISE_TIER_1', 'SMB_STANDARD'
    Billing_Address NVARCHAR(255) NOT NULL,
    Shipping_Address NVARCHAR(255) NOT NULL,
    Credit_Limit_USD DECIMAL(18, 2) NOT NULL,
    Payment_Terms VARCHAR(30) NOT NULL,         -- 'NET 30', 'NET 60', 'IMMEDIATE'
    Created_Date DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME()
);
GO

-- Table 2: Inventory Catalog Master (Financial & Logical Balances Only)
CREATE TABLE dbo.tbl_Inventory_Master (
    Item_SKU VARCHAR(50) NOT NULL PRIMARY KEY,
    Item_Description NVARCHAR(200) NOT NULL,
    Product_Category VARCHAR(50) NOT NULL,
    Unit_Cost_USD DECIMAL(18, 2) NOT NULL,
    List_Price_USD DECIMAL(18, 2) NOT NULL,
    Qty_On_Hand INT NOT NULL,                   -- Logical total in warehouse
    Qty_Allocated INT NOT NULL,                 -- Committed to open orders
    GL_Asset_Account VARCHAR(30) NOT NULL       -- General Ledger asset account
);
GO

-- Table 3: Sales Orders Header
CREATE TABLE dbo.tbl_SalesOrders (
    Order_ID VARCHAR(30) NOT NULL PRIMARY KEY,
    Cust_ID VARCHAR(20) NOT NULL REFERENCES dbo.tbl_Customers(Cust_ID),
    Order_Date DATETIME2 NOT NULL,
    PO_Number VARCHAR(50) NOT NULL,             -- Customer purchase order reference
    OrderStatus VARCHAR(30) NOT NULL,           -- 'Completed', 'Processing', 'On Hold', 'Cancelled'
    Payment_Status VARCHAR(30) NOT NULL,         -- 'Paid', 'Invoiced', 'Pending', 'Refunded'
    Subtotal_Amount DECIMAL(18, 2) NOT NULL,
    Tax_Amount DECIMAL(18, 2) NOT NULL,
    Shipping_Fee DECIMAL(18, 2) NOT NULL,
    Total_Amount DECIMAL(18, 2) NOT NULL,
    Currency_Code VARCHAR(3) NOT NULL DEFAULT 'USD',
    Internal_Notes NVARCHAR(255) NULL
);
GO

-- Table 4: Order Line Items Detail
CREATE TABLE dbo.tbl_OrderLineItems (
    Line_ID INT IDENTITY(1,1) NOT NULL PRIMARY KEY,
    Order_ID VARCHAR(30) NOT NULL REFERENCES dbo.tbl_SalesOrders(Order_ID),
    Line_Num INT NOT NULL,
    Item_SKU VARCHAR(50) NOT NULL REFERENCES dbo.tbl_Inventory_Master(Item_SKU),
    Quantity INT NOT NULL,
    Unit_Price DECIMAL(18, 2) NOT NULL,
    Extended_Price DECIMAL(18, 2) NOT NULL,
    Line_Status VARCHAR(30) NOT NULL            -- 'FULFILLED', 'PROCESSING', 'CANCELLED'
);
GO

-- ----------------------------------------------------------------------------
-- 3. DML Seed Data
-- ----------------------------------------------------------------------------

-- Seed Customers
INSERT INTO dbo.tbl_Customers 
    (Cust_ID, Cust_Name, Account_Type, Billing_Address, Shipping_Address, Credit_Limit_USD, Payment_Terms, Created_Date)
VALUES 
    ('CUST-00101', N'Acme Corp', 'ENTERPRISE_TIER_1', N'100 Industrial Parkway, Austin, TX 78701', N'100 Industrial Parkway, Dock 2, Austin, TX 78701', 500000.00, 'NET 30', '2025-01-15T08:00:00'),
    ('CUST-00202', N'Globex Corporation', 'ENTERPRISE_TIER_1', N'742 Evergreen Terrace, Springfield, OR 97477', N'742 Evergreen Terrace, Springfield, OR 97477', 1000000.00, 'NET 30', '2025-02-01T09:30:00'),
    ('CUST-00303', N'Umbrella Corporation', 'ENTERPRISE_TIER_2', N'400 Raccoon Way, Arklay, CO 80424', N'400 Raccoon Way, Arklay, CO 80424', 250000.00, 'NET 60', '2025-03-10T11:15:00'),
    ('CUST-00404', N'Initech LLC', 'SMB_STANDARD', N'4120 Freemont Blvd, Dallas, TX 75201', N'4120 Freemont Blvd, Dallas, TX 75201', 50000.00, 'NET 30', '2025-04-18T14:00:00'),
    ('CUST-00505', N'Cyberdyne Systems', 'ENTERPRISE_TIER_1', N'18144 El Camino Real, Sunnyvale, CA 94086', N'18144 El Camino Real, Sunnyvale, CA 94086', 750000.00, 'NET 30', '2025-05-22T10:45:00');
GO

-- Seed Inventory Master
INSERT INTO dbo.tbl_Inventory_Master 
    (Item_SKU, Item_Description, Product_Category, Unit_Cost_USD, List_Price_USD, Qty_On_Hand, Qty_Allocated, GL_Asset_Account)
VALUES
    ('SKU-LAPTOP-15-ENT', N'Enterprise Laptop 15-inch (Intel i7, 32GB RAM, 1TB SSD)', 'Hardware / Computing', 1200.00, 1850.00, 145, 52, '1400-FINISHED-GOODS'),
    ('SKU-CHAIR-ERG-01', N'Ergonomic Office Chair (High Back, Lumbar Support)', 'Office / Furniture', 180.00, 350.00, 80, 4, '1420-OFFICE-SUPPLIES'),
    ('SKU-MONITOR-27-UHD', N'Ultra-HD Monitor 27-inch (4K, IPS, USB-C)', 'Hardware / Displays', 260.00, 450.00, 210, 8, '1400-FINISHED-GOODS'),
    ('SKU-SERVER-RACK-2U', N'Enterprise Server Rack Unit 2U Dual Xeon', 'Hardware / Servers', 4500.00, 7200.00, 15, 0, '1450-CAPITAL-EQUIP');
GO

-- Seed Sales Orders Header
-- Covers TARGET (SO-10045) and Distractors DIST-1 through DIST-6
INSERT INTO dbo.tbl_SalesOrders 
    (Order_ID, Cust_ID, Order_Date, PO_Number, OrderStatus, Payment_Status, Subtotal_Amount, Tax_Amount, Shipping_Fee, Total_Amount, Currency_Code, Internal_Notes)
VALUES
    -- TARGET: Acme Corp Laptop Order (Completed in ERP, Shipped)
    ('SO-10045', 'CUST-00101', '2026-10-02T09:15:00', 'PO-ACM-2026-9921', 'Completed', 'Paid', 18500.00, 1480.00, 250.00, 20230.00, 'USD', N'Priority shipment for Q4 engineering team expansion'),

    -- DIST-1: Acme Corp Ergonomic Chairs (Wrong Product trap - Still processing)
    ('SO-10046', 'CUST-00101', '2026-10-03T11:00:00', 'PO-ACM-2026-9922', 'Processing', 'Invoiced', 1400.00, 112.00, 80.00, 1592.00, 'USD', N'Facilities department request'),

    -- DIST-2: Globex Corp Laptops (Wrong Customer trap - Shipped & Delivered to Globex)
    ('SO-10047', 'CUST-00202', '2026-10-01T14:30:00', 'PO-GLX-2026-1104', 'Completed', 'Paid', 46250.00, 3700.00, 500.00, 50450.00, 'USD', N'Annual sales fleet refresh'),

    -- DIST-3: Acme Corp Cancelled Order (Cancelled Order trap - Historical void)
    ('SO-10012', 'CUST-00101', '2026-09-15T08:00:00', 'PO-ACM-2026-8801', 'Cancelled', 'Refunded', 9250.00, 740.00, 0.00, 9990.00, 'USD', N'Customer requested order cancellation prior to fulfillment'),

    -- DIST-4: Acme Corp Laptops Staged (Staged at Dock trap - Processing, NOT shipped)
    ('SO-10048', 'CUST-00101', '2026-10-04T08:30:00', 'PO-ACM-2026-9930', 'Processing', 'Invoiced', 3700.00, 296.00, 100.00, 4096.00, 'USD', N'Branch office expedited requirement'),

    -- DIST-5: Umbrella Corp Laptops (Allocated Only trap - Processing, not picked)
    ('SO-10049', 'CUST-00303', '2026-10-04T10:00:00', 'PO-UMB-2026-4401', 'Processing', 'Authorized', 27750.00, 2220.00, 350.00, 30320.00, 'USD', N'Underwriting review passed'),

    -- DIST-6: Initech LLC Monitors (Background traffic trap - Completed & Dispatched)
    ('SO-10050', 'CUST-00404', '2026-10-02T13:00:00', 'PO-INI-2026-0091', 'Completed', 'Paid', 3600.00, 288.00, 120.00, 4008.00, 'USD', N'Standard hardware delivery');
GO

-- Seed Order Line Items
INSERT INTO dbo.tbl_OrderLineItems 
    (Order_ID, Line_Num, Item_SKU, Quantity, Unit_Price, Extended_Price, Line_Status)
VALUES
    -- TARGET: Acme Corp Laptops (10 units @ $1850)
    ('SO-10045', 1, 'SKU-LAPTOP-15-ENT', 10, 1850.00, 18500.00, 'FULFILLED'),

    -- DIST-1: Acme Corp Chairs (4 units @ $350)
    ('SO-10046', 1, 'SKU-CHAIR-ERG-01', 4, 350.00, 1400.00, 'PROCESSING'),

    -- DIST-2: Globex Corp Laptops (25 units @ $1850)
    ('SO-10047', 1, 'SKU-LAPTOP-15-ENT', 25, 1850.00, 46250.00, 'FULFILLED'),

    -- DIST-3: Acme Corp Cancelled Laptops (5 units @ $1850)
    ('SO-10012', 1, 'SKU-LAPTOP-15-ENT', 5, 1850.00, 9250.00, 'CANCELLED'),

    -- DIST-4: Acme Corp Staged Laptops (2 units @ $1850)
    ('SO-10048', 1, 'SKU-LAPTOP-15-ENT', 2, 1850.00, 3700.00, 'PROCESSING'),

    -- DIST-5: Umbrella Corp Allocated Laptops (15 units @ $1850)
    ('SO-10049', 1, 'SKU-LAPTOP-15-ENT', 15, 1850.00, 27750.00, 'PROCESSING'),

    -- DIST-6: Initech LLC Monitors (8 units @ $450)
    ('SO-10050', 1, 'SKU-MONITOR-27-UHD', 8, 450.00, 3600.00, 'FULFILLED');
GO
