# Local-to-Google-Drive Markdown Sync

A standalone Python utility that monitors a local folder for any changes to `.md` files and automatically syncs them to a specific Google Drive folder. It is designed to run silently in the background as a user-level process on Windows.

## Project Structure

- `sync_drive.py`: The core script that handles watchdog events and Google Drive API syncing.
- `config.json`: The configuration file mapping your local folder and target Google Drive folder.
- `start_sync.ps1`: Starts the script silently in the background, prompting for authentication first if needed.
- `stop_sync.ps1`: Stops the background process.
- `status_sync.ps1`: Displays the current status of the sync process and the last 5 log lines.
- `sync.log`: Auto-generated log file containing execution and sync history.
- `sync.pid`: File tracking the background process ID when active.

---

## Getting Started

### 1. Enable Google Drive API and Get Credentials

To allow the script to connect to your Google Drive account, you need to create a project on the Google Cloud Console and generate a desktop client configuration:

1. Go to the [Google Cloud Console](https://console.cloud.google.com/).
2. Create a new project.
3. Search for the **Google Drive API** in the API Library and enable it.
4. Go to the **OAuth consent screen** tab:
   - Choose **User Type**: **External** (or Internal if you are on a Google Workspace organization).
   - Enter basic app details (e.g., App Name: "Markdown Sync").
   - Under **Scopes**, click "Add or Remove Scopes", search for `.../auth/drive`, select it, and click save.
   - Under **Test Users**, add your Google email address.
5. Go to the **Credentials** tab:
   - Click **Create Credentials** -> **OAuth client ID**.
   - Choose **Application type**: **Desktop app**.
   - Name it (e.g., "Desktop Sync Client").
   - Click **Create**, then click the download icon (Download JSON) next to your newly created Client ID.
6. Rename this downloaded file to `credentials.json` and save it directly in this project directory (`C:\Users\Derek.Klopstein\Local Documents\Misc\google-sync\credentials.json`).

---

### 2. Configuration

Edit the `config.json` file in this directory to specify:
- `local_directory`: The path to the folder on your local machine containing the `.md` files you want to sync. (Default: `./monitored` which will be created automatically in this directory if it doesn't exist).
- `drive_folder_id`: The ID of your target Google Drive folder. You can find this ID in the URL when you open the folder in your web browser (e.g., `https://drive.google.com/drive/folders/YOUR_FOLDER_ID_HERE`).

Example `config.json`:
```json
{
    "local_directory": "./monitored",
    "drive_folder_id": "1A2B3C4D5E6F7G8H9I0J..."
}
```

---

### 3. Usage & Background Process Control

All operations can be managed using the included PowerShell scripts:

#### Authenticate & Start Sync
Run this script to start the service. If it is the very first execution, a web browser will open requesting you to sign in and grant permission to the app. Once completed, a `token.json` file will be created, and the process will run silently in the background.
```powershell
.\start_sync.ps1
```

#### Check Status & Logs
Run this script to check if the process is currently running and to inspect the most recent log entries.
```powershell
.\status_sync.ps1
```

#### Stop Sync
Run this script to stop the active background process.
```powershell
.\stop_sync.ps1
```

---

## How It Works Under the Hood

1. **Watchdog Library**: Monitors the configured local directory for `created`, `modified`, `deleted`, and `moved` events on files ending with `.md`.
2. **Google Drive API**: Uses standard v3 client calls to check if a file already exists under the target folder. If it does, it updates the content; otherwise, it uploads it as a new file. When a local file is deleted, it removes it from Drive.
3. **Windowless Process (`pythonw.exe`)**: Starting the script via `pythonw.exe` ensures that no terminal windows or console prompts remain visible while it is running.
4. **Stale Lock Mitigation**: Includes a retry loop when reading files to ensure that editors (which lock files during saving) do not cause reading errors.
