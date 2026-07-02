import os
import sys
import time
import json
import logging
import argparse
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from googleapiclient.errors import HttpError
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

# Setup logging
logging.basicConfig(
    filename='sync.log',
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
# Add console logging as well
console = logging.StreamHandler(sys.stdout)
console.setLevel(logging.INFO)
console.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
logging.getLogger('').addHandler(console)

SCOPES = ['https://www.googleapis.com/auth/drive']

def get_drive_service():
    creds = None
    if os.path.exists('token.json'):
        creds = Credentials.from_authorized_user_file('token.json', SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not os.path.exists('credentials.json'):
                raise FileNotFoundError(
                    "credentials.json file is missing! Please place your Google API desktop client "
                    "credentials.json in the same directory as this script."
                )
            flow = InstalledAppFlow.from_client_secrets_file(
                'credentials.json', SCOPES)
            creds = flow.run_local_server(port=0)
        with open('token.json', 'w') as token:
            token.write(creds.to_json())
    return build('drive', 'v3', credentials=creds, cache_discovery=False)

def sync_file(file_path, folder_id, service):
    if not os.path.exists(file_path):
        return
    
    filename = os.path.basename(file_path)
    logging.info(f"Syncing file: {filename}")
    
    # Retry loop in case file is temporarily locked or still writing
    for attempt in range(5):
        try:
            with open(file_path, 'rb') as f:
                pass
            break
        except (IOError, PermissionError) as e:
            logging.debug(f"File {filename} is temporarily unreadable, waiting to retry... ({e})")
            time.sleep(0.5)
    else:
        logging.error(f"Cannot read file {file_path} after 5 attempts. Skipping sync.")
        return

    try:
        # Search if file already exists in target Drive folder
        q = f"name = '{filename}' and '{folder_id}' in parents and trashed = false"
        results = service.files().list(q=q, fields="files(id, name)").execute()
        files = results.get('files', [])
        
        media = MediaFileUpload(file_path, mimetype='text/markdown', resumable=True)
        
        if files:
            file_id = files[0]['id']
            service.files().update(fileId=file_id, media_body=media).execute()
            logging.info(f"Successfully updated file on Drive: {filename} (ID: {file_id})")
        else:
            file_metadata = {
                'name': filename,
                'parents': [folder_id]
            }
            new_file = service.files().create(body=file_metadata, media_body=media, fields='id').execute()
            logging.info(f"Successfully created file on Drive: {filename} (ID: {new_file.get('id')})")
            
    except HttpError as error:
        logging.error(f"Google Drive API error syncing {filename}: {error}")
    except Exception as e:
        logging.error(f"Unexpected error syncing {filename}: {e}")

def delete_file(file_path, folder_id, service):
    filename = os.path.basename(file_path)
    logging.info(f"Deleting file from Drive: {filename}")
    
    try:
        # Search for file on Drive
        q = f"name = '{filename}' and '{folder_id}' in parents and trashed = false"
        results = service.files().list(q=q, fields="files(id, name)").execute()
        files = results.get('files', [])
        
        if not files:
            logging.info(f"File not found on Drive, no deletion needed: {filename}")
            return
            
        for file in files:
            file_id = file['id']
            service.files().delete(fileId=file_id).execute()
            logging.info(f"Successfully deleted file from Drive: {filename} (ID: {file_id})")
            
    except HttpError as error:
        logging.error(f"Google Drive API error deleting {filename}: {error}")
    except Exception as e:
        logging.error(f"Unexpected error deleting {filename}: {e}")

class MarkdownSyncHandler(FileSystemEventHandler):
    def __init__(self, service, folder_id):
        self.service = service
        self.folder_id = folder_id

    def on_created(self, event):
        if not event.is_directory and event.src_path.lower().endswith('.md'):
            logging.info(f"Detected creation event: {event.src_path}")
            sync_file(event.src_path, self.folder_id, self.service)

    def on_modified(self, event):
        if not event.is_directory and event.src_path.lower().endswith('.md'):
            logging.info(f"Detected modification event: {event.src_path}")
            sync_file(event.src_path, self.folder_id, self.service)

    def on_deleted(self, event):
        if not event.is_directory and event.src_path.lower().endswith('.md'):
            logging.info(f"Detected deletion event: {event.src_path}")
            delete_file(event.src_path, self.folder_id, self.service)

    def on_moved(self, event):
        if not event.is_directory:
            if event.src_path.lower().endswith('.md'):
                logging.info(f"Detected file moved out / renamed: {event.src_path}")
                delete_file(event.src_path, self.folder_id, self.service)
            if event.dest_path.lower().endswith('.md'):
                logging.info(f"Detected file moved in / renamed: {event.dest_path}")
                sync_file(event.dest_path, self.folder_id, self.service)

def load_config(config_path):
    if not os.path.exists(config_path):
        default_config = {
            "local_directory": "./monitored",
            "drive_folder_id": "YOUR_GOOGLE_DRIVE_FOLDER_ID_HERE"
        }
        with open(config_path, 'w') as f:
            json.dump(default_config, f, indent=4)
        logging.info(f"Created default config template: {config_path}")
        print(f"Created default config template: {config_path}")
        print("Please configure 'local_directory' and 'drive_folder_id' in config.json.")
        sys.exit(0)
        
    with open(config_path, 'r') as f:
        config = json.load(f)
        
    local_dir = config.get("local_directory", "./monitored")
    local_dir = os.path.abspath(os.path.expanduser(local_dir))
    config["local_directory"] = local_dir
    
    return config

def parse_args():
    parser = argparse.ArgumentParser(description="Watch local directory and sync .md changes to Google Drive.")
    parser.add_argument("--config", default="config.json", help="Path to config.json file")
    parser.add_argument("--check-auth", action="store_true", help="Run OAuth flow to generate token.json, then exit")
    return parser.parse_args()

def main():
    args = parse_args()
    
    # If the user just wants to run authentication check and exit
    if args.check_auth:
        try:
            print("Checking authentication...")
            get_drive_service()
            print("Authentication checked and active (token.json is valid).")
            sys.exit(0)
        except Exception as e:
            print(f"Error checking authentication: {e}", file=sys.stderr)
            sys.exit(1)
            
    config = load_config(args.config)
    local_dir = config["local_directory"]
    folder_id = config["drive_folder_id"]
    
    if folder_id == "YOUR_GOOGLE_DRIVE_FOLDER_ID_HERE" or not folder_id:
        logging.error("Please set a valid 'drive_folder_id' in config.json.")
        print("Error: Please set a valid 'drive_folder_id' in config.json.", file=sys.stderr)
        sys.exit(1)
        
    if not os.path.exists(local_dir):
        os.makedirs(local_dir, exist_ok=True)
        logging.info(f"Created local monitored directory: {local_dir}")
        
    logging.info(f"Initializing sync service. Monitoring local directory: {local_dir}")
    
    try:
        service = get_drive_service()
    except Exception as e:
        logging.error(f"Failed to authenticate with Google Drive API: {e}")
        print(f"Failed to authenticate: {e}", file=sys.stderr)
        sys.exit(1)
        
    # Write process ID to sync.pid to manage the background process
    pid_file = "sync.pid"
    try:
        with open(pid_file, 'w') as f:
            f.write(str(os.getpid()))
        logging.info(f"Started sync process with PID {os.getpid()}")
    except Exception as e:
        logging.warning(f"Could not write PID file: {e}")
        
    event_handler = MarkdownSyncHandler(service, folder_id)
    observer = Observer()
    observer.schedule(event_handler, path=local_dir, recursive=False)
    observer.start()
    
    logging.info("Watchdog observer started. Monitoring...")
    
    try:
        while True:
            time.sleep(1)
    except (KeyboardInterrupt, SystemExit):
        logging.info("Stopping Watchdog observer...")
        observer.stop()
    finally:
        observer.join()
        if os.path.exists(pid_file):
            try:
                os.remove(pid_file)
            except Exception:
                pass
        logging.info("Sync process stopped.")

if __name__ == "__main__":
    main()
