import os

import json
import re
import threading
from pathlib import Path

import vlc
from pytubefix import Search, YouTube

BASE_DIR = Path(__file__).parent
MUSIC_DIR = BASE_DIR / "music"
DB_FILE = BASE_DIR / "library.json"
MUSIC_DIR.mkdir(exist_ok=True)

library = []                                    
settings = {"autodownload": True, "repeat": False}
queue = {"items": [], "index": -1}              

player = vlc.MediaPlayer()




def save_data():
    data = {"settings": settings, "library": library}
    tmp = DB_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(DB_FILE)  # atomic replace, the file won't get corrupted on a crash


def load_data():
    if not DB_FILE.exists():
        return
    try:
        data = json.loads(DB_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        print("library.json is corrupted, starting with an empty library")
        return
    settings.update(data.get("settings", {}))
    for s in data.get("library", []):
        if "title" in s and "url" in s:
            path = s.get("path")
            library.append({
                "title": s["title"],
                "url": s["url"],
                "path": path if path and Path(path).exists() else None,
            })




def ask_int(prompt, lo, hi):
    while True:
        raw = input(prompt).strip()
        if raw.isdigit() and lo <= int(raw) <= hi:
            return int(raw)
        print(f"Enter a number from {lo} to {hi}")


def safe_name(title):
    return re.sub(r'[\\/:*?"<>|]', "_", title)[:100]




def get_source(item):
    if item["path"] and Path(item["path"]).exists():
        return item["path"]

    stream = YouTube(item["url"]).streams.get_audio_only()
    if settings["autodownload"]:
        print("Downloading...")
        item["path"] = stream.download(
            output_path=str(MUSIC_DIR),
            filename=safe_name(item["title"]) + ".m4a",
        )
        save_data()
        return item["path"]
    return stream.url


def play_item(item):
    """Plays a single track. Returns True on success."""
    try:
        source = get_source(item)
    except Exception as e:
        print(f"Could not get audio for \"{item['title']}\": {e}")
        return False
    player.set_media(vlc.Media(source))
    player.play()
    print(f"▶ Now playing: {item['title']}")
    return True


def start_queue(items, start=0):
    """Starts the queue from position `start`, track after track until it ends."""
    queue["items"] = list(items)
    queue["index"] = start - 1
    play_next()


def play_next(step=1):
    """Moves `step` tracks forward (or backward with step=-1)."""
    items = queue["items"]
    if not items:
        print("The queue is empty")
        return
    idx = queue["index"]
    for _ in range(len(items)):      
        idx += step
        if idx >= len(items) or idx < 0:
            if settings["repeat"]:
                idx %= len(items)
            else:
                queue["index"] = -1
                player.stop()
                print("The queue has finished")
                return
        queue["index"] = idx
        if play_item(items[idx]):
            return
    print("Could not play any track")


def on_track_end(event):

    threading.Thread(target=play_next, daemon=True).start()


player.event_manager().event_attach(vlc.EventType.MediaPlayerEndReached, on_track_end)


def toggle_pause():
    player.pause()




def search_menu():
    name = input("Enter a song name: ").strip()
    if not name:
        return
    print("Searching...")
    try:
        videos = Search(name).videos[:5]
    except Exception as e:
        print(f"Search error: {e}")
        return
    if not videos:
        print("Nothing found")
        return

    for i, v in enumerate(videos, 1):
        print(f"{i}. {v.title}\n   {v.watch_url}")

    idx = ask_int("Choose a song (0 - back): ", 0, len(videos))
    if idx == 0:
        return
    video = videos[idx - 1]
    item = {"title": video.title, "url": video.watch_url, "path": None}

    while True:
        print(f"\n[{item['title']}]")
        print("1. Play\n2. Pause / resume\n3. Add to library\n0. Back")
        c = ask_int("Choose an action: ", 0, 3)
        if c == 1:
            start_queue([item])
        elif c == 2:
            toggle_pause()
        elif c == 3:
            if any(s["url"] == item["url"] for s in library):
                print("Already in the library")
            else:
                library.append(item)
                save_data()
                print("Added")
        else:
            return


def library_menu():
    while True:
        print("\nSong library:")
        if not library:
            print("(empty)")
            return

        current = None
        if 0 <= queue["index"] < len(queue["items"]):
            current = queue["items"][queue["index"]]
        for i, s in enumerate(library, 1):
            icon = "💾" if s["path"] else "🌐"
            now = " ◀ playing" if s is current else ""
            print(f"{i}. {icon} {s['title']}{now}")

        print(
            "\n1. Play in order starting from a selected song"
            "\n2. Play the whole library from the start"
            "\n3. Next track"
            "\n4. Previous track"
            "\n5. Pause / resume"
            "\n6. Delete a song"
            "\n0. Back"
        )
        c = ask_int("Choose an action: ", 0, 6)

        if c == 0:
            return
        elif c == 1:
            n = ask_int("Song number: ", 1, len(library))
            start_queue(library, n - 1)
        elif c == 2:
            start_queue(library, 0)
        elif c == 3:
            play_next(1)
        elif c == 4:
            play_next(-1)
        elif c == 5:
            toggle_pause()
        elif c == 6:
            n = ask_int("Song number: ", 1, len(library))
            song = library.pop(n - 1)
            if song["path"] and Path(song["path"]).exists():
                os.remove(song["path"])
            save_data()
            print("Deleted")


def settings_menu():
    while True:
        dl = "on" if settings["autodownload"] else "off"
        rp = "on" if settings["repeat"] else "off"
        print(
            f"\n1. Auto-download songs: {dl}"
            f"\n2. Repeat queue: {rp}"
            "\n0. Back"
        )
        c = ask_int("Choose an action: ", 0, 2)
        if c == 1:
            settings["autodownload"] = not settings["autodownload"]
            save_data()
        elif c == 2:
            settings["repeat"] = not settings["repeat"]
            save_data()
        else:
            return


def main():
    load_data()
    while True:
        print("\nWelcome to the music player!")
        print("1. Search for a song\n2. Song library\n3. Settings\n4. Exit")
        c = ask_int("Choose an action: ", 1, 4)
        if c == 1:
            search_menu()
        elif c == 2:
            library_menu()
        elif c == 3:
            settings_menu()
        else:
            player.stop()
            if not settings["autodownload"]:
                # as in your original logic: clean up downloaded files on exit
                for s in library:
                    if s["path"] and Path(s["path"]).exists():
                        os.remove(s["path"])
                        s["path"] = None
                save_data()
            return


if __name__ == "__main__":
    main()