from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
import time
import os

class MultiFileChangeHandler(FileSystemEventHandler):
    def __init__(self, watchedFiles):
        self.watchedFiles = watchedFiles

    def on_modified(self, event):
        eventFileName = os.path.basename(event.src_path)
        for file in self.watchedFiles:
            if not file.startswith('file:'):
                continue
            file_to_watch = file[5:]
            callback = self.watchedFiles[file]
            watchFileName = os.path.basename(file_to_watch)
            if watchFileName in eventFileName:
                #print(f"The file {file_to_watch} has been modified.")
                callback(file_to_watch, eventFileName)  # Trigger the registered event (callback function)
                break

watchedFiles = {}

def watchFileChange(file_to_watch, callback):
    path = file_to_watch.rsplit('/', 1)[0]
    observer = None

    if not path in watchedFiles: 
        watchedFiles[path] = {}
    else:
        observer = watchedFiles[path]['observer']
        observer.stop()

    watchedFiles[path][f'file:{file_to_watch}'] = callback
    event_handler = MultiFileChangeHandler(watchedFiles[path])
    observer = Observer()
    watchedFiles[path]['observer'] = observer
    observer.schedule(event_handler, path=path, recursive=False)
    observer.start()

    return observer

    try:
        print(f"Watching for changes in {path_to_watch}...")
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("Stopping file watcher...")
        observer.stop()
    observer.join()
