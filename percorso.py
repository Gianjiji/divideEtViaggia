"""Ricerca delle localita' e calcolo della distanza stradale fra due punti.

Due backend, scelti automaticamente:

* **OpenRouteService** (geocoding Pelias + directions) se in ambiente c'e'
  ``ORS_API_KEY``. La chiave e' gratuita e si ottiene registrandosi su
  account.heigit.org, senza carta di credito.
* **Nominatim + OSRM**, i servizi pubblici di OpenStreetMap, se la chiave non
  c'e'. Funzionano senza registrazione ma sono demo server senza garanzie:
  vanno bene per un bot fra amici, non per traffico serio.

Le funzioni di parsing sono separate dalle chiamate HTTP, cosi' restano
testabili senza rete.
"""

from __future__ import annotations

import asyncio
import os
import time
from dataclasses import dataclass
from typing import Any

import httpx

#: Identifica il bot verso i servizi pubblici: la usage policy di Nominatim
#: richiede uno User-Agent riconoscibile.
USER_AGENT = "DivideEtViaggiaBot/1.0 (bot Telegram per dividere i costi di viaggio)"

TIMEOUT = httpx.Timeout(15.0, connect=10.0)

URL_NOMINATIM = "https://nominatim.openstreetmap.org/search"
URL_OSRM = "https://router.project-osrm.org/route/v1/driving"
URL_ORS_GEOCODE = "https://api.openrouteservice.org/geocode/search"
URL_ORS_DIRECTIONS = "https://api.openrouteservice.org/v2/directions/driving-car"

#: Nominatim consente al massimo una richiesta al secondo.
_INTERVALLO_NOMINATIM = 1.1


class ErrorePercorso(Exception):
    """Errore mostrabile all'utente durante la ricerca di un percorso."""


class LuogoNonTrovato(ErrorePercorso):
    """La localita' cercata non esiste o e' troppo generica."""


class ServizioNonDisponibile(ErrorePercorso):
    """Il servizio di mappe non ha risposto o ha risposto male."""


@dataclass(frozen=True)
class Luogo:
    """Una localita' geocodificata."""

    nome: str       # etichetta breve, per i messaggi
    etichetta: str  # descrizione estesa restituita dal servizio
    lat: float
    lon: float


@dataclass(frozen=True)
class Percorso:
    """Il tragitto stradale fra due localita'."""

    origine: Luogo
    destinazione: Luogo
    distanza_km: float
    durata_minuti: float | None
    servizio: str

    @property
    def durata_leggibile(self) -> str | None:
        if self.durata_minuti is None:
            return None
        ore, minuti = divmod(int(round(self.durata_minuti)), 60)
        return f"{ore}h {minuti:02d}min" if ore else f"{minuti} min"


def chiave_ors() -> str | None:
    """La chiave OpenRouteService, se configurata."""
    chiave = (os.environ.get("ORS_API_KEY") or "").strip()
    return chiave or None


# --------------------------------------------------------------------------- #
# Parsing delle risposte (niente rete: testabile)
# --------------------------------------------------------------------------- #

def _nome_breve(etichetta: str) -> str:
    """Tiene le prime due parti di un indirizzo lungo: «Bologna, Emilia-Romagna»."""
    parti = [p.strip() for p in etichetta.split(",") if p.strip()]
    if not parti:
        return etichetta.strip()
    return ", ".join(parti[:2])


def _nome_da_indirizzo(voce: dict, etichetta: str) -> str:
    """Compone un'etichetta breve dai campi strutturati di Nominatim.

    Preferisce la via quando il risultato e' un civico (altrimenti si finirebbe
    con il nome del negozio che sta a quell'indirizzo), il nome del punto di
    interesse negli altri casi, e ci accoda la citta' quando aggiunge qualcosa.
    """
    indirizzo = voce.get("address") or {}
    if not isinstance(indirizzo, dict):
        indirizzo = {}

    citta = next(
        (
            str(indirizzo[chiave]).strip()
            for chiave in ("city", "town", "village", "municipality", "county")
            if indirizzo.get(chiave)
        ),
        "",
    )
    strada = str(indirizzo.get("road") or "").strip()
    civico = str(indirizzo.get("house_number") or "").strip()
    poi = str(voce.get("name") or "").strip()

    if civico and strada:
        base = f"{strada} {civico}"
    else:
        base = poi or strada or citta

    if not base:
        return _nome_breve(etichetta)
    if citta and citta.lower() not in base.lower():
        return f"{base}, {citta}"
    return base


def luogo_da_nominatim(payload: Any) -> Luogo:
    if not isinstance(payload, list) or not payload:
        raise LuogoNonTrovato("Non ho trovato quella localita'.")
    voce = payload[0]
    try:
        etichetta = str(voce.get("display_name") or voce.get("name") or "").strip()
        lat, lon = float(voce["lat"]), float(voce["lon"])
    except (KeyError, TypeError, ValueError):
        raise ServizioNonDisponibile("Risposta inattesa dal servizio di mappe.") from None
    if not etichetta:
        raise LuogoNonTrovato("Non ho trovato quella localita'.")
    return Luogo(
        nome=_nome_da_indirizzo(voce, etichetta),
        etichetta=etichetta,
        lat=lat,
        lon=lon,
    )


def luogo_da_pelias(payload: Any) -> Luogo:
    if not isinstance(payload, dict):
        raise ServizioNonDisponibile("Risposta inattesa dal servizio di mappe.")
    elementi = payload.get("features") or []
    if not elementi:
        raise LuogoNonTrovato("Non ho trovato quella localita'.")
    voce = elementi[0]
    try:
        lon, lat = (float(c) for c in voce["geometry"]["coordinates"][:2])
        proprieta = voce.get("properties") or {}
    except (KeyError, TypeError, ValueError):
        raise ServizioNonDisponibile("Risposta inattesa dal servizio di mappe.") from None
    etichetta = str(proprieta.get("label") or proprieta.get("name") or "").strip()
    if not etichetta:
        raise LuogoNonTrovato("Non ho trovato quella localita'.")
    return Luogo(
        nome=_nome_breve(etichetta), etichetta=etichetta, lat=lat, lon=lon
    )


def _misure(distanza_metri: Any, durata_secondi: Any) -> tuple[float, float | None]:
    try:
        km = float(distanza_metri) / 1000.0
    except (TypeError, ValueError):
        raise ServizioNonDisponibile("Risposta inattesa dal servizio di mappe.") from None
    if km <= 0:
        raise ServizioNonDisponibile("Il servizio non ha trovato un percorso stradale.")
    try:
        minuti = float(durata_secondi) / 60.0
    except (TypeError, ValueError):
        minuti = None
    return round(km, 1), minuti


def misure_da_osrm(payload: Any) -> tuple[float, float | None]:
    if not isinstance(payload, dict):
        raise ServizioNonDisponibile("Risposta inattesa dal servizio di mappe.")
    if payload.get("code") != "Ok":
        raise ServizioNonDisponibile(
            "Il servizio non ha trovato un percorso stradale fra i due punti."
        )
    percorsi = payload.get("routes") or []
    if not percorsi:
        raise ServizioNonDisponibile("Il servizio non ha trovato un percorso stradale.")
    return _misure(percorsi[0].get("distance"), percorsi[0].get("duration"))


def misure_da_ors(payload: Any) -> tuple[float, float | None]:
    if not isinstance(payload, dict):
        raise ServizioNonDisponibile("Risposta inattesa dal servizio di mappe.")
    elementi = payload.get("features") or []
    if not elementi:
        raise ServizioNonDisponibile("Il servizio non ha trovato un percorso stradale.")
    riepilogo = ((elementi[0].get("properties") or {}).get("summary")) or {}
    if not riepilogo:
        raise ServizioNonDisponibile("Il servizio non ha trovato un percorso stradale.")
    return _misure(riepilogo.get("distance"), riepilogo.get("duration"))


# --------------------------------------------------------------------------- #
# Chiamate HTTP
# --------------------------------------------------------------------------- #

_ultima_nominatim = 0.0
_lock_nominatim = asyncio.Lock()
_cache_luoghi: dict[str, Luogo] = {}
_MAX_CACHE = 256


async def _attendi_turno_nominatim() -> None:
    """Rispetta il limite di una richiesta al secondo di Nominatim."""
    global _ultima_nominatim
    async with _lock_nominatim:
        attesa = _INTERVALLO_NOMINATIM - (time.monotonic() - _ultima_nominatim)
        if attesa > 0:
            await asyncio.sleep(attesa)
        _ultima_nominatim = time.monotonic()


async def _json(client: httpx.AsyncClient, url: str, **kwargs: Any) -> Any:
    try:
        risposta = await client.get(url, **kwargs)
        risposta.raise_for_status()
        return risposta.json()
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code in (401, 403):
            raise ServizioNonDisponibile(
                "Il servizio di mappe ha rifiutato la richiesta: controlla la "
                "chiave ORS_API_KEY."
            ) from exc
        if exc.response.status_code == 429:
            raise ServizioNonDisponibile(
                "Il servizio di mappe e' sovraccarico. Riprova fra poco."
            ) from exc
        raise ServizioNonDisponibile("Il servizio di mappe non risponde.") from exc
    except (httpx.HTTPError, ValueError) as exc:
        raise ServizioNonDisponibile("Il servizio di mappe non risponde.") from exc


async def cerca_luogo(testo: str, client: httpx.AsyncClient | None = None) -> Luogo:
    """Geocodifica una localita' scritta a mano libera."""
    query = " ".join(str(testo or "").split())
    if len(query) < 2:
        raise LuogoNonTrovato("Scrivi almeno il nome di una citta'.")

    chiave_cache = query.lower()
    if chiave_cache in _cache_luoghi:
        return _cache_luoghi[chiave_cache]

    proprio = client is None
    client = client or httpx.AsyncClient(timeout=TIMEOUT, headers={"User-Agent": USER_AGENT})
    try:
        chiave = chiave_ors()
        if chiave:
            payload = await _json(
                client,
                URL_ORS_GEOCODE,
                params={"api_key": chiave, "text": query, "size": 1, "lang": "it"},
            )
            luogo = luogo_da_pelias(payload)
        else:
            await _attendi_turno_nominatim()
            payload = await _json(
                client,
                URL_NOMINATIM,
                params={
                    "q": query,
                    "format": "json",
                    "limit": 1,
                    "addressdetails": 1,
                    "accept-language": "it",
                },
            )
            luogo = luogo_da_nominatim(payload)
    finally:
        if proprio:
            await client.aclose()

    if len(_cache_luoghi) >= _MAX_CACHE:
        _cache_luoghi.clear()
    _cache_luoghi[chiave_cache] = luogo
    return luogo


async def calcola_percorso(
    origine: Luogo,
    destinazione: Luogo,
    client: httpx.AsyncClient | None = None,
) -> Percorso:
    """Calcola la distanza stradale in auto fra due localita' gia' geocodificate."""
    proprio = client is None
    client = client or httpx.AsyncClient(timeout=TIMEOUT, headers={"User-Agent": USER_AGENT})
    try:
        chiave = chiave_ors()
        if chiave:
            payload = await _json(
                client,
                URL_ORS_DIRECTIONS,
                params={
                    "api_key": chiave,
                    "start": f"{origine.lon},{origine.lat}",
                    "end": f"{destinazione.lon},{destinazione.lat}",
                },
            )
            km, minuti = misure_da_ors(payload)
            servizio = "OpenRouteService"
        else:
            coordinate = (
                f"{origine.lon},{origine.lat};{destinazione.lon},{destinazione.lat}"
            )
            payload = await _json(
                client, f"{URL_OSRM}/{coordinate}", params={"overview": "false"}
            )
            km, minuti = misure_da_osrm(payload)
            servizio = "OSRM / OpenStreetMap"
    finally:
        if proprio:
            await client.aclose()

    return Percorso(
        origine=origine,
        destinazione=destinazione,
        distanza_km=km,
        durata_minuti=minuti,
        servizio=servizio,
    )


async def percorso_fra(
    partenza: str, arrivo: str, client: httpx.AsyncClient | None = None
) -> Percorso:
    """Scorciatoia: geocodifica i due estremi e calcola il percorso."""
    proprio = client is None
    client = client or httpx.AsyncClient(timeout=TIMEOUT, headers={"User-Agent": USER_AGENT})
    try:
        origine = await cerca_luogo(partenza, client)
        destinazione = await cerca_luogo(arrivo, client)
        return await calcola_percorso(origine, destinazione, client)
    finally:
        if proprio:
            await client.aclose()
