# Deploying to Vercel

This guide explains how to deploy the Solstice Presale dashboard to Vercel.

## Prerequisites

1. A Vercel account (sign up at https://vercel.com)
2. A PostgreSQL database (recommended: [Supabase](https://supabase.com), [Neon](https://neon.tech), or [Railway](https://railway.app))
3. Your Helius API key

## Setup Steps

### 1. Database Setup

Set up a PostgreSQL database on one of these platforms:
- **Supabase**: https://supabase.com (free tier available)
- **Neon**: https://neon.tech (free tier available)
- **Railway**: https://railway.app

After creating your database, note down:
- Database host
- Database port (usually 5432)
- Database name
- Database user
- Database password
- Connection string (if available)

### 2. Run Database Setup Script

Connect to your database and run the setup script:

```bash
# Using psql
psql -h YOUR_HOST -U YOUR_USER -d YOUR_DATABASE -f setup_database.sh

# Or manually run the SQL from setup_database.sh
```

### 3. Deploy to Vercel

#### Option A: Using Vercel CLI

1. Install Vercel CLI:
```bash
npm i -g vercel
```

2. Login to Vercel:
```bash
vercel login
```

3. Deploy:
```bash
vercel
```

4. Set environment variables:
```bash
vercel env add HELIUS_API_KEY
vercel env add DB_HOST
vercel env add DB_PORT
vercel env add DB_NAME
vercel env add DB_USER
vercel env add DB_PASSWORD
```

#### Option B: Using Vercel Dashboard

1. Go to https://vercel.com/new
2. Import your GitHub repository: `jayow/solstice_presale`
3. Configure the project:
   - **Framework Preset**: Other
   - **Root Directory**: ./
   - **Build Command**: (leave empty)
   - **Output Directory**: ./

4. Add Environment Variables:
   - `HELIUS_API_KEY`: Your Helius API key
   - `DB_HOST`: Your PostgreSQL host
   - `DB_PORT`: `5432` (or your port)
   - `DB_NAME`: Your database name
   - `DB_USER`: Your database user
   - `DB_PASSWORD`: Your database password

5. Click "Deploy"

### 4. Update Frontend API URL

After deployment, update the API URL in `usdc_dashboard.html`:

```javascript
// Change from:
const API_BASE = 'http://localhost:5000/api';

// To your Vercel URL:
const API_BASE = 'https://your-app.vercel.app/api';
```

Or better yet, use a relative path:
```javascript
const API_BASE = '/api';
```

### 5. Important Notes

- **Serverless Functions**: Vercel runs Flask as serverless functions, which means:
  - Each API request is handled independently
  - Background threads may not work as expected
  - Consider using Vercel Cron Jobs for periodic tasks instead of `setInterval`

- **Database Connections**: Use connection pooling carefully. The current implementation uses `SimpleConnectionPool` which may need adjustment for serverless.

- **Cold Starts**: First request after inactivity may be slower due to cold starts.

- **Environment Variables**: Make sure all environment variables are set in Vercel dashboard under Settings > Environment Variables.

## Troubleshooting

### Database Connection Issues
- Verify your database allows connections from Vercel's IP ranges
- Check that all environment variables are set correctly
- Test the connection string locally first

### API Not Working
- Check Vercel function logs in the dashboard
- Verify the API routes are correctly configured in `vercel.json`
- Ensure Flask-CORS is configured to allow your frontend domain

### Background Tasks Not Running
- Consider using Vercel Cron Jobs (https://vercel.com/docs/cron-jobs) for periodic tasks
- Or use an external service like GitHub Actions or a separate server for background processing

## Alternative: Separate Frontend and Backend

If you encounter issues with the serverless setup, consider:
1. Deploy frontend (`usdc_dashboard.html`) as a static site on Vercel
2. Deploy backend (`usdc_transfers_api.py`) on a platform like:
   - Railway (https://railway.app)
   - Render (https://render.com)
   - Fly.io (https://fly.io)
   - Heroku (https://heroku.com)

