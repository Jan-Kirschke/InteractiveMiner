import importlib
import pkgutil

import quiz


def test_every_quiz_module_imports():
    # The service imports modules the unit tests never touch (controller, broadcaster); a syntax
    # error there only showed up as a crash loop on the server.
    for mod in pkgutil.iter_modules(quiz.__path__):
        importlib.import_module(f"quiz.{mod.name}")
