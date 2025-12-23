from flask import Flask, jsonify, send_from_directory, send_file, request
from flask_cors import CORS
import atexit
import requests
import json
from datetime import datetime, timezone
from typing import List, Dict, Set
import time
import os
import psycopg2
from psycopg2.extras import RealDictCursor
from psycopg2.pool import SimpleConnectionPool
import threading

app = Flask(__name__, static_folder='.', static_url_path='')
CORS(app)

# Configuration
HELIUS_API_URL = "https://mainnet.helius-rpc.com/?api-key=559e77bf-c1d3-4374-8fbe-daeed8970e94"
PROGRAM_ADDRESS = "CHtfHPSiFoATLzciMtNe2QVKckXtP8ASWucu8Ad69cyK"
USDC_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"

# Presale start time: 1pm UTC, December 22, 2025
PRESALE_START_TIMESTAMP = int(datetime(2025, 12, 22, 13, 0, 0, tzinfo=timezone.utc).timestamp())  # 2025-12-22 13:00:00 UTC

# Database configuration
# Support both connection string (Vercel Postgres) and individual credentials
POSTGRES_URL = os.getenv('POSTGRES_URL') or os.getenv('POSTGRES_URL_NON_POOLING')

if POSTGRES_URL:
    # Use connection string (Vercel Postgres, Neon, Supabase, etc.)
    import urllib.parse
    parsed = urllib.parse.urlparse(POSTGRES_URL)
    DB_CONFIG = {
        'host': parsed.hostname,
        'port': parsed.port or 5432,
        'database': parsed.path.lstrip('/'),
        'user': parsed.username,
        'password': parsed.password
    }
else:
    # Use individual environment variables
    DB_CONFIG = {
        'host': os.getenv('DB_HOST', 'localhost'),
        'port': os.getenv('DB_PORT', '5432'),
        'database': os.getenv('DB_NAME', 'usdc_transfers'),
        'user': os.getenv('DB_USER', 'postgres'),
        'password': os.getenv('DB_PASSWORD', 'postgres')
    }

# Connection pool
db_pool = None
db_initialized = False

# Backfill status
backfill_complete = False
backfill_in_progress = False

def init_database():
    """Initialize database connection pool and create tables"""
    global db_pool, db_initialized
    
    if db_initialized and db_pool:
        return
    
    try:
        # Create connection pool
        db_pool = SimpleConnectionPool(1, 10, **DB_CONFIG)
        
        # Create tables
        conn = db_pool.getconn()
        try:
            cur = conn.cursor()
            
            # Create transfers table with indexes
            cur.execute("""
                CREATE TABLE IF NOT EXISTS transfers (
                    id SERIAL PRIMARY KEY,
                    transaction_id VARCHAR(88) UNIQUE NOT NULL,
                    source VARCHAR(44) NOT NULL,
                    blocktime BIGINT NOT NULL,
                    blocktime_utc TIMESTAMP,
                    amount DECIMAL(20, 6) NOT NULL,
                    direction VARCHAR(10) NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
            
            # Create indexes for fast queries
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_transaction_id ON transfers(transaction_id);
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_blocktime ON transfers(blocktime DESC);
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_source ON transfers(source);
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_direction ON transfers(direction);
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_blocktime_utc ON transfers(blocktime_utc DESC);
            """)
            
            # Create contract_transactions table to store all contract transactions
            cur.execute("""
                CREATE TABLE IF NOT EXISTS contract_transactions (
                    id SERIAL PRIMARY KEY,
                    transaction_id VARCHAR(88) UNIQUE NOT NULL,
                    blocktime BIGINT NOT NULL,
                    blocktime_utc TIMESTAMP,
                    fee BIGINT,
                    status VARCHAR(20),
                    signer VARCHAR(44),
                    program_address VARCHAR(44),
                    instruction_count INTEGER,
                    account_count INTEGER,
                    transaction_data JSONB,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
            
            # Create indexes for contract_transactions
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_contract_tx_id ON contract_transactions(transaction_id);
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_contract_blocktime ON contract_transactions(blocktime DESC);
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_contract_blocktime_utc ON contract_transactions(blocktime_utc DESC);
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_contract_signer ON contract_transactions(signer);
            """)
            
            conn.commit()
            cur.close()
            db_initialized = True
            print("✓ Database initialized successfully")
        finally:
            db_pool.putconn(conn)
            
    except Exception as e:
        print(f"✗ Database initialization error: {e}")
        print("Make sure PostgreSQL is running and credentials are correct")
        db_initialized = False
        raise


def get_db_connection():
    """Get a database connection from the pool"""
    if db_pool is None:
        raise Exception("Database pool not initialized")
    return db_pool.getconn()


def save_transfer_to_db(transfer: Dict):
    """Save a transfer to PostgreSQL"""
    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        
        # Convert blocktime to UTC timestamp - store as naive datetime (PostgreSQL will treat as UTC)
        blocktime_utc = None
        timestamp = transfer.get('timestamp')
        if timestamp:
            # Convert Unix timestamp to UTC datetime, then remove timezone info for storage
            dt_utc = datetime.fromtimestamp(timestamp, tz=timezone.utc)
            # Store as naive datetime - PostgreSQL TIMESTAMP without timezone
            blocktime_utc = dt_utc.replace(tzinfo=None)
        
        cur.execute("""
            INSERT INTO transfers (transaction_id, source, blocktime, blocktime_utc, amount, direction)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (transaction_id) DO NOTHING
            RETURNING id;
        """, (
            transfer.get('signature', ''),
            transfer.get('owner', ''),
            timestamp or 0,
            blocktime_utc,
            transfer.get('amount', 0),
            transfer.get('direction', '')
        ))
        
        conn.commit()
        cur.close()
        return cur.rowcount > 0
    except Exception as e:
        if conn:
            conn.rollback()
        print(f"Error saving transfer to DB: {e}")
        return False
    finally:
        if conn:
            db_pool.putconn(conn)


def get_seen_signatures_from_db() -> Set[str]:
    """Get all seen transaction signatures from database (only from presale start time)"""
    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT DISTINCT transaction_id FROM transfers WHERE blocktime >= %s;", (PRESALE_START_TIMESTAMP,))
        signatures = {row[0] for row in cur.fetchall()}
        cur.close()
        return signatures
    except Exception as e:
        print(f"Error getting seen signatures from DB: {e}")
        return set()
    finally:
        if conn:
            db_pool.putconn(conn)


def get_stats_from_db() -> Dict:
    """Get statistics from database (only from presale start time)"""
    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        
        cur.execute("""
            SELECT 
                COUNT(*) as total_transfers,
                SUM(amount) as total_amount,
                COUNT(DISTINCT transaction_id) as unique_transactions
            FROM transfers
            WHERE blocktime >= %s;
        """, (PRESALE_START_TIMESTAMP,))
        
        result = cur.fetchone()
        cur.close()
        
        return {
            "total_transfers": result['total_transfers'] or 0,
            "total_amount": float(result['total_amount'] or 0),
            "unique_transactions": result['unique_transactions'] or 0
        }
    except Exception as e:
        print(f"Error getting stats from DB: {e}")
        return {"total_transfers": 0, "total_amount": 0.0, "unique_transactions": 0}
    finally:
        if conn:
            db_pool.putconn(conn)

def get_latest_transactions(limit: int = 100, before: str = None) -> List[Dict]:
    """Get latest transactions for the program"""
    params = {
        "limit": limit
    }
    
    # Add 'before' parameter to fetch older transactions
    if before:
        params["before"] = before
    
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "getSignaturesForAddress",
        "params": [
            PROGRAM_ADDRESS,
            params
        ]
    }
    
    try:
        response = requests.post(HELIUS_API_URL, json=payload, timeout=30)
        response.raise_for_status()
        data = response.json()
        
        if "error" in data:
            return []
        
        return data.get("result", [])
    except Exception as e:
        print(f"Error fetching signatures: {e}")
        return []


def get_transaction_details(signature: str) -> Dict:
    """Get detailed transaction data"""
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "getTransaction",
        "params": [
            signature,
            {
                "encoding": "jsonParsed",
                "maxSupportedTransactionVersion": 0
            }
        ]
    }
    
    try:
        response = requests.post(HELIUS_API_URL, json=payload, timeout=30)
        response.raise_for_status()
        data = response.json()
        
        if "error" in data:
            return None
        
        return data.get("result")
    except Exception as e:
        return None


def extract_contract_transaction(transaction: Dict) -> Dict:
    """Extract all contract transaction information"""
    if not transaction:
        return None
    
    meta = transaction.get("meta", {})
    tx_data = transaction.get("transaction", {})
    signature = tx_data.get("signatures", [""])[0] if tx_data else ""
    
    if not signature:
        return None
    
    # Extract transaction details
    block_time = transaction.get("blockTime")
    fee = meta.get("fee", 0)
    err = meta.get("err")
    status = "success" if err is None else "failed"
    
    # Get signer (first account is usually the signer)
    account_keys = tx_data.get("message", {}).get("accountKeys", [])
    signer = account_keys[0].get("pubkey", "") if account_keys else ""
    
    # Count instructions and accounts
    instructions = tx_data.get("message", {}).get("instructions", [])
    instruction_count = len(instructions)
    account_count = len(account_keys)
    
    # Convert blocktime to UTC datetime
    blocktime_utc = None
    if block_time:
        dt_utc = datetime.fromtimestamp(block_time, tz=timezone.utc)
        blocktime_utc = dt_utc.replace(tzinfo=None)
    
    return {
        "transaction_id": signature,
        "blocktime": block_time or 0,
        "blocktime_utc": blocktime_utc,
        "fee": fee,
        "status": status,
        "signer": signer,
        "program_address": PROGRAM_ADDRESS,
        "instruction_count": instruction_count,
        "account_count": account_count,
        "transaction_data": json.dumps(transaction)  # Store full transaction as JSON
    }


def save_contract_transaction(transaction_data: Dict) -> bool:
    """Save a contract transaction to PostgreSQL"""
    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        
        cur.execute("""
            INSERT INTO contract_transactions (
                transaction_id, blocktime, blocktime_utc, fee, status, 
                signer, program_address, instruction_count, account_count, transaction_data
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (transaction_id) DO NOTHING
            RETURNING id;
        """, (
            transaction_data.get('transaction_id', ''),
            transaction_data.get('blocktime', 0),
            transaction_data.get('blocktime_utc'),
            transaction_data.get('fee', 0),
            transaction_data.get('status', ''),
            transaction_data.get('signer', ''),
            transaction_data.get('program_address', ''),
            transaction_data.get('instruction_count', 0),
            transaction_data.get('account_count', 0),
            transaction_data.get('transaction_data', '{}')
        ))
        
        conn.commit()
        cur.close()
        return cur.rowcount > 0
    except Exception as e:
        if conn:
            conn.rollback()
        print(f"Error saving contract transaction to DB: {e}")
        return False
    finally:
        if conn:
            db_pool.putconn(conn)


def extract_usdc_transfers(transaction: Dict) -> List[Dict]:
    """Extract USDC transfer information from a transaction"""
    transfers = []
    
    if not transaction:
        return transfers
    
    meta = transaction.get("meta", {})
    signature = transaction.get("transaction", {}).get("signatures", [""])[0] if "transaction" in transaction else ""
    
    if not signature:
        return transfers
    
    pre_token_balances = meta.get("preTokenBalances", [])
    post_token_balances = meta.get("postTokenBalances", [])
    
    balance_changes = {}
    
    # Process pre balances
    for balance in pre_token_balances:
        account_index = balance.get("accountIndex")
        mint = balance.get("mint")
        if mint == USDC_MINT:
            ui_token_amount = balance.get("uiTokenAmount", {})
            amount = float(ui_token_amount.get("uiAmount", 0))
            owner = balance.get("owner")
            balance_changes[account_index] = {
                "account_index": account_index,
                "mint": mint,
                "owner": owner,
                "pre_amount": amount,
                "post_amount": amount,
            }
    
    # Process post balances
    for balance in post_token_balances:
        account_index = balance.get("accountIndex")
        mint = balance.get("mint")
        if mint == USDC_MINT:
            ui_token_amount = balance.get("uiTokenAmount", {})
            amount = float(ui_token_amount.get("uiAmount", 0))
            owner = balance.get("owner")
            
            if account_index in balance_changes:
                balance_changes[account_index]["post_amount"] = amount
            else:
                balance_changes[account_index] = {
                    "account_index": account_index,
                    "mint": mint,
                    "owner": owner,
                    "pre_amount": 0,
                    "post_amount": amount,
                }
    
    # Create transfers
    for account_index, balance_info in balance_changes.items():
        change = balance_info["post_amount"] - balance_info["pre_amount"]
        if abs(change) > 0.000001:
            transfer = {
                "signature": signature,
                "timestamp": transaction.get("blockTime"),
                "owner": balance_info.get("owner", ""),
                "change": change,
                "direction": "in" if change > 0 else "out",
                "amount": abs(change)
            }
            transfers.append(transfer)
    
    return transfers


# Initialize database on first request (for Vercel serverless)
# Note: @before_first_request is deprecated in Flask 2.2+, using alternative approach
def ensure_db_initialized():
    """Ensure database is initialized before handling requests"""
    if not db_initialized:
        try:
            init_database()
        except Exception as e:
            print(f"Warning: Database initialization failed: {e}")
            raise

# Cleanup function for connection pool
def cleanup_db_pool():
    """Close all database connections on exit"""
    global db_pool
    if db_pool:
        db_pool.closeall()
        print("Database connection pool closed")

atexit.register(cleanup_db_pool)

@app.route('/')
def index():
    """Serve the frontend HTML"""
    # Ensure database is initialized
    try:
        ensure_db_initialized()
    except Exception as e:
        return f"Database initialization error: {e}", 500
    return send_file('usdc_dashboard.html')


@app.route('/api/new-transfers')
def get_new_transfers():
    """Get only new USDC transfers since last check"""
    # Ensure database is initialized
    try:
        ensure_db_initialized()
    except Exception as e:
        return jsonify({"error": f"Database initialization failed: {e}"}), 500
    
    # Get seen signatures from database
    seen_signatures = get_seen_signatures_from_db()
    
    # Get latest transactions
    signatures = get_latest_transactions(limit=50)
    
    new_transfers = []
    
    for sig_info in signatures:
        signature = sig_info["signature"]
        
        # Skip if we've already seen this transaction
        if signature in seen_signatures:
            continue
        
        # Get transaction details
        transaction = get_transaction_details(signature)
        if not transaction:
            continue
        
        # Extract USDC transfers
        transfers = extract_usdc_transfers(transaction)
        
        for transfer in transfers:
            # Only process transfers after presale start time
            transfer_timestamp = transfer.get('timestamp', 0)
            if transfer_timestamp < PRESALE_START_TIMESTAMP:
                continue
            
            # Save to database
            save_transfer_to_db(transfer)
            
            # Format transfer data for response - ensure UTC conversion
            blocktime_utc_str = ""
            timestamp = transfer.get("timestamp")
            if timestamp:
                # Always convert Unix timestamp to UTC datetime
                dt = datetime.fromtimestamp(timestamp, tz=timezone.utc)
                blocktime_utc_str = dt.strftime("%Y-%m-%d %H:%M:%S UTC")
            
            transfer_data = {
                "source": transfer.get("owner", ""),
                "blocktime": timestamp or 0,
                "blocktime_utc": blocktime_utc_str,
                "transaction_id": transfer.get("signature", ""),
                "amount": transfer.get("amount", 0),
                "direction": transfer.get("direction", ""),
                "timestamp": timestamp or 0
            }
            new_transfers.append(transfer_data)
    
    # Sort by timestamp (newest first)
    new_transfers.sort(key=lambda x: x.get("timestamp", 0), reverse=True)
    
    return jsonify({
        "new_transfers": new_transfers,
        "count": len(new_transfers)
    })


@app.route('/api/stats')
def get_stats():
    """Get total statistics from database"""
    # Ensure database is initialized
    try:
        ensure_db_initialized()
    except Exception as e:
        return jsonify({"error": f"Database initialization failed: {e}"}), 500
    
    stats = get_stats_from_db()
    return jsonify({
        "total_amount": stats["total_amount"],
        "total_transfers": stats["total_transfers"],
        "seen_signatures_count": stats["unique_transactions"]
    })


def backfill_historical_transactions(limit: int = 1000):
    """Backfill all historical transactions from presale start time onwards"""
    global backfill_complete, backfill_in_progress
    
    if backfill_in_progress:
        return {"status": "already_in_progress"}
    
    backfill_in_progress = True
    print("Starting backfill of historical transactions...")
    print(f"Presale start time: {datetime.fromtimestamp(PRESALE_START_TIMESTAMP, tz=timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")
    
    # Get seen signatures from database
    seen_signatures = get_seen_signatures_from_db()
    initial_count = len(seen_signatures)
    
    # Fetch transactions in batches, going back in time until we reach presale start
    all_signatures = []
    before = None
    batch_size = 1000
    max_batches = 100  # Safety limit to avoid infinite loops
    
    print("Fetching historical transactions...")
    for batch_num in range(max_batches):
        signatures = get_latest_transactions(limit=batch_size, before=before)
        
        if not signatures:
            break
        
        # Filter to only include transactions from presale start time onwards
        relevant_signatures = []
        oldest_timestamp = None
        
        for sig_info in signatures:
            # Get blockTime if available (to check if we've gone back far enough)
            block_time = sig_info.get("blockTime")
            if block_time and block_time < PRESALE_START_TIMESTAMP:
                # We've gone back before presale start, stop fetching
                print(f"Reached presale start time. Oldest transaction: {datetime.fromtimestamp(block_time, tz=timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")
                break
            
            if block_time and block_time >= PRESALE_START_TIMESTAMP:
                relevant_signatures.append(sig_info)
                if oldest_timestamp is None or block_time < oldest_timestamp:
                    oldest_timestamp = block_time
        
        all_signatures.extend(relevant_signatures)
        
        # Check if any transaction in this batch is before presale start
        found_before_presale = False
        for sig in signatures:
            block_time = sig.get("blockTime")
            if block_time and block_time < PRESALE_START_TIMESTAMP:
                found_before_presale = True
                print(f"Found transaction before presale start: {datetime.fromtimestamp(block_time, tz=timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")
                break
        
        if found_before_presale:
            break
        
        # If we got fewer than batch_size, we've reached the end
        if len(signatures) < batch_size:
            break
        
        # Set 'before' to the oldest signature in this batch for next iteration
        before = signatures[-1]["signature"]
        print(f"Batch {batch_num + 1}: Found {len(relevant_signatures)} relevant transactions (total: {len(all_signatures)})")
    
    print(f"Found {len(all_signatures)} historical transactions to process")
    print(f"Already have {initial_count} transactions in database")
    print(f"Processing transactions...")
    
    processed = 0
    new_transfers_count = 0
    
    for i, sig_info in enumerate(all_signatures):
        signature = sig_info["signature"]
        
        # Skip if already seen
        if signature in seen_signatures:
            continue
        
        # Get transaction details
        transaction = get_transaction_details(signature)
        if not transaction:
            continue
        
        # Extract USDC transfers
        transfers = extract_usdc_transfers(transaction)
        
        for transfer in transfers:
            # Only process transfers after presale start time
            transfer_timestamp = transfer.get('timestamp', 0)
            if transfer_timestamp < PRESALE_START_TIMESTAMP:
                continue
            
            # Save to database
            if save_transfer_to_db(transfer):
                new_transfers_count += 1
                seen_signatures.add(signature)  # Track in memory to avoid duplicates
        
        processed += 1
        
        # Progress update every 50 transactions
        if (i + 1) % 50 == 0:
            stats = get_stats_from_db()
            print(f"Processed {i + 1}/{len(all_signatures)} transactions... "
                  f"({stats['total_transfers']} transfers, ${stats['total_amount']:,.2f} USDC)")
    
    backfill_complete = True
    backfill_in_progress = False
    
    final_stats = get_stats_from_db()
    
    print(f"\n✓ Backfill complete!")
    print(f"  Total transactions processed: {processed}")
    print(f"  New transfers added: {new_transfers_count}")
    print(f"  Total USDC transfers in DB: {final_stats['total_transfers']}")
    print(f"  Total USDC amount: ${final_stats['total_amount']:,.2f}")
    print("  Now monitoring for new transactions...\n")
    
    return {
        "status": "complete",
        "transactions_processed": processed,
        "transfers_found": new_transfers_count,
        "total_amount": final_stats['total_amount'],
        "total_transfers": final_stats['total_transfers']
    }


@app.route('/api/backfill', methods=['GET', 'POST'])
def trigger_backfill():
    """Manually trigger backfill"""
    import threading
    # Run backfill in background thread to avoid timeout
    def run_backfill():
        backfill_historical_transactions(limit=1000)
    
    thread = threading.Thread(target=run_backfill, daemon=True)
    thread.start()
    
    return jsonify({
        "status": "started",
        "message": "Backfill process started in background. Check /api/backfill-status for progress."
    })


@app.route('/api/backfill-status')
def backfill_status():
    """Get backfill status"""
    global backfill_complete, backfill_in_progress
    stats = get_stats_from_db()
    seen_signatures = get_seen_signatures_from_db()
    
    return jsonify({
        "backfill_complete": backfill_complete,
        "backfill_in_progress": backfill_in_progress,
        "total_amount": stats['total_amount'],
        "total_transfers": stats['total_transfers'],
        "seen_signatures": len(seen_signatures)
    })


@app.route('/api/chart-data')
def get_chart_data():
    """Get cumulative amount data over time for chart"""
    try:
        ensure_db_initialized()
    except Exception as e:
        return jsonify({"error": f"Database initialization failed: {e}"}), 500
    
    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        
        # Get all transactions ordered by time (only from presale start)
        query = """
            SELECT 
                blocktime,
                blocktime_utc,
                amount
            FROM transfers
            WHERE blocktime >= %s
            ORDER BY blocktime ASC
        """
        
        cur.execute(query, (PRESALE_START_TIMESTAMP,))
        rows = cur.fetchall()
        cur.close()
        
        # Calculate cumulative amounts
        labels = []
        amounts = []
        cumulative = 0.0
        
        for row in rows:
            blocktime_unix = row[0]
            blocktime_utc = row[1]
            amount = float(row[2])
            
            cumulative += amount
            
            # Format timestamp for label - use blocktime_utc if available, otherwise convert from Unix timestamp
            if blocktime_utc:
                if isinstance(blocktime_utc, datetime):
                    label = blocktime_utc.strftime("%Y-%m-%d %H:%M UTC")
                elif isinstance(blocktime_utc, str):
                    label = blocktime_utc
                else:
                    # Convert from Unix timestamp
                    dt = datetime.fromtimestamp(blocktime_unix, tz=timezone.utc)
                    label = dt.strftime("%Y-%m-%d %H:%M UTC")
            else:
                # Convert from Unix timestamp
                dt = datetime.fromtimestamp(blocktime_unix, tz=timezone.utc)
                label = dt.strftime("%Y-%m-%d %H:%M UTC")
            
            labels.append(label)
            amounts.append(cumulative)
        
        return jsonify({
            "labels": labels,
            "amounts": amounts
        })
    except Exception as e:
        import traceback
        error_msg = f"{str(e)}\n{traceback.format_exc()}"
        print(f"Error in get_chart_data: {error_msg}")
        return jsonify({"error": str(e)}), 500
    finally:
        if conn:
            db_pool.putconn(conn)


@app.route('/api/transfers')
def get_transfers():
    """Get transfers with pagination and filtering"""
    # Ensure database is initialized
    try:
        ensure_db_initialized()
    except Exception as e:
        return jsonify({"error": f"Database initialization failed: {e}"}), 500
    
    try:
        limit = int(request.args.get('limit', 100))
        offset = int(request.args.get('offset', 0))
        source = request.args.get('source', None)
        direction = request.args.get('direction', None)
    except ValueError:
        return jsonify({"error": "Invalid parameter format"}), 400
    
    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        
        # Select specific columns to avoid issues
        # Only show transfers from presale start time onwards
        query = "SELECT transaction_id, source, blocktime, blocktime_utc, amount, direction FROM transfers WHERE blocktime >= %s"
        params = [PRESALE_START_TIMESTAMP]
        
        if source:
            query += " AND source = %s"
            params.append(source)
        
        if direction:
            query += " AND direction = %s"
            params.append(direction)
        
        query += " ORDER BY blocktime DESC LIMIT %s OFFSET %s"
        params.extend([limit, offset])
        
        cur.execute(query, params)
        rows = cur.fetchall()
        
        # Get total count (only from presale start time)
        count_query = "SELECT COUNT(*) FROM transfers WHERE blocktime >= %s"
        count_params = [PRESALE_START_TIMESTAMP]
        if source:
            count_query += " AND source = %s"
            count_params.append(source)
        if direction:
            count_query += " AND direction = %s"
            count_params.append(direction)
        
        cur.execute(count_query, count_params)
        total_count = cur.fetchone()[0]
        
        cur.close()
        
        # Convert rows to list of dicts manually
        transfers_list = []
        for row in rows:
            try:
                # Format blocktime_utc consistently - ALWAYS convert from Unix timestamp to ensure UTC
                blocktime_utc_str = None
                blocktime_unix = row[2]  # Use the Unix timestamp (blocktime) directly
                
                if blocktime_unix:
                    try:
                        # Convert Unix timestamp directly to UTC datetime - this is the source of truth
                        dt = datetime.fromtimestamp(blocktime_unix, tz=timezone.utc)
                        blocktime_utc_str = dt.strftime("%Y-%m-%d %H:%M:%S UTC")
                    except Exception as e:
                        print(f"Error converting blocktime {blocktime_unix} to UTC: {e}")
                        blocktime_utc_str = "N/A"
                else:
                    blocktime_utc_str = "N/A"
                
                transfer_dict = {
                    'transaction_id': row[0] or '',
                    'source': row[1] or '',
                    'blocktime': int(row[2]) if row[2] else 0,
                    'blocktime_utc': blocktime_utc_str,
                    'amount': float(row[4]) if row[4] else 0.0,
                    'direction': row[5] or ''
                }
                transfers_list.append(transfer_dict)
            except Exception as conv_error:
                print(f"Error converting transfer row: {conv_error}")
                import traceback
                print(traceback.format_exc())
                continue
        
        return jsonify({
            "transfers": transfers_list,
            "total": total_count,
            "limit": limit,
            "offset": offset
        })
    except Exception as e:
        import traceback
        error_msg = f"{str(e)}\n{traceback.format_exc()}"
        print(f"Error in get_transfers: {error_msg}")
        return jsonify({"error": str(e)}), 500
    finally:
        if conn:
            db_pool.putconn(conn)


@app.route('/api/reset')
def reset():
    """Reset database (for testing) - WARNING: Deletes all data"""
    global backfill_complete, backfill_in_progress
    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("TRUNCATE TABLE transfers RESTART IDENTITY;")
        conn.commit()
        cur.close()
        backfill_complete = False
        backfill_in_progress = False
        return jsonify({"status": "reset", "message": "All transfers deleted"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        if conn:
            db_pool.putconn(conn)


@app.route('/api/import-transaction', methods=['POST'])
def import_transaction():
    """Import a single transaction (for syncing from local DB)"""
    try:
        ensure_db_initialized()
    except Exception as e:
        return jsonify({"error": f"Database initialization failed: {e}"}), 500
    
    data = request.json
    if not data:
        return jsonify({"error": "No data provided"}), 400
    
    transfer = {
        'signature': data.get('transaction_id', ''),
        'owner': data.get('source', ''),
        'timestamp': data.get('blocktime', 0),
        'amount': data.get('amount', 0),
        'direction': data.get('direction', 'in')
    }
    
    # Only import transactions from presale start time onwards
    if transfer['timestamp'] < PRESALE_START_TIMESTAMP:
        return jsonify({"error": "Transaction before presale start time"}), 400
    
    success = save_transfer_to_db(transfer)
    if success:
        return jsonify({"status": "imported", "transaction_id": transfer['signature']})
    else:
        return jsonify({"status": "skipped", "message": "Transaction already exists or failed to save"})


if __name__ == '__main__':
    print("=" * 80)
    print("USDC Transfers Dashboard API")
    print("=" * 80)
    print(f"Program Address: {PROGRAM_ADDRESS}")
    print(f"USDC Mint: {USDC_MINT}")
    print("\nInitializing database...")
    print("-" * 80)
    
    try:
        init_database()
    except Exception as e:
        print(f"\n✗ Failed to initialize database: {e}")
        print("\nPlease ensure PostgreSQL is running and configured correctly.")
        print("You can set environment variables:")
        print("  DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD")
        print("\nOr install PostgreSQL and create a database:")
        print("  createdb usdc_transfers")
        print("\nExiting...")
        exit(1)
    
    print("\nStarting backfill of historical transactions...")
    print("This may take a few moments...")
    print("-" * 80)
    
    # Start backfill in background thread so server can start immediately
    def run_backfill():
        backfill_historical_transactions(limit=1000)
    
    backfill_thread = threading.Thread(target=run_backfill, daemon=True)
    backfill_thread.start()
    
    print("\nStarting server on http://localhost:5000")
    print("Open http://localhost:5000 in your browser")
    print("\nBackfill is running in the background...")
    print("Check /api/backfill-status for progress")
    print("\nPress Ctrl+C to stop")
    print("=" * 80)
    
    app.run(debug=True, port=5000, use_reloader=False)

