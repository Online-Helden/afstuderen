import requests
import json
import re
from pathlib import Path
from collections import defaultdict
from datetime import datetime

URL = "REDACTED ANDERS TOEGANG TOT MIJN LOCALE AI MODEL"

# ── DATUMFILTER ──────────────────────────────────────────────
DATUM_START = datetime(2026, 5, 13)
DATUM_EIND  = datetime(2026, 6, 3)
# ─────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """Je bent een data-analist die WhatsApp-gesprekken analyseert tussen een webdesignbureau (Online Heroes) en hun klanten.

De eigenaren van Online Heroes zijn Kevin en Stijn. Berichten van Kevin of Stijn zijn dus berichten van het bureau zelf, alle andere namen zijn klanten.

Je taak is om uit elk gespreksfragment drie categorieën te extraheren:

1. SUPPORT ISSUES
Een support issue is een bericht waarbij de klant een technisch probleem, storing, fout, bug, of urgente melding doet over hun website of hosting. Denk aan: "de website is down", "ik zie een fout", "het formulier werkt niet", "de mail doet het niet".
- Noteer het tijdstip van de melding (eerste bericht van klant over het issue)
- Noteer het tijdstip van de eerste reactie van Kevin of Stijn
- Bereken de responstijd in minuten
- Meenemen ongeacht tijdstip, ook buiten werkuren en in weekenden

2. FEEDBACKRONDES
Een feedbackronde is een moment waarop de klant inhoudelijke feedback geeft op een ontwerp, pagina, tekst of oplevering. Denk aan: "ik vind de kleur niet mooi", "kun je de tekst aanpassen", "het logo moet groter".
- Tel het aantal feedbackrondes
- Een nieuwe ronde begint als Kevin of Stijn iets heeft aangepast en de klant opnieuw feedback geeft

3. ALGEMENE RESPONSTIJD
Voor elk bericht van de klant waarbij zowel het klantbericht als de reactie van Kevin of Stijn binnen werkuren vallen (ma-vr 08:00-18:00):
- Tijdstip klantbericht
- Tijdstip eerste reactie Kevin of Stijn
- Responstijd in minuten
- Alleen meenemen als BEIDE tijdstempels binnen werkuren vallen

4. INITIËLE RESPONSTIJD
Meet alleen de eerste reactie op een nieuw gespreksmoment: het tijdsverschil tussen het eerste bericht van een klant na een stilte van minimaal 60 minuten en de eerste reactie van Kevin of Stijn. Berichten die onderdeel zijn van een lopend gesprek niet meenemen.
- Tijdstip eerste klantbericht na stilte van 60+ minuten
- Tijdstip eerste reactie Kevin of Stijn
- Responstijd in minuten
- Alleen binnen werkuren (ma-vr 08:00-18:00)

Neem alleen reacties mee waarbij een reactie redelijkerwijs verwacht wordt. 
Als een klantbericht een gesprek afsluit (zoals "oke top!", "bedankt!", 
"duidelijk!", "goed zo") of geen vraag of actie impliceert, 
dan hoeft er geen reactie te komen en moet dit bericht worden overgeslagen.

Geef je antwoord ALLEEN als geldig JSON, geen uitleg of tekst erbuiten:
{
  "support_issues": [
    {
      "omschrijving": "korte omschrijving van het issue",
      "tijdstip_melding": "DD/MM/YYYY HH:MM:SS",
      "tijdstip_reactie": "DD/MM/YYYY HH:MM:SS",
      "responstijd_minuten": 0
    }
  ],
  "feedbackrondes": {
    "aantal": 0,
    "omschrijvingen": ["omschrijving ronde 1"]
  },
  "algemene_responstijden": [
    {
      "tijdstip_klant": "DD/MM/YYYY HH:MM:SS",
      "tijdstip_kevin_of_stijn": "DD/MM/YYYY HH:MM:SS",
      "responstijd_minuten": 0
    }
  ],
  "initiele_responstijden": [
    {
      "tijdstip_klant": "DD/MM/YYYY HH:MM:SS",
      "tijdstip_kevin_of_stijn": "DD/MM/YYYY HH:MM:SS",
      "responstijd_minuten": 0
    }
  ]
}

Als er geen data is voor een categorie geef dan lege lijst of 0 terug. Verzin geen data."""


def normaliseer_datum(s):
    return re.sub(r'(\d{1,2})-(\d{1,2})-(\d{2,4})', r'\1/\2/\3', s)


def parse_tijdstip(s):
    s = normaliseer_datum(s.strip())
    formaten = [
        "%d/%m/%Y %H:%M:%S",
        "%d/%m/%Y %H:%M",
        "%d/%m/%y %H:%M:%S",
        "%d/%m/%y %H:%M",
    ]
    for fmt in formaten:
        try:
            return datetime.strptime(s, fmt)
        except:
            continue
    return None


def herbereken_responstijd(tijdstip_klant, tijdstip_reactie):
    if not tijdstip_klant or not tijdstip_reactie:
        return None
    t1 = parse_tijdstip(tijdstip_klant)
    t2 = parse_tijdstip(tijdstip_reactie)
    if t1 and t2:
        return round((t2 - t1).total_seconds() / 60, 1)
    return None


def is_werkuur(tijdstip_str):
    if not tijdstip_str:
        return False
    t = parse_tijdstip(tijdstip_str)
    if not t:
        return False
    return t.weekday() < 5 and 8 <= t.hour < 18


def laad_en_filter_whatsapp(pad):
    """Laad WhatsApp export en filter op DATUM_START t/m DATUM_EIND."""
    datum_patroon = re.compile(r'^\[?(\d{1,2}[-/]\d{1,2}[-/]\d{2,4})')
    gefilterde_regels = []
    huidige_datum_dt = None

    with open(pad, 'r', encoding='utf-8') as f:
        for regel in f:
            match = datum_patroon.match(regel)
            if match:
                datum_str = normaliseer_datum(match.group(1))
                for fmt in ["%d/%m/%Y", "%d/%m/%y"]:
                    try:
                        huidige_datum_dt = datetime.strptime(datum_str, fmt)
                        break
                    except:
                        continue

            # Alleen meenemen als datum binnen de nametingperiode valt
            if huidige_datum_dt:
                if DATUM_START <= huidige_datum_dt <= DATUM_EIND:
                    gefilterde_regels.append(regel.rstrip())

    print(f"  Datumfilter: {DATUM_START.strftime('%d/%m/%Y')} t/m {DATUM_EIND.strftime('%d/%m/%Y')}")
    print(f"  {len(gefilterde_regels)} regels over na filtering")
    return '\n'.join(gefilterde_regels)


def split_op_week_met_tokenlimiet(tekst, max_chars=24000):
    regels = tekst.split('\n')
    datum_patroon = re.compile(r'^\[?(\d{1,2}[-/]\d{1,2}[-/]\d{2,4})')

    dagen = defaultdict(list)
    huidige_datum = 'onbekend'
    dag_volgorde = []

    for regel in regels:
        match = datum_patroon.match(regel)
        if match:
            huidige_datum = match.group(1)
            if huidige_datum not in dag_volgorde:
                dag_volgorde.append(huidige_datum)
        dagen[huidige_datum].append(regel)

    week_chunks = []
    week_buffer = []
    dag_teller = 0

    for datum in dag_volgorde:
        week_buffer.extend(dagen[datum])
        dag_teller += 1
        if dag_teller >= 7:
            week_chunks.append(week_buffer[:])
            week_buffer = []
            dag_teller = 0

    if week_buffer:
        week_chunks.append(week_buffer)

    chunks = []
    for week in week_chunks:
        week_tekst = '\n'.join(week)
        if len(week_tekst) <= max_chars:
            chunks.append(week_tekst)
        else:
            print(f"  Week te groot ({len(week_tekst)} chars), splitsen...")
            sub_chunk = []
            sub_grootte = 0
            for regel in week:
                regel_grootte = len(regel) + 1
                if sub_grootte + regel_grootte > max_chars and sub_chunk:
                    chunks.append('\n'.join(sub_chunk))
                    sub_chunk = sub_chunk[-20:]
                    sub_grootte = sum(len(r) + 1 for r in sub_chunk)
                sub_chunk.append(regel)
                sub_grootte += regel_grootte
            if sub_chunk:
                chunks.append('\n'.join(sub_chunk))

    return chunks


def analyseer_chunk(chunk, chunk_nr, totaal):
    print(f"  Chunk {chunk_nr}/{totaal} ({len(chunk)} chars)...")

    headers = {
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
        "Content-Type": "application/json"
    }

    payload = {
        "model": "deepseek-chat",
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"Analyseer dit WhatsApp fragment:\n\n{chunk}"}
        ],
        "temperature": 0.1,
        "max_tokens": 8192
    }

    try:
        res = requests.post(URL, headers=headers, json=payload, timeout=300)
        print(f"  Status: {res.status_code}")
        content = res.json()['choices'][0]['message']['content'].strip()
        json_match = re.search(r'\{.*\}', content, re.DOTALL)
        if json_match:
            return json.loads(json_match.group())
        else:
            print(f"  Geen geldige JSON in chunk {chunk_nr}")
            return None
    except Exception as e:
        print(f"  Fout bij chunk {chunk_nr}: {e}")
        return None


def combineer_en_valideer(resultaten):
    alle_issues = []
    feedback_totaal = 0
    feedback_omschrijvingen = []
    alle_responstijden = []
    alle_initiele_responstijden = []

    for r in resultaten:
        if not r:
            continue

        for issue in r.get('support_issues', []):
            melding = issue.get('tijdstip_melding') or ''
            reactie = issue.get('tijdstip_reactie') or ''
            if not melding or not reactie:
                continue
            minuten = herbereken_responstijd(melding, reactie)
            if minuten is not None and minuten > 0:
                issue['responstijd_minuten'] = round(minuten)
                issue['tijdstip_melding'] = normaliseer_datum(melding)
                issue['tijdstip_reactie'] = normaliseer_datum(reactie)
                alle_issues.append(issue)

        feedback = r.get('feedbackrondes', {})
        feedback_totaal += feedback.get('aantal', 0)
        feedback_omschrijvingen.extend(feedback.get('omschrijvingen', []))

        for resp in r.get('algemene_responstijden', []):
            tk = resp.get('tijdstip_klant', '')
            tr = resp.get('tijdstip_kevin_of_stijn', '')
            if not is_werkuur(tk) or not is_werkuur(tr):
                continue
            minuten = herbereken_responstijd(tk, tr)
            if minuten is not None and minuten > 0:
                alle_responstijden.append({
                    "tijdstip_klant": normaliseer_datum(tk),
                    "tijdstip_kevin_of_stijn": normaliseer_datum(tr),
                    "responstijd_minuten": round(minuten)
                })

        for resp in r.get('initiele_responstijden', []):
            tk = resp.get('tijdstip_klant', '')
            tr = resp.get('tijdstip_kevin_of_stijn', '')
            if not is_werkuur(tk) or not is_werkuur(tr):
                continue
            minuten = herbereken_responstijd(tk, tr)
            if minuten is not None and minuten > 0:
                alle_initiele_responstijden.append({
                    "tijdstip_klant": normaliseer_datum(tk),
                    "tijdstip_kevin_of_stijn": normaliseer_datum(tr),
                    "responstijd_minuten": round(minuten)
                })

    seen = set()
    uniek_resp = []
    for r in alle_responstijden:
        key = r['tijdstip_klant']
        if key not in seen:
            seen.add(key)
            uniek_resp.append(r)

    seen_init = set()
    uniek_init = []
    for r in alle_initiele_responstijden:
        key = r['tijdstip_klant']
        if key not in seen_init:
            seen_init.add(key)
            uniek_init.append(r)

    seen_issues = set()
    uniek_issues = []
    for i in alle_issues:
        key = i['tijdstip_melding']
        if key not in seen_issues:
            seen_issues.add(key)
            uniek_issues.append(i)

    return {
        'support_issues': uniek_issues,
        'feedbackrondes': {
            'aantal': feedback_totaal,
            'omschrijvingen': feedback_omschrijvingen
        },
        'algemene_responstijden': uniek_resp,
        'initiele_responstijden': uniek_init
    }


def bereken_statistieken(gecombineerd):
    stats = {}

    issue_tijden = sorted([i['responstijd_minuten'] for i in gecombineerd['support_issues']])
    if issue_tijden:
        n = len(issue_tijden)
        mediaan = (issue_tijden[n//2 - 1] + issue_tijden[n//2]) / 2 if n % 2 == 0 else issue_tijden[n//2]
        stats['support_gemiddelde_minuten'] = round(sum(issue_tijden) / n, 1)
        stats['support_mediaan_minuten'] = round(mediaan, 1)
        stats['support_aantal_issues'] = n
    else:
        stats['support_gemiddelde_minuten'] = None
        stats['support_mediaan_minuten'] = None
        stats['support_aantal_issues'] = 0

    stats['feedbackrondes_totaal'] = gecombineerd['feedbackrondes']['aantal']

    resp_tijden = sorted([r['responstijd_minuten'] for r in gecombineerd['algemene_responstijden']])
    if resp_tijden:
        n = len(resp_tijden)
        mediaan = (resp_tijden[n//2 - 1] + resp_tijden[n//2]) / 2 if n % 2 == 0 else resp_tijden[n//2]
        stats['responstijd_gemiddelde_minuten'] = round(sum(resp_tijden) / n, 1)
        stats['responstijd_mediaan_minuten'] = round(mediaan, 1)
        stats['responstijd_aantal_metingen'] = n
    else:
        stats['responstijd_gemiddelde_minuten'] = None
        stats['responstijd_mediaan_minuten'] = None
        stats['responstijd_aantal_metingen'] = 0

    init_tijden = sorted([r['responstijd_minuten'] for r in gecombineerd['initiele_responstijden']])
    if init_tijden:
        n = len(init_tijden)
        mediaan = (init_tijden[n//2 - 1] + init_tijden[n//2]) / 2 if n % 2 == 0 else init_tijden[n//2]
        stats['initiele_responstijd_gemiddelde_minuten'] = round(sum(init_tijden) / n, 1)
        stats['initiele_responstijd_mediaan_minuten'] = round(mediaan, 1)
        stats['initiele_responstijd_aantal_metingen'] = n
    else:
        stats['initiele_responstijd_gemiddelde_minuten'] = None
        stats['initiele_responstijd_mediaan_minuten'] = None
        stats['initiele_responstijd_aantal_metingen'] = 0

    return stats


def analyseer_bestand(pad):
    bestandsnaam = Path(pad).stem
    print(f"\nAnalyseer: {bestandsnaam}")

    tekst = laad_en_filter_whatsapp(pad)

    if not tekst.strip():
        print(f"  Geen data binnen de nametingperiode gevonden.")
        return None

    chunks = split_op_week_met_tokenlimiet(tekst, max_chars=24000)
    print(f"  {len(chunks)} chunks aangemaakt")

    resultaten = [analyseer_chunk(chunk, i+1, len(chunks)) for i, chunk in enumerate(chunks)]
    gecombineerd = combineer_en_valideer(resultaten)
    stats = bereken_statistieken(gecombineerd)

    resultaat = {
        'bestand': bestandsnaam,
        'nametingperiode': {
            'start': DATUM_START.strftime('%d/%m/%Y'),
            'eind': DATUM_EIND.strftime('%d/%m/%Y')
        },
        'statistieken': stats,
        'detail': gecombineerd
    }

    output_pad = Path(pad).parent / f"{bestandsnaam}_nameting_resultaat.json"
    with open(output_pad, 'w', encoding='utf-8') as f:
        json.dump(resultaat, f, ensure_ascii=False, indent=2)

    print(f"  Opgeslagen: {output_pad.name}")
    print(f"  Support issues: {stats['support_aantal_issues']}")
    print(f"  Feedbackrondes: {stats['feedbackrondes_totaal']}")
    if stats['responstijd_mediaan_minuten']:
        print(f"  Mediaan responstijd: {stats['responstijd_mediaan_minuten']} min")

    return resultaat


def main():
    script_map = Path(__file__).parent
    txt_bestanden = list(script_map.glob('*.txt'))

    if not txt_bestanden:
        print("Geen .txt bestanden gevonden.")
        return

    print(f"{len(txt_bestanden)} WhatsApp export(s) gevonden")
    print(f"Nametingperiode: {DATUM_START.strftime('%d/%m/%Y')} t/m {DATUM_EIND.strftime('%d/%m/%Y')}")

    alle_statistieken = []
    for pad in txt_bestanden:
        resultaat = analyseer_bestand(pad)
        if resultaat:
            alle_statistieken.append({
                "klant": resultaat["bestand"],
                "nametingperiode": resultaat["nametingperiode"],
                "statistieken": resultaat["statistieken"]
            })

    with open(script_map / 'nameting_summary.json', 'w', encoding='utf-8') as f:
        json.dump(alle_statistieken, f, ensure_ascii=False, indent=2)

    print("\n" + "="*50)
    print("SAMENVATTING NAMETING ALLE KLANTEN")
    print("="*50)
    for r in alle_statistieken:
        s = r['statistieken']
        print(f"\n{r['klant']}")
        print(f"  Support issues: {s['support_aantal_issues']}")
        print(f"  Feedbackrondes: {s['feedbackrondes_totaal']}")
        if s['responstijd_mediaan_minuten']:
            print(f"  Mediaan algemene responstijd: {s['responstijd_mediaan_minuten']} min")
        if s['initiele_responstijd_mediaan_minuten']:
            print(f"  Mediaan initiële responstijd: {s['initiele_responstijd_mediaan_minuten']} min")

    print("\nKlaar. Per klant een aparte JSON + nameting_summary.json")


if __name__ == '__main__':
    main()
