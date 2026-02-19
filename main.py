import pytchat
import threading
import queue
from game import Game
from config import CHANNEL_ID

def youtube_chat_reader(video_id, q):
    chat = pytchat.create(video_id=video_id)
    print("Verbunden mit Live-Chat! Warte auf Befehle...")
    
    while chat.is_alive():
        for c in chat.get().sync_items():
            msg = c.message.lower() 
            user = c.author.name
            
            # Prüfen, ob die Nachricht einer deiner Befehle ist
            valid_commands = ["like", "event", "boss", "hero", "left", "mid", "right", "splash", "dig", "xbomb", "nuke"]
            if msg in valid_commands:
                q.put((msg, user)) # Ab ins Spiel damit!

if __name__ == "__main__":
    q = queue.Queue()

    
    # Chat-Reader starten
    threading.Thread(target=youtube_chat_reader, args=(CHANNEL_ID, q), daemon=True).start()
    
    # Spiel starten
    Game().run(q)