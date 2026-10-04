-- ============================================================================
-- Migration: db_02_wms.sql
-- Database: db-02-dev (WMS - Warehouse Management System)
-- Target Server: eosr-db-server.database.windows.net
-- Domain: Physical Warehouse Execution, Bin Tracking, LPN Handling Units
-- Conventions: Modern snake_case tables & columns, integer status_id codes
-- Decoupling: Autonomous database. NO cross-database foreign keys.
-- External References: erp_order_ref ('SO-10045'), customer_po_ref ('PO-ACM-2026-9921')
-- ============================================================================

-- ----------------------------------------------------------------------------
-- 1. Idempotent Teardown (Child to Parent)
-- ----------------------------------------------------------------------------
IF OBJECT_ID('dbo.outbound_picks', 'U') IS NOT NULL
    DROP TABLE dbo.outbound_picks;
GO

IF OBJECT_ID('dbo.handling_units', 'U') IS NOT NULL
    DROP TABLE dbo.handling_units;
GO

IF OBJECT_ID('dbo.inventory_lots', 'U') IS NOT NULL
    DROP TABLE dbo.inventory_lots;
GO

IF OBJECT_ID('dbo.dock_doors', 'U') IS NOT NULL
    DROP TABLE dbo.dock_doors;
GO

IF OBJECT_ID('dbo.bin_locations', 'U') IS NOT NULL
    DROP TABLE dbo.bin_locations;
GO

-- ----------------------------------------------------------------------------
-- 2. DDL Schema Definition
-- ----------------------------------------------------------------------------

-- Table 1: Warehouse Bin Locations
CREATE TABLE dbo.bin_locations (
    bin_id INT IDENTITY(1,1) NOT NULL PRIMARY KEY,
    bin_code VARCHAR(30) NOT NULL UNIQUE,       -- e.g. 'Z1-A04-S02-B01'
    zone_code VARCHAR(20) NOT NULL,             -- e.g. 'ZONE-TECH-MEZZ'
    aisle_num INT NOT NULL,
    shelf_level VARCHAR(10) NOT NULL,
    max_weight_kg DECIMAL(10, 2) NOT NULL,
    is_active BIT NOT NULL DEFAULT 1
);
GO

-- Table 2: Dock Doors and Staging Bays
CREATE TABLE dbo.dock_doors (
    dock_door_id INT IDENTITY(1,1) NOT NULL PRIMARY KEY,
    dock_code VARCHAR(20) NOT NULL UNIQUE,      -- e.g. 'DOCK-04', 'DOCK-07'
    door_status VARCHAR(20) NOT NULL,            -- 'ACTIVE', 'MAINTENANCE'
    assigned_staging_bay VARCHAR(30) NOT NULL
);
GO

-- Table 3: Physical Inventory Lots (Quality & Production Traceability)
CREATE TABLE dbo.inventory_lots (
    lot_id INT IDENTITY(1,1) NOT NULL PRIMARY KEY,
    lot_number VARCHAR(40) NOT NULL UNIQUE,
    sku_code VARCHAR(50) NOT NULL,
    manufactured_date DATE NOT NULL,
    expiration_date DATE NULL,
    qa_status VARCHAR(20) NOT NULL              -- 'PASSED', 'QUARANTINE'
);
GO

-- Table 4: Handling Units / LPN Containers (Pallets, Cartons, Totes)
CREATE TABLE dbo.handling_units (
    hu_id VARCHAR(40) NOT NULL PRIMARY KEY,     -- e.g. 'HU-8841-PLT'
    lpn_barcode VARCHAR(60) NOT NULL UNIQUE,    -- e.g. 'BC-LPN-8841029'
    hu_type VARCHAR(20) NOT NULL,               -- 'PALLET', 'CARTON', 'TOTE'
    tare_weight_kg DECIMAL(10, 2) NOT NULL,
    staged_dock_code VARCHAR(20) NULL REFERENCES dbo.dock_doors(dock_code),
    created_at DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME()
);
GO

-- Table 5: Outbound Picks (Physical Execution Tasks)
-- Status Code System:
--   1: Allocated (Reserved in wave, pending picker assignment)
--   2: Picked (Items retrieved from bin onto picker cart)
--   3: Packed (Verified and packed into handling unit)
--   4: Staged at Dock (Positioned at shipping staging lane)
--   5: Loaded (Scanned and loaded into carrier trailer)
--   9: Cancelled (Voided or restocked)
CREATE TABLE dbo.outbound_picks (
    pick_id VARCHAR(40) NOT NULL PRIMARY KEY,
    erp_order_ref VARCHAR(50) NOT NULL,         -- Loose reference to ERP Order_ID
    customer_po_ref VARCHAR(50) NULL,           -- Loose reference to ERP PO_Number
    sku_code VARCHAR(50) NOT NULL,
    lot_number VARCHAR(40) NOT NULL,
    bin_code VARCHAR(30) NOT NULL,
    handling_unit_id VARCHAR(40) NULL REFERENCES dbo.handling_units(hu_id),
    qty_requested INT NOT NULL,
    qty_picked INT NOT NULL,
    status_id INT NOT NULL,                     -- 1=Allocated, 2=Picked, 3=Packed, 4=Staged, 5=Loaded, 9=Cancelled
    picker_badge_id VARCHAR(20) NULL,
    pick_completed_at DATETIME2 NULL,
    dock_loaded_at DATETIME2 NULL
);
GO

-- ----------------------------------------------------------------------------
-- 3. DML Seed Data
-- ----------------------------------------------------------------------------

-- Seed Warehouse Bin Locations
INSERT INTO dbo.bin_locations 
    (bin_code, zone_code, aisle_num, shelf_level, max_weight_kg, is_active)
VALUES
    ('Z1-A04-S02-B01', 'ZONE-TECH-MEZZ', 4, 'B-02', 500.00, 1),
    ('Z1-A04-S02-B02', 'ZONE-TECH-MEZZ', 4, 'B-02', 500.00, 1),
    ('Z2-B12-S01-B04', 'ZONE-FURN-BULK', 12, 'B-01', 1200.00, 1),
    ('Z1-A08-S03-B01', 'ZONE-DISP-MAIN', 8, 'B-03', 600.00, 1);
GO

-- Seed Dock Doors
INSERT INTO dbo.dock_doors 
    (dock_code, door_status, assigned_staging_bay)
VALUES
    ('DOCK-04', 'ACTIVE', 'STAGE-BAY-NORTH-04'),
    ('DOCK-07', 'ACTIVE', 'STAGE-BAY-NORTH-07'),
    ('DOCK-12', 'ACTIVE', 'STAGE-BAY-SOUTH-12');
GO

-- Seed Inventory Lots
INSERT INTO dbo.inventory_lots 
    (lot_number, sku_code, manufactured_date, expiration_date, qa_status)
VALUES
    ('LOT-2026Q1-TECH', 'SKU-LAPTOP-15-ENT', '2026-01-15', NULL, 'PASSED'),
    ('LOT-2026Q2-FURN', 'SKU-CHAIR-ERG-01', '2026-02-20', NULL, 'PASSED'),
    ('LOT-2026Q1-DISP', 'SKU-MONITOR-27-UHD', '2026-01-10', NULL, 'PASSED');
GO

-- Seed Handling Units
INSERT INTO dbo.handling_units 
    (hu_id, lpn_barcode, hu_type, tare_weight_kg, staged_dock_code, created_at)
VALUES
    ('HU-8841-PLT', 'BC-LPN-8841029', 'PALLET', 22.00, 'DOCK-04', '2026-10-03T10:00:00'),
    ('HU-8842-BOX', 'BC-LPN-8842041', 'CARTON', 1.50, NULL, '2026-10-04T08:30:00'),
    ('HU-8843-PLT', 'BC-LPN-8843055', 'PALLET', 25.00, 'DOCK-04', '2026-10-02T11:00:00'),
    ('HU-8844-PLT', 'BC-LPN-8844091', 'PALLET', 18.00, 'DOCK-07', '2026-10-04T09:15:00'),
    ('HU-8845-PLT', 'BC-LPN-8845012', 'PALLET', 20.00, 'DOCK-04', '2026-10-03T12:00:00');
GO

-- Seed Outbound Picks
-- Covers TARGET (SO-10045) and Distractors DIST-1 through DIST-6
INSERT INTO dbo.outbound_picks 
    (pick_id, erp_order_ref, customer_po_ref, sku_code, lot_number, bin_code, handling_unit_id, qty_requested, qty_picked, status_id, picker_badge_id, pick_completed_at, dock_loaded_at)
VALUES
    -- TARGET: Acme Corp Laptop -> Picked, packed, loaded onto carrier trailer (status_id = 5)
    ('PK-8801', 'SO-10045', 'PO-ACM-2026-9921', 'SKU-LAPTOP-15-ENT', 'LOT-2026Q1-TECH', 'Z1-A04-S02-B01', 'HU-8841-PLT', 10, 10, 5, 'BADGE-304', '2026-10-03T14:20:00', '2026-10-04T10:45:00'),

    -- DIST-1: Acme Corp Chairs -> Picked on warehouse cart, not packed or staged (status_id = 2)
    ('PK-8802', 'SO-10046', 'PO-ACM-2026-9922', 'SKU-CHAIR-ERG-01', 'LOT-2026Q2-FURN', 'Z2-B12-S01-B04', 'HU-8842-BOX', 4, 4, 2, 'BADGE-211', '2026-10-04T09:10:00', NULL),

    -- DIST-2: Globex Corp Laptops -> Loaded onto Swift trailer (status_id = 5)
    ('PK-8803', 'SO-10047', 'PO-GLX-2026-1104', 'SKU-LAPTOP-15-ENT', 'LOT-2026Q1-TECH', 'Z1-A04-S02-B01', 'HU-8843-PLT', 25, 25, 5, 'BADGE-119', '2026-10-02T16:00:00', '2026-10-03T11:15:00'),

    -- DIST-3: Cancelled Acme Laptop order -> Cancelled pick, no HU (status_id = 9)
    ('PK-8750', 'SO-10012', 'PO-ACM-2026-8801', 'SKU-LAPTOP-15-ENT', 'LOT-2026Q1-TECH', 'Z1-A04-S02-B01', NULL, 5, 0, 9, NULL, NULL, NULL),

    -- DIST-4: Acme Corp Laptops Staged at Dock 7 -> Staged, NOT loaded (status_id = 4)
    ('PK-8804', 'SO-10048', 'PO-ACM-2026-9930', 'SKU-LAPTOP-15-ENT', 'LOT-2026Q1-TECH', 'Z1-A04-S02-B02', 'HU-8844-PLT', 2, 2, 4, 'BADGE-304', '2026-10-04T10:00:00', NULL),

    -- DIST-5: Umbrella Corp Laptops -> Allocated only, pending pick wave (status_id = 1)
    ('PK-8805', 'SO-10049', 'PO-UMB-2026-4401', 'SKU-LAPTOP-15-ENT', 'LOT-2026Q1-TECH', 'Z1-A04-S02-B01', NULL, 15, 0, 1, NULL, NULL, NULL),

    -- DIST-6: Initech Monitors -> Loaded onto Apex trailer (status_id = 5)
    ('PK-8806', 'SO-10050', 'PO-INI-2026-0091', 'SKU-MONITOR-27-UHD', 'LOT-2026Q1-DISP', 'Z1-A08-S03-B01', 'HU-8845-PLT', 8, 8, 5, 'BADGE-402', '2026-10-03T15:30:00', '2026-10-04T08:15:00');
GO
