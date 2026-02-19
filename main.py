import threading
import queue
import time
import random
from game import Game

if __name__ == "__main__":
    q = queue.Queue()
    
    def fake_spammer():
        usrs = ["Steve", "Alex", "Pro", "Noob", "Miner42", "DiamondKing", "CreeperHunter"]
        while True:
            time.sleep(0.1); u = random.choice(usrs); r = random.random()
            if r < 0.08: q.put(("!like", u))
            elif r < 0.12: q.put(("!event", u))
            elif r < 0.18: q.put(("!dig", u))
            elif r < 0.22: q.put(("!tnt", u))
            elif r < 0.26: q.put(("!hero", u))
            elif r < 0.30: q.put(("!tnt", u))
            elif r < 0.85: q.put((random.choice(["!left","!mid","!right","!splash"]), u))
            
    threading.Thread(target=fake_spammer, daemon=True).start()
    
    # Das Spiel starten
    Game().run(q)