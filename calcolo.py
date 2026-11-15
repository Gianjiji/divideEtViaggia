"""Logica pura di calcolo della ripartizione dei costi di un viaggio in auto.

Schema B — usura divisa per N, conducente incluso.

Variabili
    D = distanza percorsa in km (per tratta)
    N = numero totale partecipanti, conducente compreso
    B = costo carburante (EUR)
    T = costo pedaggi (EUR)
    c = coefficiente di usura al km, in base alla categoria dell'auto

Formule
    Usura totale        = c * D
    Q_usura (a testa)   = (c * D) / N      -> divisa per N, conducente incluso
    Q_viaggio (a testa) = (B + T) / N
    Quota PASSEGGERO    = Q_usura + Q_viaggio
    Quota CONDUCENTE    = Q_viaggio        -> non versa l'usura: la propria
                                              frazione la "assorbe" incassando
                                              meno dai passeggeri
    Usura incassata dal conducente = Q_usura * (N - 1)

Esclusi dal calcolo: assicurazione, bollo, parcheggi, multe, manutenzione
straordinaria.

Questo modulo non dipende da Telegram: e' logica pura e testabile.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Iterable, Sequence

# --------------------------------------------------------------------------- #
# Categorie e coefficienti di default
# --------------------------------------------------------------------------- #

#: Coefficienti di usura di default, in EUR/km.
COEFFICIENTI_DEFAULT: dict[str, float] = {
    "piccola": 0.05,
    "media": 0.10,
    "grande": 0.15,
}

#: Consumi medi di default, in litri ogni 100 km. Sono valori da viaggio
#: (molta autostrada, auto carica), non i dati di omologazione.
CONSUMI_DEFAULT: dict[str, float] = {
    "piccola": 5.5,
    "media": 7.0,
    "grande": 9.0,
}

#: Metadati di presentazione delle categorie (ordine incluso).
CATEGORIE: dict[str, dict[str, str]] = {
    "piccola": {"emoji": "\U0001F697", "nome": "Piccola", "descrizione": "city car, utilitaria"},
    "media": {"emoji": "\U0001F699", "nome": "Media", "descrizione": "berlina, SUV compatto"},
    "grande": {"emoji": "\U0001F690", "nome": "Grande", "descrizione": "SUV, monovolume, premium"},
}

#: Limite di sicurezza per i coefficienti personalizzati (EUR/km).
COEFFICIENTE_MASSIMO = 10.0

#: Limiti di sicurezza per consumi (l/100 km) e prezzo del carburante (EUR/l).
CONSUMO_MASSIMO = 50.0
PREZZO_LITRO_MASSIMO = 10.0

#: Limite di sicurezza per distanze e importi, per intercettare errori di battitura.
DISTANZA_MASSIMA_KM = 100_000.0
IMPORTO_MASSIMO = 1_000_000.0

#: Numero minimo di partecipanti a una tratta (conducente + almeno un passeggero).
PARTECIPANTI_MINIMI = 2
PARTECIPANTI_MASSIMI = 99


class InputNonValido(ValueError):
    """Errore di validazione di un input dell'utente, con messaggio mostrabile."""


# --------------------------------------------------------------------------- #
# Parsing e validazione degli input (formato italiano)
# --------------------------------------------------------------------------- #

_NUMERO_SEMPLICE = re.compile(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)")
_MIGLIAIA_RIPETUTE = re.compile(r"[+-]?[0-9]{1,3}(?:\.[0-9]{3}){2,}")
# Un solo punto seguito da esattamente tre cifre, senza virgola: "1.234".
_MIGLIAIA_O_DECIMALI = re.compile(r"[+-]?[0-9]{1,3}\.[0-9]{3}")


def _rifiuta_se_ambiguo(testo: str, cosa: str) -> None:
    """Ferma un numero come ``1.234`` dove tre decimali non hanno senso.

    All'italiana e' milleduecentotrentaquattro, ma chi scrive il punto come
    separatore decimale (succede spesso dalla tastiera del telefono) intende
    uno virgola due. Scegliere in silenzio vuol dire sbagliare di mille volte
    un importo o una distanza: meglio chiedere di riscriverlo.
    """
    pulito = re.sub(r"(?i)€|eur|km|[\s\u00a0]", "", str(testo))
    if _MIGLIAIA_O_DECIMALI.fullmatch(pulito):
        intero = pulito.replace(".", "")
        raise InputNonValido(
            f"«{str(testo).strip()}» si puo' leggere in due modi. "
            f"Se intendi {intero} {cosa} scrivi `{intero}`; "
            f"se intendi un numero con i decimali usa la virgola, es. `{pulito.replace('.', ',')}`."
        )


def parse_decimale(testo: str) -> float:
    """Converte in ``float`` un numero scritto all'italiana.

    Accetta virgola o punto come separatore decimale, il simbolo di euro,
    spazi e il separatore delle migliaia (``1.234,56`` oppure ``1 234,56``).

    Solleva :class:`InputNonValido` se il testo non e' un numero.
    """
    if testo is None:
        raise InputNonValido("Non ho ricevuto nessun numero.")

    grezzo = str(testo).strip()
    if not grezzo:
        raise InputNonValido("Non ho ricevuto nessun numero.")

    pulito = (
        grezzo.replace("€", "")
        .replace("EUR", "")
        .replace("eur", "")
        .replace("km", "")
        .replace("Km", "")
        .replace("KM", "")
        .replace(" ", "")
        .replace(" ", "")
        .strip()
    )

    if "," in pulito and "." in pulito:
        # Es. "1.234,56": il punto e' separatore delle migliaia.
        if pulito.rfind(",") > pulito.rfind("."):
            pulito = pulito.replace(".", "").replace(",", ".")
        else:  # Es. "1,234.56": la virgola e' separatore delle migliaia.
            pulito = pulito.replace(",", "")
    elif _MIGLIAIA_RIPETUTE.fullmatch(pulito):
        # Es. "1.234.567": piu' punti, tutti a gruppi di tre: sono migliaia.
        pulito = pulito.replace(".", "")
    else:
        pulito = pulito.replace(",", ".")

    # float() da solo accetta molto piu' di un numero scritto da una persona:
    # "1_000", "1e3", "infinity", cifre di altri alfabeti. Qui passano soltanto
    # cifre ASCII con al massimo un separatore decimale.
    if not _NUMERO_SEMPLICE.fullmatch(pulito):
        raise InputNonValido(f"«{grezzo}» non mi sembra un numero.")

    try:
        valore = float(pulito)
    except ValueError:
        raise InputNonValido(f"«{grezzo}» non mi sembra un numero.") from None

    if valore != valore or valore in (float("inf"), float("-inf")):  # NaN / infinito
        raise InputNonValido(f"«{grezzo}» non mi sembra un numero valido.")

    return valore


def parse_importo(testo: str) -> float:
    """Legge un importo in euro: numero valido, non negativo."""
    valore = parse_decimale(testo)
    _rifiuta_se_ambiguo(testo, "euro")
    if valore < 0:
        raise InputNonValido("L'importo non puo' essere negativo.")
    if valore > IMPORTO_MASSIMO:
        raise InputNonValido("L'importo mi sembra troppo alto: controlla il valore.")
    return valore


def parse_distanza(testo: str) -> float:
    """Legge una distanza in km: numero valido e strettamente positivo."""
    valore = parse_decimale(testo)
    _rifiuta_se_ambiguo(testo, "km")
    if valore <= 0:
        raise InputNonValido("La distanza deve essere maggiore di zero.")
    if valore > DISTANZA_MASSIMA_KM:
        raise InputNonValido("La distanza mi sembra troppo alta: controlla il valore.")
    return valore


def parse_partecipanti(testo: str) -> int:
    """Legge il numero di partecipanti N: intero >= 2 (conducente compreso)."""
    valore = parse_decimale(testo)
    if abs(valore - round(valore)) > 1e-9:
        raise InputNonValido("Il numero di partecipanti deve essere un numero intero.")
    intero = int(round(valore))
    if intero < PARTECIPANTI_MINIMI:
        raise InputNonValido(
            "Servono almeno 2 partecipanti (il conducente e almeno un passeggero)."
        )
    if intero > PARTECIPANTI_MASSIMI:
        raise InputNonValido("Il numero di partecipanti mi sembra troppo alto.")
    return intero


def parse_coefficiente(testo: str) -> float:
    """Legge un coefficiente di usura in EUR/km: numero strettamente positivo."""
    valore = parse_decimale(testo)
    if valore <= 0:
        raise InputNonValido("Il coefficiente deve essere un numero positivo.")
    if valore > COEFFICIENTE_MASSIMO:
        raise InputNonValido(
            f"Il coefficiente mi sembra troppo alto "
            f"(massimo {COEFFICIENTE_MASSIMO:g} €/km)."
        )
    return valore


def parse_orario(testo: str) -> str:
    """Normalizza un orario scritto liberamente in ``HH:MM``.

    Accetta ``7:30``, ``07.30``, ``7 30``, ``0730``, ``19h45`` e anche la sola
    ora (``8`` -> ``08:00``).
    """
    if testo is None:
        raise InputNonValido("Non ho ricevuto nessun orario.")

    grezzo = str(testo).strip()
    if not grezzo:
        raise InputNonValido("Non ho ricevuto nessun orario.")

    pulito = grezzo.lower()
    # Nota: il trattino non e' un separatore, altrimenti "-1:00" diventerebbe
    # "1:00" invece di essere rifiutato.
    for separatore in (".", "h", " ", ",", ";"):
        pulito = pulito.replace(separatore, ":")
    while "::" in pulito:
        pulito = pulito.replace("::", ":")
    pulito = pulito.strip(":")

    if ":" in pulito:
        pezzi = pulito.split(":")
        if len(pezzi) > 3:
            raise InputNonValido(f"«{grezzo}» non mi sembra un orario.")
        ore, minuti = pezzi[0], pezzi[1] if len(pezzi) > 1 else "0"
    elif pulito.isdigit() and len(pulito) in (3, 4):
        ore, minuti = pulito[:-2], pulito[-2:]
    else:
        ore, minuti = pulito, "0"

    if not (ore.isdigit() and minuti.isdigit()):
        raise InputNonValido(f"«{grezzo}» non mi sembra un orario.")

    ore_int, minuti_int = int(ore), int(minuti)
    if not 0 <= ore_int <= 23:
        raise InputNonValido("L'ora deve essere fra 0 e 23.")
    if not 0 <= minuti_int <= 59:
        raise InputNonValido("I minuti devono essere fra 0 e 59.")
    return f"{ore_int:02d}:{minuti_int:02d}"


def parse_testo_breve(testo: str, massimo: int = 30, cosa: str = "testo") -> str:
    """Ripulisce un testo libero (nome, indirizzo) e ne controlla la lunghezza."""
    if testo is None:
        raise InputNonValido(f"Non ho ricevuto nessun {cosa}.")
    pulito = " ".join(str(testo).split())
    if not pulito:
        raise InputNonValido(f"Non ho ricevuto nessun {cosa}.")
    if len(pulito) > massimo:
        raise InputNonValido(
            f"Il {cosa} e' troppo lungo: massimo {massimo} caratteri "
            f"(ne hai scritti {len(pulito)})."
        )
    return pulito


def parse_consumo(testo: str) -> float:
    """Legge un consumo in litri ogni 100 km: numero strettamente positivo."""
    valore = parse_decimale(testo)
    if valore <= 0:
        raise InputNonValido("Il consumo deve essere un numero positivo.")
    if valore > CONSUMO_MASSIMO:
        raise InputNonValido(
            f"Il consumo mi sembra troppo alto (massimo "
            f"{CONSUMO_MASSIMO:g} l/100 km)."
        )
    return valore


def parse_prezzo_litro(testo: str) -> float:
    """Legge il prezzo del carburante in EUR/litro: numero strettamente positivo."""
    valore = parse_decimale(testo)
    if valore <= 0:
        raise InputNonValido("Il prezzo deve essere un numero positivo.")
    if valore > PREZZO_LITRO_MASSIMO:
        raise InputNonValido(
            f"Il prezzo mi sembra troppo alto (massimo "
            f"{PREZZO_LITRO_MASSIMO:g} €/l). Scrivi il prezzo di *un litro*."
        )
    return valore


def stima_carburante(
    distanza_km: float, consumo_l_100km: float, prezzo_litro: float
) -> float:
    """Stima la spesa di carburante di una tratta.

        litri = D / 100 x consumo
        spesa = litri x prezzo al litro
    """
    if distanza_km < 0 or consumo_l_100km <= 0 or prezzo_litro <= 0:
        raise InputNonValido("Dati non validi per la stima del carburante.")
    return distanza_km / 100.0 * consumo_l_100km * prezzo_litro


def litri_stimati(distanza_km: float, consumo_l_100km: float) -> float:
    """Litri consumati su una tratta, dato il consumo medio."""
    if distanza_km < 0 or consumo_l_100km <= 0:
        raise InputNonValido("Dati non validi per la stima dei consumi.")
    return distanza_km / 100.0 * consumo_l_100km


def arrotonda(valore: float) -> float:
    """Arrotonda un importo a 2 decimali, con il mezzo centesimo per eccesso.

    ``round(2.675, 2)`` da' 2.67: il numero e' memorizzato in binario come
    2.67499999..., e Python arrotonda quello. Per dei soldi e' la risposta
    sbagliata. Qui il valore viene prima ripulito dal rumore binario (nono
    decimale), poi arrotondato in base dieci con la regola che tutti si
    aspettano: 2,675 diventa 2,68.
    """
    if not math.isfinite(valore):
        return valore
    centesimi = Decimal(repr(round(valore, 9))).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )
    return float(centesimi) + 0.0


# --------------------------------------------------------------------------- #
# Modello dati
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class Tratta:
    """Dati di una singola tratta del viaggio."""

    nome: str
    distanza_km: float
    partecipanti: int
    carburante: float
    pedaggi: float
    #: Localita' di partenza e arrivo, se la distanza e' stata calcolata
    #: dalle mappe invece che inserita a mano.
    origine: str | None = None
    destinazione: str | None = None
    #: True se il carburante e' stato stimato dai km invece che dichiarato.
    carburante_stimato: bool = False

    def __post_init__(self) -> None:
        if self.distanza_km <= 0:
            raise InputNonValido("La distanza deve essere maggiore di zero.")
        if self.partecipanti < PARTECIPANTI_MINIMI:
            raise InputNonValido("Servono almeno 2 partecipanti.")
        if self.carburante < 0 or self.pedaggi < 0:
            raise InputNonValido("Gli importi non possono essere negativi.")

    @property
    def costo_viaggio(self) -> float:
        """B + T: carburante piu' pedaggi della tratta."""
        return self.carburante + self.pedaggi

    @property
    def percorso(self) -> str | None:
        """«Bologna → Napoli», se conosciamo gli estremi della tratta."""
        if self.origine and self.destinazione:
            return f"{self.origine} \u2192 {self.destinazione}"
        return None


@dataclass(frozen=True)
class Verifica:
    """Controllo di quadratura fra quanto raccolto e il costo B + T."""

    raccolto_esatto: float
    raccolto_arrotondato: float
    atteso: float
    differenza_arrotondamento: float
    quadra: bool


@dataclass(frozen=True)
class RisultatoTratta:
    """Esito del calcolo su una tratta. Gli importi sono a piena precisione."""

    tratta: Tratta
    coefficiente: float
    usura_totale: float
    q_usura: float
    q_viaggio: float
    quota_passeggero: float
    quota_conducente: float
    usura_incassata_conducente: float
    incassato_dai_passeggeri: float
    verifica: Verifica

    @property
    def nome(self) -> str:
        return self.tratta.nome

    @property
    def partecipanti(self) -> int:
        return self.tratta.partecipanti


@dataclass(frozen=True)
class RisultatoViaggio:
    """Esito complessivo del viaggio (una o due tratte)."""

    categoria: str
    coefficiente: float
    tratte: tuple[RisultatoTratta, ...]
    totale_costi_viaggio: float
    totale_usura: float
    quota_passeggero_completo: float
    esborso_conducente: float
    usura_incassata_conducente: float
    incassato_dai_passeggeri: float
    saldo_cassa_conducente: float
    #: Valorizzati solo se il carburante e' stato stimato.
    consumo: float | None = None
    prezzo_litro: float | None = None

    @property
    def carburante_stimato(self) -> bool:
        return any(r.tratta.carburante_stimato for r in self.tratte)

    @property
    def litri_totali(self) -> float | None:
        if self.consumo is None:
            return None
        return sum(
            litri_stimati(r.tratta.distanza_km, self.consumo)
            for r in self.tratte
            if r.tratta.carburante_stimato
        )

    @property
    def quote_passeggero_per_tratta(self) -> dict[str, float]:
        """Quota di chi partecipa a una sola tratta, per nome di tratta."""
        return {r.nome: r.quota_passeggero for r in self.tratte}

    @property
    def andata_e_ritorno(self) -> bool:
        return len(self.tratte) > 1


# --------------------------------------------------------------------------- #
# Calcolo
# --------------------------------------------------------------------------- #

def calcola_tratta(tratta: Tratta, coefficiente: float) -> RisultatoTratta:
    """Applica lo Schema B a una singola tratta."""
    if coefficiente <= 0:
        raise InputNonValido("Il coefficiente deve essere un numero positivo.")

    n = tratta.partecipanti
    usura_totale = coefficiente * tratta.distanza_km
    q_usura = usura_totale / n
    q_viaggio = tratta.costo_viaggio / n

    quota_passeggero = q_usura + q_viaggio
    quota_conducente = q_viaggio
    usura_incassata = q_usura * (n - 1)
    incassato = quota_passeggero * (n - 1)

    raccolto_esatto = q_viaggio * n
    raccolto_arrotondato = arrotonda(q_viaggio) * n
    verifica = Verifica(
        raccolto_esatto=raccolto_esatto,
        raccolto_arrotondato=raccolto_arrotondato,
        atteso=tratta.costo_viaggio,
        differenza_arrotondamento=arrotonda(raccolto_arrotondato - tratta.costo_viaggio),
        quadra=abs(raccolto_esatto - tratta.costo_viaggio) < 1e-9,
    )

    return RisultatoTratta(
        tratta=tratta,
        coefficiente=coefficiente,
        usura_totale=usura_totale,
        q_usura=q_usura,
        q_viaggio=q_viaggio,
        quota_passeggero=quota_passeggero,
        quota_conducente=quota_conducente,
        usura_incassata_conducente=usura_incassata,
        incassato_dai_passeggeri=incassato,
        verifica=verifica,
    )


def calcola_viaggio(
    tratte: Sequence[Tratta],
    coefficiente: float,
    categoria: str = "media",
    consumo: float | None = None,
    prezzo_litro: float | None = None,
) -> RisultatoViaggio:
    """Applica lo Schema B a tutte le tratte e costruisce il riepilogo."""
    if not tratte:
        raise InputNonValido("Serve almeno una tratta per fare il conto.")

    risultati = tuple(calcola_tratta(t, coefficiente) for t in tratte)

    totale_costi = sum(r.tratta.costo_viaggio for r in risultati)
    incassato = sum(r.incassato_dai_passeggeri for r in risultati)
    esborso_conducente = sum(r.quota_conducente for r in risultati)

    return RisultatoViaggio(
        categoria=categoria,
        coefficiente=coefficiente,
        tratte=risultati,
        totale_costi_viaggio=totale_costi,
        totale_usura=sum(r.usura_totale for r in risultati),
        quota_passeggero_completo=sum(r.quota_passeggero for r in risultati),
        esborso_conducente=esborso_conducente,
        usura_incassata_conducente=sum(r.usura_incassata_conducente for r in risultati),
        incassato_dai_passeggeri=incassato,
        # Cassa del conducente: anticipa B+T e incassa le quote dei passeggeri.
        saldo_cassa_conducente=totale_costi - incassato,
        consumo=consumo,
        prezzo_litro=prezzo_litro,
    )


def dividi_a_meta(totale: float, quante: int = 2) -> list[float]:
    """Divide un totale A/R fra le tratte, compensando l'arrotondamento.

    L'ultima tratta assorbe il centesimo residuo, cosi' la somma delle parti
    resta esattamente uguale al totale inserito dall'utente.
    """
    if quante < 1:
        raise InputNonValido("Numero di tratte non valido.")
    quota = arrotonda(totale / quante)
    parti = [quota] * (quante - 1)
    parti.append(arrotonda(totale - quota * (quante - 1)))
    return parti


def _con_default(
    base: dict[str, float],
    personalizzati: Iterable[tuple[str, float]] | dict[str, float] | None,
    massimo: float,
) -> dict[str, float]:
    valori = dict(base)
    if not personalizzati:
        return valori
    elementi = (
        personalizzati.items() if isinstance(personalizzati, dict) else personalizzati
    )
    for categoria, valore in elementi:
        if categoria in valori:
            try:
                numero = float(valore)
            except (TypeError, ValueError):
                continue
            if 0 < numero <= massimo:
                valori[categoria] = numero
    return valori


def consumi_con_default(
    personalizzati: Iterable[tuple[str, float]] | dict[str, float] | None,
) -> dict[str, float]:
    """Unisce i consumi personalizzati ai default, ignorando chiavi ignote."""
    return _con_default(CONSUMI_DEFAULT, personalizzati, CONSUMO_MASSIMO)


def coefficienti_con_default(personalizzati: Iterable[tuple[str, float]] | dict[str, float] | None) -> dict[str, float]:
    """Unisce i coefficienti personalizzati ai default, ignorando chiavi ignote."""
    return _con_default(COEFFICIENTI_DEFAULT, personalizzati, COEFFICIENTE_MASSIMO)
