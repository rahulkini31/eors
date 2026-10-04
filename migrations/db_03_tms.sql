-- ============================================================================
-- Migration: db_03_tms.sql
-- Database: db-03-dev (TMS - Transportation Management System)
-- Target Server: eosr-db-server.database.windows.net
-- Domain: Logistics Routing, Freight Loads, BOLs, Carrier Manifests
-- Conventions: Logistics industry PascalCase / Upper_Snake_Case naming
-- Decoupling: Autonomous database. NO cross-database foreign keys.
-- External References: Handling_Unit_Ref ('HU-8841-PLT')
-- ============================================================================

-- ----------------------------------------------------------------------------
-- 1. Idempotent Teardown (Child to Parent)
-- ----------------------------------------------------------------------------
IF OBJECT_ID('dbo.Carrier_Manifests', 'U') IS NOT NULL
    DROP TABLE dbo.Carrier_Manifests;
GO

IF OBJECT_ID('dbo.Bill_Of_Lading', 'U') IS NOT NULL
    DROP TABLE dbo.Bill_Of_Lading;
GO

IF OBJECT_ID('dbo.Freight_Loads', 'U') IS NOT NULL
    DROP TABLE dbo.Freight_Loads;
GO

IF OBJECT_ID('dbo.Carrier_Master', 'U') IS NOT NULL
    DROP TABLE dbo.Carrier_Master;
GO

-- ----------------------------------------------------------------------------
-- 2. DDL Schema Definition
-- ----------------------------------------------------------------------------

-- Table 1: Carrier Master (Contracted Freight Carriers)
CREATE TABLE dbo.Carrier_Master (
    Carrier_ID VARCHAR(20) NOT NULL PRIMARY KEY,
    Carrier_Name VARCHAR(100) NOT NULL,
    SCAC_Code VARCHAR(10) NOT NULL,              -- Standard Carrier Alpha Code
    Service_Level VARCHAR(30) NOT NULL,          -- 'EXPEDITED_LTL', 'STANDARD_TRUCKLOAD', 'PRIORITY_GROUND'
    Contact_Phone VARCHAR(30) NOT NULL
);
GO

-- Table 2: Freight Loads (Trailer Shipments / Dispatches)
CREATE TABLE dbo.Freight_Loads (
    Load_ID VARCHAR(30) NOT NULL PRIMARY KEY,
    Carrier_ID VARCHAR(20) NOT NULL REFERENCES dbo.Carrier_Master(Carrier_ID),
    Trailer_Number VARCHAR(30) NOT NULL,
    Origin_Facility VARCHAR(50) NOT NULL,
    Total_Pallets INT NOT NULL,
    Total_Weight_LBS DECIMAL(10, 2) NOT NULL,
    Load_Status VARCHAR(30) NOT NULL,            -- 'DISPATCHED', 'STAGED', 'DELIVERED', 'PLANNED'
    Departure_Timestamp DATETIME2 NULL
);
GO

-- Table 3: Bill of Lading (Freight Contracts & Consignee Details)
CREATE TABLE dbo.Bill_Of_Lading (
    BOL_Number VARCHAR(40) NOT NULL PRIMARY KEY,
    Load_ID VARCHAR(30) NOT NULL REFERENCES dbo.Freight_Loads(Load_ID),
    Handling_Unit_Ref VARCHAR(40) NOT NULL,     -- Loose reference to WMS handling_units.hu_id
    Consignee_Name VARCHAR(100) NOT NULL,
    Delivery_Address VARCHAR(255) NOT NULL,
    Delivery_Zip VARCHAR(20) NOT NULL,
    Special_Instructions VARCHAR(255) NULL,
    Issued_Timestamp DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME()
);
GO

-- Table 4: Carrier Manifests (Shipment Tracking Lines)
CREATE TABLE dbo.Carrier_Manifests (
    Manifest_ID VARCHAR(40) NOT NULL PRIMARY KEY,
    BOL_Number VARCHAR(40) NOT NULL REFERENCES dbo.Bill_Of_Lading(BOL_Number),
    Carrier_ID VARCHAR(20) NOT NULL REFERENCES dbo.Carrier_Master(Carrier_ID),
    Handling_Unit_Ref VARCHAR(40) NOT NULL,     -- Loose reference to WMS handling_units.hu_id
    Tracking_Number VARCHAR(60) NOT NULL,
    Waybill_Number VARCHAR(60) NOT NULL,
    Carrier_Name VARCHAR(100) NOT NULL,
    Pallet_Count INT NOT NULL,
    Gross_Weight_LBS DECIMAL(10, 2) NOT NULL,
    Physical_Dimensions VARCHAR(50) NOT NULL,   -- e.g. '48x40x42 IN'
    Stop_Sequence INT NOT NULL,
    Shipment_Status VARCHAR(30) NOT NULL,       -- 'IN_TRANSIT', 'PENDING_PICKUP', 'DELIVERED', 'EXCEPTION'
    Dispatched_At DATETIME2 NULL,
    Estimated_Delivery DATETIME2 NULL
);
GO

-- ----------------------------------------------------------------------------
-- 3. DML Seed Data
-- ----------------------------------------------------------------------------

-- Seed Carrier Master
INSERT INTO dbo.Carrier_Master 
    (Carrier_ID, Carrier_Name, SCAC_Code, Service_Level, Contact_Phone)
VALUES
    ('CARR-APEX', 'Apex Freight Express', 'APEX', 'EXPEDITED_LTL', '+1-800-555-0199'),
    ('CARR-FXFE', 'FedEx Freight Regional', 'FXFE', 'PRIORITY_GROUND', '+1-800-555-0244'),
    ('CARR-SWFT', 'Swift Global Logistics', 'SWFT', 'STANDARD_TRUCKLOAD', '+1-800-555-0377');
GO

-- Seed Freight Loads
INSERT INTO dbo.Freight_Loads 
    (Load_ID, Carrier_ID, Trailer_Number, Origin_Facility, Total_Pallets, Total_Weight_LBS, Load_Status, Departure_Timestamp)
VALUES
    ('LD-2026-9041', 'CARR-APEX', 'TRL-8821-X', 'DISTRIBUTION-CENTER-WEST-1', 4, 3850.00, 'DISPATCHED', '2026-10-04T11:30:00'),
    ('LD-2026-9042', 'CARR-FXFE', 'TRL-4409-F', 'DISTRIBUTION-CENTER-WEST-1', 2, 1420.00, 'STAGED', NULL),
    ('LD-2026-8990', 'CARR-SWFT', 'TRL-7711-S', 'DISTRIBUTION-CENTER-WEST-1', 12, 18500.00, 'DELIVERED', '2026-10-03T12:00:00');
GO

-- Seed Bill of Lading
-- Covers TARGET (Acme Corp Shipped) and Distractors DIST-2, DIST-4, DIST-6
INSERT INTO dbo.Bill_Of_Lading 
    (BOL_Number, Load_ID, Handling_Unit_Ref, Consignee_Name, Delivery_Address, Delivery_Zip, Special_Instructions, Issued_Timestamp)
VALUES
    -- TARGET: Acme Corp Laptop Shipment (In Transit)
    ('BOL-2026-10045', 'LD-2026-9041', 'HU-8841-PLT', 'Acme Corp - Receiving Bay 2', '100 Industrial Parkway, Austin, TX', '78701', 'Liftgate required, call receiving 30m prior to delivery', '2026-10-04T10:00:00'),

    -- DIST-2: Globex Corp Laptops (Delivered to Globex)
    ('BOL-2026-10047', 'LD-2026-8990', 'HU-8843-PLT', 'Globex Corporation Warehouse', '742 Evergreen Terrace, Springfield, OR', '97477', 'Standard commercial dock', '2026-10-02T17:00:00'),

    -- DIST-4: Acme Corp Staged (Pending Carrier Pickup at Dock 7)
    ('BOL-2026-10048', 'LD-2026-9042', 'HU-8844-PLT', 'Acme Corp - Branch Receiving', '100 Industrial Parkway, Austin, TX', '78701', 'Hold for Friday afternoon delivery', '2026-10-04T10:30:00'),

    -- DIST-6: Initech LLC Monitors (Dispatched on Apex Trailer)
    ('BOL-2026-10050', 'LD-2026-9041', 'HU-8845-PLT', 'Initech LLC Shipping Hub', '4120 Freemont Blvd, Dallas, TX', '75201', 'Inside delivery requested', '2026-10-04T09:30:00');
GO

-- Seed Carrier Manifests
INSERT INTO dbo.Carrier_Manifests 
    (Manifest_ID, BOL_Number, Carrier_ID, Handling_Unit_Ref, Tracking_Number, Waybill_Number, Carrier_Name, Pallet_Count, Gross_Weight_LBS, Physical_Dimensions, Stop_Sequence, Shipment_Status, Dispatched_At, Estimated_Delivery)
VALUES
    -- TARGET: Acme Corp Laptop Shipment -> IN_TRANSIT with Apex Freight Express
    ('MNF-2026-8801', 'BOL-2026-10045', 'CARR-APEX', 'HU-8841-PLT', 'TRK-AFX-9948201', 'WB-884102', 'Apex Freight Express', 1, 48.50, '48x40x42 IN', 1, 'IN_TRANSIT', '2026-10-04T11:30:00', '2026-10-06T17:00:00'),

    -- DIST-2: Globex Corp Laptops -> DELIVERED via Swift Global Logistics
    ('MNF-2026-8790', 'BOL-2026-10047', 'CARR-SWFT', 'HU-8843-PLT', 'TRK-SW-7719283', 'WB-771928', 'Swift Global Logistics', 1, 115.00, '48x40x50 IN', 2, 'DELIVERED', '2026-10-03T12:00:00', '2026-10-04T09:00:00'),

    -- DIST-4: Acme Corp Staged -> PENDING_PICKUP via FedEx Freight (Trailer not departed)
    ('MNF-2026-8804', 'BOL-2026-10048', 'CARR-FXFE', 'HU-8844-PLT', 'TRK-FX-3301928', 'WB-330192', 'FedEx Freight Regional', 1, 12.00, '24x18x14 IN', 1, 'PENDING_PICKUP', NULL, '2026-10-07T12:00:00'),

    -- DIST-6: Initech Monitors -> IN_TRANSIT on same Apex trailer
    ('MNF-2026-8802', 'BOL-2026-10050', 'CARR-APEX', 'HU-8845-PLT', 'TRK-AFX-1102934', 'WB-110293', 'Apex Freight Express', 1, 88.00, '48x40x48 IN', 2, 'IN_TRANSIT', '2026-10-04T11:30:00', '2026-10-06T15:00:00');
GO
