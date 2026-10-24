import pygame

from quiz.gfx import SurfCache, surface_bytes


def test_cache_never_holds_more_than_its_budget():
    cache = SurfCache(1)  # 1 MB
    for i in range(50):
        cache[i] = pygame.Surface((256, 256), pygame.SRCALPHA)  # 256 KB each
        assert cache.nbytes <= 1 << 20
        assert cache.nbytes == sum(surface_bytes(s) for s in cache.values())
    assert 49 in cache


def test_replacing_and_removing_keep_the_count_right():
    cache = SurfCache(8)
    cache["a"] = pygame.Surface((100, 100), pygame.SRCALPHA)
    cache["a"] = pygame.Surface((10, 10), pygame.SRCALPHA)
    cache["b"] = "not a surface"
    cache.pop("a")
    assert cache.nbytes == 0
    cache["c"] = pygame.Surface((10, 10), pygame.SRCALPHA)
    del cache["c"]
    cache.clear()
    assert cache.nbytes == 0 and not cache
