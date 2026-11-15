"""Numeri scritti dall'utente, arrotondamento dei soldi, carta d'imbarco."""
import math

import pytest

import messaggi
from calcolo import (
    InputNonValido,
    arrotonda,
    parse_coefficiente,
    parse_consumo,
    parse_decimale,
    parse_distanza,
    parse_importo,
    parse_prezzo_litro,
)


# --- arrotondamento ---------------------------------------------------------
@pytest.mark.parametrize("valore, atteso", [
    (2.675, 2.68),          # round() dava 2.67: in binario e' 2.67499999...
    (1.005, 1.01),          # round() dava 1.0
    (0.125, 0.13),          # round() dava 0.12 (arrotonda al pari)
    (0.135, 0.14),
    (35.575, 35.58),
    (2.665, 2.67),
    (10.0, 10.0), (0.0, 0.0), (0.004, 0.0), (0.005, 0.01), (0.0049999, 0.0),
    (1234567.895, 1234567.9),
])
def test_il_mezzo_centesimo_va_per_eccesso(valore, atteso):
    assert arrotonda(valore) == atteso


def test_il_rumore_binario_non_cambia_il_risultato():
    """106,725 / 3 fa 35,575 in aritmetica, 35,574999999999996 in virgola mobile."""
    assert 106.725 / 3 != 35.575
    assert arrotonda(106.725 / 3) == 35.58
    assert arrotonda(0.1 + 0.2) == 0.3
    assert arrotonda(sum([0.015] * 3)) == 0.05          # 0,045 esatto: per eccesso


def test_negativi_simmetrici_e_niente_meno_zero():
    assert arrotonda(-2.675) == -2.68
    assert math.copysign(1.0, arrotonda(-0.001)) == 1.0     # 0.0, non -0.0
    assert math.copysign(1.0, arrotonda(-0.0)) == 1.0


def test_valori_non_finiti_non_fanno_cadere_l_arrotondamento():
    assert arrotonda(float("inf")) == float("inf")
    assert math.isnan(arrotonda(float("nan")))


def test_la_somma_delle_quote_di_un_conto_in_tre():
    """Tre quote da 11,67 fanno 35,01: un centesimo in piu' del totale, mai in meno."""
    quota = arrotonda(35 / 3)
    assert quota == 11.67
    assert arrotonda(quota * 3) >= 35.0


# --- numeri scritti dall'utente ---------------------------------------------
@pytest.mark.parametrize("testo, atteso", [
    ("12", 12.0), ("12,5", 12.5), ("12.5", 12.5), ("12,50 €", 12.5), ("€ 12,50", 12.5),
    ("1.234,56", 1234.56), ("1,234.56", 1234.56), ("1 234,56", 1234.56),
    ("1.234.567", 1234567.0), ("12.345.678,9", 12345678.9),
    ("480 km", 480.0), ("0,5", 0.5), (",5", 0.5), ("5,", 5.0), ("+3", 3.0), ("-3", -3.0),
    ("1.234", 1.234),           # da solo e' un decimale: lo decide chi conosce l'unita'
])
def test_parse_decimale_legge_i_numeri_all_italiana(testo, atteso):
    assert parse_decimale(testo) == pytest.approx(atteso)


@pytest.mark.parametrize("testo", [
    "1_000", "1e3", "1E3", "1e-3", "inf", "Infinity", "nan", "0x10", "١٢٣", "１２３",
    "1.2.3", "1,2,3", "12,34,56", "--5", "5-", "1 2 3 x", "abc", "", "   ", ".", ",",
    "12€€x", "1.23.456",
])
def test_parse_decimale_rifiuta_cio_che_non_e_un_numero_scritto_a_mano(testo):
    with pytest.raises(InputNonValido):
        parse_decimale(testo)


def test_parse_decimale_senza_testo():
    with pytest.raises(InputNonValido):
        parse_decimale(None)


@pytest.mark.parametrize("testo", ["1.234", "12.345", "123.456", "1.000", "1.234 €", "€1.234", "1.234 km"])
def test_importo_e_distanza_ambigui_vengono_rifiutati_con_spiegazione(testo):
    for funzione in (parse_importo, parse_distanza):
        with pytest.raises(InputNonValido) as errore:
            funzione(testo)
        messaggio = str(errore.value)
        assert "due modi" in messaggio
        intero = "".join(c for c in testo if c.isdigit())
        assert f"`{intero}`" in messaggio                      # come scriverlo senza ambiguita'


@pytest.mark.parametrize("testo, atteso", [
    ("1234", 1234.0), ("1.234,00", 1234.0), ("1,234", 1.234), ("1.23", 1.23), ("12.5", 12.5),
    ("1.2345", 1.2345), ("1234.567", 1234.567), ("1.234,5", 1234.5), ("0", 0.0),
])
def test_importi_non_ambigui_passano(testo, atteso):
    assert parse_importo(testo) == pytest.approx(atteso)


def test_tre_decimali_restano_validi_dove_hanno_senso():
    """Prezzo al litro, consumo e coefficienti si scrivono davvero con tre decimali."""
    assert parse_prezzo_litro("1.789") == pytest.approx(1.789)
    assert parse_prezzo_litro("1,789") == pytest.approx(1.789)
    assert parse_coefficiente("0.125") == pytest.approx(0.125)
    assert parse_consumo("6.125") == pytest.approx(6.125)


def test_importo_negativo_o_enorme():
    for testo in ("-1", "999999999999"):
        with pytest.raises(InputNonValido):
            parse_importo(testo)


# --- carta d'imbarco --------------------------------------------------------
CARTA = dict(nome="Mario Rossi", tratta="Tratta unica", orario="08:30",
             indirizzo="Via Roma 12", quota=15.67, veicolo="Auto media", partecipanti=3)


def dentro_al_blocco(testo: str) -> list[str]:
    parti = testo.split("```")
    assert len(parti) == 3, "la carta deve avere un solo blocco di codice, chiuso"
    return parti[1].strip().splitlines()


@pytest.mark.parametrize("campo, valore", [
    ("nome", "Ma`rio ```x"), ("nome", "```"), ("nome", "`" * 40),
    ("indirizzo", "Via `Roma` 12"), ("indirizzo", "``` fine ```"),
    ("tratta", "A`B"), ("veicolo", "Pan`da"), ("orario", "08`30"),
    ("origine", "Mi`lano"),
])
def test_un_backtick_non_chiude_il_blocco_della_carta(campo, valore):
    dati = {**CARTA, campo: valore}
    if campo == "origine":
        dati["destinazione"] = "Roma"
    testo = messaggi.carta_imbarco(**dati)
    assert testo.count("```") == 2
    assert all("`" not in riga for riga in dentro_al_blocco(testo))


@pytest.mark.parametrize("valore", ["Via Roma 12\nscala B", "Via Roma\r\n12", "Via\tRoma", "a\n\n\nb"])
def test_a_capo_e_tabulazioni_non_rompono_la_cornice(valore):
    righe = dentro_al_blocco(messaggi.carta_imbarco(**{**CARTA, "indirizzo": valore}))
    assert len({len(riga) for riga in righe}) == 1
    assert all(riga[0] in "|/\\+" and riga[-1] in "|/\\+" for riga in righe)


def test_la_carta_normale_non_cambia():
    righe = dentro_al_blocco(messaggi.carta_imbarco(**CARTA))
    testo = "\n".join(righe)
    assert "MARIO ROSSI" in testo and "VIA ROMA 12" in testo and "15,67 €" in testo
    assert len({len(riga) for riga in righe}) == 1


def test_l_apostrofo_del_nome_resta():
    testo = "\n".join(dentro_al_blocco(messaggi.carta_imbarco(**{**CARTA, "nome": "D'Angelo"})))
    assert "D'ANGELO" in testo
