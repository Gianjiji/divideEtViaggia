"""Banco di prova per il bot: Telegram finto, applicazione vera.

I test dei flussi non chiamano le singole funzioni di ``bot.py`` con oggetti
simulati a mano: montano l'applicazione reale (gli stessi ConversationHandler
di produzione) e le consegnano aggiornamenti come farebbe Telegram. Al posto
della rete c'e' ``TelegramFinto``, che registra ogni chiamata all'API e risponde
con dati plausibili. Cosi' si prova anche cio' che sta fra le funzioni: gli
stati, i pattern dei bottoni, i fallback.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

RADICE = Path(__file__).resolve().parent.parent
if str(RADICE) not in sys.path:
    sys.path.insert(0, str(RADICE))

# Il modulo storage sceglie il file dei coefficienti all'import: lo si punta a
# una cartella usa-e-getta prima che qualunque test importi bot.py.
import tempfile  # noqa: E402

os.environ.setdefault(
    "COEFFICIENTI_PATH", str(Path(tempfile.mkdtemp(prefix="dv-test-")) / "coefficienti.json")
)

from telegram import Update  # noqa: E402
from telegram.ext import Application  # noqa: E402
from telegram.request import BaseRequest  # noqa: E402

CHAT = 4242
UTENTE = {"id": CHAT, "is_bot": False, "first_name": "Ada"}


class TelegramFinto(BaseRequest):
    """Sostituto della rete: registra le chiamate, non contatta nessuno."""

    def __init__(self) -> None:
        self.chiamate: list[tuple[str, dict]] = []
        self._prossimo_id = 1000

    async def initialize(self) -> None:
        pass

    async def shutdown(self) -> None:
        pass

    @property
    def read_timeout(self):
        return 1.0

    async def do_request(self, url, method, request_data=None, *args, **kwargs):
        metodo = url.rsplit("/", 1)[-1]
        parametri = dict(request_data.parameters) if request_data else {}
        self.chiamate.append((metodo, parametri))
        if metodo == "getMe":
            risultato = {"id": 1, "is_bot": True, "first_name": "Divide", "username": "divide_bot"}
        elif metodo in ("sendMessage", "editMessageText", "editMessageReplyMarkup"):
            self._prossimo_id += 1
            risultato = {
                "message_id": self._prossimo_id, "date": 0,
                "chat": {"id": parametri.get("chat_id", CHAT), "type": "private"},
                "text": parametri.get("text", ""),
            }
        else:
            risultato = True
        return 200, json.dumps({"ok": True, "result": risultato}).encode()


class Conversazione:
    """Una chat con il bot, dal punto di vista dell'utente."""

    def __init__(self, app: Application, rete: TelegramFinto, chat: int = CHAT) -> None:
        self.app, self.rete, self.chat = app, rete, chat
        self._update_id = 0
        self._message_id = 0

    # -- cio' che l'utente fa -------------------------------------------------
    async def scrive(self, testo: str) -> "Conversazione":
        self._update_id += 1
        self._message_id += 1
        messaggio = {
            "message_id": self._message_id,
            "date": int(datetime.now(timezone.utc).timestamp()),
            "chat": {"id": self.chat, "type": "private"},
            "from": {**UTENTE, "id": self.chat},
            "text": testo,
        }
        if testo.startswith("/"):
            comando = testo.split()[0]
            messaggio["entities"] = [{"type": "bot_command", "offset": 0, "length": len(comando)}]
        await self._consegna({"update_id": self._update_id, "message": messaggio})
        return self

    async def preme(self, dato: str) -> "Conversazione":
        """Preme un bottone. Fallisce se quel bottone non e' fra quelli offerti."""
        assert dato in self.bottoni(), f"bottone {dato!r} non offerto: {self.bottoni()}"
        await self.preme_comunque(dato)
        return self

    async def preme_comunque(self, dato: str) -> "Conversazione":
        """Come ``preme`` ma senza controllare: per i callback forgiati o scaduti."""
        self._update_id += 1
        await self._consegna({
            "update_id": self._update_id,
            "callback_query": {
                "id": str(self._update_id), "chat_instance": "x", "data": dato,
                "from": {**UTENTE, "id": self.chat},
                "message": {"message_id": 999, "date": 0, "text": "…",
                            "chat": {"id": self.chat, "type": "private"}},
            },
        })
        return self

    async def _consegna(self, grezzo: dict) -> None:
        self._inizio = len(self.rete.chiamate)
        await self.app.process_update(Update.de_json(grezzo, self.app.bot))

    # -- cio' che l'utente vede ----------------------------------------------
    def _recenti(self) -> list[tuple[str, dict]]:
        return self.rete.chiamate[getattr(self, "_inizio", 0):]

    def messaggi(self) -> list[dict]:
        """I messaggi inviati o modificati dal bot dopo l'ultima azione."""
        return [p for m, p in self._recenti() if m in ("sendMessage", "editMessageText")]

    def testo(self) -> str:
        return "\n".join(str(p.get("text", "")) for p in self.messaggi())

    def bottoni(self) -> list[str]:
        """I callback_data offerti nell'ultimo messaggio con bottoni (di sempre)."""
        for metodo, parametri in reversed(self.rete.chiamate):
            if metodo in ("sendMessage", "editMessageText") and parametri.get("reply_markup"):
                markup = parametri["reply_markup"]
                markup = json.loads(markup) if isinstance(markup, str) else markup
                return [b["callback_data"] for riga in markup.get("inline_keyboard", [])
                        for b in riga if "callback_data" in b]
        return []

    def errori_di_formato(self) -> list[str]:
        """Messaggi in Markdown con delimitatori spaiati: Telegram li rifiuterebbe."""
        difetti = []
        for parametri in self.messaggi():
            if str(parametri.get("parse_mode", "")).lower() != "markdown":
                continue
            testo = str(parametri.get("text", ""))
            if testo.count("```") % 2:
                difetti.append(testo)
        return difetti


@pytest.fixture
def archivio_pulito(tmp_path, monkeypatch):
    """Coefficienti su file temporaneo: nessun test tocca ``dati/``."""
    import storage
    monkeypatch.setattr(storage.archivio, "percorso", tmp_path / "coefficienti.json")
    return storage.archivio


@pytest.fixture
async def chat(archivio_pulito):
    import bot

    rete = TelegramFinto()
    builder = Application.builder().request(rete).get_updates_request(TelegramFinto())
    app = bot.costruisci_applicazione("123456:TOKEN-DI-PROVA", builder=builder)
    await app.initialize()
    try:
        yield Conversazione(app, rete)
    finally:
        await app.shutdown()
