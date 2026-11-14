"""Test della formattazione dei testi."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import messaggi  # noqa: E402
from calcolo import Tratta, calcola_viaggio  # noqa: E402

ANDATA = Tratta("Andata", 480, 3, 85.00, 21.75)
RITORNO = Tratta("Ritorno", 480, 4, 85.00, 21.75)


@pytest.mark.parametrize(
    "valore,atteso",
    [(35.5833, "35,58 €"), (0, "0,00 €"), (1234.5, "1.234,50 €"), (106.75, "106,75 €")],
)
def test_formatta_euro(valore, atteso):
    assert messaggi.formatta_euro(valore) == atteso


def test_formatta_km():
    assert messaggi.formatta_km(480) == "480 km"
    assert messaggi.formatta_km(480.5) == "480,5 km"


def test_formatta_coefficiente():
    assert messaggi.formatta_coefficiente(0.1) == "0,10 €/km"
    assert messaggi.formatta_coefficiente(0.125) == "0,125 €/km"


def test_conto_contiene_le_quote_attese():
    testo = messaggi.testo_conto(calcola_viaggio([ANDATA, RITORNO], 0.10, "media"))
    # Quanto paga ciascuno: passeggeri e conducente, per tratta e in totale.
    for atteso in ("51,58 €", "35,58 €", "38,69 €", "26,69 €", "90,27 €", "62,27 €"):
        assert atteso in testo, atteso
    assert testo.count("```") % 2 == 0


def test_conto_e_semplice():
    """Niente scomposizioni intermedie: solo quanto paga ciascuno."""
    testo = messaggi.testo_conto(calcola_viaggio([ANDATA, RITORNO], 0.10, "media"))
    for assente in ("Q usura", "Q viaggio", "Verifica", "16,00 €", "12,00 €"):
        assert assente not in testo, assente
    assert "Passeggero" in testo
    assert "Conducente" in testo


def test_conto_tratta_singola():
    testo = messaggi.testo_conto(calcola_viaggio([ANDATA], 0.10, "media"))
    assert "51,58 €" in testo
    assert "35,58 €" in testo
    assert "QUANTO PAGA CIASCUNO" in testo


def test_messaggio_condivisibile():
    ris = calcola_viaggio([ANDATA, RITORNO], 0.10, "media")
    testo = messaggi.testo_condivisibile(ris, "Gianluigi")
    assert "Gianluigi" in testo
    assert "90,27 €" in testo
    assert "51,58 €" in testo
    assert "38,69 €" in testo


def test_messaggio_condivisibile_senza_nome():
    ris = calcola_viaggio([ANDATA], 0.10, "media")
    testo = messaggi.testo_condivisibile(ris, "")
    assert "chi ha guidato" in testo


def test_escape_markdown():
    assert messaggi.escape_markdown("Anna_Maria") == "Anna\\_Maria"


# --------------------------------------------------------------------------- #
# Carta d'imbarco
# --------------------------------------------------------------------------- #

CARTA_BASE = dict(
    nome="Mario Rossi",
    tratta="Andata e ritorno",
    orario="07:30",
    indirizzo="Via Roma 12",
    quota=90.27,
    veicolo="Auto media",
    partecipanti=3,
    codice="VG7K2Q",
    posto="2B",
)


def _righe_carta(testo: str) -> list[str]:
    dentro = testo.split("```")[1]
    return [r for r in dentro.splitlines() if r.strip()]


def test_carta_imbarco_passeggero():
    testo = messaggi.carta_imbarco(**CARTA_BASE)
    assert "DIVIDE ET VIAGGIA" in testo
    assert "MARIO ROSSI" in testo
    assert "07:30" in testo
    assert "VIA ROMA 12" in testo
    assert "90,27 €" in testo
    assert "VG7K2Q" in testo


def test_carta_imbarco_mostra_il_veicolo():
    testo = messaggi.carta_imbarco(**CARTA_BASE)
    assert "VEICOLO" in testo
    assert "AUTO MEDIA" in testo
    assert "VOLO" not in testo


def test_carta_imbarco_non_parla_di_usura():
    """Al viaggiatore mostriamo solo la cifra che deve versare."""
    testo = messaggi.carta_imbarco(**CARTA_BASE).lower()
    for assente in ("usura", "carburante", "pedagg"):
        assert assente not in testo, assente


def test_carta_imbarco_bordi_allineati():
    """Tutte le righe della carta devono avere la stessa larghezza."""
    righe = _righe_carta(messaggi.carta_imbarco(**CARTA_BASE))
    larghezze = {len(r) for r in righe}
    assert len(larghezze) == 1, larghezze
    for riga in righe[1:-1]:
        assert riga.startswith(("|", "+"))
        assert riga.endswith(("|", "+"))


def test_carta_imbarco_indirizzo_lungo_va_a_capo():
    dati = dict(CARTA_BASE, indirizzo="Via Generale Giuseppe Garibaldi 128 scala B")
    righe = _righe_carta(messaggi.carta_imbarco(**dati))
    assert len({len(r) for r in righe}) == 1
    assert "GARIBALDI" in "".join(righe)


def test_carta_imbarco_conducente():
    dati = dict(CARTA_BASE, ruolo="CONDUCENTE", quota=62.27)
    testo = messaggi.carta_imbarco(**dati)
    assert "COMANDANTE" in testo
    assert "A TUO CARICO" in testo
    assert "62,27 €" in testo
    assert "usura" not in testo.lower()
    assert len({len(r) for r in _righe_carta(testo)}) == 1


def test_carta_imbarco_blocco_markdown_bilanciato():
    assert messaggi.carta_imbarco(**CARTA_BASE).count("```") == 2


def test_nome_bot():
    assert messaggi.NOME_BOT == "Divide et viaggia"
    assert "Divide et viaggia" in messaggi.BENVENUTO
    assert "Divide et viaggia" in messaggi.HELP


# --------------------------------------------------------------------------- #
# Stima del carburante nei testi
# --------------------------------------------------------------------------- #

def test_formattazioni_carburante():
    assert messaggi.formatta_consumo(7.0) == "7,0 l/100 km"
    assert messaggi.formatta_prezzo_litro(1.80) == "1,80 €/l"
    assert messaggi.formatta_prezzo_litro(1.789) == "1,789 €/l"
    assert messaggi.formatta_litri(40.425) == "40,4 l"


def _viaggio_stimato():
    from calcolo import arrotonda, stima_carburante

    spesa = arrotonda(stima_carburante(480, 7.0, 1.80))
    tratte = [
        Tratta("Andata", 480, 3, spesa, 21.75, carburante_stimato=True),
        Tratta("Ritorno", 480, 4, spesa, 21.75, carburante_stimato=True),
    ]
    return calcola_viaggio(tratte, 0.10, "media", consumo=7.0, prezzo_litro=1.80)


def test_conto_spiega_la_stima():
    testo = messaggi.testo_conto(_viaggio_stimato())
    assert "(stima)" in testo
    assert "7,0 l/100 km" in testo
    assert "1,80 €/l" in testo
    assert "/coefficienti" in testo
    assert testo.count("```") % 2 == 0


def test_conto_senza_stima_non_parla_di_consumi():
    testo = messaggi.testo_conto(calcola_viaggio([ANDATA, RITORNO], 0.10, "media"))
    assert "(stima)" not in testo
    assert "l/100 km" not in testo


def test_messaggio_condivisibile_non_parla_di_usura():
    """Ai viaggiatori arriva la quota, non come e' composta."""
    testo = messaggi.testo_condivisibile(_viaggio_stimato(), "Anna").lower()
    for assente in ("usura", "carburante", "pedagg", "stima", "l/100"):
        assert assente not in testo, assente


def test_messaggio_condivisibile_mostra_solo_le_quote():
    ris = calcola_viaggio([ANDATA, RITORNO], 0.10, "media")
    testo = messaggi.testo_condivisibile(ris, "Anna")
    assert "90,27 €" in testo
    # Nessun totale di spesa da cui risalire alla scomposizione.
    for assente in ("170,00 €", "213,50 €", "96,00 €"):
        assert assente not in testo, assente


def test_schermata_coefficienti():
    from calcolo import COEFFICIENTI_DEFAULT, CONSUMI_DEFAULT

    testo = messaggi.testo_coefficienti(
        dict(COEFFICIENTI_DEFAULT, media=0.12),
        dict(CONSUMI_DEFAULT, media=8.0),
        {"media": 0.12},
        {"media": 8.0},
        1.789,
    )
    assert "0,12 €/km" in testo
    assert "8,0 l/100 km" in testo
    assert "1,789 €/l" in testo
    assert "Media *" in testo


def test_schermata_coefficienti_tutta_default():
    from calcolo import COEFFICIENTI_DEFAULT, CONSUMI_DEFAULT

    testo = messaggi.testo_coefficienti(COEFFICIENTI_DEFAULT, CONSUMI_DEFAULT, {}, {}, None)
    assert "default" in testo
    assert "*" not in testo.split("```")[1]


def test_valore_salvato_per_tipo():
    assert "usura" in messaggi.valore_salvato("media", "usura", 0.12)
    assert "0,12 €/km" in messaggi.valore_salvato("media", "usura", 0.12)
    assert "consumo" in messaggi.valore_salvato("media", "consumo", 8.0)
    assert "8,0 l/100 km" in messaggi.valore_salvato("media", "consumo", 8.0)


def test_messaggio_condivisibile_non_presuppone_il_viaggio_fatto():
    """Va bene sia inviato prima di partire, sia dopo il rientro."""
    ris = calcola_viaggio([ANDATA, RITORNO], 0.10, "media")
    testo = messaggi.testo_condivisibile(ris, "Anna").lower()
    for passato in ("c'era", "era a bordo", "e' stato", "è stato", "siamo stati"):
        assert passato not in testo, passato
