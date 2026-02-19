import pygame
from config import BLOCK_SIZE

# --- HELPER FUNKTIONEN ---
def safe_load_img(path, size=None, color=(255, 0, 255)):
    try:
        img = pygame.image.load(path).convert_alpha()
        if size: img = pygame.transform.scale(img, size)
        return img
    except (FileNotFoundError, pygame.error):
        s = pygame.Surface(size if size else (BLOCK_SIZE, BLOCK_SIZE))
        s.fill(color)
        pygame.draw.rect(s, (0,0,0), s.get_rect(), 2)
        return s

def safe_load_snd(path, vol=0.3):
    try:
        s = pygame.mixer.Sound(path)
        s.set_volume(vol)
        return s
    except (FileNotFoundError, pygame.error):
        class DummySound:
            def play(self): pass
            def set_volume(self, v): pass
        return DummySound()