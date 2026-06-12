"""Package `tools` (scripts utilitaires + publication mobile).

Le fichier ``__init__.py`` (même vide) fait de ``tools`` un vrai package Python,
ce qui permet à PyInstaller de l'embarquer dans le .exe : sans lui, l'import
``from tools.publier_dashboard import publier`` n'est pas vu par l'analyse
statique du bundle.
"""
