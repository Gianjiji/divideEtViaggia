# 🚗 Divide et viaggia

Bot Telegram che calcola la ripartizione dei costi di un viaggio in auto fra
amici: carburante, pedaggi e usura dell'auto, con un conto chiaro per ogni
tratta e un messaggio già pronto da inoltrare al gruppo. Non serve sapere né i
km né quanto è costato il pieno: basta dire da dove si parte, dove si arriva e
quanto costa un litro oggi. E, per chi vuole fare le cose in grande, c'è la
**carta d'imbarco** del viaggio 🎫

Scritto in Python con [python-telegram-bot](https://python-telegram-bot.org/)
21.x (async/await).

---

## Come calcola le quote (Schema B)

L'usura si divide fra **tutti** i partecipanti, conducente compreso. Il
conducente però non la versa: la propria frazione la "assorbe" incassando meno
dai passeggeri.

| Variabile | Significato |
|---|---|
| `D` | distanza percorsa in km (per tratta) |
| `N` | partecipanti totali, conducente compreso |
| `B` | costo carburante (€) |
| `T` | costo pedaggi (€) |
| `c` | coefficiente di usura al km |

```
Usura totale     = c × D
Q_usura          = (c × D) / N        ← divisa per N, conducente incluso
Q_viaggio        = (B + T) / N
Quota PASSEGGERO = Q_usura + Q_viaggio
Quota CONDUCENTE = Q_viaggio
Usura incassata dal conducente = Q_usura × (N − 1)
```

**Valori di default per categoria**

| Categoria | Tipologia | usura `c` | consumo |
|---|---|---|---|
| 🚗 Piccola | city car, utilitaria | 0,05 €/km | 5,5 l/100 km |
| 🚙 Media | berlina, SUV compatto | 0,10 €/km | 7,0 l/100 km |
| 🚐 Grande | SUV, monovolume, premium | 0,15 €/km | 9,0 l/100 km |

Il consumo serve solo a stimare il carburante; entrambi si modificano con
`/coefficienti`.

**Esclusi dal calcolo:** assicurazione, bollo, parcheggi, multe, manutenzione
straordinaria.

### Esempio

Viaggio A/R di 480 km per tratta, auto media (0,10 €/km), carburante + pedaggi
106,75 € a tratta, 3 persone all'andata e 4 al ritorno:

| | Andata (N=3) | Ritorno (N=4) |
|---|---|---|
| Q_usura | 16,00 € | 12,00 € |
| Q_viaggio | 35,58 € | 26,69 € |
| **Passeggero** | **51,58 €** | **38,69 €** |
| **Conducente** | **35,58 €** | **26,69 €** |
| Usura incassata dal conducente | 32,00 € | 36,00 € |

Chi c'era su entrambe le tratte versa 90,27 €.

---

## Creare il bot con BotFather

1. Su Telegram apri una chat con [@BotFather](https://t.me/BotFather).
2. Manda `/newbot`.
3. Scegli un **nome** visualizzato (es. `Divide et viaggia`).
4. Scegli uno **username**, che deve finire in `bot` (es. `divide_et_viaggia_bot`).
5. BotFather risponde con il **token**, una stringa tipo
   `123456789:AAH...`. Tienilo riservato: chi ha il token controlla il bot.

Opzionale, ma consigliato — sempre da BotFather:

- `/setdescription` → descrizione del bot;
- `/setcommands` → incolla questo elenco, così i comandi compaiono nel menù:

```
start - Avvia Divide et viaggia
nuovo - Nuovo calcolo
cartaimbarco - Stampa la carta d'imbarco del viaggio
coefficienti - Mostra e modifica i coefficienti di usura
reset_coefficienti - Riporta i coefficienti ai default
annulla - Annulla la conversazione in corso
help - Guida e formule
```

---

## Installazione

Serve Python 3.10 o successivo.

```bash
# 1. Dipendenze, in un ambiente virtuale
python3 -m venv .venv
source .venv/bin/activate          # su Windows: .venv\Scripts\activate
pip install -r requirements.txt

# 2. Token
cp .env.example .env
# apri .env e incolla il token ricevuto da BotFather

# 3. Avvio
python bot.py
```

All'avvio vedrai `Divide et viaggia: avviato, in ascolto...`: da quel momento il bot
risponde su Telegram. Si ferma con `Ctrl+C`.

### Configurazione

| Variabile d'ambiente | Obbligatoria | Default | A cosa serve |
|---|---|---|---|
| `TELEGRAM_BOT_TOKEN` | sì | — | Token fornito da BotFather |
| `ORS_API_KEY` | no | — | Chiave OpenRouteService per il calcolo dei km |
| `COEFFICIENTI_PATH` | no | `./dati/coefficienti.json` | File dei coefficienti personalizzati |

Le variabili si possono mettere nel file `.env` (letto con `python-dotenv`)
oppure esportare nell'ambiente.

---

## Uso

1. `/start` → il bot ti dà il benvenuto e chiede se il viaggio è a **tratta
   singola** o **andata e ritorno**.
2. Scegli la **categoria dell'auto** con i tre bottoni: da lì vengono usura e
   consumo.
3. Dici **quanto costa un litro** oggi. Da questo e dai km il bot stima la
   spesa di carburante. Se invece lo sai già, c'è il bottone «💶 So quanto ho
   speso»; se l'avevi già inserito, c'è «↩️ Come l'ultima volta».
4. Per ogni tratta il bot chiede **da dove si parte e dove si arriva**,
   calcola i km del percorso stradale e te li fa confermare; poi il numero di
   partecipanti (può cambiare fra andata e ritorno) e i pedaggi. Per il ritorno
   c'è il bottone «Come l'andata», e in qualunque momento puoi scegliere
   «Inserisco i km a mano».
5. Per l'andata e ritorno puoi dare i pedaggi tratta per tratta oppure come
   **totale A/R**, che il bot divide a metà.
6. Ricevi il conto: quanto paga ogni persona, conducente compreso. Per ogni
   tratta la quota del passeggero e quella del conducente, e in fondo il
   totale per chi c'era su entrambe le tratte, su una sola, e per chi guidava.
7. Il bot ti chiede se vuoi il **messaggio pronto da inoltrare** ai
   partecipanti: se rispondi sì, te lo manda in un messaggio a parte, pronto da
   girare al gruppo.

Il messaggio finale indica come destinatario delle quote il tuo nome Telegram:
il bot dà per scontato che a fare il conto sia chi ha guidato.

### 🗺 Come calcola i km

Basta scrivere le località (`Bologna`, `Via Roma 12, Torino`, `Milano
Centrale`): il bot le geocodifica, calcola il percorso stradale in auto e
mostra distanza e tempo di guida stimato prima di usarli.

Due backend, scelti automaticamente:

| Backend | Quando | Chiave | Limiti |
|---|---|---|---|
| **Nominatim + OSRM** | default | nessuna | Demo server pubblici di OpenStreetMap: 1 richiesta/s su Nominatim, nessuna garanzia di servizio |
| **OpenRouteService** | se c'è `ORS_API_KEY` | gratuita, senza carta di credito | ~2.000 richieste/giorno, 40/min |

Per la chiave ORS: registrati su [account.heigit.org](https://account.heigit.org),
crea un token e mettilo nel `.env`. Non è obbligatorio — senza, il bot funziona
lo stesso — ma se il bot lo usano in tanti conviene, perché il server demo di
OSRM non è pensato per il traffico continuativo.

Il bot rispetta la usage policy di Nominatim: User-Agent identificativo, al
massimo una richiesta al secondo, e le località già cercate restano in cache.

Se le mappe non rispondono o la località non viene trovata, il bot non si
blocca: passa alla richiesta dei km a mano.

### ⛽ Come stima il carburante

```
litri = D / 100 × consumo
B     = litri × prezzo al litro
```

Il consumo viene dalla categoria dell'auto (vedi tabella sopra), il prezzo al
litro lo chiede il bot a ogni calcolo — è l'unico dato che cambia di giorno in
giorno — e viene **ricordato per la prossima volta**, offerto con un bottone.

La stima è dichiarata come tale: il conto mostra `Carburante (stima)`, il
calcolo per esteso e i litri totali. Se la tua auto beve diversamente, cambia
il consumo con `/coefficienti`; se hai lo scontrino del pieno, scegli «💶 So
quanto ho speso» e il bot chiede la spesa reale come prima.

**Cosa resta manuale:** i **pedaggi**. Le API di routing gratuite danno
distanza e tempo, non il costo dei caselli — quello è esattamente il servizio
che vendono ViaMichelin e TollGuru.

### 🧾 Il conto

Il conto risponde a una domanda sola: **quanto paga ciascuno**. Per ogni tratta
la quota del passeggero e quella del conducente, poi il totale per chi c'era su
entrambe le tratte, su una sola, e per chi guidava. In coda una riga con la
spesa complessiva e due note: come è composta la quota e, se il carburante è
stimato, con quali valori.

L'usura compare nel conto (è per chi organizza), **non** nel messaggio ai
partecipanti né sulla carta d'imbarco: lì si vede solo la cifra da versare.

### 🎫 Carta d'imbarco

Dopo aver fatto un conto, `/cartaimbarco` stampa un biglietto in stile
compagnia aerea, da inoltrare al viaggiatore. Il bot chiede il **nome del
viaggiatore**, l'**orario di imbarco** e l'**indirizzo o luogo di ritrovo**,
poi ti fa scegliere di chi è la carta (passeggero A+R, passeggero di una sola
tratta, oppure il conducente) e compone il biglietto con la quota dovuta:

```
/================================\
| DIVIDE ET VIAGGIA        CARTA |
|                      D'IMBARCO |
+--------------------------------+
| PASSEGGERO                     |
| MARIO ROSSI                    |
|                                |
| TRATTA        ANDATA E RITORNO |
| DA                     BOLOGNA |
| A                       NAPOLI |
| IMBARCO ORE              07:30 |
| GATE               VIA ROMA 12 |
| A BORDO              3 PERSONE |
| VEICOLO             AUTO MEDIA |
| POSTO                       2B |
+--------------------------------+
| QUOTA DOVUTA           88,82 € |
+--------------------------------+
|   | | ||| | | | | | | | |||    |
| VG7K2Q            BUON VIAGGIO |
\================================/
```

Codice di prenotazione e posto sono ovviamente di fantasia.
L'orario si può scrivere come viene: `07:30`, `7.30`, `0730`, `19h45`.
La carta si appoggia all'**ultimo conto calcolato** in quella chat, quindi puoi
stamparne una per ogni partecipante senza rifare il calcolo.

### Comandi

| Comando | Cosa fa |
|---|---|
| `/start` | Benvenuto e avvio guidato |
| `/nuovo` | Inizia un nuovo calcolo |
| `/cartaimbarco` (o `/imbarco`) | Stampa la carta d'imbarco del viaggio 🎫 |
| `/coefficienti` | Mostra i coefficienti correnti e permette di modificarli |
| `/reset_coefficienti` | Riporta i coefficienti ai valori di default |
| `/annulla` | Esce dalla conversazione in corso |
| `/help` | Guida, comandi e formule |

### Coefficienti personalizzati

Con `/coefficienti` scegli la categoria, poi se modificare l'**usura** (€/km)
o il **consumo** (l/100 km), e inserisci il nuovo valore (va bene sia `0,12`
sia `0.12`). I valori vengono salvati su file JSON **per chat**, quindi
sopravvivono al riavvio del bot e non interferiscono con le altre
conversazioni. `/reset_coefficienti` cancella le personalizzazioni della chat
corrente, ultimo prezzo del carburante compreso.

Il file dati tiene anche l'ultimo prezzo al litro usato:

```json
{
  "123456789": {
    "categorie": {"media": {"usura": 0.12, "consumo": 7.5}},
    "prezzo_litro": 1.789
  }
}
```

I file scritti dalle versioni precedenti (`{"media": 0.12}`) vengono ancora
letti e migrati alla prima modifica.

### Input numerici

Tutti i numeri accettano la virgola decimale all'italiana e il punto come
separatore delle migliaia: `35,58`, `35.58`, `1.234,56`, `480 km`, `85,00 €`.
Valori negativi, non numerici o fuori scala vengono rifiutati con un messaggio
gentile e la richiesta di reinserire. Il numero minimo di partecipanti è 2.

---

## Struttura del progetto

```
calcolaCosti/
├── bot.py               # handler Telegram e ConversationHandler
├── calcolo.py           # logica pura di calcolo, parsing e validazione
├── percorso.py          # geocoding e distanze stradali (OSM / OpenRouteService)
├── storage.py           # persistenza JSON delle preferenze, per chat_id
├── messaggi.py          # testi del bot e formattazione in stile italiano
├── requirements.txt
├── requirements-dev.txt # requirements + pytest
├── .env.example
├── pytest.ini
├── dati/                # file JSON dei coefficienti (creato all'occorrenza)
└── tests/
    ├── test_calcolo.py
    ├── test_messaggi.py
    ├── test_percorso.py
    └── test_storage.py
```

`calcolo.py` non importa nulla di Telegram: è logica pura e interamente
testabile a riga di comando.

---

## Test

```bash
pip install -r requirements-dev.txt
pytest
```

La suite copre il caso di verifica dello Schema B (480 km, N=3 e N=4,
c=0,10 €/km, B+T=106,75 €), la stima del carburante, la quadratura fra quote
raccolte e costi, il
parsing dei numeri in formato italiano, la persistenza dei coefficienti, la
formattazione dei testi e il parsing delle risposte dei servizi di mappe.
La suite non fa chiamate di rete: usa risposte reali salvate nei test.

---

## Note

- Il bot funziona in **polling**: non serve un server pubblico né HTTPS, basta
  che il processo resti in esecuzione.
- I dati di un calcolo vivono in memoria per la durata della conversazione; su
  disco finiscono solo i coefficienti personalizzati.
- Gli importi mostrati sono arrotondati a 2 decimali: quando l'arrotondamento
  lascia uno scarto di qualche centesimo rispetto a `B + T`, il conto lo
  segnala esplicitamente nella riga di verifica.
