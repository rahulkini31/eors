#!/usr/bin/env python3
"""Cross-Database Order Resolution and Verification Challenge Script.

Solves the core EORS multi-agent challenge across three decoupled Azure SQL databases:
  1. ERP (db-01-dev): Resolves Sales Order ID for Customer 'Acme Corp' and Product '%Laptop%'
  2. WMS (db-02-dev): Resolves Warehouse Pick & Handling Unit (LPN) for ERP Order 'SO-10045'
  3. TMS (db-03-dev): Resolves Freight Carrier, Load, Tracking & Waybill for Handling Unit 'HU-8841-PLT'

Decoupling Constraint:
  Databases are autonomous without cross-database foreign keys.
  Linkage is achieved through loose external keys (Order_ID and Handling_Unit_Ref).

Authentication:
  Microsoft Entra ID token auth with pytds pure-Python driver.
  Supports --mock / --offline flag for local fixture verification.
"""

import argparse
import json
import logging
import os
import subprocess
import sys
import time
from typing import Any, Dict, Optional, Tuple

import certifi
import pytds

DEFAULT_SQL_SERVER = "eosr-db-server.database.windows.net"
AZURE_SQL_RESOURCE_SCOPE = "https://database.windows.net/.default"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("cross_db_verifier")

_cached_token: Optional[str] = None


def resolve_entra_token() -> str:
    """Acquires Microsoft Entra ID access token via env var, SDK, or az CLI fallback."""
    global _cached_token
    if _cached_token:
        return _cached_token

    env_token = os.environ.get("AZURE_SQL_ACCESS_TOKEN")
    if env_token and env_token.strip():
        _cached_token = env_token.strip()
        return _cached_token

    try:
        from azure.identity import AzureCliCredential, DefaultAzureCredential

        try:
            cred = DefaultAzureCredential()
            token_obj = cred.get_token(AZURE_SQL_RESOURCE_SCOPE)
            if token_obj and token_obj.token:
                _cached_token = token_obj.token
                os.environ["AZURE_SQL_ACCESS_TOKEN"] = _cached_token
                return _cached_token
        except Exception:
            pass

        try:
            cli_cred = AzureCliCredential()
            token_obj = cli_cred.get_token(AZURE_SQL_RESOURCE_SCOPE)
            if token_obj and token_obj.token:
                _cached_token = token_obj.token
                os.environ["AZURE_SQL_ACCESS_TOKEN"] = _cached_token
                return _cached_token
        except Exception:
            pass
    except ImportError:
        pass

    try:
        cmd = [
            "az",
            "account",
            "get-access-token",
            "--resource",
            "https://database.windows.net",
            "-o",
            "json",
        ]
        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True)
        data = json.loads(proc.stdout)
        token = data.get("accessToken")
        if token:
            _cached_token = token
            os.environ["AZURE_SQL_ACCESS_TOKEN"] = _cached_token
            return _cached_token
    except Exception as ex:
        logger.error("Failed to acquire token via az CLI: %s", ex)

    raise RuntimeError("Unable to acquire Entra ID access token for Azure SQL.")


def connect_live(database: str, server: str = DEFAULT_SQL_SERVER, max_retries: int = 6) -> pytds.Connection:
    """Connects to an Azure SQL database using pytds and Entra ID auth with serverless resume."""
    token = resolve_entra_token()
    delay = 5.0
    last_ex = None

    for attempt in range(1, max_retries + 1):
        try:
            return pytds.connect(
                server=server,
                database=database,
                access_token_callable=lambda: token,
                cafile=certifi.where(),
                validate_host=False,
                login_timeout=30,
                timeout=60,
                autocommit=True,
            )
        except Exception as ex:
            last_ex = ex
            err_msg = str(ex) or repr(ex)
            is_paused = (
                "40613" in err_msg
                or "not currently available" in err_msg.lower()
                or "timed out" in err_msg.lower()
                or "wantreaderror" in err_msg.lower()
                or "timeouterror" in err_msg.lower()
            )
            if is_paused and attempt < max_retries:
                logger.warning("[%s] Database waking up... retrying in %.1fs (attempt %d/%d)", database, delay, attempt, max_retries)
                time.sleep(delay)
                delay += 4.0
                continue
            raise ex

    raise RuntimeError(f"Failed to connect to [{database}]: {last_ex}")


class DatabaseAdapter:
    """Abstract interface supporting both Live Azure SQL and Offline SQLite mock fixtures."""

    def __init__(self, mode: str = "live", server: str = DEFAULT_SQL_SERVER):
        self.mode = mode
        self.server = server

    def execute_query(self, database_name: str, query: str) -> List[Dict[str, Any]]:
        if self.mode == "mock":
            from e2e_tests.conftest_helpers import load_in_memory_db

            conn = load_in_memory_db(database_name)
            # Remove dbo. prefix for SQLite compatibility
            clean_query = query.replace("dbo.", "")
            cursor = conn.cursor()
            cursor.execute(clean_query)
            rows = cursor.fetchall()
            col_names = [description[0] for description in cursor.description]
            return [dict(zip(col_names, row)) for row in rows]
        else:
            conn = connect_live(database=database_name, server=self.server)
            try:
                with conn.cursor() as cur:
                    cur.execute(query)
                    rows = cur.fetchall()
                    col_names = [desc[0] for desc in cur.description] if cur.description else []
                    return [dict(zip(col_names, row)) for row in rows]
            finally:
                conn.close()


def query_stage1_erp(adapter: DatabaseAdapter) -> Dict[str, Any]:
    """Stage 1: Resolve Acme Corp Laptop Order in ERP (db-01-dev)."""
    logger.info("--> [STAGE 1: ERP (db-01-dev)] Querying customer 'Acme Corp' and product 'Laptop'...")

    sql = """
    SELECT 
        c.Cust_ID,
        c.Cust_Name,
        c.Billing_Address,
        c.Shipping_Address,
        so.Order_ID,
        so.Order_Date,
        so.PO_Number,
        so.OrderStatus,
        so.Payment_Status,
        so.Subtotal_Amount,
        so.Tax_Amount,
        so.Shipping_Fee,
        so.Total_Amount,
        oli.Line_ID,
        oli.Item_SKU,
        im.Item_Description,
        im.Product_Category,
        oli.Quantity,
        oli.Unit_Price,
        oli.Extended_Price,
        oli.Line_Status
    FROM dbo.tbl_SalesOrders so
    INNER JOIN dbo.tbl_Customers c ON so.Cust_ID = c.Cust_ID
    INNER JOIN dbo.tbl_OrderLineItems oli ON so.Order_ID = oli.Order_ID
    INNER JOIN dbo.tbl_Inventory_Master im ON oli.Item_SKU = im.Item_SKU
    WHERE c.Cust_Name = 'Acme Corp'
      AND (im.Item_Description LIKE '%Laptop%' OR oli.Item_SKU LIKE '%LAPTOP%')
      AND so.OrderStatus = 'Completed'
    """
    rows = adapter.execute_query("db-01-dev", sql)
    if not rows:
        raise ValueError("Stage 1 Failed: No completed sales order found for Acme Corp laptop in ERP!")

    order = rows[0]
    logger.info("    Found Sales Order: %s (PO: %s, Status: %s, Item: %s, Qty: %s, Total: $%s)",
                order["Order_ID"], order["PO_Number"], order["OrderStatus"],
                order["Item_SKU"], order["Quantity"], order["Total_Amount"])
    return order


def query_stage2_wms(adapter: DatabaseAdapter, erp_order_id: str) -> Dict[str, Any]:
    """Stage 2: Resolve Warehouse Pick and Handling Unit in WMS (db-02-dev)."""
    logger.info("--> [STAGE 2: WMS (db-02-dev)] Querying outbound picks for order '%s'...", erp_order_id)

    sql = f"""
    SELECT 
        op.pick_id,
        op.erp_order_ref,
        op.customer_po_ref,
        op.sku_code,
        op.lot_number,
        op.bin_code,
        op.handling_unit_id,
        op.qty_requested,
        op.qty_picked,
        op.status_id,
        op.picker_badge_id,
        op.pick_completed_at,
        op.dock_loaded_at,
        hu.lpn_barcode,
        hu.hu_type,
        hu.tare_weight_kg,
        hu.staged_dock_code
    FROM dbo.outbound_picks op
    LEFT JOIN dbo.handling_units hu ON op.handling_unit_id = hu.hu_id
    WHERE op.erp_order_ref = '{erp_order_id}'
    """
    rows = adapter.execute_query("db-02-dev", sql)
    if not rows:
        raise ValueError(f"Stage 2 Failed: No outbound pick found in WMS for erp_order_ref '{erp_order_id}'!")

    pick = rows[0]
    status_meanings = {
        1: "Allocated",
        2: "Picked",
        3: "Packed",
        4: "Staged at Dock",
        5: "Loaded",
        9: "Cancelled",
    }
    status_str = status_meanings.get(pick["status_id"], f"Unknown ({pick['status_id']})")

    logger.info("    Found Pick Task: %s (Status: %d - %s, Handling Unit: %s, Dock: %s, LPN: %s)",
                pick["pick_id"], pick["status_id"], status_str,
                pick["handling_unit_id"], pick["staged_dock_code"], pick["lpn_barcode"])
    return pick


def query_stage3_tms(adapter: DatabaseAdapter, handling_unit_id: str) -> Dict[str, Any]:
    """Stage 3: Resolve Carrier Manifest, Tracking and Waybill in TMS (db-03-dev)."""
    logger.info("--> [STAGE 3: TMS (db-03-dev)] Querying carrier manifests for handling unit '%s'...", handling_unit_id)

    sql = f"""
    SELECT 
        cm.Manifest_ID,
        cm.BOL_Number,
        cm.Carrier_ID,
        cm.Carrier_Name,
        cm.Handling_Unit_Ref,
        cm.Tracking_Number,
        cm.Waybill_Number,
        cm.Pallet_Count,
        cm.Gross_Weight_LBS,
        cm.Physical_Dimensions,
        cm.Stop_Sequence,
        cm.Shipment_Status,
        cm.Dispatched_At,
        cm.Estimated_Delivery,
        bol.Consignee_Name,
        bol.Delivery_Address,
        bol.Delivery_Zip,
        bol.Special_Instructions,
        fl.Load_ID,
        fl.Trailer_Number,
        fl.Load_Status,
        fl.Departure_Timestamp,
        carr.Service_Level,
        carr.Contact_Phone
    FROM dbo.Carrier_Manifests cm
    LEFT JOIN dbo.Bill_Of_Lading bol ON cm.BOL_Number = bol.BOL_Number
    LEFT JOIN dbo.Freight_Loads fl ON bol.Load_ID = fl.Load_ID
    LEFT JOIN dbo.Carrier_Master carr ON cm.Carrier_ID = carr.Carrier_ID
    WHERE cm.Handling_Unit_Ref = '{handling_unit_id}'
    """
    rows = adapter.execute_query("db-03-dev", sql)
    if not rows:
        raise ValueError(f"Stage 3 Failed: No carrier manifest found in TMS for Handling_Unit_Ref '{handling_unit_id}'!")

    manifest = rows[0]
    logger.info("    Found Manifest: %s (Carrier: %s, Tracking: %s, Status: %s, Waybill: %s)",
                manifest["Manifest_ID"], manifest["Carrier_Name"], manifest["Tracking_Number"],
                manifest["Shipment_Status"], manifest["Waybill_Number"])
    return manifest


def format_challenge_report(erp: Dict[str, Any], wms: Dict[str, Any], tms: Dict[str, Any]) -> str:
    """Constructs a comprehensive, human-readable ASCII report synthesizing all 3 stages."""
    lines = [
        "",
        "=" * 82,
        "          AZURE SQL CROSS-DATABASE ORDER RESOLUTION REPORT (EORS)",
        "=" * 82,
        "",
        " [STAGE 1] ERP DOMAIN RESOLUTION (db-01-dev: Commercial System of Record)",
        " --------------------------------------------------------------------------------",
        f"  Customer Account:     {erp.get('Cust_ID')} | {erp.get('Cust_Name')}",
        f"  Shipping Address:     {erp.get('Shipping_Address')}",
        f"  Sales Order ID:       {erp.get('Order_ID')}",
        f"  Customer PO Ref:      {erp.get('PO_Number')}",
        f"  Order Date:           {erp.get('Order_Date')}",
        f"  ERP Order Status:     {erp.get('OrderStatus')} (Payment: {erp.get('Payment_Status')})",
        f"  Purchased SKU:        {erp.get('Item_SKU')}",
        f"  Product Description:  {erp.get('Item_Description')}",
        f"  Quantity Ordered:     {erp.get('Quantity')} units @ ${float(erp.get('Unit_Price', 0)):,.2f}",
        f"  Total Order Value:    ${float(erp.get('Total_Amount', 0)):,.2f} USD",
        "",
        " [STAGE 2] WMS DOMAIN RESOLUTION (db-02-dev: Warehouse Execution System)",
        " --------------------------------------------------------------------------------",
        f"  ERP Order Ref:        {wms.get('erp_order_ref')}",
        f"  Customer PO Ref:      {wms.get('customer_po_ref')}",
        f"  Pick Task ID:         {wms.get('pick_id')}",
        f"  Physical Status:      status_id = {wms.get('status_id')} (5 = LOADED onto trailer)",
        f"  Inventory Lot:        {wms.get('lot_number')} (Bin: {wms.get('bin_code')})",
        f"  Quantity Picked:      {wms.get('qty_picked')} of {wms.get('qty_requested')} units",
        f"  Handling Unit (LPN):  {wms.get('handling_unit_id')}",
        f"  Barcode Tag:          {wms.get('lpn_barcode')} ({wms.get('hu_type')}, Tare: {wms.get('tare_weight_kg')} kg)",
        f"  Staging Bay / Dock:   {wms.get('staged_dock_code')}",
        f"  Dock Loaded At:       {wms.get('dock_loaded_at')}",
        "",
        " [STAGE 3] TMS DOMAIN RESOLUTION (db-03-dev: Transportation Management System)",
        " --------------------------------------------------------------------------------",
        f"  Handling Unit Ref:    {tms.get('Handling_Unit_Ref')}",
        f"  Bill of Lading (BOL): {tms.get('BOL_Number')}",
        f"  Consignee:            {tms.get('Consignee_Name')}",
        f"  Delivery Destination: {tms.get('Delivery_Address')} ({tms.get('Delivery_Zip')})",
        f"  Special Instructions: {tms.get('Special_Instructions')}",
        f"  Carrier Name:         {tms.get('Carrier_Name')} ({tms.get('Carrier_ID')})",
        f"  Service Level:        {tms.get('Service_Level')} (Phone: {tms.get('Contact_Phone')})",
        f"  Freight Load ID:      {tms.get('Load_ID')} (Trailer: {tms.get('Trailer_Number')})",
        f"  Dispatched Timestamp: {tms.get('Dispatched_At')}",
        f"  Estimated Delivery:   {tms.get('Estimated_Delivery')}",
        f"  Waybill Number:       {tms.get('Waybill_Number')}",
        f"  Tracking Number:      {tms.get('Tracking_Number')}",
        f"  Freight Metrics:      {tms.get('Pallet_Count')} Pallet, {tms.get('Gross_Weight_LBS')} LBS, {tms.get('Physical_Dimensions')}",
        f"  Shipment Status:      {tms.get('Shipment_Status')}",
        "",
        "=" * 82,
        "                            FINAL VERIFICATION SYNTHESIS",
        "=" * 82,
        "  CONCLUSION: Customer 'Acme Corp' Laptop Order (SO-10045) HAS SHIPPED.",
        f"  - Carrier:            {tms.get('Carrier_Name')}",
        f"  - Tracking Number:    {tms.get('Tracking_Number')}",
        f"  - Waybill Number:     {tms.get('Waybill_Number')}",
        f"  - Current Status:     {tms.get('Shipment_Status')}",
        f"  - Dispatched At:      {tms.get('Dispatched_At')}",
        "=" * 82,
        "",
    ]
    return "\n".join(lines)


def run_cross_db_verification(
    server: str = DEFAULT_SQL_SERVER,
    mock: bool = False,
) -> bool:
    """Executes the full 3-stage cross-database verification challenge."""
    mode = "mock" if mock else "live"
    logger.info("Initializing Cross-DB Challenge Verification (Mode: %s, Server: %s)...", mode.upper(), server)

    adapter = DatabaseAdapter(mode=mode, server=server)

    # 1. Stage 1: ERP
    erp_data = query_stage1_erp(adapter)
    order_id = erp_data["Order_ID"]
    assert order_id == "SO-10045", f"Expected Order_ID SO-10045, got {order_id}"
    assert erp_data["OrderStatus"] == "Completed", f"Expected OrderStatus Completed, got {erp_data['OrderStatus']}"

    # 2. Stage 2: WMS
    wms_data = query_stage2_wms(adapter, erp_order_id=order_id)
    hu_id = wms_data["handling_unit_id"]
    assert wms_data["status_id"] == 5, f"Expected status_id 5 (Loaded), got {wms_data['status_id']}"
    assert hu_id == "HU-8841-PLT", f"Expected handling_unit_id HU-8841-PLT, got {hu_id}"

    # 3. Stage 3: TMS
    tms_data = query_stage3_tms(adapter, handling_unit_id=hu_id)
    assert tms_data["Shipment_Status"] == "IN_TRANSIT", f"Expected IN_TRANSIT, got {tms_data['Shipment_Status']}"
    assert tms_data["Carrier_Name"] == "Apex Freight Express", f"Expected Apex Freight Express, got {tms_data['Carrier_Name']}"
    assert tms_data["Tracking_Number"] == "TRK-AFX-9948201", f"Expected TRK-AFX-9948201, got {tms_data['Tracking_Number']}"
    assert tms_data["Waybill_Number"] == "WB-884102", f"Expected WB-884102, got {tms_data['Waybill_Number']}"

    # 4. Format and display synthesis report
    report = format_challenge_report(erp_data, wms_data, tms_data)
    print(report)

    logger.info("Cross-database challenge successfully solved and verified across all 3 databases!")
    return True


def main():
    parser = argparse.ArgumentParser(description="Cross-Database Order Tracking Challenge Verification")
    parser.add_argument(
        "--server",
        default=os.environ.get("SQL_SERVER", DEFAULT_SQL_SERVER),
        help=f"Azure SQL Server FQDN (default: {DEFAULT_SQL_SERVER})",
    )
    parser.add_argument(
        "--mock",
        "--offline",
        action="store_true",
        help="Run verification using offline in-memory SQLite fixtures instead of live Azure SQL",
    )
    args = parser.parse_args()

    try:
        success = run_cross_db_verification(
            server=args.server,
            mock=args.mock,
        )
        sys.exit(0 if success else 1)
    except Exception as ex:
        logger.exception("Cross-database verification challenge failed: %s", ex)
        sys.exit(1)


if __name__ == "__main__":
    main()
