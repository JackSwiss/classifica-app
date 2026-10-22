"""
Ogni giorno scarica da Apple la classifica delle app più scaricate dell'App Store USA
(gratuite e a pagamento), salva lo storico in data.json e calcola le top 10
del giorno, della settimana in corso e del mese in corso.

Al posto dei download (che Apple non rende pubblici) registra il numero di
valutazioni di ogni app, così si può vedere quanto cresce nel tempo.

Non serve installare niente: usa solo librerie già incluse in Python.
"""

import json
import os
import time
import urllib.request
from datetime import date, datetime, timedelta, timezone

PAESE = "us"
QUANTE = 50          # quante posizioni salvare ogni giorno (servono per calcolare settimana e mese)
MOSTRA = 10          # quante app mostrare in ogni classifica
ASSENTE = QUANTE + 1  # posizione assegnata a un'app nei giorni in cui è fuori dalla top 50

CLASSIFICHE = {
    "gratuite": {"nuovo": "top-free", "vecchio": "topfreeapplications"},
    "pagamento": {"nuovo": "top-paid", "vecchio": "toppaidapplications"},
}

FILE_DATI = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data.json")


# ---------- Scaricare i dati ----------

def scarica_json(url, tentativi=3):
    for n in range(tentativi):
        try:
            richiesta = urllib.request.Request(url, headers={"User-Agent": "appstore-classifica/1.0"})
            with urllib.request.urlopen(richiesta, timeout=30) as risposta:
                return json.load(risposta)
        except Exception as errore:
            if n == tentativi - 1:
                raise
            print(f"  Tentativo {n + 1} fallito ({errore}), riprovo…")
            time.sleep(5)


def classifica_feed_nuovo(tipo):
    url = f"https://rss.marketingtools.apple.com/api/v2/{PAESE}/apps/{tipo}/{QUANTE}/apps.json"
    risultati = scarica_json(url)["feed"]["results"]
    app = []
    for r in risultati:
        app.append({
            "id": str(r["id"]),
            "nome": r.get("name", ""),
            "sviluppatore": r.get("artistName", ""),
            "icona": r.get("artworkUrl100", ""),
            "genere": (r.get("genres") or [{}])[0].get("name", ""),
            "url": r.get("url", ""),
        })
    return app


def classifica_feed_vecchio(tipo):
    url = f"https://itunes.apple.com/{PAESE}/rss/{tipo}/limit={QUANTE}/json"
    voci = scarica_json(url)["feed"].get("entry", [])
    app = []
    for v in voci:
        immagini = v.get("im:image") or [{}]
        app.append({
            "id": v["id"]["attributes"]["im:id"],
            "nome": v.get("im:name", {}).get("label", ""),
            "sviluppatore": v.get("im:artist", {}).get("label", ""),
            "icona": immagini[-1].get("label", ""),
            "genere": v.get("category", {}).get("attributes", {}).get("label", ""),
            "url": v["id"].get("label", ""),
        })
    return app


def scarica_classifica(nomi):
    try:
        return classifica_feed_nuovo(nomi["nuovo"])
    except Exception as errore:
        print(f"  Feed nuovo non disponibile ({errore}), uso quello vecchio")
        return classifica_feed_vecchio(nomi["vecchio"])


def scarica_valutazioni(ids):
    """Numero di valutazioni, voto medio e prezzo per ogni app, a gruppi di 100."""
    info = {}
    ids = list(ids)
    for i in range(0, len(ids), 100):
        gruppo = ",".join(ids[i:i + 100])
        dati = scarica_json(f"https://itunes.apple.com/lookup?id={gruppo}&country={PAESE}")
        for r in dati.get("results", []):
            info[str(r["trackId"])] = {
                "valutazioni": r.get("userRatingCount"),
                "voto": r.get("averageUserRating"),
                "prezzo": r.get("formattedPrice"),
                "icona": r.get("artworkUrl100"),
            }
    return info


# ---------- Calcolare le classifiche ----------

def giorni_nel_periodo(storico, inizio, fine):
    return sorted(g for g in storico if inizio <= g <= fine)


def crescita_valutazioni(app, inizio, fine):
    """Quante valutazioni ha guadagnato l'app tra il primo e l'ultimo giorno registrati nel periodo."""
    serie = app.get("valutazioni", {})
    giorni = sorted(g for g in serie if inizio <= g <= fine and serie[g] is not None)
    if len(giorni) < 2:
        return None
    return serie[giorni[-1]] - serie[giorni[0]]


def classifica_periodo(storico, archivio_app, inizio, fine):
    giorni = giorni_nel_periodo(storico, inizio, fine)
    if not giorni:
        return None
    posizioni = {}
    for g in giorni:
        for pos, app_id in enumerate(storico[g], start=1):
            posizioni.setdefault(app_id, {})[g] = pos

    righe = []
    for app_id, per_giorno in posizioni.items():
        media = sum(per_giorno.get(g, ASSENTE) for g in giorni) / len(giorni)
        righe.append({
            "id": app_id,
            "media": round(media, 1),
            "migliore": min(per_giorno.values()),
            "giorni_top10": sum(1 for p in per_giorno.values() if p <= MOSTRA),
            "crescita": crescita_valutazioni(archivio_app.get(app_id, {}), inizio, fine),
        })
    righe.sort(key=lambda r: (r["media"], r["migliore"]))
    return {"giorni": len(giorni), "dal": giorni[0], "al": giorni[-1], "app": righe[:MOSTRA]}


def classifica_giorno(storico, archivio_app, oggi):
    if oggi not in storico:
        return None
    precedenti = sorted(g for g in storico if g < oggi)
    ieri = precedenti[-1] if precedenti else None
    pos_ieri = {a: i for i, a in enumerate(storico[ieri], start=1)} if ieri else {}

    righe = []
    for pos, app_id in enumerate(storico[oggi][:MOSTRA], start=1):
        if not ieri:
            variazione = None
        elif app_id in pos_ieri:
            variazione = pos_ieri[app_id] - pos   # positivo = è salita
        else:
            variazione = "nuova"
        righe.append({
            "id": app_id,
            "posizione": pos,
            "variazione": variazione,
            "crescita": crescita_valutazioni(archivio_app.get(app_id, {}), ieri or oggi, oggi),
        })
    return {"giorni": 1, "dal": oggi, "al": oggi, "app": righe}


# ---------- Programma principale ----------

def main():
    if os.path.exists(FILE_DATI):
        with open(FILE_DATI, encoding="utf-8") as f:
            archivio = json.load(f)
    else:
        archivio = {}
    storico = archivio.get("storico", {})
    archivio_app = archivio.get("app", {})

    adesso = datetime.now(timezone.utc)
    oggi = adesso.date()
    oggi_s = oggi.isoformat()

    # 1. Classifiche di oggi
    tutte_le_app = {}
    for chiave, nomi in CLASSIFICHE.items():
        print(f"Scarico la classifica {chiave}…")
        lista = scarica_classifica(nomi)
        storico.setdefault(chiave, {})[oggi_s] = [a["id"] for a in lista]
        for a in lista:
            tutte_le_app[a["id"]] = a

    # 2. Valutazioni di ogni app in classifica
    print(f"Scarico le valutazioni di {len(tutte_le_app)} app…")
    extra = scarica_valutazioni(tutte_le_app)

    for app_id, a in tutte_le_app.items():
        voce = archivio_app.setdefault(app_id, {"valutazioni": {}})
        voce.update({k: v for k, v in a.items() if v and k != "id"})
        e = extra.get(app_id, {})
        if e.get("icona"):
            voce["icona"] = e["icona"]
        voce["voto"] = e.get("voto")
        voce["prezzo"] = e.get("prezzo")
        voce["visto"] = oggi_s
        if e.get("valutazioni") is not None:
            voce["valutazioni"][oggi_s] = e["valutazioni"]

    # 3. Pulizia: teniamo le valutazioni degli ultimi 70 giorni e le app viste negli ultimi 70 giorni
    limite = (oggi - timedelta(days=70)).isoformat()
    for app_id in list(archivio_app):
        voce = archivio_app[app_id]
        voce["valutazioni"] = {g: n for g, n in voce.get("valutazioni", {}).items() if g >= limite}
        if voce.get("visto", "") < limite:
            del archivio_app[app_id]

    # 4. Classifiche del giorno, della settimana (da lunedì) e del mese in corso
    inizio_settimana = (oggi - timedelta(days=oggi.weekday())).isoformat()
    inizio_mese = oggi.replace(day=1).isoformat()
    viste = {}
    for chiave in CLASSIFICHE:
        s = storico.get(chiave, {})
        viste[chiave] = {
            "giorno": classifica_giorno(s, archivio_app, oggi_s),
            "settimana": classifica_periodo(s, archivio_app, inizio_settimana, oggi_s),
            "mese": classifica_periodo(s, archivio_app, inizio_mese, oggi_s),
        }

    archivio = {
        "aggiornato": adesso.isoformat(timespec="seconds"),
        "paese": PAESE,
        "classifiche": viste,
        "app": archivio_app,
        "storico": storico,
    }
    with open(FILE_DATI, "w", encoding="utf-8") as f:
        json.dump(archivio, f, ensure_ascii=False, separators=(",", ":"))

    for chiave in CLASSIFICHE:
        prime = [archivio_app[r["id"]]["nome"] for r in viste[chiave]["giorno"]["app"][:3]]
        print(f"Top 3 {chiave} oggi: {', '.join(prime)}")


if __name__ == "__main__":
    main()
