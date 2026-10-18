# PX Economy Lab — secured AI backend for Render

This backend contains **no `.env` file and no OpenAI API key**. Do not upload
such files to GitHub, Netlify, or any static web host.

## Render settings

- Runtime: Python
- Build command: `python -m compileall -q .`
- Start command: `python api_server.py`
- Health check path (optional): `/health`
- Root directory: leave blank if repository files are at its root

Configure the following **on Render → your Web Service → Environment**:

- `OPENAI_API_KEY` = your existing key (value is secret)
- `PX_LLM_ENABLED` = `1`
- `PX_LLM_MODEL` = `gpt-5.6-luna` (or another model you can access)
- `PX_LLM_REASONING_EFFORT` = `low`
- `PX_API_PASSWORD` = a **different**, strong access password at least 20 characters long; this is NOT the API key
- `PX_ALLOWED_ORIGIN` = `https://YOUR-NETLIFY-SITE.netlify.app` (replace with your precise Netlify URL, no trailing slash)

Optional safety limits: `PX_LLM_MAX_CALLS=2`, `PX_LLM_TOTAL_SECONDS=75`,
`PX_LLM_SESSION_TOKEN_BUDGET=160000`. If you do not set them, the original
application's defaults apply.

The publicly accessible `GET /health` endpoint returns `{ "status": "ok" }`
when the server is alive. Other `/api/*` endpoints require the independent
`PX_API_PASSWORD`; browser requests are allowed only from `PX_ALLOWED_ORIGIN`.

## Connect Netlify

1. Copy the Render service URL such as `https://my-px-backend.onrender.com`.
2. Extract the **Netlify-Connected** ZIP.
3. Open `api-config.js` in that folder and replace the URL in quotes.
4. Drag the whole folder to the **Deploys** dropzone of the **existing** Netlify project.
5. Visit the Netlify website; on the Economy data page choose **Unlock AI**,
   enter `PX_API_PASSWORD` (NOT `OPENAI_API_KEY`), and select **Test connection**.

Keep the API access password private. Sharing it allows others to call the
OpenAI-backed features at your expense. Set budgets in your OpenAI account.
