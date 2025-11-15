ARTIFACT 6: README.md
Stock Data Repository 
Automated stock data collection and RS (Relative Strength) scoring system using Polygon.io API. Generates JSON files for consumption by React web applications.
Overview
This repository automatically:
	•	Weekly (Fridays 4:05 PM EST): Full rebuild of all stock data with 12 months of history
	•	Daily (Mon-Thu 4:05 PM EST): Updates with latest trading day data
Data Output
rankings.json
Main file for React app consumption with:
	•	RS rankings (1-99 percentile scores)
	•	Formatted returns and volumes
	•	All metrics needed for display
historical_data.json
Compressed historical data for daily updates:
	•	Rolling 12-month window
	•	Minimal storage format
	•	S&P 500 benchmark data
RS Score Calculation
Uses IBD-style formula:
RS = 2×(3-month relative) + (6-month relative) + (9-month relative) + (12-month relative)
Where: relative return = (stock return - S&P 500 return)
Setup Instructions
1. Create GitHub Repository
	1	Go to GitHub and create a new repository
	2	Clone it locally: git clone https://github.com/YOUR_USERNAME/YOUR_REPO_NAME.gitcd YOUR_REPO_NAME
	3	
2. Add Files to Repository
Create the following file structure:
your-repo/
├── process_stocks.py
├── process_stocks_daily.py
├── requirements.txt
├── .github/
│   └── workflows/
│       ├── weekly-refresh.yml
│       └── daily-update.yml
└── README.md
Copy the contents from the artifacts into each file.
3. Configure GitHub Secrets
Required Secrets:
Go to your repository → Settings → Secrets and variables → Actions → New repository secret
Add the following secrets:
Secret Name
Description
Example
POLYGON_API_KEY
Your Polygon.io API key
your_polygon_api_key_here
EMAIL_USERNAME
Gmail address for notifications
tacticaltrades1@gmail.com
EMAIL_PASSWORD
Gmail App Password (see below)
xxxx xxxx xxxx xxxx
Setting up Gmail App Password:
	1	Go to your Google Account settings
	2	Navigate to Security → 2-Step Verification (enable if not already)
	3	Scroll to "App passwords" at the bottom
	4	Select "Mail" and "Other (Custom name)"
	5	Name it "GitHub Actions" and generate
	6	Copy the 16-character password (spaces will be removed automatically)
	7	Use this as EMAIL_PASSWORD secret
4. Configure Repository Permissions
Enable GitHub Actions to write to repository:
	1	Go to repository → Settings → Actions → General
	2	Scroll to "Workflow permissions"
	3	Select "Read and write permissions"
	4	Check "Allow GitHub Actions to create and approve pull requests"
	5	Click Save
5. Initial Commit and Push
git add .
git commit -m "Initial setup: Stock data collection system"
git push origin main
6. Manual First Run (Recommended)
Before waiting for the Friday schedule, manually trigger the weekly refresh:
	1	Go to repository → Actions tab
	2	Click "Weekly Stock Data Refresh" workflow
	3	Click "Run workflow" → "Run workflow" button
	4	Monitor the run (takes 15-30 minutes for all stocks)
This will generate the initial rankings.json and historical_data.json files.
Workflow Schedules
Weekly Refresh
	•	When: Every Friday at 4:05 PM EST (21:05 UTC)
	•	What: Full rebuild of all stock data
	•	Duration: 15-30 minutes (depending on number of stocks)
	•	File: .github/workflows/weekly-refresh.yml
Daily Update
	•	When: Monday-Thursday at 4:05 PM EST (21:05 UTC)
	•	What: Updates yesterday's OHLC data
	•	Duration: 10-15 minutes
	•	File: .github/workflows/daily-update.yml
Adjusting Schedule Times
To change the schedule times, edit the cron expressions in the workflow files:
schedule:
  - cron: '5 21 * * 5'  # Minute Hour DayOfMonth Month DayOfWeek
Cron format: minute hour day month dayofweek
Examples:
	•	0 16 * * 5 = 4:00 PM UTC every Friday
	•	30 20 * * 1-4 = 8:30 PM UTC Monday-Thursday
⚠️ Note: GitHub Actions uses UTC time. EST = UTC-5, EDT = UTC-4
Monitoring
Check Workflow Status
	1	Go to repository → Actions tab
	2	View recent workflow runs
	3	Click on any run to see detailed logs
Email Notifications
	•	Automatically sent to tacticaltrades1@gmail.com on failure
	•	Includes link to failed workflow run
	•	Check spam folder if not receiving
Troubleshooting
Workflow Not Running
	•	Verify repository permissions (Step 4 above)
	•	Check that secrets are properly set
	•	Ensure workflows are enabled in Actions tab
API Rate Limiting
	•	Polygon Starter plan: Unlimited calls with 5 calls/second limit
	•	Built-in rate limiting: 0.2 seconds between calls
	•	If issues persist, increase sleep time in Python files
Failed Updates
	•	Check email for failure notifications
	•	Review workflow logs in Actions tab
	•	Common issues:
	◦	Invalid API key
	◦	Network timeout
	◦	Missing historical_data.json (run weekly refresh first)
Missing Stocks
	•	ETFs and warrants are filtered out automatically
	•	Stocks need 252 trading days (12 months) of data
	•	New IPOs with insufficient data are excluded
Manual Execution
You can manually trigger workflows anytime:
	1	Go to Actions tab
	2	Select workflow (Weekly or Daily)
	3	Click "Run workflow"
	4	Select branch (usually main)
	5	Click "Run workflow" button
Data Size Estimates
	•	rankings.json: ~3-5 MB (formatted, readable)
	•	historical_data.json: ~20-40 MB (compressed format)
	•	Both well under GitHub's 100 MB file limit
Using Data in React App
Fetch Rankings
const response = await fetch('https://raw.githubusercontent.com/YOUR_USERNAME/YOUR_REPO/main/rankings.json');
const data = await response.json();

console.log(`Total stocks: ${data.total_stocks}`);
console.log(`Last updated: ${data.last_updated}`);
console.log(`Top stock: ${data.data[0].symbol} (RS: ${data.data[0].rs_rank})`);
Filter High RS Stocks
const highRS = data.data.filter(stock => stock.rs_rank >= 90);
Support
For issues or questions:
	•	Open an issue in this repository
	•	Check workflow logs in Actions tab
	•	Verify secrets are correctly configured
License
This is a private data collection system for personal use.
