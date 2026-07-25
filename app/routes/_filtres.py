"""Persistance (session) + rappel visuel des filtres d'une page « liste ».

Même comportement partout :
  - ``reinit=1`` oublie les filtres mémorisés et remontre tout ;
  - une arrivée « nue » sur la page ré-applique les derniers filtres posés
    (redirection vers l'URL canonique, pour que les liens/export les reprennent) ;
  - le formulaire poste toujours ``f=1`` : on distingue ainsi une vraie
    soumission (même « tout à Tous ») d'une simple navigation.
"""

from __future__ import annotations

from typing import Iterable

from flask import redirect, request, session, url_for


def resoudre_filtres(
    session_key: str, endpoint: str, cles: Iterable[str]
):
    """Renvoie ``(redirection | None, valeurs, nb_actifs)``.

    ``valeurs`` : dict {clé: str} (chaîne vide si non renseignée), à passer au
    template pour repeupler ET surligner les champs. ``nb_actifs`` : nombre de
    filtres réellement posés (badge / accent de barre). Si ``redirection`` n'est
    pas ``None``, la vue doit la retourner telle quelle.
    """
    cles = tuple(cles)
    if request.args.get("reinit"):
        session.pop(session_key, None)
        return redirect(url_for(endpoint)), {c: "" for c in cles}, 0
    soumis = request.args.get("f") == "1"
    memorises = session.get(session_key)
    if not soumis and memorises:
        return (
            redirect(url_for(endpoint, f="1", **memorises)),
            {c: "" for c in cles},
            0,
        )
    valeurs = {c: (request.args.get(c) or "") for c in cles}
    if soumis:
        actifs = {c: v for c, v in valeurs.items() if v}
        if actifs:
            session[session_key] = actifs
        else:
            session.pop(session_key, None)
    nb_actifs = sum(1 for v in valeurs.values() if v)
    return None, valeurs, nb_actifs
