# Cross-Database Multi-Agent Evaluation Suite: QA Pairs

This benchmark evaluates multi-agent LLM systems against three decoupled Azure SQL databases:
1. **ERP (`db-01-dev`)**: Commercial & financial order management (legacy `tbl_*` conventions, PascalCase, text statuses).
2. **WMS (`db-02-dev`)**: Physical warehouse execution (modern snake_case, integer `status_id`, bin/lot/dock coordinates).
3. **TMS (`db-03-dev`)**: Transportation & logistics routing (freight loads, BOLs, pallet metrics, tracking numbers).

---

## 1. Single-Domain ERP Questions (`db-01-dev`)

### Question 1 (TC-ERP-01)
> **Question:** *"What is the total order value and current order status for Acme Corp's purchase order PO-ACM-2026-9921?"*  
> **Target Database:** `db-01-dev`  
> **SQL Answer:**
```sql
SELECT 
    o.Order_ID, 
    o.PO_Number, 
    o.OrderStatus, 
    o.Payment_Status, 
    o.Total_Amount 
FROM dbo.tbl_SalesOrders o 
WHERE o.PO_Number = 'PO-ACM-2026-9921';
```
> **Expected Output:**
> - `Order_ID`: `SO-10045`
> - `PO_Number`: `PO-ACM-2026-9921`
> - `OrderStatus`: `Completed`
> - `Payment_Status`: `Paid`
> - `Total_Amount`: `$20,230.00`

---

### Question 2 (TC-ERP-02)
> **Question:** *"How many enterprise 15-inch laptops are currently on hand in inventory, and what is their total financial asset valuation?"*  
> **Target Database:** `db-01-dev`  
> **SQL Answer:**
```sql
SELECT 
    Item_SKU, 
    Item_Description, 
    Qty_On_Hand, 
    Unit_Cost_USD, 
    (Qty_On_Hand * Unit_Cost_USD) AS Total_Asset_Valuation_USD 
FROM dbo.tbl_Inventory_Master 
WHERE Item_SKU = 'SKU-LAPTOP-15-ENT';
```
> **Expected Output:**
> - `Item_SKU`: `SKU-LAPTOP-15-ENT`
> - `Qty_On_Hand`: `145` units
> - `Unit_Cost_USD`: `$1,200.00`
> - `Total_Asset_Valuation_USD`: `$174,000.00`

---

### Question 3 (TC-ERP-03)
> **Question:** *"List all customers who hold Enterprise Tier 1 accounts along with their credit limits, ordered from highest to lowest credit limit."*  
> **Target Database:** `db-01-dev`  
> **SQL Answer:**
```sql
SELECT 
    Cust_ID, 
    Cust_Name, 
    Account_Type, 
    Credit_Limit_USD, 
    Payment_Terms 
FROM dbo.tbl_Customers 
WHERE Account_Type = 'ENTERPRISE_TIER_1' 
ORDER BY Credit_Limit_USD DESC;
```
> **Expected Output:**
> 1. `Globex Corporation` ($1,000,000.00)
> 2. `Cyberdyne Systems` ($750,000.00)
> 3. `Acme Corp` ($500,000.00)

---

## 2. Single-Domain WMS Questions (`db-02-dev`)

### Question 4 (TC-WMS-01)
> **Question:** *"Which bin location, warehouse zone, and quality lot number contain active stock for Enterprise Laptops (SKU-LAPTOP-15-ENT)?"*  
> **Target Database:** `db-02-dev`  
> **SQL Answer:**
```sql
SELECT 
    l.lot_number, 
    l.sku_code, 
    l.qa_status, 
    p.bin_code, 
    b.zone_code, 
    b.shelf_level 
FROM dbo.inventory_lots l 
JOIN dbo.outbound_picks p ON l.lot_number = p.lot_number 
JOIN dbo.bin_locations b ON p.bin_code = b.bin_code 
WHERE l.sku_code = 'SKU-LAPTOP-15-ENT' 
GROUP BY l.lot_number, l.sku_code, l.qa_status, p.bin_code, b.zone_code, b.shelf_level;
```
> **Expected Output:**
> - `lot_number`: `LOT-2026Q1-TECH`
> - `bin_code`: `Z1-A04-S02-B01`
> - `zone_code`: `ZONE-TECH-MEZZ`
> - `shelf_level`: `B-02`
> - `qa_status`: `PASSED`

---

### Question 5 (TC-WMS-02)
> **Question:** *"What is the physical execution status code, quantity picked, handling unit, and dock door assignment for pick task PK-8801?"*  
> **Target Database:** `db-02-dev`  
> **SQL Answer:**
```sql
SELECT 
    p.pick_id, 
    p.status_id, 
    p.qty_picked, 
    p.handling_unit_id, 
    hu.lpn_barcode, 
    hu.hu_type, 
    hu.staged_dock_code, 
    d.assigned_staging_bay 
FROM dbo.outbound_picks p 
LEFT JOIN dbo.handling_units hu ON p.handling_unit_id = hu.hu_id 
LEFT JOIN dbo.dock_doors d ON hu.staged_dock_code = d.dock_code 
WHERE p.pick_id = 'PK-8801';
```
> **Expected Output:**
> - `pick_id`: `PK-8801`
> - `status_id`: `5` (5 = Loaded onto carrier trailer)
> - `qty_picked`: `10`
> - `handling_unit_id`: `HU-8841-PLT`
> - `lpn_barcode`: `BC-LPN-8841029`
> - `staged_dock_code`: `DOCK-04`
> - `assigned_staging_bay`: `STAGE-BAY-NORTH-04`

---

### Question 6 (TC-WMS-03)
> **Question:** *"List all pallet handling units currently positioned at DOCK-04 and their tare weights."*  
> **Target Database:** `db-02-dev`  
> **SQL Answer:**
```sql
SELECT 
    hu_id, 
    lpn_barcode, 
    hu_type, 
    tare_weight_kg, 
    staged_dock_code 
FROM dbo.handling_units 
WHERE staged_dock_code = 'DOCK-04' 
ORDER BY hu_id;
```
> **Expected Output:**
> - `HU-8841-PLT` (22.00 kg)
> - `HU-8843-PLT` (25.00 kg)
> - `HU-8845-PLT` (20.00 kg)

---

## 3. Single-Domain TMS Questions (`db-03-dev`)

### Question 7 (TC-TMS-01)
> **Question:** *"What carrier name, trailer number, and total load weight are assigned to freight load LD-2026-9041?"*  
> **Target Database:** `db-03-dev`  
> **SQL Answer:**
```sql
SELECT 
    fl.Load_ID, 
    fl.Trailer_Number, 
    fl.Load_Status, 
    fl.Total_Pallets, 
    fl.Total_Weight_LBS, 
    cm.Carrier_Name, 
    cm.SCAC_Code, 
    cm.Contact_Phone 
FROM dbo.Freight_Loads fl 
JOIN dbo.Carrier_Master cm ON fl.Carrier_ID = cm.Carrier_ID 
WHERE fl.Load_ID = 'LD-2026-9041';
```
> **Expected Output:**
> - `Carrier_Name`: `Apex Freight Express`
> - `SCAC_Code`: `APEX`
> - `Trailer_Number`: `TRL-8821-X`
> - `Total_Pallets`: `4`
> - `Total_Weight_LBS`: `3,850.00 lbs`
> - `Load_Status`: `DISPATCHED`

---

### Question 8 (TC-TMS-02)
> **Question:** *"What is the carrier, tracking number, and current shipment status for Bill of Lading BOL-2026-10045?"*  
> **Target Database:** `db-03-dev`  
> **SQL Answer:**
```sql
SELECT 
    Manifest_ID, 
    BOL_Number, 
    Carrier_Name, 
    Tracking_Number, 
    Waybill_Number, 
    Shipment_Status, 
    Dispatched_At, 
    Estimated_Delivery 
FROM dbo.Carrier_Manifests 
WHERE BOL_Number = 'BOL-2026-10045';
```
> **Expected Output:**
> - `Carrier_Name`: `Apex Freight Express`
> - `Tracking_Number`: `TRK-AFX-9948201`
> - `Waybill_Number`: `WB-884102`
> - `Shipment_Status`: `IN_TRANSIT`

---

## 4. Two-Domain Cross-DB Questions (ERP <-> WMS)

### Question 9 (TC-CROSS-01)
> **Question:** *"For customer Acme Corp's laptop order, what is the physical pick task ID, who picked it, and which handling unit was it packed into?"*  
> **Step 1 (`db-01-dev`):**
```sql
SELECT o.Order_ID, o.PO_Number, c.Cust_Name, li.Item_SKU 
FROM dbo.tbl_SalesOrders o 
JOIN dbo.tbl_Customers c ON o.Cust_ID = c.Cust_ID 
JOIN dbo.tbl_OrderLineItems li ON o.Order_ID = li.Order_ID 
WHERE c.Cust_Name = 'Acme Corp' AND li.Item_SKU = 'SKU-LAPTOP-15-ENT';
```
*(Resolves `Order_ID = 'SO-10045'`)*

> **Step 2 (`db-02-dev`):**
```sql
SELECT 
    pick_id, 
    erp_order_ref, 
    sku_code, 
    qty_picked, 
    status_id, 
    picker_badge_id, 
    handling_unit_id, 
    dock_loaded_at 
FROM dbo.outbound_picks 
WHERE erp_order_ref = 'SO-10045';
```
> **Expected Output:**
> - `pick_id`: `PK-8801`
> - `picker_badge_id`: `BADGE-304`
> - `handling_unit_id`: `HU-8841-PLT`
> - `status_id`: `5` (Loaded)

---

### Question 10 (TC-CROSS-02)
> **Question:** *"What is the physical status of Acme Corp's ergonomic chairs order in the warehouse?"*  
> **Step 1 (`db-01-dev`):**
```sql
SELECT o.Order_ID, li.Item_SKU, o.OrderStatus 
FROM dbo.tbl_SalesOrders o 
JOIN dbo.tbl_Customers c ON o.Cust_ID = c.Cust_ID 
JOIN dbo.tbl_OrderLineItems li ON o.Order_ID = li.Order_ID 
WHERE c.Cust_Name = 'Acme Corp' AND li.Item_SKU = 'SKU-CHAIR-ERG-01';
```
*(Resolves `Order_ID = 'SO-10046'`)*

> **Step 2 (`db-02-dev`):**
```sql
SELECT pick_id, erp_order_ref, status_id, qty_picked, handling_unit_id, bin_code 
FROM dbo.outbound_picks 
WHERE erp_order_ref = 'SO-10046';
```
> **Expected Output:**
> - `pick_id`: `PK-8802`
> - `status_id`: `2` (Picked onto warehouse cart, NOT packed or loaded)
> - `bin_code`: `Z2-B12-S01-B04`

---

## 5. Two-Domain Cross-DB Questions (WMS <-> TMS)

### Question 11 (TC-CROSS-03)
> **Question:** *"Which carrier freight load and trailer is handling unit HU-8841-PLT loaded onto, and what is the trailer departure status?"*  
> **Step 1 (`db-02-dev`):**
```sql
SELECT hu_id, lpn_barcode, staged_dock_code 
FROM dbo.handling_units 
WHERE hu_id = 'HU-8841-PLT';
```
*(Staged at `DOCK-04`)*

> **Step 2 (`db-03-dev`):**
```sql
SELECT 
    bol.Handling_Unit_Ref, 
    bol.BOL_Number, 
    fl.Load_ID, 
    fl.Trailer_Number, 
    fl.Load_Status, 
    fl.Departure_Timestamp 
FROM dbo.Bill_Of_Lading bol 
JOIN dbo.Freight_Loads fl ON bol.Load_ID = fl.Load_ID 
WHERE bol.Handling_Unit_Ref = 'HU-8841-PLT';
```
> **Expected Output:**
> - `Load_ID`: `LD-2026-9041`
> - `Trailer_Number`: `TRL-8821-X`
> - `Load_Status`: `DISPATCHED`

---

## 6. Three-Domain Core Agentic Challenge (ERP -> WMS -> TMS)

### Question 12 (TC-CORE-01: The Benchmark Benchmark Challenge)
> **Question:** *"Has customer Acme Corp's laptop order shipped, and if so, what is the carrier and tracking number?"*  
> **Step 1 (`db-01-dev`):**
```sql
SELECT o.Order_ID, o.PO_Number, c.Cust_Name, li.Item_SKU, o.OrderStatus 
FROM dbo.tbl_SalesOrders o 
JOIN dbo.tbl_Customers c ON o.Cust_ID = c.Cust_ID 
JOIN dbo.tbl_OrderLineItems li ON o.Order_ID = li.Order_ID 
WHERE c.Cust_Name = 'Acme Corp' AND li.Item_SKU LIKE '%LAPTOP%';
```
*(Yields `Order_ID = 'SO-10045'`, `OrderStatus = 'Completed'`)*

> **Step 2 (`db-02-dev`):**
```sql
SELECT pick_id, erp_order_ref, status_id, handling_unit_id, dock_loaded_at 
FROM dbo.outbound_picks 
WHERE erp_order_ref = 'SO-10045';
```
*(Yields `status_id = 5` [Loaded onto trailer at DOCK-04], `handling_unit_id = 'HU-8841-PLT'`)*

> **Step 3 (`db-03-dev`):**
```sql
SELECT 
    cm.Manifest_ID, 
    cm.Carrier_Name, 
    cm.Tracking_Number, 
    cm.Waybill_Number, 
    cm.Shipment_Status, 
    cm.Dispatched_At 
FROM dbo.Carrier_Manifests cm 
WHERE cm.Handling_Unit_Ref = 'HU-8841-PLT';
```
> **Final Answer:**
> **YES, it has shipped.**  
> Order `SO-10045` was fulfilled from lot `LOT-2026Q1-TECH`, packed into pallet `HU-8841-PLT`, loaded onto trailer `TRL-8821-X`, and dispatched via **Apex Freight Express** under tracking number **`TRK-AFX-9948201`** (Waybill: `WB-884102`) with status **`IN_TRANSIT`**.

---

### Question 13 (TC-CORE-02: Complete Lifecycle Lineage)
> **Question:** *"What is the complete end-to-end audit trail (from financial order, to warehouse staging, to freight tracking) for customer purchase order PO-ACM-2026-9921?"*  
> **Step 1 (`db-01-dev`):**
```sql
SELECT Order_ID, PO_Number, OrderStatus, Total_Amount, Order_Date 
FROM dbo.tbl_SalesOrders 
WHERE PO_Number = 'PO-ACM-2026-9921';
```
> **Step 2 (`db-02-dev`):**
```sql
SELECT pick_id, erp_order_ref, customer_po_ref, status_id, handling_unit_id, dock_loaded_at 
FROM dbo.outbound_picks 
WHERE customer_po_ref = 'PO-ACM-2026-9921';
```
> **Step 3 (`db-03-dev`):**
```sql
SELECT 
    cm.BOL_Number, 
    cm.Carrier_Name, 
    cm.Tracking_Number, 
    cm.Gross_Weight_LBS, 
    cm.Shipment_Status, 
    cm.Estimated_Delivery 
FROM dbo.Carrier_Manifests cm 
JOIN dbo.Bill_Of_Lading bol ON cm.BOL_Number = bol.BOL_Number 
WHERE bol.Handling_Unit_Ref = 'HU-8841-PLT';
```
> **Expected Output:**
> Full 3-hop trace matching:
> `SO-10045` ($20,230.00) -> `PK-8801` (`status_id = 5`, `HU-8841-PLT`) -> `BOL-2026-10045` (`TRK-AFX-9948201`, Apex Freight Express).

---

## 7. Adversarial & Distractor Disambiguation Tests

### Question 14 (TC-DISTRACTOR-01: Cancelled Order Trap)
> **Question:** *"Did Acme Corp order SO-10012 ever get picked or loaded onto a delivery truck?"*  
> **Step 1 (`db-01-dev`):**
```sql
SELECT Order_ID, Cust_ID, OrderStatus, Payment_Status, Internal_Notes 
FROM dbo.tbl_SalesOrders 
WHERE Order_ID = 'SO-10012';
```
*(Status: `'Cancelled'`, Payment: `'Refunded'`)*

> **Step 2 (`db-02-dev`):**
```sql
SELECT pick_id, erp_order_ref, status_id 
FROM dbo.outbound_picks 
WHERE erp_order_ref = 'SO-10012';
```
*(Returns 0 rows)*

> **Final Answer:**
> **NO.** Order `SO-10012` was cancelled and refunded prior to fulfillment. No pick task was generated in the warehouse.

---

### Question 15 (TC-DISTRACTOR-02: Customer Disambiguation Trap)
> **Question:** *"Has Globex Corporation's laptop order shipped, and which carrier handled it?"*  
> **Step 1 (`db-01-dev`):**
```sql
SELECT o.Order_ID, c.Cust_Name, li.Item_SKU 
FROM dbo.tbl_SalesOrders o 
JOIN dbo.tbl_Customers c ON o.Cust_ID = c.Cust_ID 
JOIN dbo.tbl_OrderLineItems li ON o.Order_ID = li.Order_ID 
WHERE c.Cust_Name LIKE '%Globex%' AND li.Item_SKU = 'SKU-LAPTOP-15-ENT';
```
*(Yields `Order_ID = 'SO-10047'`)*

> **Step 2 (`db-02-dev`):**
```sql
SELECT pick_id, erp_order_ref, handling_unit_id, status_id 
FROM dbo.outbound_picks 
WHERE erp_order_ref = 'SO-10047';
```
*(Yields `status_id = 5`, `handling_unit_id = 'HU-8843-PLT'`)*

> **Step 3 (`db-03-dev`):**
```sql
SELECT Carrier_Name, Tracking_Number, Shipment_Status 
FROM dbo.Carrier_Manifests 
WHERE Handling_Unit_Ref = 'HU-8843-PLT';
```
> **Final Answer:**
> **YES.** Globex Corporation's laptop order was dispatched via **Swift Global Logistics** (NOT Apex Freight Express) under tracking number **`TRK-SW-7719283`** and has already been **`DELIVERED`**.

---

### Question 16 (TC-DISTRACTOR-03: Staged vs Dispatched Trap)
> **Question:** *"Is Acme Corp's branch office expedited order (PO-ACM-2026-9930) currently on a delivery truck?"*  
> **Step 1 (`db-01-dev`):**
```sql
SELECT Order_ID, PO_Number, OrderStatus 
FROM dbo.tbl_SalesOrders 
WHERE PO_Number = 'PO-ACM-2026-9930';
```
*(Yields `Order_ID = 'SO-10048'`)*

> **Step 2 (`db-02-dev`):**
```sql
SELECT pick_id, erp_order_ref, status_id, handling_unit_id 
FROM dbo.outbound_picks 
WHERE erp_order_ref = 'SO-10048';
```
*(Yields `status_id = 4` [Staged at Dock 7, NOT loaded/5], `handling_unit_id = 'HU-8844-PLT'`)*

> **Step 3 (`db-03-dev`):**
```sql
SELECT Carrier_Name, Tracking_Number, Shipment_Status, Dispatched_At 
FROM dbo.Carrier_Manifests 
WHERE Handling_Unit_Ref = 'HU-8844-PLT';
```
> **Final Answer:**
> **NO, it is NOT on a delivery truck.** While packed on pallet `HU-8844-PLT`, it is currently staged at Dock 7 (`status_id = 4`) and marked `PENDING_PICKUP` by FedEx Freight Regional. The trailer has not departed (`Dispatched_At` is NULL).
