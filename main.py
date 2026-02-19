import pytchat
import threading
import queue
import scrapetube
from game import Game
from config import CHANNEL_ID

def get_live_video_id(channel_id):
    print("Suche aktiven Livestream für den Chat...")
    try:
        vids = scrapetube.get_channel(channel_id, content_type="streams", limit=5)
        for v in vids:
            if v.get('thumbnailOverlays') and any('LIVE' in str(o) for o in v['thumbnailOverlays']):
                vid_id = v['videoId']
                print(f"Livestream gefunden! Video-ID: {vid_id}")
                return vid_id
    except Exception as e:
        print(f"Fehler bei der Suche: {e}")
    return None

def youtube_chat_reader(channel_id, q):
    # 1. Video ID vollautomatisch suchen
    video_id = get_live_video_id(channel_id)
    
    if not video_id:
        print("Kanal ist gerade offline. Chat-Reader wartet...")
        return

    # 2. Mit dem Chat verbinden
    print("Verbinde mit Live-Chat...")
    try:
        chat = pytchat.create(video_id=video_id)
        print("Erfolgreich mit Live-Chat verbunden! Warte auf Befehle...")
        
        while chat.is_alive():
            for c in chat.get().sync_items():
                msg = c.message.lower() # Alles klein machen für den Check
                user = c.author.name
                
                # Nur Befehle durchlassen, die das Spiel auch versteht
                valid_commands = ["like", "event", "boss", "hero", "left", "mid", "right", "splash", "dig", "xbomb", "nuke"]
                if msg in valid_commands:
                    q.put((msg, user))
                    print(f"Befehl erkannt: {user} -> {msg}")
                    
    except Exception as e:
        print(f"Chat-Verbindung abgebrochen: {e}")

if __name__ == "__main__":
    q = queue.Queue()
    
    # Startet den Chat-Reader im Hintergrund (nutzt CHANNEL_ID aus deiner config.py)
    threading.Thread(target=youtube_chat_reader, args=(CHANNEL_ID, q), daemon=True).start()
    
    # Spiel starten
    Game().run(q)