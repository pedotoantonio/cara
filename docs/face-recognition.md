# Riconoscimento facciale — guida per chi vive in casa

CARA può riconoscere i volti di chi vive in casa per caricare
automaticamente il profilo giusto: preferenze, voce, memoria, livello
di linguaggio. Questa guida spiega cosa fa, cosa NON fa, e come
abilitarlo.

## In due righe

CARA usa la webcam del dispositivo che hai davanti per identificare
chi sei. **Le foto non lasciano mai il browser.** Quello che viene
salvato sul server di casa è una sequenza di 128 numeri (un
*descrittore*), non un'immagine. Funziona anche senza internet dopo il
primo avvio.

## Quando lo usi

- Sul tablet a parete (CARA Wall): CARA vede chi è davanti e ti saluta
  per nome.
- Sul tuo laptop / telefono: quando apri la PWA di CARA, può caricare
  automaticamente il tuo profilo senza che debba fare login.

## Quando NON ti riconosce

- La feature è **disattivata di default**. Va abilitata da
  `/admin/face` (sezione Impostazioni → "Riconoscimento attivo").
- Anche con la feature attiva, ogni persona va **registrata** prima di
  poter essere riconosciuta (vedi sotto).
- Niente cloud. Se il server di casa è spento, niente riconoscimento.

## Come registrare un volto

1. Apri `https://192.168.1.23:8455/face/enroll` sul dispositivo della
   persona da registrare (il browser deve avere accesso alla webcam).
2. Leggi e accetta l'avviso privacy.
3. Scrivi il nome (es. "Antonio") e indica se è un bambino o una
   bambina.
4. CARA ti chiede di guardarla in 5 posizioni diverse: dritto, un po' a
   sinistra, un po' a destra, sorridi, neutro.
5. Quando la qualità del frame è abbastanza buona (anello che si chiude
   in alto a destra del video), CARA scatta in automatico. Devi solo
   stare fermo per circa 1 secondo per ogni posa.
6. Alla fine vedi le 5 qualità. Se almeno 4 sono sopra l'80%, puoi
   salvare. Altrimenti puoi rifare le acquisizioni in un punto meglio
   illuminato.

In 90 secondi sei dentro.

## Modalità bambino

I profili contrassegnati come *Bambino/a*:

- Vengono riconosciuti con una tolleranza più ampia (i visi dei piccoli
  cambiano spesso).
- Attivano la voce TTS più morbida.
- Attivano il dizionario semplificato in chat.
- Bloccano automaticamente alcuni comandi smart-home pericolosi
  (apertura porte, accensione boiler, telefonate, allarmi). Questa
  protezione è applicata sia lato client (il pulsante non appare) sia
  lato server (anche se appare, l'azione non parte).

## La spia verde

Quando il riconoscimento è attivo nella schermata che stai guardando,
vedrai un piccolo punto verde lampeggiante con il tuo nome. Quel punto
significa: la webcam è accesa, CARA sta cercando volti, e ti ha
riconosciuto. Se non vuoi essere riconosciuto, basta uscire dalla
pagina o disattivare la feature dal toggle in alto.

## Privacy in tre punti

1. **Niente foto sul server.** Il browser calcola un vettore di 128
   numeri e manda solo quello. Da quei 128 numeri non si può
   ricostruire il tuo viso.
2. **Consenso esplicito.** Senza spuntare la casella nel passo 1 del
   wizard non si registra niente. Versione + data del consenso vengono
   salvate sul server (richiesta GDPR).
3. **Cancellazione totale.** Da `/admin/face` puoi cancellare un
   profilo. Il server elimina ogni descrittore associato. La pulizia è
   immediata e verificabile in DB.

## Toggle "spegni tutto"

In `/admin/face` → Impostazioni → "Riconoscimento attivo". Se lo
spegni:

- Le pipeline di cattura non partono su nessun dispositivo.
- I profili e i descrittori rimangono salvati ma non vengono usati.
- CARA continua a funzionare normalmente per tutto il resto.

Per riattivarlo basta rimettere il toggle.

## Cosa fare se non funziona

| Sintomo | Cosa controllare |
|---------|------------------|
| Nessun box compare sul video | Permesso camera negato? Vedi la barra del browser. |
| "Camera non trovata" | Sul desktop senza webcam — usa un dispositivo che ne ha una. |
| Riconosce uno per un altro | Apri `/admin/face` e abbassa la soglia di match (più stringente). |
| Non riconosce mai un profilo | Apri `/admin/face`, controlla quanti descrittori ha (deve averne ≥ 5). |
| Lentezza | Apri `/admin/face/debug`: se la latenza media è > 200 ms, CARA è già in modalità "watch" 1 FPS — è normale. |

## Per chi vuole vedere sotto il cofano

`/admin/face/debug` mostra: FPS effettivi, latenza per frame, ultimi 20
eventi del bus interno (detection, identified, lost, unknown), e la
distribuzione delle distanze degli ultimi match. Utile per capire
perché CARA scambia Antonio per Matteo.
