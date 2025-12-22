# Database Setup Guide

## Option 1: Vercel Postgres (Recommended)

1. Go to your Vercel project dashboard: https://vercel.com/jay-ows-projects/solstice-presale/storage
2. Click "Create Database" → Select "Postgres"
3. Choose a plan (Free tier is available)
4. Vercel will automatically configure environment variables

After setup, you'll get:
- `POSTGRES_URL` - Connection string
- `POSTGRES_PRISMA_URL` - Prisma connection string
- `POSTGRES_URL_NON_POOLING` - Direct connection string

## Option 2: Neon (Free PostgreSQL)

1. Go to https://neon.tech
2. Sign up for a free account
3. Create a new project
4. Copy your connection string (looks like: `postgres://user:password@host/dbname`)

Then add to Vercel:
```bash
echo "your-neon-connection-string" | vercel env add POSTGRES_URL production
echo "your-neon-connection-string" | vercel env add POSTGRES_URL preview
echo "your-neon-connection-string" | vercel env add POSTGRES_URL development
```

## Option 3: Supabase (Free PostgreSQL)

1. Go to https://supabase.com
2. Create a new project
3. Go to Settings → Database
4. Copy the connection string

Then add to Vercel:
```bash
echo "your-supabase-connection-string" | vercel env add POSTGRES_URL production
echo "your-supabase-connection-string" | vercel env add POSTGRES_URL preview
echo "your-supabase-connection-string" | vercel env add POSTGRES_URL development
```

## After Database Setup

1. Run the database setup script on your database:
   ```bash
   psql "your-connection-string" -f setup_database.sh
   ```

2. Update the Flask app to use `POSTGRES_URL` if using Vercel Postgres

3. Redeploy:
   ```bash
   vercel --prod
   ```

