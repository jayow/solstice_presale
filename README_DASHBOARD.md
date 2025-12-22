# USDC Transfers Dashboard

A real-time dashboard that monitors USDC transfers for a Solana program address with PostgreSQL backend for easy indexing and querying.

## Features

- 🔄 Real-time monitoring (checks every 5 seconds)
- 💰 Total amount tracking
- 📊 Transaction flow visualization
- 🕐 UTC timestamp conversion
- 🎨 Modern, responsive UI
- ⚡ Only shows new transactions (no duplicates)
- 🗄️ PostgreSQL backend with indexes for fast queries
- 📈 Historical data backfill on startup

## Setup

### 1. Install PostgreSQL

**macOS:**
```bash
brew install postgresql@14
brew services start postgresql@14
```

**Ubuntu/Debian:**
```bash
sudo apt-get update
sudo apt-get install postgresql postgresql-contrib
sudo systemctl start postgresql
```

**Or download from:** https://www.postgresql.org/download/

### 2. Setup Database

Run the setup script:
```bash
./setup_database.sh
```

Or manually:
```bash
createdb usdc_transfers
```

### 3. Install Python Dependencies

```bash
pip3 install -r requirements.txt
```

### 4. Configure Database (Optional)

If you need custom database settings, set environment variables:
```bash
export DB_HOST=localhost
export DB_PORT=5432
export DB_NAME=usdc_transfers
export DB_USER=postgres
export DB_PASSWORD=your_password
```

### 5. Start the Server

```bash
python3 usdc_transfers_api.py
```

### 6. Open Dashboard

Navigate to:
```
http://localhost:5000
```

## How It Works

- The backend API polls the Helius RPC endpoint every 5 seconds
- It tracks which transactions have already been seen
- Only new transactions are returned to the frontend
- The frontend displays transactions in real-time with animations
- Blocktimes are automatically converted to UTC format

## API Endpoints

- `GET /` - Serves the dashboard HTML
- `GET /api/new-transfers` - Returns only new transfers since last check
- `GET /api/stats` - Returns total statistics from database
- `GET /api/backfill-status` - Get backfill progress status
- `GET /api/backfill` - Manually trigger backfill
- `GET /api/transfers` - Get transfers with pagination and filtering
  - Query params: `limit`, `offset`, `source`, `direction`
- `GET /api/reset` - Resets database (WARNING: deletes all data)

## Database Schema

The `transfers` table has the following structure:

```sql
CREATE TABLE transfers (
    id SERIAL PRIMARY KEY,
    transaction_id VARCHAR(88) UNIQUE NOT NULL,
    source VARCHAR(44) NOT NULL,
    blocktime BIGINT NOT NULL,
    blocktime_utc TIMESTAMP,
    amount DECIMAL(20, 6) NOT NULL,
    direction VARCHAR(10) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

**Indexes:**
- `idx_transaction_id` - Fast lookup by transaction ID
- `idx_blocktime` - Fast sorting by blocktime (DESC)
- `idx_source` - Fast filtering by source address
- `idx_direction` - Fast filtering by direction (in/out)
- `idx_blocktime_utc` - Fast sorting by UTC timestamp

## Example Queries

**Get transfers for a specific source:**
```bash
curl "http://localhost:5000/api/transfers?source=YOUR_ADDRESS&limit=50"
```

**Get only incoming transfers:**
```bash
curl "http://localhost:5000/api/transfers?direction=in&limit=100"
```

**Get paginated results:**
```bash
curl "http://localhost:5000/api/transfers?limit=50&offset=100"
```

## Configuration

Edit `usdc_transfers_api.py` to change:
- Program address
- USDC mint address
- Helius API endpoint
- Polling interval (currently 5 seconds)

