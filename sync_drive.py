import os
import sys
import time
import json
import logging
import argparse
import datetime
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

def download_file(file_id, local_path, service):
    try:
        request = service.files().get_media(fileId=file_id)
        file_content = request.execute()
        with open(local_path, 'wb') as f:
            f.write(file_content)
        return True
    except Exception as e:
        logging.error(f"Error downloading file {file_id} to {local_path}: {e}")
        return False

drive_folder_id_cache = {}

def is_ignored_path(path, local_dir):
    rel_path = os.path.relpath(path, local_dir)
    parts = rel_path.split(os.sep)
    for part in parts:
        if part.startswith('.') and part != '.' and part != '..':
            return True
    return False

def get_or_create_drive_folder(local_dir, file_path, root_folder_id, service):
    file_dir = os.path.dirname(file_path)
    rel_dir = os.path.relpath(file_dir, local_dir)
    
    if rel_dir == '.':
        return root_folder_id
        
    normalized_rel_dir = os.path.normpath(rel_dir)
    if normalized_rel_dir in drive_folder_id_cache:
        return drive_folder_id_cache[normalized_rel_dir]
        
    parts = normalized_rel_dir.split(os.sep)
    current_parent_id = root_folder_id
    current_rel_path = ""
    
    for part in parts:
        current_rel_path = os.path.join(current_rel_path, part) if current_rel_path else part
        normalized_part_path = os.path.normpath(current_rel_path)
        
        if normalized_part_path in drive_folder_id_cache:
            current_parent_id = drive_folder_id_cache[normalized_part_path]
            continue
            
        q = f"name = '{part}' and '{current_parent_id}' in parents and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
        try:
            results = service.files().list(q=q, fields="files(id, name)").execute()
            folders = results.get('files', [])
            if folders:
                folder_id = folders[0]['id']
            else:
                folder_metadata = {
                    'name': part,
                    'mimeType': 'application/vnd.google-apps.folder',
                    'parents': [current_parent_id]
                }
                new_folder = service.files().create(body=folder_metadata, fields='id').execute()
                folder_id = new_folder.get('id')
                logging.info(f"Created subfolder on Google Drive: '{part}' (ID: {folder_id})")
                
            drive_folder_id_cache[normalized_part_path] = folder_id
            current_parent_id = folder_id
        except Exception as e:
            logging.error(f"Error resolving Google Drive folder '{part}' under '{current_parent_id}': {e}")
            raise e
            
    return current_parent_id

def list_drive_files_recursive(service, folder_id, current_rel_path=""):
    drive_items = []
    page_token = None
    q = f"'{folder_id}' in parents and trashed = false"
    while True:
        try:
            results = service.files().list(
                q=q,
                fields="nextPageToken, files(id, name, modifiedTime, mimeType)",
                pageToken=page_token
            ).execute()
            files = results.get('files', [])
            for f in files:
                name = f.get('name')
                item_id = f.get('id')
                mime_type = f.get('mimeType')
                is_dir = (mime_type == 'application/vnd.google-apps.folder')
                rel_path = os.path.join(current_rel_path, name) if current_rel_path else name
                
                drive_items.append({
                    'id': item_id,
                    'name': name,
                    'modifiedTime': f.get('modifiedTime'),
                    'rel_path': rel_path,
                    'is_dir': is_dir
                })
                
                if is_dir:
                    sub_items = list_drive_files_recursive(service, item_id, rel_path)
                    drive_items.extend(sub_items)
                    
            page_token = results.get('nextPageToken')
            if not page_token:
                break
        except Exception as e:
            logging.error(f"Error listing Google Drive files in folder {folder_id}: {e}")
            break
    return drive_items

def sync_file(file_path, local_dir, root_folder_id, service):
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
        target_folder_id = get_or_create_drive_folder(local_dir, file_path, root_folder_id, service)
        
        q = f"name = '{filename}' and '{target_folder_id}' in parents and trashed = false"
        results = service.files().list(q=q, fields="files(id, name)").execute()
        files = results.get('files', [])
        
        media = MediaFileUpload(file_path, mimetype='text/markdown', resumable=True)
        
        local_mtime = os.path.getmtime(file_path)
        local_dt = datetime.datetime.fromtimestamp(local_mtime, tz=datetime.timezone.utc)
        modified_time_str = local_dt.strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + 'Z'
        
        if files:
            file_id = files[0]['id']
            service.files().update(
                fileId=file_id,
                body={'modifiedTime': modified_time_str},
                media_body=media
            ).execute()
            logging.info(f"Successfully updated file on Drive: {filename} (ID: {file_id})")
        else:
            file_metadata = {
                'name': filename,
                'parents': [target_folder_id],
                'modifiedTime': modified_time_str
            }
            new_file = service.files().create(body=file_metadata, media_body=media, fields='id').execute()
            logging.info(f"Successfully created file on Drive: {filename} (ID: {new_file.get('id')})")
            
    except HttpError as error:
        logging.error(f"Google Drive API error syncing {filename}: {error}")
    except Exception as e:
        logging.error(f"Unexpected error syncing {filename}: {e}")

def delete_file(file_path, local_dir, root_folder_id, service):
    filename = os.path.basename(file_path)
    logging.info(f"Deleting file from Drive: {filename}")
    
    try:
        target_folder_id = get_or_create_drive_folder(local_dir, file_path, root_folder_id, service)
        
        q = f"name = '{filename}' and '{target_folder_id}' in parents and trashed = false"
        results = service.files().list(q=q, fields="files(id, name)").execute()
        files = results.get('files', [])
        
        if not files:
            logging.info(f"File not found on Drive, no deletion needed: {filename}")
            return
            
        for file in files:
            file_id = file['id']
            service.files().update(fileId=file_id, body={'trashed': True}).execute()
            logging.info(f"Successfully trashed file on Drive: {filename} (ID: {file_id})")
            
    except HttpError as error:
        logging.error(f"Google Drive API error deleting {filename}: {error}")
    except Exception as e:
        logging.error(f"Unexpected error deleting {filename}: {e}")

def initial_sync(service, local_dir, folder_id):
    logging.info("Starting initial startup synchronization...")
    
    # 1. List all local .md files recursively (excluding ignored)
    local_files = {}
    try:
        for root, dirs, files in os.walk(local_dir):
            # Skip hidden directories in-place
            dirs[:] = [d for d in dirs if not d.startswith('.')]
            for file in files:
                if file.lower().endswith('.md'):
                    local_path = os.path.join(root, file)
                    rel_path = os.path.relpath(local_path, local_dir)
                    normalized_rel_path = os.path.normpath(rel_path)
                    local_files[normalized_rel_path] = local_path
    except Exception as e:
        logging.error(f"Error listing local files: {e}")
        return

    # 2. List all Drive files recursively
    drive_items = list_drive_files_recursive(service, folder_id)
    
    # Cache existing directories on Drive to avoid redundant API queries
    for item in drive_items:
        if item['is_dir']:
            normalized_rel_path = os.path.normpath(item['rel_path'])
            drive_folder_id_cache[normalized_rel_path] = item['id']
            
    # Track files to process
    for item in drive_items:
        if item['is_dir']:
            continue
            
        filename = item['name']
        if not filename.lower().endswith('.md'):
            continue
            
        rel_path = os.path.normpath(item['rel_path'])
        file_id = item['id']
        gdrive_modified_str = item['modifiedTime']
        
        # Parse Google Drive modifiedTime (UTC)
        gdrive_mtime = None
        if gdrive_modified_str:
            try:
                gdrive_mtime = datetime.datetime.fromisoformat(gdrive_modified_str.replace('Z', '+00:00')).timestamp()
            except Exception as e:
                logging.warning(f"Could not parse modification time for {rel_path}: {e}")
            
        local_path = os.path.join(local_dir, rel_path)
        
        if rel_path in local_files:
            # File exists both locally and on Drive
            if gdrive_mtime is not None:
                try:
                    local_mtime = os.path.getmtime(local_path)
                except Exception as e:
                    logging.warning(f"Could not get local modification time for {rel_path}: {e}")
                    local_mtime = 0
                
                # Check diff
                if gdrive_mtime > local_mtime + 2:
                    logging.info(f"Drive file '{rel_path}' is newer. Downloading update...")
                    if download_file(file_id, local_path, service):
                        try:
                            os.utime(local_path, (gdrive_mtime, gdrive_mtime))
                        except Exception as e:
                            logging.warning(f"Could not set local modification time for {rel_path}: {e}")
                elif local_mtime > gdrive_mtime + 2:
                    logging.info(f"Local file '{rel_path}' is newer. Uploading update...")
                    sync_file(local_path, local_dir, folder_id, service)
                else:
                    logging.debug(f"File '{rel_path}' is in sync.")
            else:
                pass
                
            # Remove from local files dict so we know it's been handled
            del local_files[rel_path]
        else:
            # File exists on Drive but not locally
            logging.info(f"Downloading new file from Drive: '{rel_path}'")
            os.makedirs(os.path.dirname(local_path), exist_ok=True)
            if download_file(file_id, local_path, service):
                if gdrive_mtime is not None:
                    try:
                        os.utime(local_path, (gdrive_mtime, gdrive_mtime))
                    except Exception as e:
                        logging.warning(f"Could not set local modification time for {rel_path}: {e}")

    # 3. Any files left in local_files exist locally but not on Drive
    for rel_path, local_path in local_files.items():
        logging.info(f"Uploading new local file to Drive: '{rel_path}'")
        sync_file(local_path, local_dir, folder_id, service)
        
    logging.info("Initial synchronization completed successfully.")

class MarkdownSyncHandler(FileSystemEventHandler):
    def __init__(self, service, local_dir, folder_id):
        self.service = service
        self.local_dir = local_dir
        self.folder_id = folder_id

    def on_created(self, event):
        if not event.is_directory and event.src_path.lower().endswith('.md'):
            if not is_ignored_path(event.src_path, self.local_dir):
                logging.info(f"Detected creation event: {event.src_path}")
                sync_file(event.src_path, self.local_dir, self.folder_id, self.service)

    def on_modified(self, event):
        if not event.is_directory and event.src_path.lower().endswith('.md'):
            if not is_ignored_path(event.src_path, self.local_dir):
                logging.info(f"Detected modification event: {event.src_path}")
                sync_file(event.src_path, self.local_dir, self.folder_id, self.service)

    def on_deleted(self, event):
        if not event.is_directory and event.src_path.lower().endswith('.md'):
            if not is_ignored_path(event.src_path, self.local_dir):
                logging.info(f"Detected deletion event: {event.src_path}")
                delete_file(event.src_path, self.local_dir, self.folder_id, self.service)

    def on_moved(self, event):
        if not event.is_directory:
            if event.src_path.lower().endswith('.md') and not is_ignored_path(event.src_path, self.local_dir):
                logging.info(f"Detected file moved out / renamed: {event.src_path}")
                delete_file(event.src_path, self.local_dir, self.folder_id, self.service)
            if event.dest_path.lower().endswith('.md') and not is_ignored_path(event.dest_path, self.local_dir):
                logging.info(f"Detected file moved in / renamed: {event.dest_path}")
                sync_file(event.dest_path, self.local_dir, self.folder_id, self.service)

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
        
    # Perform initial bidirectional sync before starting watchdog observer
    initial_sync(service, local_dir, folder_id)
        
    event_handler = MarkdownSyncHandler(service, local_dir, folder_id)
    observer = Observer()
    observer.schedule(event_handler, path=local_dir, recursive=True)
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
