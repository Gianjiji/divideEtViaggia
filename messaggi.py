"""Testi del bot e formattazione dei numeri in stile italiano.

Tutti i messaggi usano il Markdown "classico" di Telegram (``parse_mode
Markdown``): grassetto con ``*...*`` e blocchi monospazio con i tripli
backtick, che tengono allineate le colonne del conto.
"""

from __future__ import annotations

import textwrap

from calcolo import (
    CATEGORIE,
    COEFFICIENTI_DEFAULT,
    CONSUMI_DEFAULT,
    RisultatoTratta,
    RisultatoViaggio,
    litri_stimati,
)

#: Nome del bot, usato nelle intestazioni dei messaggi.
NOME_BOT = "Divide et viaggia"

# Larghezza delle tabelle monospazio: etichetta + importo.
_ETICHETTA = 20
_VALORE = 11
_RIGHELLO = "-" * (_ETICHETTA + _VALORE)


# --------------------------------------------------------------------------- #
# Formattazione numerica (formato italiano: virgola decimale, punto migliaia)
# --------------------------------------------------------------------------- #

def formatta_numero(valore: float, decimali: int = 2) -> str:
    """1234.5 -> ``1.234,50``."""
    testo = f"{valore:,.{decimali}f}"
    return testo.replace(",", "\x00").replace(".", ",").replace("\x00", ".")


def formatta_euro(valore: float) -> str:
    """35.5833 -> ``35,58 €``."""
    return f"{formatta_numero(valore)} €"


def formatta_km(valore: float) -> str:
    """480.0 -> ``480 km``; 480.5 -> ``480,5 km``."""
    if abs(valore - round(valore)) < 1e-9:
        return f"{formatta_numero(valore, 0)} km"
    return f"{formatta_numero(valore, 1)} km"


def formatta_coefficiente(valore: float) -> str:
    """0.1 -> ``0,10 €/km``; 0.125 -> ``0,125 €/km``."""
    decimali = 2 if abs(valore - round(valore, 2)) < 1e-9 else 3
    return f"{formatta_numero(valore, decimali)} €/km"


def formatta_consumo(valore: float) -> str:
    """7.0 -> ``7,0 l/100 km``."""
    return f"{formatta_numero(valore, 1)} l/100 km"


def formatta_prezzo_litro(valore: float) -> str:
    """1.789 -> ``1,789 €/l``."""
    decimali = 3 if abs(valore - round(valore, 2)) > 1e-9 else 2
    return f"{formatta_numero(valore, decimali)} €/l"


def formatta_litri(valore: float) -> str:
    return f"{formatta_numero(valore, 1)} l"


def escape_markdown(testo: str) -> str:
    """Neutralizza i caratteri speciali del Markdown classico di Telegram."""
    for carattere in ("_", "*", "`", "["):
        testo = testo.replace(carattere, "\\" + carattere)
    return testo


def etichetta_categoria(categoria: str) -> str:
    """``media`` -> ``🚙 Media``."""
    meta = CATEGORIE.get(categoria)
    if not meta:
        return categoria
    return f"{meta['emoji']} {meta['nome']}"


def _riga(etichetta: str, valore: str) -> str:
    return f"{etichetta:<{_ETICHETTA}}{valore:>{_VALORE}}"


def _blocco(righe: list[str]) -> str:
    corpo = "\n".join(righe)
    return f"```\n{corpo}\n```"


# --------------------------------------------------------------------------- #
# Messaggi statici e prompt della conversazione
# --------------------------------------------------------------------------- #

BENVENUTO = (
    "\U0001F697 *Divide et viaggia*\n"
    "Ciao! Ti aiuto a dividere le spese di un viaggio in auto fra amici.\n\n"
    "Calcolo carburante, pedaggi e usura dell'auto: l'usura si divide fra "
    "*tutti* i partecipanti (conducente compreso), ma il conducente non la "
    "versa — la assorbe incassando meno dai passeggeri.\n\n"
    "Non sono inclusi assicurazione, bollo, parcheggi, multe e manutenzione "
    "straordinaria.\n\n"
    "Partiamo: il viaggio e' a tratta singola o andata e ritorno?"
)

HELP = (
    "\U0001F697 *Divide et viaggia — guida*\n\n"
    "*Comandi*\n"
    "/start — messaggio di benvenuto e avvio guidato\n"
    "/nuovo — inizia un nuovo calcolo\n"
    "/cartaimbarco — la carta d'imbarco del tuo viaggio \U0001F3AB\n"
    "/coefficienti — usura e consumi per categoria di auto\n"
    "/reset\\_coefficienti — riporta i coefficienti ai valori di default\n"
    "/annulla — esce dalla conversazione in corso\n"
    "/help — questo messaggio\n\n"
    "*Come calcolo le quote*\n"
    "```\n"
    "Usura totale = c x D\n"
    "Q usura      = (c x D) / N\n"
    "Q viaggio    = (B + T) / N\n"
    "Passeggero   = Q usura + Q viaggio\n"
    "Conducente   = Q viaggio\n"
    "```\n"
    "D = km della tratta, N = partecipanti (conducente compreso), "
    "B = carburante, T = pedaggi, c = usura al km.\n\n"
    "*Da dove a dove*\n"
    "Non serve sapere i km: dimmi le localita' di partenza e arrivo e calcolo "
    "io il percorso stradale. Se preferisci, puoi sempre scrivere i km a mano."
    "\n\n"
    "*Carburante*\n"
    "Non serve nemmeno sapere quanto e' costato il pieno: dimmi il prezzo di "
    "un litro e stimo la spesa dai km e dai consumi della categoria d'auto.\n"
    "```\n"
    "litri = D / 100 x consumo\n"
    "B     = litri x prezzo al litro\n"
    "```\n"
    "Consumi di default: piccola 5,5 — media 7,0 — grande 9,0 l/100 km, "
    "modificabili con /coefficienti. Se hai lo scontrino, c'e' il bottone "
    "«So quanto ho speso».\n\n"
    "I *pedaggi* restano una domanda: il costo dei caselli non e' disponibile "
    "da servizi gratuiti.\n\n"
    "Il conducente incassa dai passeggeri `Q usura x (N-1)`: la sua frazione "
    "di usura resta a suo carico, come compenso per l'auto che ci mette lui.\n\n"
    "*Numeri*\n"
    "Puoi scrivere sia `35,58` sia `35.58`. Il numero di partecipanti e' "
    "minimo 2."
)

ANNULLATO = (
    "Va bene, ho annullato tutto. \U0001F44B\n"
    "Quando vuoi ricominciare: /nuovo"
)

CHIEDI_TIPO = "Il viaggio e' a *tratta singola* o *andata e ritorno*?"

def chiedi_modo_costi(carburante_manuale: bool) -> str:
    voci = "carburante e pedaggi" if carburante_manuale else "pedaggi"
    return (
        f"Come mi dai i *{voci}*?\n\n"
        "\U0001F4A1 Se hai solo i totali complessivi di andata e ritorno, "
        "scegli la seconda opzione: li divido io a meta' fra le due tratte."
    )

CHIEDI_PREZZO_LITRO = (
    "⛽ Quanto costa *un litro* di carburante oggi?\n"
    "(es. `1,789` — lo trovi sul distributore o sullo scontrino)\n\n"
    "Con questo e i km stimo la spesa di carburante: cosi' non devi sapere "
    "quanto e' costato il pieno."
)


def prezzo_litro_ricordato(prezzo: float) -> str:
    return f"↩️ Come l'ultima volta ({formatta_prezzo_litro(prezzo)})"


def stima_carburante_spiegata(
    km: float, consumo: float, prezzo: float, spesa: float
) -> str:
    litri = litri_stimati(km, consumo)
    return (
        f"⛽ Stima: {formatta_km(km)} a {formatta_consumo(consumo)} = "
        f"{formatta_litri(litri)} x {formatta_prezzo_litro(prezzo)} = "
        f"*{formatta_euro(spesa)}*"
    )


CHIEDI_CATEGORIA = (
    "Ultima cosa: che *auto* avete usato?\n\n"
    "Serve a stimare l'usura al km."
)

CHIEDI_MESSAGGIO_FINALE = (
    "Vuoi che prepari il messaggio da inviare ai partecipanti?"
)

USA_I_BOTTONI = "Usa i bottoni qui sopra per scegliere \U0001F446"

CALCOLO_IN_CORSO = (
    "Sto ancora facendo il conto del viaggio.\n"
    "Chiudi con /annulla e poi riprova."
)


def chiedi_partenza(tratta: str, totale_tratte: int, indice: int) -> str:
    intestazione = _intestazione_tratta(tratta, totale_tratte, indice)
    return (
        f"{intestazione}"
        "Da dove si parte? Scrivi una citta' o un indirizzo\n"
        "(es. `Bologna` oppure `Via Roma 12, Torino`).\n\n"
        "Calcolo io i km del percorso stradale."
    )


def chiedi_arrivo(partenza: str) -> str:
    return (
        f"\U0001F4CD Partenza: *{escape_markdown(partenza)}*\n\n"
        "E dove si arriva?"
    )


def percorso_trovato(
    origine: str, destinazione: str, km: float, durata: str | None, servizio: str
) -> str:
    righe = [
        f"\U0001F6E3 *{escape_markdown(origine)}* \u2192 "
        f"*{escape_markdown(destinazione)}*",
        f"\U0001F4CF *{formatta_km(km)}*"
        + (f" \u00b7 circa {durata} di guida" if durata else ""),
        "",
        f"_Percorso stradale calcolato con {servizio}._",
        "",
        "Confermi questa distanza?",
    ]
    return "\n".join(righe)


MAPPE_NON_DISPONIBILI = (
    "\U0001F5FA Non riesco a calcolare il percorso in questo momento.\n"
    "Nessun problema: scrivimi direttamente i *km* della tratta."
)


def chiedi_distanza(tratta: str, totale_tratte: int, indice: int) -> str:
    intestazione = _intestazione_tratta(tratta, totale_tratte, indice)
    return (
        f"{intestazione}"
        "Quanti *km* sono? (es. `480` oppure `480,5`)"
    )


def chiedi_partecipanti(tratta: str) -> str:
    return (
        f"Quante *persone* erano in auto sulla tratta *{tratta.lower()}*, "
        "conducente compreso? (minimo 2)"
    )


CARBURANTE_NOTO = "\U0001F4B6 So quanto ho speso"


def chiedi_carburante(tratta: str) -> str:
    return (
        f"Quanto e' costato il *carburante* per la tratta *{tratta.lower()}*? "
        "(in €, es. `85,00`)\n\n"
        "Se non ce n'e' stato, scrivi `0`."
    )


def chiedi_pedaggi(tratta: str) -> str:
    return (
        f"E i *pedaggi* della tratta *{tratta.lower()}*? (in €, es. `21,75`)\n\n"
        "Se non ce ne sono stati, scrivi `0`."
    )


CHIEDI_TOT_CARBURANTE = (
    "Qual e' il *totale del carburante* di andata e ritorno? (in €)\n\n"
    "Lo divido a meta' fra le due tratte."
)

CHIEDI_TOT_PEDAGGI = (
    "E il *totale dei pedaggi* di andata e ritorno? (in €)\n\n"
    "Anche questo lo divido a meta'."
)


def _intestazione_tratta(tratta: str, totale_tratte: int, indice: int) -> str:
    if totale_tratte == 1:
        return "\U0001F4CD *Tratta unica*\n\n"
    return f"\U0001F4CD *{tratta}* (tratta {indice + 1} di {totale_tratte})\n\n"


def errore_input(dettaglio: str) -> str:
    return (
        f"⚠️ {dettaglio}\n\n"
        "Riprova pure: scrivi di nuovo il valore."
    )


# --------------------------------------------------------------------------- #
# Coefficienti
# --------------------------------------------------------------------------- #

ETICHETTE_TIPO = {
    "usura": ("\U0001F527", "usura", "€/km"),
    "consumo": ("⛽", "consumo", "l/100 km"),
}


def _valore_formattato(tipo: str, valore: float) -> str:
    return formatta_coefficiente(valore) if tipo == "usura" else formatta_consumo(valore)


def testo_coefficienti(
    coefficienti: dict[str, float],
    consumi: dict[str, float],
    personalizzati_usura: dict[str, float],
    personalizzati_consumo: dict[str, float],
    prezzo: float | None = None,
) -> str:
    righe: list[str] = []
    for categoria, meta in CATEGORIE.items():
        usura = coefficienti.get(categoria, COEFFICIENTI_DEFAULT[categoria])
        consumo = consumi.get(categoria, CONSUMI_DEFAULT[categoria])
        modificata = categoria in personalizzati_usura or categoria in personalizzati_consumo
        if righe:
            righe.append("")
        righe.append(f"{meta['nome']}{' *' if modificata else ''}")
        righe.append(_riga("  usura", formatta_coefficiente(usura)))
        righe.append(_riga("  consumo", formatta_consumo(consumo)))

    nota = (
        "\n`*` = personalizzata per questa chat.\n"
        if personalizzati_usura or personalizzati_consumo
        else "\nSono tutti valori di default.\n"
    )
    if prezzo is not None:
        nota += f"Ultimo prezzo carburante usato: *{formatta_prezzo_litro(prezzo)}*\n"

    return (
        "\U0001F527 *Preferenze di calcolo*\n"
        + _blocco(righe)
        + nota
        + "\nL'*usura* e' quanto costa al km tenere l'auto; il *consumo* serve "
        "a stimare il carburante dai km.\n\n"
        "Quale categoria vuoi modificare?"
    )


def chiedi_tipo_coefficiente(
    categoria: str, usura: float, consumo: float
) -> str:
    meta = CATEGORIE[categoria]
    return (
        f"{meta['emoji']} *{meta['nome']}* ({meta['descrizione']})\n"
        + _blocco(
            [
                _riga("  usura", formatta_coefficiente(usura)),
                _riga("  consumo", formatta_consumo(consumo)),
            ]
        )
        + "\nCosa vuoi cambiare?"
    )


def chiedi_nuovo_valore(categoria: str, tipo: str, valore_attuale: float) -> str:
    meta = CATEGORIE[categoria]
    emoji, nome_tipo, unita = ETICHETTE_TIPO[tipo]
    esempio = "`0,12` oppure `0.12`" if tipo == "usura" else "`7,5` oppure `7.5`"
    return (
        f"{emoji} *{meta['nome']} — {nome_tipo}*\n"
        f"Valore attuale: *{_valore_formattato(tipo, valore_attuale)}*\n\n"
        f"Scrivi il nuovo valore in {unita} ({esempio}).\n"
        "Deve essere un numero positivo.\n\n"
        "Per lasciare tutto com'e': /annulla"
    )


def valore_salvato(categoria: str, tipo: str, valore: float) -> str:
    meta = CATEGORIE[categoria]
    _, nome_tipo, _ = ETICHETTE_TIPO[tipo]
    return (
        f"✅ Salvato: *{meta['nome']} — {nome_tipo}* = "
        f"*{_valore_formattato(tipo, valore)}*\n\n"
        "Il valore resta memorizzato anche dopo un riavvio del bot.\n"
        "Vedi tutto con /coefficienti, torna ai default con "
        "/reset\\_coefficienti."
    )


COEFFICIENTI_RESETTATI = (
    "♻️ Fatto: preferenze riportate ai valori di default.\n"
    + _blocco(
        [
            _riga("Piccola", "0,05 €/km"),
            _riga("", "5,5 l/100 km"),
            _riga("Media", "0,10 €/km"),
            _riga("", "7,0 l/100 km"),
            _riga("Grande", "0,15 €/km"),
            _riga("", "9,0 l/100 km"),
        ]
    )
    + "\nDimenticato anche l'ultimo prezzo del carburante."
)


# --------------------------------------------------------------------------- #
# Il conto
# --------------------------------------------------------------------------- #

def _quote_tratta(r: RisultatoTratta) -> str:
    return _blocco(
        [
            _riga("Passeggero", formatta_euro(r.quota_passeggero)),
            _riga("Conducente", formatta_euro(r.quota_conducente)),
        ]
    )


def _intestazione_percorso(r: RisultatoTratta) -> list[str]:
    """Una riga con il tragitto (se noto) e una con km e persone."""
    righe = []
    if r.tratta.percorso:
        righe.append(escape_markdown(r.tratta.percorso))
    righe.append(
        f"{formatta_km(r.tratta.distanza_km)} \u00b7 {r.partecipanti} persone"
    )
    return righe


def testo_conto(ris: RisultatoViaggio) -> str:
    """Il conto: quanto paga ciascuno, conducente compreso."""
    parti = [
        "\U0001F9FE *Divide et viaggia — il conto*",
        f"{etichetta_categoria(ris.categoria)} \u00b7 usura "
        f"{formatta_coefficiente(ris.coefficiente)}",
        "",
    ]

    if ris.andata_e_ritorno:
        for r in ris.tratte:
            parti.append(f"*{r.nome.upper()}*")
            parti += _intestazione_percorso(r)
            parti.append(_quote_tratta(r))
            parti.append("")

        righe = [
            _riga("Andata e ritorno", formatta_euro(ris.quota_passeggero_completo))
        ]
        for nome, quota in ris.quote_passeggero_per_tratta.items():
            righe.append(_riga(f"Solo {nome.lower()}", formatta_euro(quota)))
        righe.append(_riga("Conducente", formatta_euro(ris.esborso_conducente)))

        parti.append("\U0001F4B0 *QUANTO PAGA CIASCUNO*")
        parti.append(_blocco(righe))
    else:
        r = ris.tratte[0]
        parti += _intestazione_percorso(r)
        parti.append("")
        parti.append("\U0001F4B0 *QUANTO PAGA CIASCUNO*")
        parti.append(_quote_tratta(r))

    spese = (
        f"Spese: {formatta_euro(sum(t.tratta.carburante for t in ris.tratte))} "
        f"di carburante"
        + (" (stima)" if ris.carburante_stimato else "")
        + f" + {formatta_euro(sum(t.tratta.pedaggi for t in ris.tratte))} di pedaggi"
    )
    parti += ["", spese]

    note = [
        "_Passeggeri: carburante, pedaggi e usura dell'auto. Conducente: solo "
        "carburante e pedaggi. Esclusi bollo, assicurazione, parcheggi e multe._"
    ]
    if ris.carburante_stimato and ris.consumo and ris.prezzo_litro:
        note.append(
            f"_Carburante stimato con {formatta_consumo(ris.consumo)} a "
            f"{formatta_prezzo_litro(ris.prezzo_litro)}: cambialo con "
            "/coefficienti._"
        )
    parti += note
    return "\n".join(parti)


# --------------------------------------------------------------------------- #
# Messaggio pronto da inoltrare ai partecipanti
# --------------------------------------------------------------------------- #

def testo_condivisibile(ris: RisultatoViaggio, conducente: str | None = None) -> str:
    nome = escape_markdown((conducente or "").strip()) or "chi ha guidato"
    righe = [
        "\U0001F697 *Spese del viaggio — ecco il conto!*",
        "",
    ]

    for r in ris.tratte:
        titolo = r.nome if ris.andata_e_ritorno else "Tratta"
        tragitto = (
            f"{escape_markdown(r.tratta.percorso)}, " if r.tratta.percorso else ""
        )
        righe.append(
            f"\U0001F4CD {titolo}: {tragitto}"
            f"{formatta_km(r.tratta.distanza_km)} in {r.partecipanti} persone"
        )

    righe += [
        "",
        f"\U0001F4B6 *Quote da versare a {nome}*",
    ]

    if ris.andata_e_ritorno:
        righe.append(
            f"• Chi fa *andata e ritorno*: "
            f"*{formatta_euro(ris.quota_passeggero_completo)}*"
        )
        for nome_tratta, quota in ris.quote_passeggero_per_tratta.items():
            righe.append(
                f"• Chi fa *solo {nome_tratta.lower()}*: "
                f"*{formatta_euro(quota)}*"
            )
    else:
        righe.append(
            f"• Ogni passeggero: "
            f"*{formatta_euro(ris.quota_passeggero_completo)}*"
        )

    righe += [
        "",
        "La quota copre tutte le spese del viaggio, divise fra chi viaggia.",
        "",
        # Il messaggio puo' essere inviato prima o dopo il viaggio: la chiusura
        # non deve presupporre ne' l'uno ne' l'altro.
        "Grazie a tutti, in compagnia si viaggia meglio e si spende meno! "
        "\U0001F60E",
    ]
    return "\n".join(righe)


# --------------------------------------------------------------------------- #
# Carta d'imbarco
# --------------------------------------------------------------------------- #

#: Larghezza del contenuto della carta, bordi esclusi.
_CARTA = 32

CHIEDI_NOME_VIAGGIATORE = (
    "\U0001F3AB *Carta d'imbarco*\n\n"
    "Come si chiama il viaggiatore? (nome e cognome, o solo il nome)"
)

CHIEDI_ORARIO_IMBARCO = (
    "A che *ora* e' l'imbarco? (es. `07:30`, `7.30`, `0730`)"
)

CHIEDI_INDIRIZZO_IMBARCO = (
    "Da dove si parte? Scrivi l'*indirizzo o il luogo di imbarco*\n"
    "(es. `Via Roma 12` oppure `Bar della stazione`)"
)

CHIEDI_TRATTA_IMBARCO = (
    "Per chi e' questa carta d'imbarco?"
)

IMBARCO_SENZA_CONTO = (
    "\U0001F3AB Per stampare la carta d'imbarco mi serve prima il conto del "
    "viaggio.\n\n"
    "Fai un calcolo con /nuovo e poi torna qui con /cartaimbarco."
)

CARTA_PIEDE = (
    "\U0001F9F3 Bagaglio a mano: una borsa a testa. "
    "\U0001F3B6 Playlist a cura del conducente.\n"
    "\U0001F4E4 Inoltra la carta al viaggiatore: la quota si versa "
    "all'imbarco. \U0001F609"
)


def _carta_riga(testo: str = "") -> str:
    """Una riga della carta, sempre larga uguale e sempre su una riga sola.

    La carta e' un blocco di codice: nome e indirizzo arrivano dall'utente e un
    loro backtick chiuderebbe il blocco in anticipo, lasciando il Markdown
    spaiato (Telegram rifiuta l'intero messaggio). Un a-capo romperebbe la
    cornice. Entrambi vengono sostituiti qui, dove passa ogni riga.
    """
    testo = testo.replace("`", "'")
    testo = " ".join(testo.splitlines()) if "\n" in testo or "\r" in testo else testo
    testo = testo.replace("\t", " ")
    return "|" + testo.ljust(_CARTA)[:_CARTA] + "|"


def _carta_bordo(angolo_sx: str, angolo_dx: str) -> str:
    return angolo_sx + "=" * _CARTA + angolo_dx


def _carta_separatore() -> str:
    return "+" + "-" * _CARTA + "+"


def _carta_campo(etichetta: str, valore: str) -> list[str]:
    """Etichetta a sinistra e valore a destra; va a capo se non ci sta."""
    etichetta = f" {etichetta}"
    valore = f"{valore} "
    if len(etichetta) + 2 + len(valore) <= _CARTA:
        return [_carta_riga(etichetta + valore.rjust(_CARTA - len(etichetta)))]

    righe = [_carta_riga(etichetta)]
    for pezzo in textwrap.wrap(valore.strip(), _CARTA - 3) or [""]:
        righe.append(_carta_riga((pezzo + " ").rjust(_CARTA)))
    return righe


def _codice_a_barre(codice: str) -> str:
    motivi = ("|||", "|", "| |", "||")
    tratti = " ".join(motivi[(ord(c) + i * 5) % 4] for i, c in enumerate(codice * 2))
    return _carta_riga(tratti[: _CARTA - 6].center(_CARTA))


def carta_imbarco(
    *,
    nome: str,
    tratta: str,
    orario: str,
    indirizzo: str,
    quota: float,
    ruolo: str = "PASSEGGERO",
    veicolo: str | None = None,
    partecipanti: int | None = None,
    origine: str | None = None,
    destinazione: str | None = None,
    codice: str = "DVXXXX",
    posto: str = "1A",
) -> str:
    """Compone la carta d'imbarco in un blocco monospazio.

    Mostra solo la cifra che interessa al viaggiatore: la quota dovuta, senza
    scomporla in carburante, pedaggi e usura.
    """
    conducente = ruolo.upper() == "CONDUCENTE"

    righe = [
        _carta_bordo("/", "\\"),
        _carta_riga(" DIVIDE ET VIAGGIA" + "CARTA ".rjust(_CARTA - 18)),
        _carta_riga("D'IMBARCO ".rjust(_CARTA)),
        _carta_separatore(),
        _carta_riga(f" {'COMANDANTE' if conducente else 'PASSEGGERO'}"),
        _carta_riga(f" {nome.upper()}"[: _CARTA]),
        _carta_riga(),
    ]

    righe += _carta_campo("TRATTA", tratta.upper())
    if origine and destinazione:
        righe += _carta_campo("DA", origine.upper())
        righe += _carta_campo("A", destinazione.upper())
    righe += _carta_campo("IMBARCO ORE", orario)
    righe += _carta_campo("GATE", indirizzo.upper())
    if partecipanti:
        righe += _carta_campo("A BORDO", f"{partecipanti} PERSONE")

    if veicolo:
        righe += _carta_campo("VEICOLO", veicolo.upper())
    righe += _carta_campo("POSTO", posto.upper())

    righe.append(_carta_separatore())
    righe += _carta_campo(
        "A TUO CARICO" if conducente else "QUOTA DOVUTA", formatta_euro(quota)
    )

    righe += [
        _carta_separatore(),
        _codice_a_barre(codice),
        _carta_riga(f" {codice}".ljust(_CARTA - 13) + "BUON VIAGGIO "),
        _carta_bordo("\\", "/"),
    ]

    intestazione = (
        "\U0001F3AB *Carta d'imbarco* — imbarco prioritario per chi paga "
        "subito \U0001F60E"
    )
    return f"{intestazione}\n{_blocco(righe)}\n{CARTA_PIEDE}"
