"""I flussi di conversazione, provati sull'applicazione vera.

Ogni test recita una chat dall'inizio: comandi, bottoni, risposte scritte. Le
cifre attese sono calcolate a mano nei commenti, non chieste a ``calcolo.py``:
altrimenti un errore nel calcolo passerebbe indisturbato.
"""
import json

import pytest

from conftest import CHAT, Conversazione

OPS = "qualcosa e' andato storto"       # il messaggio del gestore di errori


async def fino_al_conto(chat, *, km="120", persone="3", carburante="20", pedaggi="15"):
    """Tratta singola, auto media, carburante noto, km scritti a mano."""
    await chat.scrive("/nuovo")
    await chat.preme("tipo:singola")
    await chat.preme("cat:media")
    await chat.preme("carb:noto")
    await chat.preme("km:manuale")
    for risposta in (km, persone, carburante, pedaggi):
        await chat.scrive(risposta)
    return chat


async def fino_alla_carta(chat, **conto):
    """Conto fatto e chiuso: la carta d'imbarco si chiede a calcolo terminato."""
    await fino_al_conto(chat, **conto)
    await chat.preme("msg:no")
    return chat


# --- il percorso principale -------------------------------------------------
async def test_tratta_singola_con_carburante_noto(chat):
    await fino_al_conto(chat)
    conto = chat.testo()
    # usura: 120 km x 0,10 = 12,00 -> 4,00 a testa
    # viaggio: (20 + 15) / 3 = 11,67 a testa
    # passeggero = 11,67 + 4,00 = 15,67; conducente = 11,67
    assert "il conto" in conto
    assert "120 km · 3 persone" in conto
    assert "Passeggero              15,67 €" in conto
    assert "Conducente              11,67 €" in conto
    assert "20,00 € di carburante + 15,00 € di pedaggi" in conto
    assert chat.bottoni() == ["msg:si", "msg:no"]
    assert chat.errori_di_formato() == []


async def test_carburante_stimato_dal_prezzo_al_litro(chat):
    await chat.scrive("/nuovo")
    await chat.preme("tipo:singola")
    await chat.preme("cat:media")
    await chat.scrive("1,80")                 # €/l: il consumo dell'auto media e' 7,0 l/100 km
    assert "1,80 €/l" in chat.testo()
    await chat.preme("km:manuale")
    await chat.scrive("120")
    await chat.scrive("3")
    await chat.scrive("15")                   # con il carburante stimato si chiedono solo i pedaggi
    conto = chat.testo()
    # carburante: 120 / 100 x 7,0 x 1,80 = 15,12; viaggio: (15,12 + 15) / 3 = 10,04
    # passeggero = 10,04 + 4,00 = 14,04; conducente = 10,04
    assert "Passeggero              14,04 €" in conto
    assert "Conducente              10,04 €" in conto
    assert "15,12 €" in conto


async def test_andata_e_ritorno_tratta_per_tratta(chat):
    await chat.scrive("/nuovo")
    await chat.preme("tipo:ar")
    await chat.preme("cat:media")
    await chat.preme("carb:noto")
    assert chat.bottoni() == ["modo:per_tratta", "modo:meta"]
    await chat.preme("modo:per_tratta")
    await chat.preme("km:manuale")
    for risposta in ("100", "3", "20", "10"):          # andata
        await chat.scrive(risposta)
    assert "Ritorno" in chat.testo()
    assert chat.bottoni() == ["km:come_andata", "km:manuale"]
    await chat.preme("km:come_andata")
    assert "100 km" in chat.testo()
    for risposta in ("2", "18", "9"):                  # ritorno, in due
        await chat.scrive(risposta)
    conto = chat.testo()
    assert "ANDATA" in conto and "RITORNO" in conto
    assert "100 km · 3 persone" in conto and "100 km · 2 persone" in conto
    # andata:  usura 10,00 -> 3,33; viaggio 30 / 3 = 10,00 -> passeggero 13,33
    # ritorno: usura 10,00 -> 5,00; viaggio 27 / 2 = 13,50 -> passeggero 18,50
    assert "13,33 €" in conto and "18,50 €" in conto
    assert chat.errori_di_formato() == []


async def test_messaggio_per_il_gruppo(chat):
    await fino_al_conto(chat)
    await chat.preme("msg:si")
    testo = chat.testo()
    assert "Quote da versare a Ada" in testo
    assert "Ogni passeggero: *15,67 €*" in testo


async def test_si_puo_rifiutare_il_messaggio_per_il_gruppo(chat):
    await fino_al_conto(chat)
    await chat.preme("msg:no")
    assert OPS not in chat.testo()
    await chat.scrive("ciao")                 # conversazione finita: nessuna risposta, nessun errore
    assert chat.messaggi() == []


# --- risposte sbagliate: si resta sulla stessa domanda ----------------------
@pytest.mark.parametrize("sbagliata", ["abc", "-5", "0", "", "1e3", "1_000", "١٢٣", "1.234"])
async def test_distanza_non_valida_viene_richiesta_di_nuovo(chat, sbagliata):
    await chat.scrive("/nuovo")
    await chat.preme("tipo:singola")
    await chat.preme("cat:media")
    await chat.preme("carb:noto")
    await chat.preme("km:manuale")
    if sbagliata:
        await chat.scrive(sbagliata)
        assert chat.testo(), "una risposta sbagliata merita una spiegazione"
        assert OPS not in chat.testo()
    await chat.scrive("120")                  # la domanda e' ancora quella dei km
    assert "persone" in chat.testo()


@pytest.mark.parametrize("sbagliata", ["1", "0", "uno", "2,5", "-3", "1000"])
async def test_partecipanti_non_validi(chat, sbagliata):
    await chat.scrive("/nuovo")
    await chat.preme("tipo:singola")
    await chat.preme("cat:media")
    await chat.preme("carb:noto")
    await chat.preme("km:manuale")
    await chat.scrive("120")
    await chat.scrive(sbagliata)
    assert OPS not in chat.testo()
    await chat.scrive("3")
    assert "carburante" in chat.testo()


async def test_importo_ambiguo_non_viene_indovinato(chat):
    """«1.234» e' milleduecento euro o uno virgola due? Si chiede, non si sceglie."""
    await chat.scrive("/nuovo")
    await chat.preme("tipo:singola")
    await chat.preme("cat:media")
    await chat.preme("carb:noto")
    await chat.preme("km:manuale")
    await chat.scrive("120")
    await chat.scrive("3")
    await chat.scrive("1.234")
    risposta = chat.testo()
    assert "due modi" in risposta and "1234" in risposta and "1,234" in risposta
    await chat.scrive("20")                   # ancora la domanda sul carburante
    assert "pedaggi" in chat.testo()


async def test_testo_al_posto_dei_bottoni(chat):
    await chat.scrive("/nuovo")
    await chat.scrive("andata e ritorno")
    assert chat.testo() and OPS not in chat.testo()
    await chat.preme("tipo:ar")               # la scelta e' ancora aperta
    assert "auto" in chat.testo()


# --- interruzioni -----------------------------------------------------------
async def test_annulla_a_meta(chat):
    await chat.scrive("/nuovo")
    await chat.preme("tipo:singola")
    await chat.scrive("/annulla")
    assert chat.testo() and OPS not in chat.testo()
    await chat.scrive("120")
    assert chat.messaggi() == []              # nessuna conversazione aperta


async def test_nuovo_a_meta_ricomincia_da_capo(chat):
    await fino_al_conto(chat, km="999")
    await chat.scrive("/nuovo")
    assert chat.bottoni() == ["tipo:singola", "tipo:ar"]
    await chat.preme("tipo:singola")
    await chat.preme("cat:media")
    await chat.preme("carb:noto")
    await chat.preme("km:manuale")
    for risposta in ("120", "3", "20", "15"):
        await chat.scrive(risposta)
    assert "120 km" in chat.testo() and "999" not in chat.testo()


async def test_altri_comandi_durante_il_calcolo(chat):
    await chat.scrive("/nuovo")
    for comando in ("/coefficienti", "/cartaimbarco", "/reset_coefficienti"):
        await chat.scrive(comando)
        assert chat.testo() and OPS not in chat.testo()
    await chat.preme("tipo:singola")          # il calcolo e' ancora li'
    assert "auto" in chat.testo()


@pytest.mark.parametrize("dato", [
    "tipo:xyz", "cat:enorme", "imb:t99", "msg:forse", "dist:ok", "coef:media", "x" * 60,
    "cat:media;drop", "TIPO:SINGOLA", " tipo:singola",
])
async def test_bottone_forgiato_o_scaduto_non_fa_danni(chat, dato):
    await chat.scrive("/nuovo")
    await chat.preme_comunque(dato)
    assert OPS not in chat.testo()
    await chat.preme("tipo:singola")
    assert "auto" in chat.testo()


async def test_bottone_di_una_chat_chiusa(chat):
    await chat.preme_comunque("msg:si")       # nessun conto aperto
    assert OPS not in chat.testo()


# --- carta d'imbarco --------------------------------------------------------
async def test_carta_d_imbarco_senza_conto(chat):
    await chat.scrive("/cartaimbarco")
    assert "/nuovo" in chat.testo()


async def test_carta_d_imbarco_a_calcolo_ancora_aperto(chat):
    """Finché non si risponde alla domanda sul messaggio, il calcolo è in corso."""
    await fino_al_conto(chat)
    await chat.scrive("/cartaimbarco")
    assert chat.testo() and OPS not in chat.testo()
    assert chat.bottoni() == ["msg:si", "msg:no"]          # la domanda resta quella


async def test_carta_d_imbarco(chat):
    await fino_alla_carta(chat)
    await chat.scrive("/cartaimbarco")
    await chat.scrive("Mario Rossi")
    await chat.scrive("8:30")
    await chat.scrive("Via Roma 12")
    assert chat.bottoni() == ["imb:tutto", "imb:conducente"]
    await chat.preme("imb:tutto")
    carta = chat.testo()
    assert "MARIO ROSSI" in carta and "08:30" in carta and "VIA ROMA 12" in carta
    assert "QUOTA DOVUTA           15,67 €" in carta
    assert carta.count("```") == 2


async def test_carta_d_imbarco_del_conducente(chat):
    await fino_alla_carta(chat)
    for risposta in ("/cartaimbarco", "Ada", "7.15", "Bar della stazione"):
        await chat.scrive(risposta)
    await chat.preme("imb:conducente")
    carta = chat.testo()
    assert "COMANDANTE" in carta and "11,67 €" in carta and "07:15" in carta


@pytest.mark.parametrize("nome, indirizzo", [
    ("Ma`rio ```x", "Via Roma 12"),
    ("Mario", "Via `Roma` 12\nscala B"),
    ("```", "```"),
    ("*Mario* _Rossi_ [x](y)", "Piazza_del_Popolo *1*"),
])
async def test_carta_con_caratteri_del_markdown(chat, nome, indirizzo):
    """Un backtick nel nome chiudeva il blocco di codice: Telegram rifiutava la carta."""
    await fino_alla_carta(chat)
    for risposta in ("/cartaimbarco", nome, "8:30", indirizzo):
        await chat.scrive(risposta)
        assert OPS not in chat.testo()
    await chat.preme("imb:tutto")
    carta = chat.testo()
    assert carta.count("```") == 2, carta
    dentro = carta.split("```")[1]
    assert "`" not in dentro
    righe = [r for r in dentro.strip().splitlines()]
    assert len({len(r) for r in righe}) == 1, "la cornice deve restare allineata"


@pytest.mark.parametrize("orario", ["25:00", "ore otto", "8:75", ""])
async def test_orario_d_imbarco_non_valido(chat, orario):
    await fino_alla_carta(chat)
    await chat.scrive("/cartaimbarco")
    await chat.scrive("Mario")
    if orario:
        await chat.scrive(orario)
        assert OPS not in chat.testo()
    await chat.scrive("8:30")
    assert "indirizzo" in chat.testo().lower()


# --- coefficienti -----------------------------------------------------------
async def test_modifica_di_un_coefficiente_e_suo_effetto(chat, archivio_pulito):
    await chat.scrive("/coefficienti")
    await chat.preme("coef:media")
    await chat.preme("tipo_coef:usura")
    await chat.scrive("0,20")
    assert "0,20 €/km" in chat.testo()
    salvati = json.loads(archivio_pulito.percorso.read_text(encoding="utf-8"))
    assert str(CHAT) in json.dumps(salvati)

    await fino_al_conto(chat)
    conto = chat.testo()
    # usura: 120 x 0,20 = 24,00 -> 8,00 a testa; passeggero = 11,67 + 8,00 = 19,67
    assert "usura 0,20 €/km" in conto
    assert "Passeggero              19,67 €" in conto


@pytest.mark.parametrize("sbagliato", ["abc", "-1", "0", "1e3"])
async def test_coefficiente_non_valido(chat, sbagliato):
    await chat.scrive("/coefficienti")
    await chat.preme("coef:media")
    await chat.preme("tipo_coef:usura")
    await chat.scrive(sbagliato)
    assert "Salvato" not in chat.testo() and OPS not in chat.testo()
    await chat.scrive("0,12")
    assert "Salvato" in chat.testo()


async def test_reset_dei_coefficienti(chat):
    await chat.scrive("/coefficienti")
    await chat.preme("coef:media")
    await chat.preme("tipo_coef:usura")
    await chat.scrive("0,20")
    await chat.scrive("/reset_coefficienti")
    assert "default" in chat.testo()
    await fino_al_conto(chat)
    assert "usura 0,10 €/km" in chat.testo()


# --- piu' chat insieme ------------------------------------------------------
async def test_due_chat_non_si_mescolano(chat):
    altra = Conversazione(chat.app, chat.rete, chat=CHAT + 1)
    await chat.scrive("/nuovo")
    await altra.scrive("/nuovo")
    await chat.preme("tipo:singola")
    await altra.preme_comunque("tipo:ar")
    await chat.preme_comunque("cat:media")
    await altra.preme_comunque("cat:grande")
    await chat.preme_comunque("carb:noto")
    assert "Tratta unica" in chat.testo()
    await altra.preme_comunque("carb:noto")
    assert "modo:per_tratta" in altra.bottoni()      # l'altra e' un'andata e ritorno


async def test_il_coefficiente_di_una_chat_non_vale_per_l_altra(chat):
    await chat.scrive("/coefficienti")
    await chat.preme("coef:media")
    await chat.preme("tipo_coef:usura")
    await chat.scrive("0,20")
    altra = Conversazione(chat.app, chat.rete, chat=CHAT + 1)
    await altra.scrive("/nuovo")
    await altra.preme_comunque("tipo:singola")
    await altra.preme_comunque("cat:media")
    assert "usura *0,10 €/km*" in altra.testo()


# --- comandi semplici -------------------------------------------------------
async def test_help_e_start(chat):
    await chat.scrive("/help")
    assert "/nuovo" in chat.testo()
    await chat.scrive("/start")
    assert chat.testo() and OPS not in chat.testo()


async def test_nessun_messaggio_ha_markdown_spaiato_lungo_tutto_il_percorso(chat):
    await fino_al_conto(chat)
    await chat.preme("msg:si")
    for risposta in ("/cartaimbarco", "Mario", "8:30", "Via Roma 12"):
        await chat.scrive(risposta)
    await chat.preme("imb:tutto")
    inviati = [p for m, p in chat.rete.chiamate if m in ("sendMessage", "editMessageText")]
    assert len(inviati) > 12
    for parametri in inviati:
        if str(parametri.get("parse_mode", "")).lower() == "markdown":
            testo = str(parametri["text"])
            assert testo.count("```") % 2 == 0, testo
            assert testo.replace("```", "").count("`") % 2 == 0, testo
