#!/bin/sh
# Installa "Divide et viaggia" come servizio systemd.
#
# Va lanciato come root dalla cartella del progetto:
#     sh deploy/install.sh
#
# Prepara l'ambiente virtuale, installa le dipendenze, registra il servizio
# e lo avvia. Rilanciarlo e' sicuro: aggiorna quello che c'e' gia'.

set -eu

NOME_SERVIZIO=divideetviaggia
UNIT=/etc/systemd/system/${NOME_SERVIZIO}.service

if [ -t 1 ]; then
    BLU=$(printf '\033[1;34m'); VERDE=$(printf '\033[1;32m')
    ROSSO=$(printf '\033[1;31m'); FINE=$(printf '\033[0m')
else
    BLU=''; VERDE=''; ROSSO=''; FINE=''
fi

info()   { printf '%s==>%s %s\n' "$BLU" "$FINE" "$1"; }
ok()     { printf '%s  ok%s %s\n' "$VERDE" "$FINE" "$1"; }
errore() { printf '%sErrore:%s %s\n' "$ROSSO" "$FINE" "$1" >&2; exit 1; }

RICREA_VENV=0
for argomento in "$@"; do
    case "$argomento" in
        --ricrea-venv)
            RICREA_VENV=1
            ;;
        -h|--help)
            printf 'Uso: sh deploy/install.sh [--ricrea-venv]\n\n'
            printf '  --ricrea-venv  cancella e ricrea .venv da zero\n'
            exit 0
            ;;
        *)
            errore "opzione sconosciuta: $argomento"
            ;;
    esac
done

# --- Controlli preliminari ------------------------------------------------ #

[ "$(id -u)" -eq 0 ] || errore "serve root: rilancia con sudo"

DIR_SCRIPT=$(cd "$(dirname "$0")" && pwd)
DIR_PROGETTO=$(cd "$DIR_SCRIPT/.." && pwd)

for file in bot.py requirements.txt deploy/divideetviaggia.service; do
    [ -f "$DIR_PROGETTO/$file" ] || errore "manca $file in $DIR_PROGETTO"
done

command -v systemctl >/dev/null 2>&1 || errore "systemd non disponibile su questa macchina"
command -v python3 >/dev/null 2>&1 || errore "python3 non trovato"

info "Progetto: $DIR_PROGETTO"

# Su Debian/Ubuntu il modulo venv sta in un pacchetto a parte.
if ! python3 -c 'import ensurepip' >/dev/null 2>&1; then
    if command -v apt-get >/dev/null 2>&1; then
        info "Installo python3-venv (manca il modulo venv)"
        apt-get update -qq
        apt-get install -y python3-venv
    else
        errore "modulo venv assente: installa il pacchetto python3-venv (o equivalente)"
    fi
fi

# --- Token ---------------------------------------------------------------- #

if [ ! -f "$DIR_PROGETTO/.env" ]; then
    if [ -f "$DIR_PROGETTO/.env.example" ]; then
        cp "$DIR_PROGETTO/.env.example" "$DIR_PROGETTO/.env"
        chmod 600 "$DIR_PROGETTO/.env"
        errore "ho creato .env da .env.example: mettici il token di BotFather e rilancia"
    fi
    errore "manca il file .env con TELEGRAM_BOT_TOKEN"
fi

TOKEN=$(grep -E '^[[:space:]]*TELEGRAM_BOT_TOKEN[[:space:]]*=' "$DIR_PROGETTO/.env" \
        | head -n 1 | cut -d= -f2- | tr -d ' ')
case "$TOKEN" in
    "")
        errore "TELEGRAM_BOT_TOKEN vuoto o assente in .env"
        ;;
    123456789:*)
        errore "in .env c'e' ancora il token di esempio: sostituiscilo con il tuo"
        ;;
esac
ok "token trovato in .env"

# --- Servizio gia' attivo ------------------------------------------------- #

if systemctl is-active --quiet "$NOME_SERVIZIO" 2>/dev/null; then
    info "Fermo il servizio gia' in esecuzione"
    systemctl stop "$NOME_SERVIZIO"
fi

# --- Ambiente virtuale ----------------------------------------------------- #

PYTHON="$DIR_PROGETTO/.venv/bin/python"

# Un .venv copiato da un'altra macchina non esegue: in quel caso lo rifacciamo.
if [ "$RICREA_VENV" -eq 1 ] || [ ! -x "$PYTHON" ] || ! "$PYTHON" -c '' >/dev/null 2>&1; then
    info "Creo l'ambiente virtuale"
    rm -rf "$DIR_PROGETTO/.venv"
    python3 -m venv "$DIR_PROGETTO/.venv"
else
    info "Ambiente virtuale gia' presente"
fi

info "Installo le dipendenze"
"$DIR_PROGETTO/.venv/bin/pip" install --quiet --upgrade pip
"$DIR_PROGETTO/.venv/bin/pip" install --quiet -r "$DIR_PROGETTO/requirements.txt"
"$PYTHON" -c 'import telegram, dotenv, httpx' \
    || errore "le dipendenze non si importano: controlla l'output di pip"
ok "dipendenze a posto ($("$PYTHON" --version))"

# --- Cartelle e permessi --------------------------------------------------- #

mkdir -p "$DIR_PROGETTO/dati"
chmod 600 "$DIR_PROGETTO/.env"

# --- Unit systemd ---------------------------------------------------------- #

info "Installo $UNIT"
# La unit distribuita punta a /opt/divideEtViaggia: la riscriviamo sul percorso reale.
sed "s#/opt/divideEtViaggia#$DIR_PROGETTO#g" \
    "$DIR_PROGETTO/deploy/divideetviaggia.service" > "$UNIT"
chmod 644 "$UNIT"

# Se nella unit e' stato abilitato User=, i file devono appartenere a quell'utente.
UTENTE=$(grep -E '^User=' "$UNIT" | head -n 1 | cut -d= -f2- || true)
if [ -n "${UTENTE:-}" ]; then
    id "$UTENTE" >/dev/null 2>&1 \
        || errore "la unit usa User=$UTENTE ma quell'utente non esiste (status=217/USER)"
    info "Assegno i file a $UTENTE"
    chown -R "$UTENTE" "$DIR_PROGETTO"
fi

systemctl daemon-reload
systemctl enable --quiet "$NOME_SERVIZIO"
systemctl restart "$NOME_SERVIZIO"

# --- Verifica -------------------------------------------------------------- #

sleep 3
if systemctl is-active --quiet "$NOME_SERVIZIO"; then
    ok "servizio attivo e abilitato all'avvio della macchina"
else
    printf '\n'
    journalctl -u "$NOME_SERVIZIO" -n 20 --no-pager || true
    errore "il servizio non e' partito: vedi il log qui sopra"
fi

printf '\n%sFatto.%s Comandi utili:\n\n' "$VERDE" "$FINE"
printf '  systemctl status %s\n' "$NOME_SERVIZIO"
printf '  journalctl -u %s -f\n' "$NOME_SERVIZIO"
printf '  systemctl restart %s\n\n' "$NOME_SERVIZIO"
