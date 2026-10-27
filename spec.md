# Beancount MCP Server — Specifiche v0.1

Documento di partenza per l'implementazione · 25 ottobre 2026 · Destinatario: agente di sviluppo

## 1. Obiettivo e contesto

Realizzare un server MCP in Python che permetta a un LLM di **interrogare e modificare in sicurezza** un ledger Beancount. Il server non esegue alcun modello: espone solo tool. La priorità del progetto, in ordine, è:

1. **Non corrompere mai il ledger.** Ogni scrittura è atomica, validata e reversibile.
2. **Essere facile da usare per un LLM.** Pochi tool, descrizioni ricche, errori che spiegano come correggersi, risposte compatte.
3. **Essere testabile.** Il sistema di test è parte del prodotto, non un'aggiunta finale (vedi sezione 8).

Il server nasce specifico per Beancount. Il nucleo che gestisce scritture atomiche, versioni e validazione va però tenuto in moduli separati dalla logica contabile, in modo da poterlo estrarre in futuro come server generico per file.

## 2. Non-obiettivi (v0.1)

- Nessun supporto a backend remoti (SFTP, S3): il server gira sulla stessa macchina dei file, oppure su una copia sincronizzata (es. repository git).
- Nessuna importazione automatica di estratti conto (fase 2).
- Nessuna interfaccia web, nessuna autenticazione utente (trasporto stdio; HTTP è opzionale e fuori scopo per ora).
- Nessuna generazione automatica di direttive `pad`. Le `balance` assertion non vengono mai modificate dai tool di scrittura.
- Nessuna transazione multi-file: ogni operazione di scrittura tocca un solo file.
- Nessuna modifica ai file dell'utente per impostazione predefinita: i tool di scrittura toccano solo l'inbox. Modifica ed eliminazione di entry in altri file sono possibili solo se l'utente avvia il server con `--allow-edit-outside-inbox` (sezioni 5.4 e 9). Il comando `init` crea solo file nuovi e non sovrascrive mai file esistenti.

## 3. Stack e vincoli tecnici

- **Linguaggio:** Python, versione minima da fissare in `pyproject.toml` (proposta: 3.11 o superiore).
- **Librerie ufficiali:** `beancount`, `beanquery`, SDK MCP ufficiale per Python (`mcp`, con `FastMCP`).
- **Versioni:** prima di scrivere codice, verificare sulla documentazione attuale quale major di Beancount è raccomandata (v2 o v3, che hanno API diverse in alcuni punti, e in v3 beanquery è un pacchetto separato). Fissare le versioni esatte e annotare la scelta in `docs/decisions.md`. Le API citate in questo documento vanno verificate sulle versioni scelte.
- **Tooling:** `uv` per dipendenze e ambienti, `pytest`, `ruff`, `mypy` in modalità strict (o `pyright`), GitHub Actions per la CI.
- **Distribuzione:** pacchetto su PyPI, avviabile con `uvx beancount-mcp /percorso/main.beancount`.
- **Trasporto:** stdio di default.

## 4. Architettura

### 4.1 Struttura del repository

```
beancount-mcp/
  src/beancount_mcp/
    server.py        # FastMCP, registrazione dei tool
    config.py        # CLI e variabili d'ambiente
    ledger.py        # caricamento e versione del ledger
    entries.py       # identità delle direttive, estrazione dello span di testo
    validation.py    # confronto errori prima/dopo
    writer.py        # staging, lock, scrittura atomica
    queries.py       # esecuzione BQL e limiti
    errors.py        # tipi di errore e formato delle risposte
    tools/           # una funzione per tool, senza logica di dominio
  tests/
    fixtures/        # ledger di esempio
    unit/
    integration/
  docs/decisions.md
  pyproject.toml
```

### 4.2 Regole di separazione

- I moduli in `tools/` sono sottili: validano gli input, chiamano `ledger`, `writer`, `validation`, `queries` e formattano la risposta.
- `writer.py` e la parte di `validation.py` che gestisce staging e confronto non devono importare nulla di specifico di Beancount se non tramite un'interfaccia `Validator` (vedi 5.3). Questo è il punto di estrazione futuro del core generico.
- Nessuno stato globale mutabile fuori da un oggetto `LedgerService` istanziato dal server e passato ai tool, per poterlo sostituire nei test.

### 4.3 Versione del ledger

Il ledger viene caricato da disco a ogni richiesta, senza cache in memoria: ogni risposta riflette sempre lo stato attuale dei file. La **versione del ledger** è l'hash SHA-256 calcolato sulla concatenazione ordinata (percorso, hash del contenuto) di tutti i file coinvolti nel caricamento (file principale più include). Una cache del ledger caricato è un'ottimizzazione rimandata a dopo la v0.1, da introdurre solo se i tempi di caricamento lo richiedono.

## 5. Modello di scrittura e sicurezza

### 5.1 Principi

- Si scrive solo dopo aver validato. Una scrittura rifiutata non lascia alcuna traccia sul disco.
- Le scritture avvengono con file temporaneo nella stessa directory, `fsync` e `os.replace`, così il file è sempre nella versione vecchia o in quella nuova, mai a metà.
- Un **lock** esclusivo (file di lock accanto al ledger) serializza le scritture, anche tra processi diversi.
- Un ledger il cui stato non coincide con `expected_ledger_version`, quando fornita, produce un errore di conflitto e nessuna scrittura.

### 5.2 File inbox

L'inbox (di default `inbox.bean`, accanto al file principale) è l'unico file in cui il server scrive: ci finiscono le entry aggiunte dall'LLM, comprese le direttive `open` create con `open_account`. Per impostazione predefinita il server non crea né modifica file dell'utente (l'unica eccezione, da abilitare esplicitamente, è descritta in 5.4). Per un ledger esistente è l'utente a creare l'inbox e ad aggiungere al proprio file principale la riga `include "inbox.bean"`. Per un ledger nuovo ci pensa il comando `init` (sezione 9). Se l'inbox non esiste o non è inclusa, `ledger_info` lo segnala come avviso e i tool di scrittura rifiutano con `INBOX_NOT_INCLUDED`, indicando la riga da aggiungere.

### 5.3 Validazione prima/dopo

Ogni scrittura segue questo flusso:

1. **Parsing isolato** del testo proposto: se non è sintassi Beancount valida, rifiuto con riga e motivo.
2. **Staging:** si costruisce una copia temporanea dell'albero dei file del ledger con la modifica applicata.
3. **Caricamento** della copia con il loader di Beancount e raccolta degli errori.
4. **Confronto:** gli errori preesistenti (caricamento del ledger corrente) vengono sottratti come multiinsieme di coppie (tipo di errore, messaggio), ignorando i numeri di riga che cambiano con le modifiche. Sono bloccanti solo gli **errori nuovi**.
5. **Controlli aggiuntivi** sulle entry nuove: account esistente e aperto alla data, valuta ammessa per l'account, transazione bilanciata, data non anteriore all'apertura dell'account, nessun `pad` o `balance` nel testo proposto.
6. Se tutto passa: scrittura atomica, risposta con riepilogo e nuova versione.

L'interfaccia per rendere il confronto riusabile è:

```python
class Validator(Protocol):
    def validate(self, before: Tree, after: Tree) -> list[Issue]: ...
```

dove `Tree` rappresenta la vista dei file con la modifica proposta applicata.

### 5.4 Identità delle entry

Per modificare o eliminare una transazione serve un identificatore stabile. Un identificatore è la tripla **file, riga iniziale, hash SHA-256 del testo della direttiva**. Il testo di una direttiva è il blocco che parte dalla riga iniziale e arriva alla riga precedente la successiva riga non vuota e non indentata. Per impostazione predefinita modifica ed eliminazione sono ammesse solo sulle entry dell'inbox, e per un'entry in un altro file il tool risponde `ENTRY_NOT_IN_INBOX`. Se l'hash non coincide al momento della modifica (qualcosa è cambiato nel frattempo), il tool risponde `ENTRY_CHANGED` con il testo attuale.

Se l'utente avvia il server con `--allow-edit-outside-inbox`, le stesse operazioni sono ammesse anche su altri file del ledger, con queste regole:

- L'abilitazione dipende solo dalla configurazione del server, decisa dall'utente all'avvio. Nessun parametro dei tool e nessuna istruzione dell'LLM può attivarla.
- Sono modificabili solo file inclusi dal ledger che si trovano dentro la directory del file principale o in una sua sottodirectory, dopo la risoluzione di eventuali symlink. Qualunque altro percorso viene rifiutato con `PATH_NOT_ALLOWED`.
- Valgono la stessa validazione prima/dopo, lo stesso lock e la stessa scrittura atomica, con il file temporaneo creato nella directory del file di destinazione.
- `ledger_info` riporta se il flag è attivo.

## 6. Tool

Tutte le risposte sono oggetti strutturati con un campo booleano `ok`. Gli importi sono sempre **stringhe** con valuta, mai numeri in virgola mobile. Le descrizioni dei tool (docstring) fanno parte dell'interfaccia e devono contenere esempi.

### 6.1 `ledger_info`

Senza parametri. Restituisce: file inclusi, operating currency, elenco degli account (aperti e chiusi, con valute ammesse e date), data prima e ultima transazione, numero di errori preesistenti, tag e link più usati, versione del ledger, stato dell'inbox, modalità read-only. Va chiamato a inizio sessione.

### 6.2 `query`

Parametri: `bql` (stringa), `limit` (intero, default 100, massimo 1000), `offset` (intero, default 0).

- Esegue solo istruzioni di lettura. Qualunque altra istruzione viene rifiutata con `QUERY_ERROR`.
- La risposta contiene colonne, righe, `truncated` (booleano) e `total_rows` quando noto. Se disponibili, includere file e riga delle entry.
- La descrizione del tool contiene 3 o 4 esempi (spese per categoria in un mese, saldo di un account a una data, ultime N transazioni di un payee).

### 6.3 `find_transactions`

Parametri opzionali: `payee`, `narration_contains`, `account`, `date_from`, `date_to`, `min_amount`, `max_amount`, `tags`, `limit`. Restituisce transazioni complete come testo Beancount, ciascuna con il proprio identificatore (5.4). Pensato per riconciliazione e correzioni.

### 6.4 `add_transactions`

Parametri: `text` (una o più direttive), `dry_run` (default `false`), `expected_ledger_version` (opzionale).

- Segue il flusso della sezione 5.3 e scrive in coda al file inbox.
- Con `dry_run`, esegue tutto tranne la scrittura e mostra il testo che verrebbe aggiunto.
- La risposta contiene le entry scritte, la nuova versione del ledger e il numero di avvisi.

### 6.5 `edit_transaction`

Parametri: `entry_id`, `new_text`, `dry_run`. Sostituisce una direttiva identificata come in 5.4, con la stessa validazione e lo stesso rollback. Di default agisce solo sull'inbox: per entry in altri file risponde `ENTRY_NOT_IN_INBOX`, a meno che il server sia avviato con `--allow-edit-outside-inbox`.

### 6.6 `delete_transaction`

Parametri: `entry_id`, `dry_run`. Rimuove una transazione. Non elimina `open`, `close`, `balance`, `pad`. Di default agisce solo sull'inbox (altrimenti `ENTRY_NOT_IN_INBOX`); con `--allow-edit-outside-inbox` anche su altri file ammessi dalle regole di 5.4.

### 6.7 `validate`

Senza parametri. Esegue il controllo completo del ledger e restituisce l'elenco degli errori con file, riga e messaggio.

### 6.8 `open_account`

Parametri: `account`, `currencies` (valute ammesse, opzionale), `date` (default: oggi), `confirm_new` (default `false`), `dry_run`. Scrive una direttiva `open` nell'inbox, con la stessa validazione prima/dopo di `add_transactions`.

- Verifica che il nome sia ben formato e che la radice sia una di quelle ammesse dalle opzioni del ledger (di default `Assets`, `Liabilities`, `Equity`, `Income`, `Expenses`).
- Se esiste già un account aperto con quel nome, rifiuta con `ACCOUNT_EXISTS`.
- Se esiste un account aperto con nome molto simile (ad esempio `Expenses:Resturant` accanto a `Expenses:Restaurant`), rifiuta con `ACCOUNT_SIMILAR_EXISTS` e propone quello esistente. Con `confirm_new` a `true` procede comunque.

### 6.9 Fase 2 (non implementare ora)

`check_duplicates` (dato un insieme di candidati, segnala quelli già presenti), `suggest_account` (propone l'account in base allo storico), un prompt MCP con le convenzioni del ledger.

## 7. Formato degli errori

Gli errori sono pensati per essere letti da un LLM. Ogni errore contiene: `code`, `message`, `details` (elenco di problemi con file, riga e testo), e `hint` (cosa fare per correggere, con suggerimenti concreti, ad esempio gli account simili a quello inesistente).

| Codice | Quando |
| --- | --- |
| `SYNTAX_ERROR` | Il testo proposto non è Beancount valido |
| `VALIDATION_FAILED` | La scrittura introdurrebbe errori nuovi |
| `VERSION_CONFLICT` | `expected_ledger_version` non coincide |
| `ENTRY_NOT_FOUND` | L'identificatore non esiste |
| `ENTRY_CHANGED` | L'hash della direttiva non coincide |
| `ENTRY_NOT_IN_INBOX` | L'entry si trova fuori dall'inbox e il server non è avviato con `--allow-edit-outside-inbox` |
| `PATH_NOT_ALLOWED` | Con il flag attivo, il file è fuori dalla directory del ledger o non è incluso da esso |
| `ACCOUNT_EXISTS` | L'account che si vuole aprire esiste già ed è aperto |
| `ACCOUNT_SIMILAR_EXISTS` | Esiste un account aperto con nome molto simile |
| `QUERY_ERROR` | BQL non valida o istruzione non ammessa |
| `LIMIT_EXCEEDED` | Parametri oltre i limiti consentiti |
| `READ_ONLY` | Il server è in modalità sola lettura |
| `LOCKED` | Impossibile ottenere il lock di scrittura |
| `INBOX_NOT_INCLUDED` | L'inbox non esiste o non è inclusa dal file principale |

## 8. Strategia di testing

Per la v0.1 i test sono di due livelli: unit e integrazione. Nessun tool è considerato completo senza i test descritti qui, e l'obiettivo è poter modificare il codice con fiducia e dimostrare che il ledger non viene lasciato in uno stato incoerente. Test property-based, di guasto e concorrenza, end-to-end MCP, di contratto ed eval con LLM reale sono rimandati a una fase successiva.

### 8.1 Livelli di test

1. **Unit test** (`tests/unit/`): funzioni pure e componenti isolati, cioè estrazione dello span di una direttiva, calcolo degli hash, confronto degli errori come multiinsieme, parsing dei parametri, formattazione degli errori, scrittura atomica del `writer`.
2. **Test di integrazione** (`tests/integration/`): `LedgerService` e funzioni dei tool su ledger reali in directory temporanee, con scrittura vera sul disco. I tool si chiamano direttamente come funzioni Python, senza client MCP.

### 8.2 Fixture

In `tests/fixtures/` ledger di esempio, ciascuno con uno scopo preciso:

- `minimal`: pochi account, poche transazioni, nessun errore.
- `empty`: file principale vuoto o con soli commenti, per il percorso dal ledger vuoto alla prima transazione.
- `multifile`: file principale con `include` annidati e inbox inclusa.
- `with_errors`: errori preesistenti noti (account non aperto, transazione sbilanciata), per verificare che solo gli errori **nuovi** blocchino le scritture.
- `no_inbox`: inbox inesistente o non inclusa, per testare `INBOX_NOT_INCLUDED`.
- `multicurrency`: più valute, costi e prezzi.

Una factory di test crea ledger temporanei da descrizioni compatte, così ogni test costruisce solo ciò che gli serve ed è leggibile.

### 8.3 Casi minimi da coprire

- Dopo ogni `add_transactions` riuscita, il numero di errori del ledger non aumenta rispetto a prima.
- Dopo una scrittura rifiutata, il contenuto di tutti i file è **byte per byte identico** a prima.
- `dry_run` non modifica mai alcun file.
- Aggiungere e poi eliminare la stessa transazione riporta il ledger a uno stato equivalente.
- Le somme degli importi restituiti da `query` coincidono con quelle calcolate direttamente dalle entry.
- Con `expected_ledger_version` obsoleta, risposta `VERSION_CONFLICT` e nessuna scrittura.
- Se un file viene modificato dall'esterno tra una lettura e una scrittura, `edit_transaction` risponde `ENTRY_CHANGED`.
- Un errore simulato in `os.replace` (monkeypatch, test unit su `writer.py`) lascia intatto il file originale e senza file temporanei.
- Ogni codice di errore della sezione 7 è raggiungibile e contiene un `hint` utile.
- Dal ledger creato da `init` alla prima transazione: `open_account` apre un account e `add_transactions` registra una transazione senza errori nuovi.
- `init` rifiuta di sovrascrivere un file esistente non vuoto.
- Un file principale vuoto o con soli commenti viene caricato e `ledger_info` lo segnala come vuoto.
- `open_account` rifiuta nomi simili a un account esistente (`ACCOUNT_SIMILAR_EXISTS`), salvo conferma.
- Senza flag, `edit_transaction` e `delete_transaction` su un'entry fuori dall'inbox rispondono `ENTRY_NOT_IN_INBOX` e non modificano alcun file.
- Con `--allow-edit-outside-inbox`, modifica ed eliminazione su un file incluso diverso dall'inbox riescono, con validazione prima/dopo e rollback in caso di errori nuovi.
- Con il flag attivo, un file fuori dalla directory del ledger (anche raggiunto tramite symlink) viene rifiutato con `PATH_NOT_ALLOWED`.
- L'abilitazione dipende solo dalla configurazione del server: nessun input dei tool la modifica.

### 8.4 CI e soglie

- GitHub Actions su più versioni di Python.
- Passi obbligatori: `ruff`, `mypy` strict, `pytest` (unit e integration).
- Copertura minima proposta: 90% sui moduli `ledger`, `entries`, `validation`, `writer`, `queries`.

## 9. Configurazione

Opzioni da riga di comando e variabili d'ambiente:

- `ledger`: percorso del file principale (opzionale). Se omesso, si usa la variabile d'ambiente `BEANCOUNT_MCP_LEDGER` quando impostata, altrimenti il percorso predefinito `~/.beancount-mcp/ledger/main.bean`.
- `--inbox`: percorso relativo dell'inbox (default `inbox.bean`).
- `--read-only`: disabilita tutti i tool di scrittura.
- `--allow-edit-outside-inbox`: consente a `edit_transaction` e `delete_transaction` di agire anche su file diversi dall'inbox, purché inclusi dal ledger e dentro la directory del file principale. Disattivato di default.
- `--query-limit`: limite predefinito di righe per `query`.
- `--transport`: `stdio` (default) o `streamable-http`.
- `--host`: host di ascolto HTTP (default `127.0.0.1`).
- `--port`: porta HTTP (default `8000`).
- `--http-path`: percorso HTTP (default `/mcp`).
- `--version`: stampa la versione ed esce.

`--host`, `--port` e `--http-path` sono validi solo con
`--transport streamable-http`. Il server HTTP usa il protocollo 2026-07-28 in
modalità stateless e restituisce risposte JSON.

### 9.1 Comando `init`

`beancount-mcp init /percorso/main.bean --currency EUR` crea un ledger nuovo da zero, e serve solo per questo caso.

- Crea il file principale con titolo e `operating_currency`, la riga `include "inbox.bean"` e la direttiva `open` per `Equity:Opening-Balances`.
- Crea un `inbox.bean` vuoto accanto al file principale.
- Si rifiuta di sovrascrivere un file principale o un'inbox che contengano già qualcosa, con un messaggio che lo spiega.
- Non esiste una modalità per adattare un ledger esistente: in quel caso è l'utente a creare l'inbox e ad aggiungere `include "inbox.bean"` al proprio file principale.

**Avvio normale del server**

- File principale inesistente: il server termina con un messaggio che rimanda a `init`.
- File vuoto o con soli commenti: accettato. `ledger_info` lo segnala come ledger vuoto e suggerisce di aprire gli account con `open_account`.
- Inbox inesistente o non inclusa: avviso in `ledger_info`, e i tool di scrittura rispondono `INBOX_NOT_INCLUDED` con la riga da aggiungere.

## 10. Comportamento del sistema nei vari scenari

Questa sezione descrive passo per passo cosa accade all'avvio e quando si aggiunge un account o una transazione. È la specifica di riferimento per i test di integrazione di questi percorsi.

### 10.1 Scenario 1: avvio senza indicare un ledger

L'utente avvia il server senza argomento `ledger` (e senza `BEANCOUNT_MCP_LEDGER`). Il server usa il percorso predefinito, `~/.beancount-mcp/ledger/main.bean`.

1. **Ledger predefinito non ancora creato.** Il server non scrive nulla e termina con un messaggio che dice che non ha trovato un ledger in quel percorso e che spiega le due strade: eseguire `beancount-mcp init --currency EUR` per crearne uno nuovo, oppure avviare il server indicando il proprio ledger.
2. **`init` senza percorso** crea il ledger nel percorso predefinito: il file principale (titolo, `operating_currency`, `include` dell'inbox, direttiva `open` per `Equity:Opening-Balances`) e un `inbox.bean` vuoto. Con un percorso indicato crea gli stessi file in quella posizione. Se esistono già file non vuoti, si ferma senza toccare nulla.
3. **Primo avvio dopo `init`.** Il server carica il ledger, che non ha errori. `ledger_info` riporta un solo account (`Equity:Opening-Balances`), nessuna transazione, inbox inclusa e un suggerimento: aprire gli account necessari con `open_account`.
4. **Avvii successivi.** Se il ledger predefinito esiste già, il server parte come nello scenario 2, senza differenze.

### 10.2 Scenario 2: avvio con un ledger esistente

L'utente avvia il server con `beancount-mcp /percorso/main.beancount`. All'avvio il server non modifica né crea alcun file.

1. **File principale inesistente.** Il percorso indicato esplicitamente non viene mai creato: il server termina con un messaggio che chiede di controllare il percorso o di usare `init` per un ledger nuovo.
2. **Caricamento.** Carica il file principale e i suoi `include`, calcola gli errori preesistenti e la versione del ledger.
3. **Controllo dell'inbox** (`inbox.bean` accanto al file principale, o il percorso di `--inbox`):
   - esiste ed è inclusa dal file principale: tutto abilitato;
   - non esiste o non è inclusa: il server parte comunque, la lettura funziona, `ledger_info` mostra un avviso con la riga `include` da aggiungere, e ogni tool di scrittura risponde `INBOX_NOT_INCLUDED` finché l'utente non crea il file e non aggiunge l'`include` al proprio file principale.
4. **Errori preesistenti.** Non impediscono l'avvio. `ledger_info` ne riporta il numero e `validate` li elenca. Le scritture bloccano solo gli errori nuovi.
5. **Ledger vuoto o con soli commenti.** Viene accettato e segnalato come vuoto da `ledger_info`. Dopo aver collegato l'inbox, l'utente può cominciare con `open_account`.
6. **Altri file.** Il server non li tocca. Possono essere modificati solo da `edit_transaction` e `delete_transaction`, e solo con `--allow-edit-outside-inbox`.

Il server non riorganizza il ledger, non aggiunge `include` e non sposta entry.

### 10.3 Aggiungere un account (`open_account`)

1. **Controlli preliminari:** il server non è in `--read-only` e l'inbox è pronta, altrimenti `READ_ONLY` o `INBOX_NOT_INCLUDED`.
2. **Controlli sul nome:** nome ben formato e radice ammessa. Se l'account esiste già ed è aperto, `ACCOUNT_EXISTS`. Se esiste un account aperto con nome molto simile, `ACCOUNT_SIMILAR_EXISTS`, con l'account esistente nel suggerimento (ad esempio `Expenses:Restaurant` per `Expenses:Resturant`), a meno che `confirm_new` sia `true`.
3. **Costruzione** della direttiva `open` con la data indicata (default: oggi) e le valute.
4. **Validazione prima/dopo** in staging (sezione 5.3). Errori nuovi: `VALIDATION_FAILED` e nessuna scrittura.
5. **`dry_run`:** la risposta mostra il testo che verrebbe scritto e il processo si ferma, senza modificare file.
6. **Scrittura:** lock, scrittura atomica in coda all'inbox.
7. **Risposta:** direttiva scritta, nuova versione del ledger, e conferma che l'account è ora disponibile per le transazioni.

### 10.4 Aggiungere una transazione (`add_transactions`)

1. **Controlli preliminari:** come in 10.3.
2. **Parsing isolato** del testo. Se non è Beancount valido: `SYNTAX_ERROR` con riga e motivo.
3. **Controlli sulle entry nuove:** account esistenti e aperti alla data, valuta ammessa per l'account, transazione bilanciata, nessun `pad` né `balance`. Un account non aperto produce `VALIDATION_FAILED` con un suggerimento che indica gli account simili e rimanda a `open_account`.
4. **Validazione prima/dopo** in staging. Sono bloccanti solo gli errori nuovi.
5. **`dry_run`:** si ferma qui, senza scrivere.
6. **Scrittura:** lock, controllo di `expected_ledger_version` se fornita (`VERSION_CONFLICT` in caso di mancata corrispondenza), scrittura atomica in coda all'inbox.
7. **Risposta:** entry scritte, nuova versione del ledger, eventuali avvisi. Aggiungere due volte lo stesso testo produce due entry, perché la v0.1 non deduplica.

### 10.5 Riepilogo per situazione

| Situazione | Lettura | Scritture |
| --- | --- | --- |
| Nessun ledger al percorso predefinito | Il server non parte, il messaggio rimanda a `init` | Non applicabile |
| Ledger creato da `init` | Abilitata | Abilitate |
| Ledger esistente con inbox collegata | Abilitata | Abilitate |
| Ledger esistente senza inbox o con inbox non inclusa | Abilitata | Rifiutate con `INBOX_NOT_INCLUDED` |
| Ledger esistente con errori preesistenti | Abilitata | Abilitate, bloccano solo gli errori nuovi |
| File principale vuoto o con soli commenti | Abilitata, segnalato come vuoto | Abilitate dopo il collegamento dell'inbox |
| Server avviato con `--read-only` | Abilitata | Rifiutate con `READ_ONLY` |

## 11. Milestone e criteri di accettazione

Ogni milestone è completa solo quando i test del livello corrispondente passano in CI.

- **M0, scheletro:** repository, `pyproject.toml`, CI con lint, tipi e un test di prova, ledger di esempio, `docs/decisions.md` con la scelta delle versioni.
- **M1, lettura del ledger:** `LedgerService`, calcolo della versione del ledger, `ledger_info`, comando `init` e gestione di file mancante o vuoto. Test: unit sugli hash, integrazione sulle fixture `minimal`, `empty` e `no_inbox`.
- **M2, query:** `query` con limiti, paginazione e rifiuto delle istruzioni non di lettura. Test: unit e integrazione.
- **M3, validazione:** modulo di confronto prima/dopo, `validate`. Test: fixture `with_errors`, unit sul multiinsieme.
- **M4, scrittura:** `writer.py` con lock e scrittura atomica, `add_transactions` con `dry_run` e inbox, `open_account`. Test: unit sul writer (incluso l'errore simulato in `os.replace`), integrazione su rifiuto, `dry_run`, inbox, conflitto di versione e percorso dal ledger vuoto alla prima transazione.
- **M5, modifica ed eliminazione:** identità delle entry, `edit_transaction` e `delete_transaction` (solo inbox di default, altri file con `--allow-edit-outside-inbox` e controllo dei percorsi). Test: casi `ENTRY_CHANGED`, `ENTRY_NOT_FOUND`, `ENTRY_NOT_IN_INBOX` e `PATH_NOT_ALLOWED`, round trip aggiungi/elimina.
- **M6, ricerca:** `find_transactions`. Test: unit e integrazione.
- **M7, rifinitura:** modalità read-only, README con esempi di configurazione per i client MCP e istruzioni per collegare l'inbox a un ledger esistente, pubblicazione su PyPI.

## 12. Regole di lavoro per l'agente

1. Procedere per milestone, in ordine, senza anticipare quelle successive.
2. Scrivere prima i test di ogni funzionalità, poi l'implementazione. Nessuna milestone si chiude con test mancanti o disattivati.
3. Commit piccoli, con messaggi che indicano milestone e tool interessato.
4. Non allargare lo scopo: ciò che è nei non-obiettivi o nella fase 2 non si implementa senza una decisione esplicita.
5. Ogni scelta tecnica non coperta da queste specifiche, in particolare versioni delle librerie e API verificate, va annotata in `docs/decisions.md` con motivazione.
6. In caso di ambiguità che cambi il comportamento dei tool, fermarsi e chiedere invece di scegliere in silenzio.
7. Non scrivere su file dell'utente fuori dall'inbox, salvo `edit_transaction` e `delete_transaction` quando il server è stato avviato con `--allow-edit-outside-inbox`. Il comando `init` crea solo file nuovi, senza sovrascrivere quelli esistenti.

## 13. Questioni aperte

- Versione di Beancount da adottare (v2 o v3) e stabilità delle API usate per il loader e per beanquery.
- Se beanquery espone file e riga delle entry nei risultati; in caso contrario, valutare un'alternativa per collegare i risultati di `query` alle direttive.
- Comportamento con ledger molto grandi: tempo di caricamento a ogni richiesta e quando valutare l'introduzione di una cache.
- Strategia di lock su file system di rete o cartelle sincronizzate (il lock tramite file può non essere affidabile).
- Modalità di deploy remoto (HTTP con autenticazione) e relativo modello di sicurezza, rimandati a dopo la v0.1.
- Politica di privacy: filtro opzionale sugli account sensibili nelle risposte dei tool.
- Percorso predefinito del ledger gestito dal server (proposta: `~/.beancount-mcp/ledger/main.bean`) e sue convenzioni sui diversi sistemi operativi.
- Copia di backup del file prima di modificarlo fuori dall'inbox, con `--allow-edit-outside-inbox`.
