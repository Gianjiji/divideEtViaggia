"""Persistenza delle preferenze di calcolo, per chat_id.

I dati vivono in un semplice file JSON locale, con questa forma::

    {
      "123456789": {
        "categorie": {"media": {"usura": 0.12, "consumo": 7.5}},
        "prezzo_litro": 1.789
      }
    }

Vengono salvati solo i valori effettivamente modificati: tutto il resto ricade
sui default di :mod:`calcolo`. La scrittura e' atomica (file temporaneo +
``os.replace``) e protetta da un lock, cosi' un riavvio o due handler
concorrenti non lasciano mai un JSON a meta'.

Il formato piu' vecchio, in cui ogni categoria era direttamente il coefficiente
di usura (``{"media": 0.12}``), viene ancora letto: i file scritti dalle
versioni precedenti continuano a funzionare.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
from pathlib import Path

from calcolo import (
    COEFFICIENTE_MASSIMO,
    COEFFICIENTI_DEFAULT,
    CONSUMI_DEFAULT,
    CONSUMO_MASSIMO,
    PREZZO_LITRO_MASSIMO,
    coefficienti_con_default,
    consumi_con_default,
)

logger = logging.getLogger(__name__)

#: Percorso di default del file dati (sovrascrivibile con COEFFICIENTI_PATH).
PERCORSO_DEFAULT = Path(__file__).resolve().parent / "dati" / "coefficienti.json"

#: Le due grandezze personalizzabili per categoria di auto.
TIPI = {
    "usura": (COEFFICIENTI_DEFAULT, COEFFICIENTE_MASSIMO, coefficienti_con_default),
    "consumo": (CONSUMI_DEFAULT, CONSUMO_MASSIMO, consumi_con_default),
}


def _normalizza(voce: object) -> dict:
    """Porta una voce di chat al formato corrente, accettando quello vecchio."""
    if not isinstance(voce, dict):
        return {"categorie": {}}

    categorie = voce.get("categorie")
    if isinstance(categorie, dict):
        pulite = {
            nome: valori
            for nome, valori in categorie.items()
            if isinstance(valori, dict)
        }
        return {"categorie": pulite, "prezzo_litro": voce.get("prezzo_litro")}

    # Formato vecchio: {"media": 0.12} erano i coefficienti di usura.
    vecchie = {
        nome: {"usura": valore}
        for nome, valore in voce.items()
        if nome in COEFFICIENTI_DEFAULT and isinstance(valore, (int, float))
    }
    return {"categorie": vecchie, "prezzo_litro": voce.get("prezzo_litro")}


class ArchivioCoefficienti:
    """Archivio JSON delle preferenze di calcolo, indicizzato per chat."""

    def __init__(self, percorso: str | os.PathLike[str] | None = None) -> None:
        if percorso is None:
            percorso = os.environ.get("COEFFICIENTI_PATH") or PERCORSO_DEFAULT
        self.percorso = Path(percorso)
        self._lock = threading.Lock()

    # -- lettura/scrittura del file ---------------------------------------- #

    def _leggi_tutto(self) -> dict[str, dict]:
        try:
            with self.percorso.open("r", encoding="utf-8") as f:
                dati = json.load(f)
        except FileNotFoundError:
            return {}
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("File preferenze illeggibile (%s): riparto dai default.", exc)
            return {}
        if not isinstance(dati, dict):
            logger.warning("File preferenze con formato inatteso: riparto dai default.")
            return {}
        return dati

    def _scrivi_tutto(self, dati: dict[str, dict]) -> None:
        self.percorso.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(
            dir=str(self.percorso.parent), prefix=".coefficienti-", suffix=".tmp"
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(dati, f, ensure_ascii=False, indent=2, sort_keys=True)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, self.percorso)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise

    def _voce(self, chat_id: int | str) -> dict:
        with self._lock:
            dati = self._leggi_tutto()
        return _normalizza(dati.get(str(chat_id)))

    # -- valori per categoria ---------------------------------------------- #

    def _valori(self, chat_id: int | str, tipo: str) -> dict[str, float]:
        _, _, completa = TIPI[tipo]
        categorie = self._voce(chat_id)["categorie"]
        salvati = {
            nome: valori[tipo]
            for nome, valori in categorie.items()
            if isinstance(valori, dict) and tipo in valori
        }
        return completa(salvati)

    def coefficienti(self, chat_id: int | str) -> dict[str, float]:
        """Coefficienti di usura della chat: default + eventuali personalizzati."""
        return self._valori(chat_id, "usura")

    def consumi(self, chat_id: int | str) -> dict[str, float]:
        """Consumi in l/100 km della chat: default + eventuali personalizzati."""
        return self._valori(chat_id, "consumo")

    def personalizzati(self, chat_id: int | str, tipo: str = "usura") -> dict[str, float]:
        """Solo i valori salvati e diversi dal default (puo' essere vuoto)."""
        default, _, _ = TIPI[tipo]
        return {
            categoria: valore
            for categoria, valore in self._valori(chat_id, tipo).items()
            if valore != default[categoria]
        }

    def imposta(
        self,
        chat_id: int | str,
        categoria: str,
        valore: float,
        tipo: str = "usura",
    ) -> dict[str, float]:
        """Salva un valore per una categoria e restituisce i valori aggiornati."""
        if tipo not in TIPI:
            raise KeyError(f"Grandezza sconosciuta: {tipo}")
        default, massimo, _ = TIPI[tipo]
        if categoria not in default:
            raise KeyError(f"Categoria sconosciuta: {categoria}")
        valore = float(valore)
        if not 0 < valore <= massimo:
            raise ValueError("Valore fuori dai limiti consentiti.")

        chiave = str(chat_id)
        with self._lock:
            dati = self._leggi_tutto()
            voce = _normalizza(dati.get(chiave))
            voce["categorie"].setdefault(categoria, {})[tipo] = valore
            if voce.get("prezzo_litro") is None:
                voce.pop("prezzo_litro", None)
            dati[chiave] = voce
            self._scrivi_tutto(dati)
        return self._valori(chat_id, tipo)

    # -- prezzo del carburante --------------------------------------------- #

    def prezzo_litro(self, chat_id: int | str) -> float | None:
        """Ultimo prezzo al litro usato da questa chat, se ce n'e' uno."""
        valore = self._voce(chat_id).get("prezzo_litro")
        try:
            numero = float(valore)
        except (TypeError, ValueError):
            return None
        return numero if 0 < numero <= PREZZO_LITRO_MASSIMO else None

    def salva_prezzo_litro(self, chat_id: int | str, valore: float) -> float:
        """Ricorda il prezzo al litro, per proporlo al calcolo successivo."""
        valore = float(valore)
        if not 0 < valore <= PREZZO_LITRO_MASSIMO:
            raise ValueError("Prezzo fuori dai limiti consentiti.")
        chiave = str(chat_id)
        with self._lock:
            dati = self._leggi_tutto()
            voce = _normalizza(dati.get(chiave))
            voce["prezzo_litro"] = valore
            dati[chiave] = voce
            self._scrivi_tutto(dati)
        return valore

    # -- azzeramento -------------------------------------------------------- #

    def reset(self, chat_id: int | str) -> dict[str, float]:
        """Rimuove tutte le personalizzazioni della chat."""
        chiave = str(chat_id)
        with self._lock:
            dati = self._leggi_tutto()
            if chiave in dati:
                del dati[chiave]
                self._scrivi_tutto(dati)
        return dict(COEFFICIENTI_DEFAULT)


#: Istanza condivisa usata dal bot.
archivio = ArchivioCoefficienti()
