"""Test del modulo percorsi: parsing delle risposte, senza toccare la rete."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import percorso  # noqa: E402
from percorso import (  # noqa: E402
    Luogo,
    LuogoNonTrovato,
    Percorso,
    ServizioNonDisponibile,
    luogo_da_nominatim,
    luogo_da_pelias,
    misure_da_ors,
    misure_da_osrm,
)

# Risposte reali accorciate, raccolte dai servizi veri.
NOMINATIM_CITTA = [
    {
        "lat": "44.4938203",
        "lon": "11.3426327",
        "name": "Bologna",
        "display_name": "Bologna, Emilia-Romagna, Italia",
        "address": {"city": "Bologna", "county": "Bologna", "country": "Italia"},
    }
]

NOMINATIM_CIVICO = [
    {
        "lat": "45.0665",
        "lon": "7.6825",
        "name": "CK",
        "display_name": "CK, 12, Via Roma, Torino, Piemonte, Italia",
        "address": {
            "shop": "clothes",
            "house_number": "12",
            "road": "Via Roma",
            "city": "Torino",
        },
    }
]

OSRM_OK = {
    "code": "Ok",
    "routes": [{"distance": 577478.9, "duration": 21497.2}],
}

ORS_OK = {
    "features": [{"properties": {"summary": {"distance": 577478.9, "duration": 21497.2}}}]
}

PELIAS_OK = {
    "features": [
        {
            "geometry": {"coordinates": [11.3426, 44.4938]},
            "properties": {"name": "Bologna", "label": "Bologna, Emilia-Romagna, Italia"},
        }
    ]
}


# --------------------------------------------------------------------------- #
# Geocoding
# --------------------------------------------------------------------------- #

def test_nominatim_citta():
    luogo = luogo_da_nominatim(NOMINATIM_CITTA)
    assert luogo.nome == "Bologna"
    assert luogo.lat == pytest.approx(44.4938203)
    assert luogo.lon == pytest.approx(11.3426327)


def test_nominatim_civico_preferisce_la_via_al_negozio():
    """Su un civico Nominatim restituisce il POI che ci sta sopra: non ci serve."""
    luogo = luogo_da_nominatim(NOMINATIM_CIVICO)
    assert luogo.nome == "Via Roma 12, Torino"


def test_nominatim_non_ripete_la_citta():
    payload = [
        {
            "lat": "45.4",
            "lon": "9.1",
            "name": "Milano Centrale",
            "display_name": "Milano Centrale, Milano, Lombardia, Italia",
            "address": {"city": "Milano"},
        }
    ]
    assert luogo_da_nominatim(payload).nome == "Milano Centrale"


@pytest.mark.parametrize("payload", [[], None, {}])
def test_nominatim_senza_risultati(payload):
    with pytest.raises(LuogoNonTrovato):
        luogo_da_nominatim(payload)


def test_nominatim_risposta_malformata():
    with pytest.raises(ServizioNonDisponibile):
        luogo_da_nominatim([{"display_name": "X", "lat": "boh", "lon": "1"}])


def test_pelias():
    luogo = luogo_da_pelias(PELIAS_OK)
    assert luogo.nome == "Bologna, Emilia-Romagna"
    assert luogo.lat == pytest.approx(44.4938)
    assert luogo.lon == pytest.approx(11.3426)


def test_pelias_senza_risultati():
    with pytest.raises(LuogoNonTrovato):
        luogo_da_pelias({"features": []})


# --------------------------------------------------------------------------- #
# Percorsi
# --------------------------------------------------------------------------- #

def test_osrm():
    km, minuti = misure_da_osrm(OSRM_OK)
    assert km == pytest.approx(577.5)
    assert minuti == pytest.approx(358.29, abs=0.1)


def test_ors():
    km, minuti = misure_da_ors(ORS_OK)
    assert km == pytest.approx(577.5)


@pytest.mark.parametrize(
    "payload",
    [
        {"code": "NoRoute", "routes": []},
        {"code": "Ok", "routes": []},
        {"code": "Ok", "routes": [{"distance": 0, "duration": 0}]},
        {},
        None,
    ],
)
def test_osrm_risposte_inutilizzabili(payload):
    with pytest.raises(ServizioNonDisponibile):
        misure_da_osrm(payload)


def test_durata_mancante_non_blocca():
    km, minuti = misure_da_osrm({"code": "Ok", "routes": [{"distance": 1000}]})
    assert km == pytest.approx(1.0)
    assert minuti is None


# --------------------------------------------------------------------------- #
# Presentazione
# --------------------------------------------------------------------------- #

def _percorso(minuti):
    luogo = Luogo("A", "A", 0.0, 0.0)
    return Percorso(luogo, luogo, 100.0, minuti, "test")


@pytest.mark.parametrize(
    "minuti,atteso", [(358.29, "5h 58min"), (45.0, "45 min"), (60.0, "1h 00min"), (None, None)]
)
def test_durata_leggibile(minuti, atteso):
    assert _percorso(minuti).durata_leggibile == atteso


def test_chiave_ors_da_ambiente(monkeypatch):
    monkeypatch.delenv("ORS_API_KEY", raising=False)
    assert percorso.chiave_ors() is None
    monkeypatch.setenv("ORS_API_KEY", "  ")
    assert percorso.chiave_ors() is None
    monkeypatch.setenv("ORS_API_KEY", "abc123")
    assert percorso.chiave_ors() == "abc123"


def test_query_troppo_corta_non_chiama_la_rete():
    import asyncio

    with pytest.raises(LuogoNonTrovato):
        asyncio.run(percorso.cerca_luogo("a"))
