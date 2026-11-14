"""Test della persistenza dei coefficienti."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from calcolo import COEFFICIENTI_DEFAULT, CONSUMI_DEFAULT  # noqa: E402
from storage import ArchivioCoefficienti  # noqa: E402


@pytest.fixture()
def archivio(tmp_path):
    return ArchivioCoefficienti(tmp_path / "coefficienti.json")


def test_default_se_non_esiste_nulla(archivio):
    assert archivio.coefficienti(123) == COEFFICIENTI_DEFAULT
    assert archivio.personalizzati(123) == {}


def test_salva_e_rilegge(archivio):
    archivio.imposta(123, "media", 0.12)
    assert archivio.coefficienti(123)["media"] == pytest.approx(0.12)
    assert archivio.personalizzati(123) == {"media": 0.12}
    # Le altre categorie restano ai default.
    assert archivio.coefficienti(123)["grande"] == pytest.approx(0.15)


def test_persistenza_fra_istanze(tmp_path):
    percorso = tmp_path / "coefficienti.json"
    ArchivioCoefficienti(percorso).imposta(42, "grande", 0.2)
    # Simula il riavvio del bot: nuova istanza, stesso file.
    assert ArchivioCoefficienti(percorso).coefficienti(42)["grande"] == pytest.approx(0.2)


def test_chat_isolate(archivio):
    archivio.imposta(1, "piccola", 0.07)
    assert archivio.coefficienti(2) == COEFFICIENTI_DEFAULT


def test_reset(archivio):
    archivio.imposta(1, "piccola", 0.07)
    archivio.imposta(1, "media", 0.11)
    assert archivio.reset(1) == COEFFICIENTI_DEFAULT
    assert archivio.coefficienti(1) == COEFFICIENTI_DEFAULT
    assert archivio.personalizzati(1) == {}


def test_reset_su_chat_mai_vista(archivio):
    assert archivio.reset(999) == COEFFICIENTI_DEFAULT


def test_categoria_sconosciuta(archivio):
    with pytest.raises(KeyError):
        archivio.imposta(1, "camion", 0.3)


@pytest.mark.parametrize("valore", [0, -1, 1000])
def test_valori_fuori_limite(archivio, valore):
    with pytest.raises(ValueError):
        archivio.imposta(1, "media", valore)


def test_file_corrotto_ricade_sui_default(tmp_path):
    percorso = tmp_path / "coefficienti.json"
    percorso.write_text("{non e' json", encoding="utf-8")
    archivio = ArchivioCoefficienti(percorso)
    assert archivio.coefficienti(1) == COEFFICIENTI_DEFAULT
    # E deve poter riscrivere sopra senza esplodere.
    archivio.imposta(1, "media", 0.13)
    assert json.loads(percorso.read_text(encoding="utf-8")) == {
        "1": {"categorie": {"media": {"usura": 0.13}}}
    }


# --------------------------------------------------------------------------- #
# Consumi e prezzo del carburante
# --------------------------------------------------------------------------- #

def test_consumi_default(archivio):
    assert archivio.consumi(1) == CONSUMI_DEFAULT


def test_consumi_personalizzati(archivio):
    archivio.imposta(1, "media", 8.2, tipo="consumo")
    assert archivio.consumi(1)["media"] == pytest.approx(8.2)
    assert archivio.personalizzati(1, "consumo") == {"media": 8.2}
    # L'usura della stessa categoria resta al default.
    assert archivio.coefficienti(1)["media"] == pytest.approx(0.10)


def test_usura_e_consumo_convivono(archivio):
    archivio.imposta(1, "grande", 0.18, tipo="usura")
    archivio.imposta(1, "grande", 11.0, tipo="consumo")
    assert archivio.coefficienti(1)["grande"] == pytest.approx(0.18)
    assert archivio.consumi(1)["grande"] == pytest.approx(11.0)


def test_tipo_sconosciuto(archivio):
    with pytest.raises(KeyError):
        archivio.imposta(1, "media", 5, tipo="gomme")


def test_prezzo_litro(archivio):
    assert archivio.prezzo_litro(1) is None
    archivio.salva_prezzo_litro(1, 1.789)
    assert archivio.prezzo_litro(1) == pytest.approx(1.789)


@pytest.mark.parametrize("valore", [0, -1, 99])
def test_prezzo_litro_fuori_limite(archivio, valore):
    with pytest.raises(ValueError):
        archivio.salva_prezzo_litro(1, valore)


def test_prezzo_litro_sopravvive_alle_modifiche_di_categoria(archivio):
    archivio.salva_prezzo_litro(1, 1.75)
    archivio.imposta(1, "media", 0.11)
    assert archivio.prezzo_litro(1) == pytest.approx(1.75)


def test_reset_azzera_anche_il_prezzo(archivio):
    archivio.salva_prezzo_litro(1, 1.75)
    archivio.imposta(1, "media", 8.0, tipo="consumo")
    archivio.reset(1)
    assert archivio.prezzo_litro(1) is None
    assert archivio.consumi(1) == CONSUMI_DEFAULT


def test_legge_il_formato_vecchio(tmp_path):
    """I file scritti dalle versioni precedenti devono continuare a funzionare."""
    percorso = tmp_path / "coefficienti.json"
    percorso.write_text('{"7": {"media": 0.12, "grande": 0.2}}', encoding="utf-8")
    archivio = ArchivioCoefficienti(percorso)
    assert archivio.coefficienti(7)["media"] == pytest.approx(0.12)
    assert archivio.coefficienti(7)["grande"] == pytest.approx(0.2)
    assert archivio.coefficienti(7)["piccola"] == pytest.approx(0.05)
    assert archivio.consumi(7) == CONSUMI_DEFAULT
    # E la prima scrittura deve migrarlo al formato nuovo senza perdere nulla.
    archivio.imposta(7, "media", 7.7, tipo="consumo")
    assert archivio.coefficienti(7)["media"] == pytest.approx(0.12)
    assert archivio.consumi(7)["media"] == pytest.approx(7.7)
