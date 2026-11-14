"""Unit test della logica di calcolo (Schema B)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from calcolo import (  # noqa: E402
    COEFFICIENTI_DEFAULT,
    InputNonValido,
    Tratta,
    arrotonda,
    calcola_tratta,
    calcola_viaggio,
    coefficienti_con_default,
    dividi_a_meta,
    parse_coefficiente,
    parse_decimale,
    parse_distanza,
    parse_importo,
    parse_partecipanti,
)

# Caso di verifica richiesto dalla specifica: viaggio A/R di 480 km per tratta,
# carburante + pedaggi = 106,75 € a tratta, auto di categoria media (0,10 €/km),
# 3 partecipanti all'andata e 4 al ritorno.
ANDATA = Tratta(nome="Andata", distanza_km=480, partecipanti=3, carburante=85.00, pedaggi=21.75)
RITORNO = Tratta(nome="Ritorno", distanza_km=480, partecipanti=4, carburante=85.00, pedaggi=21.75)
C_MEDIA = 0.10


# --------------------------------------------------------------------------- #
# Caso di verifica della specifica
# --------------------------------------------------------------------------- #

def test_andata_caso_di_verifica():
    r = calcola_tratta(ANDATA, C_MEDIA)
    assert r.tratta.costo_viaggio == pytest.approx(106.75)
    assert arrotonda(r.usura_totale) == 48.00
    assert arrotonda(r.q_usura) == 16.00
    assert arrotonda(r.q_viaggio) == 35.58
    assert arrotonda(r.quota_passeggero) == 51.58
    assert arrotonda(r.quota_conducente) == 35.58
    assert arrotonda(r.usura_incassata_conducente) == 32.00


def test_ritorno_caso_di_verifica():
    r = calcola_tratta(RITORNO, C_MEDIA)
    assert arrotonda(r.usura_totale) == 48.00
    assert arrotonda(r.q_usura) == 12.00
    assert arrotonda(r.q_viaggio) == 26.69
    assert arrotonda(r.quota_passeggero) == 38.69
    assert arrotonda(r.quota_conducente) == 26.69
    assert arrotonda(r.usura_incassata_conducente) == 36.00


def test_viaggio_completo_caso_di_verifica():
    ris = calcola_viaggio([ANDATA, RITORNO], C_MEDIA, "media")

    assert ris.andata_e_ritorno is True
    # Passeggero presente su entrambe le tratte: 51,58 + 38,69
    assert arrotonda(ris.quota_passeggero_completo) == 90.27
    quote = ris.quote_passeggero_per_tratta
    assert arrotonda(quote["Andata"]) == 51.58
    assert arrotonda(quote["Ritorno"]) == 38.69
    # Esborso del conducente: 35,58 + 26,69
    assert arrotonda(ris.esborso_conducente) == 62.27
    # Usura incassata: 32,00 + 36,00
    assert arrotonda(ris.usura_incassata_conducente) == 68.00
    assert arrotonda(ris.totale_costi_viaggio) == 213.50
    assert arrotonda(ris.totale_usura) == 96.00


# --------------------------------------------------------------------------- #
# Proprieta' generali dello Schema B
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("n", [2, 3, 4, 5, 7, 10])
@pytest.mark.parametrize("coefficiente", [0.05, 0.10, 0.15])
def test_quadratura_carburante_e_pedaggi(n, coefficiente):
    """Le quote viaggio raccolte da tutti coprono esattamente B + T."""
    tratta = Tratta("X", distanza_km=333, partecipanti=n, carburante=77.7, pedaggi=12.3)
    r = calcola_tratta(tratta, coefficiente)
    raccolto = r.quota_conducente + r.q_viaggio * (n - 1)
    assert raccolto == pytest.approx(tratta.costo_viaggio)
    assert r.verifica.quadra is True
    assert r.verifica.atteso == pytest.approx(tratta.costo_viaggio)


@pytest.mark.parametrize("n", [2, 3, 6])
def test_usura_divisa_per_n_conducente_incluso(n):
    """Q_usura = c*D/N e il conducente ne incassa solo (N-1) frazioni."""
    tratta = Tratta("X", distanza_km=200, partecipanti=n, carburante=50, pedaggi=0)
    r = calcola_tratta(tratta, 0.10)
    assert r.usura_totale == pytest.approx(20.0)
    assert r.q_usura == pytest.approx(20.0 / n)
    assert r.usura_incassata_conducente == pytest.approx(r.q_usura * (n - 1))
    # La frazione di usura del conducente resta a suo carico.
    assert r.usura_totale - r.usura_incassata_conducente == pytest.approx(r.q_usura)


def test_conducente_non_versa_usura():
    r = calcola_tratta(ANDATA, C_MEDIA)
    assert r.quota_conducente == pytest.approx(r.q_viaggio)
    assert r.quota_passeggero - r.quota_conducente == pytest.approx(r.q_usura)


def test_cassa_del_conducente():
    """Anticipo B+T, incasso dai passeggeri, saldo che copre l'usura."""
    ris = calcola_viaggio([ANDATA, RITORNO], C_MEDIA, "media")
    incassato = arrotonda(ris.incassato_dai_passeggeri)
    # Andata: 51,58 x 2 = 103,17 (esatto 103,1666); Ritorno: 38,69 x 3 = 116,06
    assert incassato == pytest.approx(51.5833333 * 2 + 38.6875 * 3, abs=0.01)
    # saldo_cassa = quanto anticipato meno quanto incassato
    assert ris.saldo_cassa_conducente == pytest.approx(
        ris.totale_costi_viaggio - ris.incassato_dai_passeggeri
    )


def test_tratta_singola():
    ris = calcola_viaggio([ANDATA], C_MEDIA, "media")
    assert ris.andata_e_ritorno is False
    assert arrotonda(ris.quota_passeggero_completo) == 51.58
    assert arrotonda(ris.esborso_conducente) == 35.58


@pytest.mark.parametrize(
    "categoria,atteso", [("piccola", 0.05), ("media", 0.10), ("grande", 0.15)]
)
def test_coefficienti_default(categoria, atteso):
    assert COEFFICIENTI_DEFAULT[categoria] == pytest.approx(atteso)


def test_costi_a_zero():
    """Viaggio senza carburante ne' pedaggi: resta solo l'usura."""
    tratta = Tratta("X", distanza_km=100, partecipanti=4, carburante=0, pedaggi=0)
    r = calcola_tratta(tratta, 0.15)
    assert r.q_viaggio == 0
    assert r.quota_conducente == 0
    assert r.quota_passeggero == pytest.approx(15.0 / 4)


# --------------------------------------------------------------------------- #
# Validazione degli input
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize(
    "testo,atteso",
    [
        ("35,58", 35.58),
        ("35.58", 35.58),
        (" 35,58 € ", 35.58),
        ("1.234,56", 1234.56),
        ("1,234.56", 1234.56),
        ("480 km", 480.0),
        ("0,05", 0.05),
        ("12", 12.0),
    ],
)
def test_parse_decimale_formati_italiani(testo, atteso):
    assert parse_decimale(testo) == pytest.approx(atteso)


@pytest.mark.parametrize("testo", ["", "   ", "abc", "12,3,4", "€", None])
def test_parse_decimale_rifiuta_non_numeri(testo):
    with pytest.raises(InputNonValido):
        parse_decimale(testo)


@pytest.mark.parametrize("testo", ["-1", "-0,01"])
def test_parse_importo_rifiuta_negativi(testo):
    with pytest.raises(InputNonValido):
        parse_importo(testo)


def test_parse_importo_accetta_zero():
    assert parse_importo("0") == 0.0


@pytest.mark.parametrize("testo", ["0", "-10", "0,0"])
def test_parse_distanza_rifiuta_non_positivi(testo):
    with pytest.raises(InputNonValido):
        parse_distanza(testo)


@pytest.mark.parametrize("testo,atteso", [("2", 2), ("3", 3), ("4,0", 4), ("10", 10)])
def test_parse_partecipanti_validi(testo, atteso):
    assert parse_partecipanti(testo) == atteso


@pytest.mark.parametrize("testo", ["1", "0", "-3", "2,5", "abc"])
def test_parse_partecipanti_rifiuta_non_validi(testo):
    with pytest.raises(InputNonValido):
        parse_partecipanti(testo)


@pytest.mark.parametrize("testo,atteso", [("0,12", 0.12), ("0.2", 0.2), ("1", 1.0)])
def test_parse_coefficiente_valido(testo, atteso):
    assert parse_coefficiente(testo) == pytest.approx(atteso)


@pytest.mark.parametrize("testo", ["0", "-0,1", "999", "tanto"])
def test_parse_coefficiente_rifiuta_non_validi(testo):
    with pytest.raises(InputNonValido):
        parse_coefficiente(testo)


def test_tratta_rifiuta_dati_impossibili():
    with pytest.raises(InputNonValido):
        Tratta("X", distanza_km=0, partecipanti=3, carburante=10, pedaggi=0)
    with pytest.raises(InputNonValido):
        Tratta("X", distanza_km=10, partecipanti=1, carburante=10, pedaggi=0)
    with pytest.raises(InputNonValido):
        Tratta("X", distanza_km=10, partecipanti=2, carburante=-1, pedaggi=0)


def test_calcola_viaggio_rifiuta_lista_vuota():
    with pytest.raises(InputNonValido):
        calcola_viaggio([], C_MEDIA)


def test_calcola_tratta_rifiuta_coefficiente_non_positivo():
    with pytest.raises(InputNonValido):
        calcola_tratta(ANDATA, 0)


# --------------------------------------------------------------------------- #
# Utilita'
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize(
    "totale,parti",
    [(106.75, [53.38, 53.37]), (100.0, [50.0, 50.0]), (0.0, [0.0, 0.0])],
)
def test_dividi_a_meta_conserva_il_totale(totale, parti):
    risultato = dividi_a_meta(totale, 2)
    assert risultato == parti
    assert arrotonda(sum(risultato)) == arrotonda(totale)


def test_coefficienti_con_default_ignora_valori_strani():
    valori = coefficienti_con_default(
        {"media": 0.12, "inesistente": 9.9, "grande": -1, "piccola": "boh"}
    )
    assert valori["media"] == pytest.approx(0.12)
    assert valori["grande"] == pytest.approx(0.15)
    assert valori["piccola"] == pytest.approx(0.05)
    assert "inesistente" not in valori


def test_coefficienti_con_default_senza_personalizzazioni():
    assert coefficienti_con_default(None) == COEFFICIENTI_DEFAULT
    assert coefficienti_con_default({}) == COEFFICIENTI_DEFAULT


# --------------------------------------------------------------------------- #
# Input della carta d'imbarco
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize(
    "testo,atteso",
    [
        ("07:30", "07:30"),
        ("7:30", "07:30"),
        ("7.30", "07:30"),
        ("7 30", "07:30"),
        ("0730", "07:30"),
        ("730", "07:30"),
        ("19h45", "19:45"),
        ("8", "08:00"),
        ("  23:59  ", "23:59"),
        ("0:00", "00:00"),
    ],
)
def test_parse_orario_formati_liberi(testo, atteso):
    from calcolo import parse_orario

    assert parse_orario(testo) == atteso


@pytest.mark.parametrize("testo", ["", "   ", "abc", "24:00", "12:60", "25", "-1:00", None])
def test_parse_orario_rifiuta_non_validi(testo):
    from calcolo import parse_orario

    with pytest.raises(InputNonValido):
        parse_orario(testo)


def test_parse_testo_breve_normalizza_spazi():
    from calcolo import parse_testo_breve

    assert parse_testo_breve("  Mario   Rossi ", 28, "nome") == "Mario Rossi"


@pytest.mark.parametrize("testo", ["", "    ", None])
def test_parse_testo_breve_rifiuta_vuoti(testo):
    from calcolo import parse_testo_breve

    with pytest.raises(InputNonValido):
        parse_testo_breve(testo, 28, "nome")


def test_parse_testo_breve_rifiuta_troppo_lungo():
    from calcolo import parse_testo_breve

    with pytest.raises(InputNonValido):
        parse_testo_breve("x" * 29, 28, "nome")


# --------------------------------------------------------------------------- #
# Stima del carburante
# --------------------------------------------------------------------------- #

def test_stima_carburante_caso_tipico():
    from calcolo import stima_carburante

    # 577,5 km a 7 l/100 km = 40,425 l; a 1,80 €/l = 72,765 €
    assert stima_carburante(577.5, 7.0, 1.80) == pytest.approx(72.765)
    assert arrotonda(stima_carburante(577.5, 7.0, 1.80)) == 72.77


def test_litri_stimati():
    from calcolo import litri_stimati

    assert litri_stimati(100, 7.0) == pytest.approx(7.0)
    assert litri_stimati(577.5, 7.0) == pytest.approx(40.425)


def test_stima_proporzionale_ai_km():
    from calcolo import stima_carburante

    singola = stima_carburante(300, 6.0, 1.9)
    doppia = stima_carburante(600, 6.0, 1.9)
    assert doppia == pytest.approx(singola * 2)


def test_stima_a_zero_km():
    from calcolo import stima_carburante

    assert stima_carburante(0, 7.0, 1.8) == 0.0


@pytest.mark.parametrize(
    "km,consumo,prezzo", [(-1, 7, 1.8), (100, 0, 1.8), (100, 7, 0), (100, -7, 1.8)]
)
def test_stima_rifiuta_dati_impossibili(km, consumo, prezzo):
    from calcolo import stima_carburante

    with pytest.raises(InputNonValido):
        stima_carburante(km, consumo, prezzo)


@pytest.mark.parametrize(
    "categoria,atteso", [("piccola", 5.5), ("media", 7.0), ("grande", 9.0)]
)
def test_consumi_default(categoria, atteso):
    from calcolo import CONSUMI_DEFAULT

    assert CONSUMI_DEFAULT[categoria] == pytest.approx(atteso)


def test_consumi_con_default_ignora_valori_strani():
    from calcolo import CONSUMI_DEFAULT, consumi_con_default

    valori = consumi_con_default({"media": 8.5, "grande": -2, "camion": 30})
    assert valori["media"] == pytest.approx(8.5)
    assert valori["grande"] == pytest.approx(CONSUMI_DEFAULT["grande"])
    assert "camion" not in valori


@pytest.mark.parametrize(
    "testo,atteso", [("1,80", 1.80), ("1.899", 1.899), ("1,789 €", 1.789), ("2", 2.0)]
)
def test_parse_prezzo_litro_valido(testo, atteso):
    from calcolo import parse_prezzo_litro

    assert parse_prezzo_litro(testo) == pytest.approx(atteso)


@pytest.mark.parametrize("testo", ["0", "-1,8", "180", "gratis", ""])
def test_parse_prezzo_litro_rifiuta_non_validi(testo):
    from calcolo import parse_prezzo_litro

    with pytest.raises(InputNonValido):
        parse_prezzo_litro(testo)


@pytest.mark.parametrize("testo,atteso", [("7", 7.0), ("7,5", 7.5), ("12.3", 12.3)])
def test_parse_consumo_valido(testo, atteso):
    from calcolo import parse_consumo

    assert parse_consumo(testo) == pytest.approx(atteso)


@pytest.mark.parametrize("testo", ["0", "-5", "100", "boh"])
def test_parse_consumo_rifiuta_non_validi(testo):
    from calcolo import parse_consumo

    with pytest.raises(InputNonValido):
        parse_consumo(testo)


def test_viaggio_con_carburante_stimato():
    from calcolo import stima_carburante

    consumo, prezzo = 7.0, 1.80
    tratte = [
        Tratta(
            "Andata",
            480,
            3,
            arrotonda(stima_carburante(480, consumo, prezzo)),
            21.75,
            carburante_stimato=True,
        ),
        Tratta("Ritorno", 480, 4, 85.00, 21.75),
    ]
    ris = calcola_viaggio(tratte, 0.10, "media", consumo=consumo, prezzo_litro=prezzo)

    assert ris.carburante_stimato is True
    assert ris.consumo == pytest.approx(consumo)
    assert ris.prezzo_litro == pytest.approx(prezzo)
    # I litri contano solo le tratte effettivamente stimate.
    assert ris.litri_totali == pytest.approx(480 / 100 * consumo)


def test_viaggio_senza_stima_non_espone_consumi():
    ris = calcola_viaggio([ANDATA, RITORNO], C_MEDIA, "media")
    assert ris.carburante_stimato is False
    assert ris.consumo is None
    assert ris.litri_totali is None
