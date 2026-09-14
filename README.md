# Salesforce Query Studio

A Streamlit-based Salesforce toolkit for running SOQL queries, exploring object metadata, and managing records directly from your browser.

<!-- Badges -->
[![Python](https://img.shields.io/badge/Python-3.10%2B-blue?logo=python&logoColor=white)](https://www.python.org/)
[![Streamlit - Live Demo](https://static.streamlit.io/badges/streamlit_badge_black_white.svg)](https://sf-query-studio.streamlit.app/)

## Overview

This app provides a clean, dark-themed interface for:

- Connecting to a Salesforce org using username, password, and optional security token.
- Running ad hoc `SELECT` SOQL queries and viewing results in an interactive table.
- Using the new “Ask in Plain English” helper to turn natural-language requests into SOQL queries.
- Chatting with a read-only Salesforce assistant that answers questions about your connected org and about Salesforce in general.
- Downloading query results as CSV.
- Loading Salesforce records for inline editing, insert, update, and delete operations.
- Exploring Salesforce object metadata, field counts, relationships, picklists, and field type distributions.
- Managing custom objects and fields, including new Field-Level Security (FLS) support for assigning profile-based read and edit access.

## Features

### 1. Salesforce Connection

Found under the `Configuration` page:

- Choose between `Production` and `Sandbox` environments.
- Enter Salesforce username and password.
- Provide a security token when required by your org.
- Test the connection and display success or troubleshooting hints.

### 2. SOQL Query Editor

Found under the `Salesforce SOQL Editor` page:

- Write any valid `SELECT` SOQL query.
- Use the new “Ask in Plain English” feature to describe the data you want in plain language and generate or refine a SOQL query.
- Execute the query and show response data in a sortable Streamlit table.
- Support for relationship fields and child relationship expansion in query results.
- Download query results as a CSV file.

### 3. Inline Record Editor

Also on the `Salesforce SOQL Editor` page:

- Select a Salesforce object and choose fields to display.
- Load records using an optional `WHERE` clause.
- Edit returned records directly in a spreadsheet-like editor.
- Insert new rows, update modified rows, and delete checked rows.
- Automatically detect real changes to avoid unnecessary updates.

### 4. Bulkification

Also on the `Salesforce SOQL Editor` page:

- Perform bulk record operations in the SOQL editor using Salesforce-compliant batch logic.
- Select multiple records and apply insert, update, or delete actions together.
- Reduce API round trips and improve throughput for large data changes.
- View bulk operation progress and error feedback directly in the app.

### 5. Field Analysis

Found under the `Field Analysis` page:

- Analyze any Salesforce object metadata.
- Show total field counts, custom fields, required fields, relationships, and child relations.
- Display field type distributions with Plotly charts.
- Browse detailed field rows with labels, types, lookup relationships, and custom field flags.
- Inspect picklist values for picklist and multipicklist fields.

### 6. Object Manager

Found under the `Object Manager` page:

- Create new custom objects and define custom fields (Text, Number, Picklist, etc.) using the Metadata API.
- Modify or delete existing custom fields on any object.
- Apply Field-Level Security (FLS) when creating or updating fields, including profile-based read and edit permissions.
- Set default FLS behavior for newly created fields to streamline field rollout across profiles.
- Browse all available Salesforce objects in the connected org.
- View object labels, API names, field counts, and record counts at a glance.
- Search and filter objects for faster navigation.
- Expand object details to inspect schema metadata and relationship summaries.

### 7. Session Information

Found under the `Session Information` page:

- Display the current Salesforce connection status and org details.
- Show the active username, instance URL, and API version in use.
- Provide helpful connection diagnostics for troubleshooting login issues.
- Allow users to verify whether the app is connected to Production or Sandbox.
- Useful for verifying that the app is connected to the correct Salesforce org before performing operations.

### 8. Salesforce Chatbot

Found under the `SF Chatbot` page:

- Ask plain-English questions about the org you are currently connected to, answered with live read-only SOQL run through your own Salesforce session.
- Ask general Salesforce questions — platform concepts, admin and developer how-to, terminology, SOQL and Apex syntax — answered directly without touching your org.
- Ask how any SF Query Studio page works, including access modes and what each page can and cannot do.
- Inspect every answer: an expandable "SOQL evidence" panel shows the exact query that was run, the records it returned, and whether a `LIMIT` was applied automatically.
- See an "Actions" trail under each answer listing the metadata lookups and queries used to build it.

Design constraints worth knowing:

- **Read-only, always.** The assistant can only run `SELECT` queries. Statements that attempt DML (`INSERT`, `UPDATE`, `DELETE`), stacked statements, and row-locking clauses such as `FOR UPDATE` are rejected before Salesforce is contacted. This holds even in Admin mode — the assistant will explain how to make a change and point you at the SOQL Editor or Object Manager, but never performs one.
- **Scoped to Salesforce.** Questions unrelated to Salesforce or this app are declined.
- **Session-bound.** The conversation lives only in your browser session. It is cleared automatically when you disconnect, reconnect, or connect as a different user, so one user's questions and results are never visible to the next.
- **Bounded reads.** A query without a `LIMIT` automatically receives `LIMIT 100`, so a broad question cannot page through an entire object.
- Requires an OpenAI API key — see [AI Feature Configuration](#ai-feature-configuration).

## AI Feature Configuration

Two pages use the OpenAI API and need an API key: the “Ask in Plain English” helper on the `Salesforce SOQL Editor` page, and the `SF Chatbot` page. Every other feature works without one.

Create `.streamlit/secrets.toml` in the repository root:

```toml
OPENAI_API_KEY = "sk-your-key-here"
```

Alternatively, set it as an environment variable:

```bash
export OPENAI_API_KEY="sk-your-key-here"   # macOS / Linux
$env:OPENAI_API_KEY = "sk-your-key-here"   # Windows PowerShell
```

Without a key, the `SF Chatbot` page shows a configuration notice and disables its input rather than failing at runtime.

> **Important:** `.streamlit/secrets.toml` is listed in `.gitignore`. Keep it that way — never commit an API key.

### What is sent to OpenAI

Be deliberate about this before pointing the AI features at a Production org:

- **Sent:** your question, the recent conversation turns, your Salesforce username, your profile name, the org instance hostname, and **the records and field metadata returned by the queries the assistant runs**. If your org holds personal or regulated data, that data may leave your infrastructure.
- **Never sent:** your Salesforce password, security token, or API session ID. The assistant's own Salesforce access is confined to your existing session.

If this matters for your organization, review your OpenAI account's data-retention terms (and whether you need a Data Processing Agreement or zero-retention configuration) before use, or run the AI features against a sandbox with non-sensitive data.

## Repository Structure

The project is organized around a main app entry point, a small set of shared utilities, and a multi-page Streamlit interface:

- `Home.py` - Main Streamlit entry point, homepage layout, and overall app styling.
- `permissions.py` - Shared helpers for loading Salesforce profile permissions, applying read-only safeguards, and controlling access to admin-level features.
- `pages/1_⚙️_Configuration.py` - Connection setup page for authenticating to Salesforce and selecting the environment.
- `pages/2_📝_Salesforce_SOQL_Editor.py` - SOQL editor for running queries, viewing results, and managing records inline.
- `pages/3_📊_Field_Analysis.py` - Metadata explorer for analyzing fields, relationships, picklists, and field type distributions.
- `pages/4_📦_Object_Manager.py` - Object and field management experience for creating, editing, and configuring custom metadata.
- `pages/5_👤_Session_Info.py` - Session diagnostics page showing the active connection details and org information.
- `pages/6_🤖_SF_Chatbot.py` - Read-only Salesforce assistant that answers questions about the connected org and about Salesforce, with SOQL evidence for every answer.
- `requirements.txt` - Python dependencies required to run the app.
- `.gitignore` - Lists files and folders that Git should ignore, such as virtual environments, local secrets, and editor-specific artifacts.
- `LICENSE` - Contains the open-source license terms for the project.
- `README.md` - Provides project overview, setup instructions, usage guidance, and feature documentation.

## Dependencies

The app relies on the following packages:

- `streamlit`
- `pandas`
- `simple-salesforce`
- `plotly`
- `requests`
- `zeep`
- `openai` - used by the “Ask in Plain English” helper and the `SF Chatbot` page

Python 3.10 or newer is required.

## Installation

1. Create a Python virtual environment:

```bash
python -m venv .venv
```

2.Activate the virtual environment:

Windows PowerShell:

```powershell
.\.venv\Scripts\Activate.ps1
```

3.Install dependencies:

```bash
pip install -r requirements.txt
```

## Running the App

From the repository root, run:

```bash
streamlit run Home.py
```

Then open the URL shown in your browser (usually `http://localhost:8501`).

## Salesforce Connection Notes

- Use `Production` for a live org and `Sandbox` for developer/test instances.
- If your org enforces IP restrictions, include your Salesforce security token.
- If your IP is already trusted, leave the security token blank.
- Common connection issues include invalid credentials, missing security token, and selecting the wrong environment.

## Usage Flow

1. Open the app in your browser.
2. Go to the `Configuration` page and connect to Salesforce.
3. Use the `Salesforce SOQL Editor` page to run queries and manage records.
4. Use the `Field Analysis` page to inspect object metadata and picklist values.
5. Use the `SF Chatbot` page to ask questions about your org or about Salesforce in plain English, and copy the SOQL it shows into the editor when you want to go deeper.

## Troubleshooting

- `INVALID_LOGIN` means your username or password is incorrect, or the org selection is wrong.
- `security token` errors indicate that a token is required by your Salesforce org.
- `Could not connect` or `404` errors usually mean the wrong environment was selected (Production vs Sandbox).
- `OPENAI_API_KEY is not configured` on the `SF Chatbot` page means no key was found in `.streamlit/secrets.toml` or the environment — see [AI Feature Configuration](#ai-feature-configuration).
- If the chatbot reports that the API key was rejected or that a rate limit was reached, the problem is with the OpenAI account rather than the Salesforce connection; check the key and your usage quota.

## Notes

- The app is designed for Salesforce admins, analysts, and developers who need quick query and data editing capabilities without switching to Salesforce UI.
- The app uses the Salesforce REST API via `simple-salesforce` and requires valid Salesforce credentials.

## Live Demo

You can try the hosted version of this app here:

- [opens the deployed Streamlit app](https://sf-query-studio.streamlit.app/)

Note: The deployed demo may not include a working Salesforce connection for security reasons — use your own credentials via the `Configuration` page when running locally or in a trusted environment.

## Quick Start

1. Clone the repository:

```bash
git clone https://github.com/abuawaish/salesforce_db_app.git
cd salesforce_db_app
```

2.Create and activate a Python virtual environment (recommended):

```bash
python -m venv .venv
source .venv/bin/activate  # macOS / Linux
.\.venv\Scripts\Activate.ps1 # Windows PowerShell
```

3.Install requirements and run the app:

```bash
pip install -r requirements.txt
streamlit run Home.py
```

4.Optional — enable the AI features (“Ask in Plain English” and `SF Chatbot`) by adding your OpenAI key to `.streamlit/secrets.toml`:

```toml
OPENAI_API_KEY = "sk-your-key-here"
```

## Security & Privacy

- This app requires Salesforce credentials (username, password, and optionally a security token). Do not commit credentials to version control.
- Store secrets securely using environment variables, Streamlit secrets, or a secrets manager rather than hard-coding them into source files. This applies to your OpenAI API key as well — keep it in `.streamlit/secrets.toml`, which is already gitignored.
- Use least-privilege access when connecting to Salesforce. The app should only be used with accounts that have the minimum permissions needed for the intended operations.
- Be mindful of data exposure: SOQL results, record edits, and object metadata can contain sensitive business information. Avoid sharing screenshots or exports that include confidential data.
- The AI features send org data to OpenAI. Review [What is sent to OpenAI](#what-is-sent-to-openai) before enabling them against a Production org.
- Salesforce remains the real permission boundary. The app's Admin mode only unlocks features for users whose Salesforce profile already grants "Modify All Data" or "Customize Application"; it cannot grant access your org does not.
- If your org enforces IP whitelisting, you can leave the security token blank when your IP is already trusted in Salesforce.
- When deploying publicly, ensure your app is protected behind authentication and that any hosted environment is configured to avoid leaking session or credential information.
- Review any generated reports, exports, or copied query results before sharing them externally.

## Contributing

Contributions are welcome. Suggested workflow:

1. Fork the repo and create a feature branch.
2. Add tests for new functionality where appropriate.
3. Open a pull request describing your changes.

## Contact

If you have questions, run into issues, or want to suggest improvements, please open an issue in the GitHub repository or reach out to the maintainer via GitHub: abuawaish.

Contributions and feedback are always welcome.
