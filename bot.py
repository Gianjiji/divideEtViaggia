"""Divide et viaggia — bot Telegram per dividere i costi di un viaggio in auto.

Avvio:
    python bot.py

Richiede la variabile d'ambiente ``TELEGRAM_BOT_TOKEN`` (anche via file .env).
"""

from __future__ import annotations

import logging
import os
import random
import string
import sys
import warnings

from dotenv import load_dotenv
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ChatAction, ParseMode
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)
from telegram.warnings import PTBUserWarning

import messaggi
from calcolo import (
    CATEGORIE,
    COEFFICIENTI_DEFAULT,
    CONSUMI_DEFAULT,
    InputNonValido,
    Tratta,
    arrotonda,
    calcola_viaggio,
    dividi_a_meta,
    parse_coefficiente,
    parse_consumo,
    parse_distanza,
    parse_importo,
    parse_orario,
    parse_partecipanti,
    parse_prezzo_litro,
    parse_testo_breve,
    stima_carburante,
)
import percorso as mappe
from storage import archivio

# I nostri ConversationHandler mescolano, per scelta, handler di messaggi e di
# callback query: il warning di PTB su `per_message` e' atteso e non segnala un
# problema, quindi evitiamo di stamparlo a ogni avvio.
warnings.filterwarnings(
    "ignore", category=PTBUserWarning, message=r".*per_message.*"
)

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO,
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger("divide-et-viaggia")

# --------------------------------------------------------------------------- #
# Stati delle conversazioni
# --------------------------------------------------------------------------- #

(
    TIPO_VIAGGIO,
    CATEGORIA,
    PREZZO_CARBURANTE,
    MODO_COSTI,
    PARTENZA,
    ARRIVO,
    CONFERMA_DISTANZA,
    DISTANZA,
    PARTECIPANTI,
    CARBURANTE,
    PEDAGGI,
    TOT_CARBURANTE,
    TOT_PEDAGGI,
    MESSAGGIO_FINALE,
) = range(14)

COEF_CATEGORIA, COEF_TIPO, COEF_VALORE = range(100, 103)

IMB_NOME, IMB_ORARIO, IMB_INDIRIZZO, IMB_QUOTA = range(200, 204)

#: Limiti di lunghezza dei testi liberi della carta d'imbarco.
MAX_NOME = 28
MAX_INDIRIZZO = 40

MD = ParseMode.MARKDOWN


# --------------------------------------------------------------------------- #
# Tastiere
# --------------------------------------------------------------------------- #

def tastiera_tipo() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("➡️ Tratta singola", callback_data="tipo:singola")],
            [InlineKeyboardButton("\U0001F504 Andata e ritorno", callback_data="tipo:ar")],
        ]
    )


def tastiera_modo_costi() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("\U0001F9FE Tratta per tratta", callback_data="modo:per_tratta")],
            [InlineKeyboardButton("✂️ Ho i totali A/R: dividi a meta'", callback_data="modo:meta")],
        ]
    )


def tastiera_categorie(prefisso: str = "cat") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    f"{meta['emoji']} {meta['nome']}",
                    callback_data=f"{prefisso}:{chiave}",
                )
                for chiave, meta in CATEGORIE.items()
            ]
        ]
    )


def tastiera_quote(risultato) -> InlineKeyboardMarkup:
    """Un bottone per ogni quota che ha senso stampare su una carta."""
    righe = []
    if risultato.andata_e_ritorno:
        righe.append(
            [InlineKeyboardButton("\U0001F9CD Passeggero A+R", callback_data="imb:tutto")]
        )
        for indice, tratta in enumerate(risultato.tratte):
            righe.append(
                [
                    InlineKeyboardButton(
                        f"\U0001F9CD Solo {tratta.nome.lower()}",
                        callback_data=f"imb:t{indice}",
                    )
                ]
            )
    else:
        righe.append(
            [InlineKeyboardButton("\U0001F9CD Passeggero", callback_data="imb:tutto")]
        )
    righe.append(
        [InlineKeyboardButton("\U0001F9D1\u200D✈️ Conducente", callback_data="imb:conducente")]
    )
    return InlineKeyboardMarkup(righe)


def tastiera_si_no() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("✅ Si'", callback_data="msg:si"),
                InlineKeyboardButton("❌ No, grazie", callback_data="msg:no"),
            ]
        ]
    )


# --------------------------------------------------------------------------- #
# Utilita'
# --------------------------------------------------------------------------- #

async def _chiudi_bottoni(update: Update, testo_scelta: str) -> None:
    """Risponde al tap e sostituisce la tastiera con la scelta fatta."""
    query = update.callback_query
    await query.answer()
    try:
        await query.edit_message_text(testo_scelta, parse_mode=MD)
    except Exception:  # messaggio identico o non modificabile: non e' un problema
        logger.debug("Impossibile aggiornare il messaggio della tastiera", exc_info=True)


def _dati(context: ContextTypes.DEFAULT_TYPE) -> dict:
    return context.user_data.setdefault("viaggio", {})


async def _chiedi_partenza_corrente(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Apre una tratta chiedendo la localita' di partenza."""
    dati = _dati(context)
    indice = dati["indice"]
    nomi = dati["nomi"]

    bottoni = []
    precedente = dati["tratte"][indice - 1] if indice else None
    if precedente and precedente.get("distanza_km"):
        bottoni.append(
            [
                InlineKeyboardButton(
                    f"↩️ Come l'andata "
                    f"({messaggi.formatta_km(precedente['distanza_km'])})",
                    callback_data="km:come_andata",
                )
            ]
        )
    bottoni.append(
        [InlineKeyboardButton("✏️ Inserisco i km a mano", callback_data="km:manuale")]
    )

    await update.effective_chat.send_message(
        messaggi.chiedi_partenza(nomi[indice], len(nomi), indice),
        parse_mode=MD,
        reply_markup=InlineKeyboardMarkup(bottoni),
    )
    return PARTENZA


async def _chiedi_distanza_corrente(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Ripiego: i km inseriti a mano."""
    dati = _dati(context)
    indice = dati["indice"]
    nomi = dati["nomi"]
    await update.effective_chat.send_message(
        messaggi.chiedi_distanza(nomi[indice], len(nomi), indice),
        parse_mode=MD,
    )
    return DISTANZA


async def _chiedi_partecipanti_correnti(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    dati = _dati(context)
    await update.effective_chat.send_message(
        messaggi.chiedi_partecipanti(dati["nomi"][dati["indice"]]), parse_mode=MD
    )
    return PARTECIPANTI


async def _avanza(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Passa alla tratta successiva, ai totali A/R oppure al conto."""
    dati = _dati(context)
    dati["indice"] += 1
    if dati["indice"] < len(dati["nomi"]):
        return await _chiedi_partenza_corrente(update, context)

    if dati["modo"] == "meta":
        if dati.get("carburante_manuale"):
            await update.effective_chat.send_message(
                messaggi.CHIEDI_TOT_CARBURANTE, parse_mode=MD
            )
            return TOT_CARBURANTE
        await update.effective_chat.send_message(
            messaggi.CHIEDI_TOT_PEDAGGI, parse_mode=MD
        )
        return TOT_PEDAGGI

    return await _mostra_conto(update, context)


async def _chiedi_categoria(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.effective_chat.send_message(
        messaggi.CHIEDI_CATEGORIA,
        parse_mode=MD,
        reply_markup=tastiera_categorie(),
    )
    return CATEGORIA


# --------------------------------------------------------------------------- #
# Conversazione principale: il calcolo
# --------------------------------------------------------------------------- #

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["viaggio"] = {}
    await update.effective_chat.send_message(
        messaggi.BENVENUTO, parse_mode=MD, reply_markup=tastiera_tipo()
    )
    return TIPO_VIAGGIO


async def nuovo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["viaggio"] = {}
    await update.effective_chat.send_message(
        messaggi.CHIEDI_TIPO, parse_mode=MD, reply_markup=tastiera_tipo()
    )
    return TIPO_VIAGGIO


async def scelta_tipo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    scelta = update.callback_query.data.split(":", 1)[1]
    dati = _dati(context)

    if scelta == "singola":
        dati["nomi"] = ["Tratta unica"]
        dati["modo"] = "per_tratta"
        await _chiudi_bottoni(update, "➡️ Viaggio a *tratta singola*.")
    else:
        dati["nomi"] = ["Andata", "Ritorno"]
        await _chiudi_bottoni(update, "\U0001F504 Viaggio di *andata e ritorno*.")

    dati["tratte"] = [{} for _ in dati["nomi"]]
    dati["indice"] = 0

    return await _chiedi_categoria(update, context)


async def scelta_modo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    modo = update.callback_query.data.split(":", 1)[1]
    _dati(context)["modo"] = modo
    testo = (
        "✂️ Ok: mi dai i *totali* di andata e ritorno, li divido a meta'."
        if modo == "meta"
        else "\U0001F9FE Ok: mi dai i costi *tratta per tratta*."
    )
    await _chiudi_bottoni(update, testo)
    return await _chiedi_partenza_corrente(update, context)


async def ricevi_partenza(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.effective_chat.send_action(ChatAction.TYPING)
    try:
        luogo = await mappe.cerca_luogo(update.message.text)
    except mappe.LuogoNonTrovato as exc:
        await update.message.reply_text(messaggi.errore_input(str(exc)), parse_mode=MD)
        return PARTENZA
    except mappe.ErrorePercorso as exc:
        logger.warning("Geocoding non riuscito: %s", exc)
        await update.message.reply_text(messaggi.MAPPE_NON_DISPONIBILI, parse_mode=MD)
        return DISTANZA

    _dati(context)["partenza"] = luogo
    await update.message.reply_text(messaggi.chiedi_arrivo(luogo.nome), parse_mode=MD)
    return ARRIVO


async def ricevi_arrivo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    dati = _dati(context)
    partenza = dati.get("partenza")
    if partenza is None:
        return await _chiedi_partenza_corrente(update, context)

    await update.effective_chat.send_action(ChatAction.TYPING)
    try:
        arrivo = await mappe.cerca_luogo(update.message.text)
        tragitto = await mappe.calcola_percorso(partenza, arrivo)
    except mappe.LuogoNonTrovato as exc:
        await update.message.reply_text(messaggi.errore_input(str(exc)), parse_mode=MD)
        return ARRIVO
    except mappe.ErrorePercorso as exc:
        logger.warning("Calcolo percorso non riuscito: %s", exc)
        await update.message.reply_text(messaggi.MAPPE_NON_DISPONIBILI, parse_mode=MD)
        return DISTANZA

    dati["percorso"] = tragitto
    await update.message.reply_text(
        messaggi.percorso_trovato(
            tragitto.origine.nome,
            tragitto.destinazione.nome,
            tragitto.distanza_km,
            tragitto.durata_leggibile,
            tragitto.servizio,
        ),
        parse_mode=MD,
        reply_markup=InlineKeyboardMarkup(
            [
                [InlineKeyboardButton("✅ Confermo", callback_data="dist:ok")],
                [InlineKeyboardButton("\U0001F501 Cambio localita'", callback_data="dist:ripeti")],
                [InlineKeyboardButton("✏️ Inserisco i km a mano", callback_data="km:manuale")],
            ]
        ),
    )
    return CONFERMA_DISTANZA


async def conferma_distanza(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    scelta = update.callback_query.data.split(":", 1)[1]
    dati = _dati(context)

    if scelta == "ripeti":
        await _chiudi_bottoni(update, "\U0001F501 Ricominciamo da capo con le localita'.")
        dati.pop("partenza", None)
        dati.pop("percorso", None)
        return await _chiedi_partenza_corrente(update, context)

    tragitto = dati.get("percorso")
    if tragitto is None:
        await _chiudi_bottoni(update, "✏️ Inserisci i km a mano.")
        return await _chiedi_distanza_corrente(update, context)

    tratta = dati["tratte"][dati["indice"]]
    tratta["distanza_km"] = tragitto.distanza_km
    tratta["origine"] = tragitto.origine.nome
    tratta["destinazione"] = tragitto.destinazione.nome
    dati.pop("partenza", None)
    dati.pop("percorso", None)

    await _chiudi_bottoni(
        update,
        f"\U0001F6E3 *{messaggi.escape_markdown(tratta['origine'])}* \u2192 "
        f"*{messaggi.escape_markdown(tratta['destinazione'])}* — "
        f"*{messaggi.formatta_km(tratta['distanza_km'])}*",
    )
    return await _chiedi_partecipanti_correnti(update, context)


async def km_manuale(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """L'utente preferisce scrivere i km invece di far calcolare il percorso."""
    dati = _dati(context)
    dati.pop("partenza", None)
    dati.pop("percorso", None)
    await _chiudi_bottoni(update, "✏️ Va bene, i km li inserisci tu.")
    return await _chiedi_distanza_corrente(update, context)


async def km_come_andata(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Il ritorno ripercorre l'andata: stessi km, localita' invertite."""
    dati = _dati(context)
    indice = dati["indice"]
    precedente = dati["tratte"][indice - 1] if indice else None
    if not precedente or not precedente.get("distanza_km"):
        await _chiudi_bottoni(update, "✏️ Inserisci i km a mano.")
        return await _chiedi_distanza_corrente(update, context)

    tratta = dati["tratte"][indice]
    tratta["distanza_km"] = precedente["distanza_km"]
    if precedente.get("origine") and precedente.get("destinazione"):
        tratta["origine"] = precedente["destinazione"]
        tratta["destinazione"] = precedente["origine"]

    etichetta = messaggi.formatta_km(tratta["distanza_km"])
    if tratta.get("origine"):
        etichetta = (
            f"{messaggi.escape_markdown(tratta['origine'])} \u2192 "
            f"{messaggi.escape_markdown(tratta['destinazione'])} — {etichetta}"
        )
    await _chiudi_bottoni(update, f"↩️ *{etichetta}*")
    return await _chiedi_partecipanti_correnti(update, context)


async def ricevi_distanza(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        km = parse_distanza(update.message.text)
    except InputNonValido as exc:
        await update.message.reply_text(messaggi.errore_input(str(exc)), parse_mode=MD)
        return DISTANZA

    dati = _dati(context)
    tratta = dati["tratte"][dati["indice"]]
    tratta["distanza_km"] = km
    # Km scritti a mano: non abbiamo localita' da mostrare.
    tratta.pop("origine", None)
    tratta.pop("destinazione", None)
    return await _chiedi_partecipanti_correnti(update, context)


async def ricevi_partecipanti(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        n = parse_partecipanti(update.message.text)
    except InputNonValido as exc:
        await update.message.reply_text(messaggi.errore_input(str(exc)), parse_mode=MD)
        return PARTECIPANTI

    dati = _dati(context)
    dati["tratte"][dati["indice"]]["partecipanti"] = n

    if dati["modo"] == "meta":
        return await _avanza(update, context)

    if dati.get("carburante_manuale"):
        await update.message.reply_text(
            messaggi.chiedi_carburante(dati["nomi"][dati["indice"]]), parse_mode=MD
        )
        return CARBURANTE

    await update.message.reply_text(
        messaggi.chiedi_pedaggi(dati["nomi"][dati["indice"]]), parse_mode=MD
    )
    return PEDAGGI


async def ricevi_carburante(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        importo = parse_importo(update.message.text)
    except InputNonValido as exc:
        await update.message.reply_text(messaggi.errore_input(str(exc)), parse_mode=MD)
        return CARBURANTE

    dati = _dati(context)
    dati["tratte"][dati["indice"]]["carburante"] = importo
    await update.message.reply_text(
        messaggi.chiedi_pedaggi(dati["nomi"][dati["indice"]]), parse_mode=MD
    )
    return PEDAGGI


async def ricevi_pedaggi(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        importo = parse_importo(update.message.text)
    except InputNonValido as exc:
        await update.message.reply_text(messaggi.errore_input(str(exc)), parse_mode=MD)
        return PEDAGGI

    dati = _dati(context)
    dati["tratte"][dati["indice"]]["pedaggi"] = importo
    return await _avanza(update, context)


async def ricevi_tot_carburante(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        importo = parse_importo(update.message.text)
    except InputNonValido as exc:
        await update.message.reply_text(messaggi.errore_input(str(exc)), parse_mode=MD)
        return TOT_CARBURANTE

    _dati(context)["tot_carburante"] = importo
    await update.message.reply_text(messaggi.CHIEDI_TOT_PEDAGGI, parse_mode=MD)
    return TOT_PEDAGGI


async def ricevi_tot_pedaggi(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        importo = parse_importo(update.message.text)
    except InputNonValido as exc:
        await update.message.reply_text(messaggi.errore_input(str(exc)), parse_mode=MD)
        return TOT_PEDAGGI

    dati = _dati(context)
    quante = len(dati["tratte"])
    pedaggi = dividi_a_meta(importo, quante)
    carburanti = (
        dividi_a_meta(dati["tot_carburante"], quante)
        if dati.get("carburante_manuale")
        else [None] * quante
    )
    for tratta, b, t in zip(dati["tratte"], carburanti, pedaggi):
        if b is not None:
            tratta["carburante"] = b
        tratta["pedaggi"] = t

    dettaglio = f"*{messaggi.formatta_euro(pedaggi[0])}* di pedaggi per tratta"
    if carburanti[0] is not None:
        dettaglio = (
            f"*{messaggi.formatta_euro(carburanti[0])}* di carburante e " + dettaglio
        )
    await update.message.reply_text(
        "✂️ Divisi a meta': " + dettaglio + ".", parse_mode=MD
    )
    return await _mostra_conto(update, context)


async def scelta_categoria(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    categoria = update.callback_query.data.split(":", 1)[1]
    dati = _dati(context)
    chat_id = update.effective_chat.id
    coefficiente = archivio.coefficienti(chat_id).get(
        categoria, COEFFICIENTI_DEFAULT[categoria]
    )
    consumo = archivio.consumi(chat_id).get(categoria, CONSUMI_DEFAULT[categoria])

    dati["categoria"] = categoria
    dati["coefficiente"] = coefficiente
    dati["consumo"] = consumo

    await _chiudi_bottoni(
        update,
        f"Auto: *{messaggi.etichetta_categoria(categoria)}* — usura "
        f"*{messaggi.formatta_coefficiente(coefficiente)}*, consumo "
        f"*{messaggi.formatta_consumo(consumo)}*",
    )
    return await _chiedi_prezzo(update, context)


async def _chiedi_prezzo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    ricordato = archivio.prezzo_litro(update.effective_chat.id)
    bottoni = []
    if ricordato:
        bottoni.append(
            [
                InlineKeyboardButton(
                    messaggi.prezzo_litro_ricordato(ricordato),
                    callback_data="carb:ricordato",
                )
            ]
        )
    bottoni.append(
        [InlineKeyboardButton(messaggi.CARBURANTE_NOTO, callback_data="carb:noto")]
    )
    await update.effective_chat.send_message(
        messaggi.CHIEDI_PREZZO_LITRO,
        parse_mode=MD,
        reply_markup=InlineKeyboardMarkup(bottoni),
    )
    return PREZZO_CARBURANTE


async def ricevi_prezzo_litro(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        prezzo = parse_prezzo_litro(update.message.text)
    except InputNonValido as exc:
        await update.message.reply_text(messaggi.errore_input(str(exc)), parse_mode=MD)
        return PREZZO_CARBURANTE

    dati = _dati(context)
    dati["prezzo_litro"] = prezzo
    dati["carburante_manuale"] = False
    archivio.salva_prezzo_litro(update.effective_chat.id, prezzo)
    await update.message.reply_text(
        f"⛽ Carburante a *{messaggi.formatta_prezzo_litro(prezzo)}*: "
        "la spesa la stimo io dai km.",
        parse_mode=MD,
    )
    return await _dopo_costi_globali(update, context)


async def prezzo_ricordato(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    prezzo = archivio.prezzo_litro(update.effective_chat.id)
    if prezzo is None:
        await _chiudi_bottoni(update, messaggi.CHIEDI_PREZZO_LITRO)
        return PREZZO_CARBURANTE

    dati = _dati(context)
    dati["prezzo_litro"] = prezzo
    dati["carburante_manuale"] = False
    await _chiudi_bottoni(
        update, f"⛽ Carburante a *{messaggi.formatta_prezzo_litro(prezzo)}*"
    )
    return await _dopo_costi_globali(update, context)


async def carburante_noto(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """L'utente ha lo scontrino: niente stima, chiediamo la spesa reale."""
    dati = _dati(context)
    dati["carburante_manuale"] = True
    dati["prezzo_litro"] = None
    await _chiudi_bottoni(
        update, "\U0001F4B6 Va bene: il carburante me lo dici tu."
    )
    return await _dopo_costi_globali(update, context)


async def _dopo_costi_globali(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Chiede come inserire i costi manuali, poi apre la prima tratta."""
    dati = _dati(context)
    if len(dati["nomi"]) > 1:
        await update.effective_chat.send_message(
            messaggi.chiedi_modo_costi(dati.get("carburante_manuale", False)),
            parse_mode=MD,
            reply_markup=tastiera_modo_costi(),
        )
        return MODO_COSTI

    dati["modo"] = "per_tratta"
    return await _chiedi_partenza_corrente(update, context)


async def _mostra_conto(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    dati = _dati(context)
    consumo = dati.get("consumo")
    prezzo = dati.get("prezzo_litro")

    try:
        tratte = []
        for nome, valori in zip(dati["nomi"], dati["tratte"]):
            carburante = valori.get("carburante")
            stimato = carburante is None
            if stimato:
                carburante = arrotonda(
                    stima_carburante(valori["distanza_km"], consumo, prezzo)
                )
            tratte.append(
                Tratta(
                    nome=nome,
                    distanza_km=valori["distanza_km"],
                    partecipanti=valori["partecipanti"],
                    carburante=carburante,
                    pedaggi=valori["pedaggi"],
                    origine=valori.get("origine"),
                    destinazione=valori.get("destinazione"),
                    carburante_stimato=stimato,
                )
            )
        stima_usata = any(t.carburante_stimato for t in tratte)
        risultato = calcola_viaggio(
            tratte,
            dati["coefficiente"],
            dati["categoria"],
            consumo=consumo if stima_usata else None,
            prezzo_litro=prezzo if stima_usata else None,
        )
    except (InputNonValido, KeyError, TypeError) as exc:
        logger.warning("Dati incompleti o non validi: %s", exc)
        await update.effective_chat.send_message(
            "⚠️ Qualcosa non torna nei dati inseriti. Ricominciamo con /nuovo."
        )
        context.user_data.pop("viaggio", None)
        return ConversationHandler.END

    dati["risultato"] = risultato
    # Tenuto da parte anche dopo la fine della conversazione: serve a
    # /cartaimbarco, che si appoggia all'ultimo conto fatto.
    context.user_data["ultimo_risultato"] = risultato

    await update.effective_chat.send_message(messaggi.testo_conto(risultato), parse_mode=MD)
    await update.effective_chat.send_message(
        messaggi.CHIEDI_MESSAGGIO_FINALE, parse_mode=MD, reply_markup=tastiera_si_no()
    )
    return MESSAGGIO_FINALE


async def scelta_messaggio_finale(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    scelta = update.callback_query.data.split(":", 1)[1]
    dati = _dati(context)
    risultato = dati.get("risultato")

    if scelta == "no" or risultato is None:
        await _chiudi_bottoni(update, "Va bene, niente messaggio. \U0001F44D")
        await update.effective_chat.send_message(
            "Quando vuoi un altro conto: /nuovo\n"
            "\U0001F3AB Oppure stampa la carta d'imbarco: /cartaimbarco"
        )
        context.user_data.pop("viaggio", None)
        return ConversationHandler.END

    await _chiudi_bottoni(update, "✅ Ecco il messaggio pronto da inoltrare:")
    conducente = (update.effective_user.first_name or "").strip()
    await update.effective_chat.send_message(
        messaggi.testo_condivisibile(risultato, conducente), parse_mode=MD
    )
    await update.effective_chat.send_message(
        "\U0001F4E4 Tienilo premuto per inoltrarlo al gruppo, oppure copialo.\n"
        "\U0001F3AB Carta d'imbarco: /cartaimbarco — nuovo conto: /nuovo"
    )
    context.user_data.pop("viaggio", None)
    return ConversationHandler.END


async def solo_bottoni(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """L'utente ha scritto del testo dove servirebbe un tap: glielo ricordo."""
    await update.message.reply_text(messaggi.USA_I_BOTTONI)


async def annulla(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.pop("viaggio", None)
    context.user_data.pop("coef_categoria", None)
    context.user_data.pop("coef_tipo", None)
    context.user_data.pop("imbarco", None)
    await update.effective_chat.send_message(messaggi.ANNULLATO, parse_mode=MD)
    return ConversationHandler.END


async def aiuto(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.effective_chat.send_message(messaggi.HELP, parse_mode=MD)


async def comando_occupato(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Comando laterale durante un calcolo: non interrompo il conto in corso."""
    await update.effective_chat.send_message(messaggi.CALCOLO_IN_CORSO)


# --------------------------------------------------------------------------- #
# Conversazione dei coefficienti
# --------------------------------------------------------------------------- #

async def mostra_coefficienti(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    chat_id = update.effective_chat.id
    await update.effective_chat.send_message(
        messaggi.testo_coefficienti(
            archivio.coefficienti(chat_id),
            archivio.consumi(chat_id),
            archivio.personalizzati(chat_id, "usura"),
            archivio.personalizzati(chat_id, "consumo"),
            archivio.prezzo_litro(chat_id),
        ),
        parse_mode=MD,
        reply_markup=tastiera_categorie(prefisso="coef"),
    )
    return COEF_CATEGORIA


async def scelta_coef_categoria(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    categoria = update.callback_query.data.split(":", 1)[1]
    chat_id = update.effective_chat.id
    context.user_data["coef_categoria"] = categoria

    await _chiudi_bottoni(
        update, f"Modifico: *{messaggi.etichetta_categoria(categoria)}*"
    )
    await update.effective_chat.send_message(
        messaggi.chiedi_tipo_coefficiente(
            categoria,
            archivio.coefficienti(chat_id).get(categoria, COEFFICIENTI_DEFAULT[categoria]),
            archivio.consumi(chat_id).get(categoria, CONSUMI_DEFAULT[categoria]),
        ),
        parse_mode=MD,
        reply_markup=InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "\U0001F527 Usura (€/km)", callback_data="tipo_coef:usura"
                    ),
                    InlineKeyboardButton(
                        "⛽ Consumo (l/100 km)", callback_data="tipo_coef:consumo"
                    ),
                ]
            ]
        ),
    )
    return COEF_TIPO


async def scelta_coef_tipo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    tipo = update.callback_query.data.split(":", 1)[1]
    categoria = context.user_data.get("coef_categoria")
    if categoria is None:
        await _chiudi_bottoni(update, "Ricominciamo.")
        return await mostra_coefficienti(update, context)

    context.user_data["coef_tipo"] = tipo
    chat_id = update.effective_chat.id
    attuale = (
        archivio.coefficienti(chat_id).get(categoria, COEFFICIENTI_DEFAULT[categoria])
        if tipo == "usura"
        else archivio.consumi(chat_id).get(categoria, CONSUMI_DEFAULT[categoria])
    )

    emoji, nome_tipo, _ = messaggi.ETICHETTE_TIPO[tipo]
    await _chiudi_bottoni(update, f"{emoji} Modifico: *{nome_tipo}*")
    await update.effective_chat.send_message(
        messaggi.chiedi_nuovo_valore(categoria, tipo, attuale), parse_mode=MD
    )
    return COEF_VALORE


async def ricevi_coefficiente(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    tipo = context.user_data.get("coef_tipo", "usura")
    lettore = parse_coefficiente if tipo == "usura" else parse_consumo
    try:
        valore = lettore(update.message.text)
    except InputNonValido as exc:
        await update.message.reply_text(messaggi.errore_input(str(exc)), parse_mode=MD)
        return COEF_VALORE

    categoria = context.user_data.pop("coef_categoria", None)
    context.user_data.pop("coef_tipo", None)
    if categoria is None:
        await update.message.reply_text("Ricominciamo: /coefficienti")
        return ConversationHandler.END

    archivio.imposta(update.effective_chat.id, categoria, valore, tipo=tipo)
    await update.message.reply_text(
        messaggi.valore_salvato(categoria, tipo, valore), parse_mode=MD
    )
    return ConversationHandler.END


async def reset_coefficienti(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    archivio.reset(update.effective_chat.id)
    await update.effective_chat.send_message(
        messaggi.COEFFICIENTI_RESETTATI, parse_mode=MD
    )


# --------------------------------------------------------------------------- #
# Carta d'imbarco
# --------------------------------------------------------------------------- #

_ALFABETO_CODICE = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def _codice_prenotazione() -> str:
    return "".join(random.choice(_ALFABETO_CODICE) for _ in range(6))


def _posto_a_bordo() -> str:
    return f"{random.randint(1, 9)}{random.choice(string.ascii_uppercase[:6])}"


def _dati_imbarco(context: ContextTypes.DEFAULT_TYPE) -> dict:
    return context.user_data.setdefault("imbarco", {})


async def carta_imbarco_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if context.user_data.get("ultimo_risultato") is None:
        await update.effective_chat.send_message(
            messaggi.IMBARCO_SENZA_CONTO, parse_mode=MD
        )
        return ConversationHandler.END

    context.user_data["imbarco"] = {}
    await update.effective_chat.send_message(
        messaggi.CHIEDI_NOME_VIAGGIATORE, parse_mode=MD
    )
    return IMB_NOME


async def ricevi_nome_viaggiatore(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        nome = parse_testo_breve(update.message.text, MAX_NOME, "nome")
    except InputNonValido as exc:
        await update.message.reply_text(messaggi.errore_input(str(exc)), parse_mode=MD)
        return IMB_NOME

    _dati_imbarco(context)["nome"] = nome
    await update.message.reply_text(messaggi.CHIEDI_ORARIO_IMBARCO, parse_mode=MD)
    return IMB_ORARIO


async def ricevi_orario_imbarco(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        orario = parse_orario(update.message.text)
    except InputNonValido as exc:
        await update.message.reply_text(messaggi.errore_input(str(exc)), parse_mode=MD)
        return IMB_ORARIO

    _dati_imbarco(context)["orario"] = orario
    await update.message.reply_text(messaggi.CHIEDI_INDIRIZZO_IMBARCO, parse_mode=MD)
    return IMB_INDIRIZZO


async def ricevi_indirizzo_imbarco(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        indirizzo = parse_testo_breve(update.message.text, MAX_INDIRIZZO, "indirizzo")
    except InputNonValido as exc:
        await update.message.reply_text(messaggi.errore_input(str(exc)), parse_mode=MD)
        return IMB_INDIRIZZO

    _dati_imbarco(context)["indirizzo"] = indirizzo
    risultato = context.user_data.get("ultimo_risultato")
    if risultato is None:
        await update.message.reply_text(messaggi.IMBARCO_SENZA_CONTO, parse_mode=MD)
        return ConversationHandler.END

    await update.message.reply_text(
        messaggi.CHIEDI_TRATTA_IMBARCO,
        parse_mode=MD,
        reply_markup=tastiera_quote(risultato),
    )
    return IMB_QUOTA


async def stampa_carta_imbarco(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    scelta = update.callback_query.data.split(":", 1)[1]
    risultato = context.user_data.get("ultimo_risultato")
    dati = _dati_imbarco(context)

    if risultato is None or not dati.get("nome"):
        await _chiudi_bottoni(update, "\U0001F3AB Carta d'imbarco")
        await update.effective_chat.send_message(
            messaggi.IMBARCO_SENZA_CONTO, parse_mode=MD
        )
        return ConversationHandler.END

    # Estremi del viaggio, se li conosciamo: partenza della prima tratta e
    # arrivo dell'ultima.
    estremi = {
        "origine": risultato.tratte[0].tratta.origine,
        "destinazione": risultato.tratte[-1].tratta.destinazione,
    }
    partecipanti = {r.partecipanti for r in risultato.tratte}
    etichetta_intera = (
        "Andata e ritorno" if risultato.andata_e_ritorno else risultato.tratte[0].nome
    )

    if scelta == "conducente":
        parametri = dict(
            **estremi,
            tratta=etichetta_intera,
            quota=risultato.esborso_conducente,
            ruolo="CONDUCENTE",
            partecipanti=partecipanti.pop() if len(partecipanti) == 1 else None,
        )
    elif scelta == "tutto":
        parametri = dict(
            **estremi,
            tratta=etichetta_intera,
            quota=risultato.quota_passeggero_completo,
            partecipanti=partecipanti.pop() if len(partecipanti) == 1 else None,
        )
    else:
        indice = int(scelta[1:])
        if indice >= len(risultato.tratte):
            await _chiudi_bottoni(update, "\U0001F3AB Carta d'imbarco")
            await update.effective_chat.send_message(
                "⚠️ Quella tratta non esiste piu'. Riprova con /cartaimbarco."
            )
            return ConversationHandler.END
        tratta = risultato.tratte[indice]
        parametri = dict(
            origine=tratta.tratta.origine,
            destinazione=tratta.tratta.destinazione,
            tratta=tratta.nome,
            quota=tratta.quota_passeggero,
            partecipanti=tratta.partecipanti,
        )

    await _chiudi_bottoni(update, "\U0001F3AB Imbarco confermato!")
    await update.effective_chat.send_message(
        messaggi.carta_imbarco(
            nome=dati["nome"],
            orario=dati["orario"],
            indirizzo=dati["indirizzo"],
            veicolo=f"Auto {CATEGORIE[risultato.categoria]['nome']}",
            codice=_codice_prenotazione(),
            posto=_posto_a_bordo(),
            **parametri,
        ),
        parse_mode=MD,
    )
    await update.effective_chat.send_message(
        "Un'altra carta per un altro viaggiatore? /cartaimbarco"
    )
    context.user_data.pop("imbarco", None)
    return ConversationHandler.END


# --------------------------------------------------------------------------- #
# Errori
# --------------------------------------------------------------------------- #

async def gestore_errori(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.exception("Errore non gestito", exc_info=context.error)
    if isinstance(update, Update) and update.effective_chat:
        try:
            await update.effective_chat.send_message(
                "⚠️ Ops, qualcosa e' andato storto. Riprova con /nuovo."
            )
        except Exception:
            logger.debug("Impossibile notificare l'errore all'utente", exc_info=True)


# --------------------------------------------------------------------------- #
# Avvio
# --------------------------------------------------------------------------- #

def costruisci_applicazione(token: str) -> Application:
    app = Application.builder().token(token).build()

    testo = filters.TEXT & ~filters.COMMAND

    fallback_comuni = [
        CommandHandler("annulla", annulla),
        CommandHandler("nuovo", nuovo),
        CommandHandler("start", start),
        CommandHandler("help", aiuto),
        CommandHandler("coefficienti", comando_occupato),
        CommandHandler("reset_coefficienti", comando_occupato),
        CommandHandler("cartaimbarco", comando_occupato),
        CommandHandler("imbarco", comando_occupato),
    ]

    calcolo_conv = ConversationHandler(
        entry_points=[
            CommandHandler("start", start),
            CommandHandler("nuovo", nuovo),
        ],
        states={
            TIPO_VIAGGIO: [
                CallbackQueryHandler(scelta_tipo, pattern=r"^tipo:(singola|ar)$"),
                MessageHandler(testo, solo_bottoni),
            ],
            CATEGORIA: [
                CallbackQueryHandler(
                    scelta_categoria, pattern=r"^cat:(piccola|media|grande)$"
                ),
                MessageHandler(testo, solo_bottoni),
            ],
            PREZZO_CARBURANTE: [
                CallbackQueryHandler(prezzo_ricordato, pattern=r"^carb:ricordato$"),
                CallbackQueryHandler(carburante_noto, pattern=r"^carb:noto$"),
                MessageHandler(testo, ricevi_prezzo_litro),
            ],
            MODO_COSTI: [
                CallbackQueryHandler(scelta_modo, pattern=r"^modo:(per_tratta|meta)$"),
                MessageHandler(testo, solo_bottoni),
            ],
            PARTENZA: [
                CallbackQueryHandler(km_manuale, pattern=r"^km:manuale$"),
                CallbackQueryHandler(km_come_andata, pattern=r"^km:come_andata$"),
                MessageHandler(testo, ricevi_partenza),
            ],
            ARRIVO: [
                CallbackQueryHandler(km_manuale, pattern=r"^km:manuale$"),
                MessageHandler(testo, ricevi_arrivo),
            ],
            CONFERMA_DISTANZA: [
                CallbackQueryHandler(conferma_distanza, pattern=r"^dist:(ok|ripeti)$"),
                CallbackQueryHandler(km_manuale, pattern=r"^km:manuale$"),
                MessageHandler(testo, solo_bottoni),
            ],
            DISTANZA: [MessageHandler(testo, ricevi_distanza)],
            PARTECIPANTI: [MessageHandler(testo, ricevi_partecipanti)],
            CARBURANTE: [MessageHandler(testo, ricevi_carburante)],
            PEDAGGI: [MessageHandler(testo, ricevi_pedaggi)],
            TOT_CARBURANTE: [MessageHandler(testo, ricevi_tot_carburante)],
            TOT_PEDAGGI: [MessageHandler(testo, ricevi_tot_pedaggi)],
            MESSAGGIO_FINALE: [
                CallbackQueryHandler(scelta_messaggio_finale, pattern=r"^msg:(si|no)$"),
                MessageHandler(testo, solo_bottoni),
            ],
        },
        fallbacks=fallback_comuni,
        name="calcolo_viaggio",
    )

    coefficienti_conv = ConversationHandler(
        entry_points=[CommandHandler("coefficienti", mostra_coefficienti)],
        states={
            COEF_CATEGORIA: [
                CallbackQueryHandler(
                    scelta_coef_categoria, pattern=r"^coef:(piccola|media|grande)$"
                ),
                MessageHandler(filters.TEXT & ~filters.COMMAND, solo_bottoni),
            ],
            COEF_TIPO: [
                CallbackQueryHandler(
                    scelta_coef_tipo, pattern=r"^tipo_coef:(usura|consumo)$"
                ),
                MessageHandler(filters.TEXT & ~filters.COMMAND, solo_bottoni),
            ],
            COEF_VALORE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, ricevi_coefficiente)
            ],
        },
        fallbacks=[
            CommandHandler("annulla", annulla),
            CommandHandler("help", aiuto),
            CommandHandler("coefficienti", mostra_coefficienti),
        ],
        name="modifica_coefficienti",
    )

    imbarco_conv = ConversationHandler(
        entry_points=[
            CommandHandler("cartaimbarco", carta_imbarco_start),
            CommandHandler("imbarco", carta_imbarco_start),
        ],
        states={
            IMB_NOME: [MessageHandler(testo, ricevi_nome_viaggiatore)],
            IMB_ORARIO: [MessageHandler(testo, ricevi_orario_imbarco)],
            IMB_INDIRIZZO: [MessageHandler(testo, ricevi_indirizzo_imbarco)],
            IMB_QUOTA: [
                CallbackQueryHandler(
                    stampa_carta_imbarco, pattern=r"^imb:(tutto|conducente|t\d+)$"
                ),
                MessageHandler(testo, solo_bottoni),
            ],
        },
        fallbacks=[
            CommandHandler("annulla", annulla),
            CommandHandler("help", aiuto),
            CommandHandler("cartaimbarco", carta_imbarco_start),
            CommandHandler("imbarco", carta_imbarco_start),
        ],
        name="carta_imbarco",
    )

    app.add_handler(calcolo_conv)
    app.add_handler(coefficienti_conv)
    app.add_handler(imbarco_conv)
    app.add_handler(CommandHandler("reset_coefficienti", reset_coefficienti))
    app.add_handler(CommandHandler("help", aiuto))
    app.add_error_handler(gestore_errori)
    return app


def main() -> None:
    load_dotenv()
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        print(
            "Manca il token del bot.\n"
            "Crea un file .env (copialo da .env.example) con:\n"
            "    TELEGRAM_BOT_TOKEN=il-token-che-ti-da-BotFather\n"
            "oppure esporta la variabile d'ambiente TELEGRAM_BOT_TOKEN.",
            file=sys.stderr,
        )
        raise SystemExit(1)

    app = costruisci_applicazione(token)
    logger.info("Divide et viaggia: avviato, in ascolto...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
