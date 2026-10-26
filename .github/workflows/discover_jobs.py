#!/usr/bin/env python3
"""Daily Werkstudent discovery via the Arbeitsagentur Jobsuche API v6 (Germany only). v4.1"""
import base64, json, re, time, datetime as dt, pathlib, requests

API = "https://rest.arbeitsagentur.de/jobboerse/jobsuche-service/pc"
HEAD = {"X-API-Key": "jobboerse-jobsuche", "Accept": "application/json"}
DAYS_OLD = 7           # API accepts only 0, 1, 7, 14, 28
NEW_WINDOW_DAYS = 3     # hand the agent only jobs first seen in the last N days
MAX_DETAILS = 150
MAX_OUT = 30

STUDENT_QUERIES = [("Werkstudent", 3), ("Working Student", 2), ("Studentische Hilfskraft", 2), ("Student Assistant", 1), ("HiWi", 1)]
FIELD_QUERIES = ["Robotik","Robotics","ROS","Computer Vision","Bildverarbeitung","Machine Learning","Deep Learning","KI",
                 "Autonome Systeme","SLAM","Sensorik","Embedded","Mechatronik","Automatisierung","Künstliche Intelligenz",
                 "Perception","Punktwolke","Reinforcement Learning","Python","Software Entwicklung"]
STUDENT = ["werkstudent","working student","student assistant","studentische","hiwi","werkstudierende","wissenschaftliche hilfskraft"]
CORE = ["robot","robotik","robotics","autonom","ros","ros2","slam","perception","vision","bildverarbeitung","3d","sensor",
        "sensorik","embedded","mechatron","ki","ai","machine learning","deep learning","computer vision","reinforcement","automatisierung"]
BROAD = ["python","software","informatik","daten","data","entwicklung","development","simulation","elektro","c++"]
REJECT = ["praktikum","intern","internship","masterarbeit","thesis","abschlussarbeit","trainee","ausbildung","senior",
          "lead","principal","vollzeit","full-time","kita","kindergarten","kinder","personal","recruiting","hr",
          "pflege","erzieher","vertrieb","sales","marketing","human resources","data entry","verkauf","aushilfe","social media"]
TOPICS = ["ros2","ros 2","ros","manipulation","navigation","motion planning","slam","sensor fusion","lidar","depth camera","tof",
          "time-of-flight","point cloud","punktwolke","3d vision","opencv","pytorch","reinforcement learning","sim-to-real",
          "embodied ai","imitation learning","simulation","gazebo","computer vision","deep learning","machine learning"]
PREFERRED = {"BADEN_WUERTTEMBERG","BAYERN","BRANDENBURG","BREMEN","HAMBURG","NIEDERSACHSEN","SAARLAND","NORDRHEIN_WESTFALEN"}
GERMAN_HARD = re.compile(r"(deutsch(kenntnisse)?[^.\n]{0,40}(c1|c2|fließend|verhandlungssicher|muttersprach|sehr gut))|(c1|c2)[^.\n]{0,20}deutsch|native german|fluent german", re.I)
GERMAN_SOFT = re.compile(r"deutsch(kenntnisse)?[^.\n]{0,30}\b(b1|b2)\b|german[^.\n]{0,20}\b(b1|b2)\b", re.I)
ENGLISH_OK = re.compile(r"\benglish\b|\benglisch\b", re.I)

def words(text, terms):
    """Whole-word match so 'ros' does not hit 'Prozess' and 'ki' does not hit 'Kiel'."""
    return sorted({t for t in terms if re.search(r"(?<![a-zäöüß0-9])" + re.escape(t) + r"(?![a-zäöüß0-9])", text)})

here = pathlib.Path(__file__).parent
state_f = here / "state.json"
state = json.loads(state_f.read_text()) if state_f.exists() else {}
today = dt.date.today()

def get(url, **params):
    for attempt in range(3):
        try:
            r = requests.get(url, headers=HEAD, params=params, timeout=40)
            if r.status_code == 200:
                return r.json()
            print(f"  HTTP {r.status_code} {url.split('/pc/')[-1]} {params.get('was','')}")
            if r.status_code in (400, 404):
                break
        except (requests.RequestException, ValueError) as e:
            print(f"  error {type(e).__name__}: {e}")
        time.sleep(2 + attempt * 3)
    return {}

def loc(j):
    l = (j.get("stellenlokationen") or [{}])[0].get("adresse") or {}
    return l.get("ort"), (l.get("region") or "")

found = {}
plan = STUDENT_QUERIES + [(q, 2) for q in FIELD_QUERIES]
for q, pages in plan:
    n_items = 0
    for page in range(1, pages + 1):
        data = get(f"{API}/v6/jobs", was=q, size=100, page=page, veroeffentlichtseit=DAYS_OLD, angebotsart=1)
        items = data.get("ergebnisliste") or []
        n_items += len(items)
        for j in items:
            ref = j.get("referenznummer") or j.get("refnr")
            title = (j.get("stellenangebotsTitel") or "").strip()
            t = " " + re.sub(r"[^\wäöüß]+", " ", title.lower()) + " "
            if not ref or not words(t, STUDENT) or words(t, REJECT):
                continue
            city, region = loc(j)
            found.setdefault(ref, {"refnr": ref, "title": title, "employer": j.get("firma"), "city": city, "region": region,
                "published": j.get("datumErsteVeroeffentlichung"), "updated": j.get("aenderungsdatum"),
                "external_url": j.get("externeURL"),
                "fulltime": j.get("arbeitszeitVollzeit"), "parttime_flexible": j.get("arbeitszeitTeilzeitFlexibel")})
        if len(items) < 100:
            break
        time.sleep(0.7)
    print(f"{q!r}: {n_items} results fetched")
    time.sleep(0.7)
print(f"{len(found)} student-titled results after reject filter")

out, checked = [], 0
for ref, j in list(found.items())[:MAX_DETAILS]:
    enc = base64.b64encode(ref.encode()).decode()
    d = get(f"{API}/v4/jobdetails/{enc}")
    checked += 1
    desc = d.get("stellenangebotsBeschreibung") or d.get("stellenbeschreibung") or ""
    t = " " + re.sub(r"[^\wäöüß]+", " ", j["title"].lower()) + " "
    low = " " + re.sub(r"[^\wäöüß+\-]+", " ", (j["title"] + " " + desc).lower()) + " "
    hits = words(low, TOPICS)
    core_hits = words(t, CORE)
    broad_hits = words(low, BROAD)
    strong = bool(core_hits) or len(hits) >= 2
    if not (strong or broad_hits):
        print("  dropped:", j["title"], "|", j["employer"], "|", j["city"])
        continue
    first = state.setdefault(ref, today.isoformat())
    ext = j["external_url"] or d.get("allianzpartnerUrl") or ""
    if ext and not ext.startswith("http"):
        ext = "https://" + ext
    row = {"refnr": ref, "title": j["title"], "employer": j["employer"], "city": j["city"], "region": j["region"],
        "published": j["published"], "updated": j["updated"],
        "apply_url": ext or f"https://www.arbeitsagentur.de/jobsuche/jobdetail/{ref}",
        "arbeitsagentur_url": f"https://www.arbeitsagentur.de/jobsuche/jobdetail/{ref}",
        "posted_via": d.get("allianzpartnerName"), "fulltime_flag": j["fulltime"],
        "topic_hits": hits, "core_hits_in_title": core_hits, "broad_hits": broad_hits, "broad_only": not strong,
        "german_hard_required": bool(GERMAN_HARD.search(desc)),
        "german_b_level_mentioned": bool(GERMAN_SOFT.search(desc)),
        "english_mentioned": bool(ENGLISH_OK.search(desc)),
        "preferred_state": j["region"] in PREFERRED, "first_seen": first,
        "description_excerpt": re.sub(r"\s+", " ", desc)[:1500]}
    row["prelim"] = len(hits)*3 + len(core_hits)*4 + len(broad_hits) + (3 if row["preferred_state"] else 0) \
                    - (10 if row["german_hard_required"] else 0) - (6 if not strong else 0)
    out.append(row)
    time.sleep(0.4)
print(f"{checked} detail pages checked, {len(out)} passed filters")

cut = (today - dt.timedelta(days=NEW_WINDOW_DAYS)).isoformat()
out = [j for j in out if j["first_seen"] >= cut and not j["german_hard_required"]]
out.sort(key=lambda x: x["prelim"], reverse=True)
out = out[:MAX_OUT]

state = {k: v for k, v in state.items() if v >= (today - dt.timedelta(days=30)).isoformat()}
state_f.write_text(json.dumps(state, indent=1))
(here / "candidates.json").write_text(json.dumps(
    {"generated": today.isoformat(), "count": len(out), "jobs": out}, ensure_ascii=False, indent=1))
print(f"{len(out)} candidates written")
