import base64
import json
import os
import re
import time
import unicodedata
from datetime import datetime, timedelta
import pdfplumber
import requests
import streamlit as st

# ==========================================
# 1. CONFIGURATION STREAMLIT & STYLES (ADC)
# ==========================================
st.set_page_config(
    page_title="Le Décrypteur ADC",
    page_icon="🦛",
    layout="wide"
)

ALLOWED_DOMAIN = "adc-labo.fr"

st.markdown("""
    <style>
        .stApp { 
            background-color: #F8F9FA; 
        }
        .main-title {
            font-size: 2.4rem;
            font-weight: 700;
            color: #004B87;
            margin-bottom: 0px;
            line-height: 1.2;
        }
        .highlight-letter {
            color: #8DB600;
            font-weight: 900;
        }
        .hippo-badge {
            font-size: 2.2rem;
            text-align: center;
            margin-top: -5px;
        }
        div[data-testid="metric-container"] {
            background-color: #FFFFFF;
            padding: 15px 20px;
            border-radius: 12px;
            box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.05);
            border-left: 5px solid #8DB600;
            border-top: 1px solid #E2E8F0;
            border-right: 1px solid #E2E8F0;
            border-bottom: 1px solid #E2E8F0;
        }
        .stTabs [data-baseweb="tab-list"] { gap: 10px; }
        .stTabs [data-baseweb="tab"] {
            background-color: #E2E8F0;
            border-radius: 8px 8px 0 0;
            padding: 10px 20px;
            color: #004B87;
            font-weight: 600;
        }
        .stTabs [aria-selected="true"] {
            background-color: #004B87 !important;
            color: #FFFFFF !important;
        }
        section[data-testid="stFileUploadDropzone"] {
            background-color: #FFFFFF;
            border: 2px dashed #004B87;
            border-radius: 12px;
        }
        .stButton>button {
            background-color: #004B87 !important;
            color: white !important;
            border-radius: 8px !important;
            border: none !important;
            padding: 0.6rem 1.2rem !important;
            font-weight: 600 !important;
            transition: all 0.3s ease !important;
            width: 100%;
        }
        .stButton>button:hover {
            background-color: #8DB600 !important;
            color: white !important;
        }
        .login-card {
            background-color: #FFFFFF;
            padding: 2.5rem;
            border-radius: 16px;
            box-shadow: 0 10px 25px rgba(0, 0, 0, 0.08);
            border-top: 6px solid #004B87;
            text-align: center;
        }
    </style>
""", unsafe_allow_html=True)

# ==========================================
# 2. AUTHENTIFICATION (EXECUTION EN PREMIER)
# ==========================================
def check_auth():
    if "authenticated" not in st.session_state:
        st.session_state.authenticated = False

    if not st.session_state.authenticated:
        col1, col2, col3 = st.columns([1, 2, 1])
        with col2:
            st.markdown('<div class="login-card">', unsafe_allow_html=True)
            try:
                st.image("ACD_WEB_RVB.png", width='stretch')
            except Exception:
                st.markdown('<div class="main-title"><span class="highlight-letter">L</span>e <span class="highlight-letter">D</span>écrypteur - ADC</div>', unsafe_allow_html=True)
            
            st.caption("Connexion requise pour accéder à la plateforme")
            st.write("---")

            with st.form("auth_form"):
                email_input = st.text_input("Saisissez votre e-mail professionnel :", placeholder=f"exemple@{ALLOWED_DOMAIN}")
                submit_button = st.form_submit_button("Se connecter 🚀", type="primary", width='stretch')

                if submit_button:
                    clean_email = email_input.strip().lower()
                    if clean_email.endswith(f"@{ALLOWED_DOMAIN.lower()}"):
                        st.session_state.authenticated = True
                        st.session_state.user_email = clean_email
                        st.rerun()
                    else:
                        st.error(f"Accès refusé. Seules les adresses e-mail finissant par @{ALLOWED_DOMAIN} sont autorisées.")
            
            st.markdown('</div>', unsafe_allow_html=True)
        return False
    return True

if not check_auth():
    st.stop()

# ==========================================
# 3. SYNCHROTEAM & HISTORIQUE
# ==========================================
try:
    SYNCHROTEAM_DOMAIN = st.secrets["SYNCHROTEAM_DOMAIN"].strip()
    SYNCHROTEAM_API_KEY = st.secrets["SYNCHROTEAM_API_KEY"].strip()
except Exception:
    SYNCHROTEAM_DOMAIN = ""
    SYNCHROTEAM_API_KEY = ""

BASE_URL = "https://ws.synchroteam.com/api/v3"
HISTORY_FILE = "import_history.json"

# Construction de l'authentification Basic Auth Synchroteam
auth_str = f"{SYNCHROTEAM_DOMAIN}:{SYNCHROTEAM_API_KEY}"
b64_auth = base64.b64encode(auth_str.encode()).decode()

HEADERS = {
    "Authorization": f"Basic {b64_auth}",
    "Content-Type": "application/json",
    "Accept": "application/json",
}

# Header de fallback si le domaine est géré directement par le serveur
auth_str_alt = f"{SYNCHROTEAM_API_KEY}:"
b64_auth_alt = base64.b64encode(auth_str_alt.encode()).decode()
HEADERS_ALT = {
    "Authorization": f"Basic {b64_auth_alt}",
    "Content-Type": "application/json",
    "Accept": "application/json",
}

def normalize_string(text):
    if not text:
        return ""
    text = unicodedata.normalize('NFKC', str(text))
    text = re.sub(r"[\s\xa0\u200b\u202f]+", " ", text)
    return text.strip().upper()

def build_url(endpoint):
    sep = "&" if "?" in endpoint else "?"
    return f"{BASE_URL}{endpoint}{sep}domain={SYNCHROTEAM_DOMAIN}"

def safe_get(endpoint):
    url = build_url(endpoint)
    # Essai 1 : Authorization domain:api_key
    try:
        res = requests.get(url, headers=HEADERS, timeout=10)
        if res.status_code == 200:
            return res
    except Exception:
        pass
    # Essai 2 : Authorization api_key:
    try:
        res = requests.get(url, headers=HEADERS_ALT, timeout=10)
        if res.status_code == 200:
            return res
    except Exception:
        pass
    return res

def safe_post(endpoint, json_data, retries=2, delay=1):
    url = build_url(endpoint)
    for attempt in range(retries):
        try:
            res = requests.post(url, headers=HEADERS, json=json_data, timeout=15)
            if res.status_code in [200, 201]:
                return res
            res_alt = requests.post(url, headers=HEADERS_ALT, json=json_data, timeout=15)
            if res_alt.status_code in [200, 201]:
                return res_alt
            if res.status_code in [502, 503, 504, 429]:
                time.sleep(delay)
            else:
                return res
        except requests.exceptions.RequestException:
            time.sleep(delay)
    return None

def load_history():
    if not os.path.exists(HISTORY_FILE):
        return []
    try:
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        cutoff = datetime.now() - timedelta(days=2)
        return [item for item in data if datetime.fromisoformat(item["timestamp"]) >= cutoff]
    except Exception:
        return []

def save_history_entry(entry):
    history = load_history()
    history.insert(0, entry)
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)

@st.cache_data(ttl=3600)
def fetch_job_types_map():
    job_types_map = {}
    if not SYNCHROTEAM_DOMAIN or not SYNCHROTEAM_API_KEY:
        return job_types_map

    page = 1
    page_size = 50
    
    while page <= 10:
        res = safe_get(f"/jobType/list?page={page}&pageSize={page_size}")
        if res and res.status_code == 200:
            data = res.json()
            records = data.get("data", []) if isinstance(data, dict) else data
            if not records:
                break
            for item in records:
                if isinstance(item, dict) and "name" in item and "id" in item:
                    clean_key = normalize_string(item["name"])
                    job_types_map[clean_key] = item["id"]
            if len(records) < page_size:
                break
            page += 1
        else:
            break

    return job_types_map

def find_existing_site_by_myid(myid):
    try:
        res = safe_get(f"/site/list?myId={requests.utils.quote(myid)}")
        if res and res.status_code == 200:
            data = res.json()
            sites = data.get("data", []) if isinstance(data, dict) else data
            for site in sites:
                if normalize_string(site.get("myId", "")) == normalize_string(myid):
                    return site.get("id"), site.get("customerId")
    except Exception:
        pass
    return None, None

def get_or_create_customer(pdf_client_name):
    clean_client_name = pdf_client_name.strip()
    norm_target = normalize_string(clean_client_name)
    
    endpoints_to_try = [
        f"/customer/list?name={requests.utils.quote(clean_client_name)}",
        "/customer/list?pageSize=100"
    ]
    
    for endpoint in endpoints_to_try:
        try:
            res_search = safe_get(endpoint)
            if res_search and res_search.status_code == 200:
                data = res_search.json()
                clients = data.get("data", []) if isinstance(data, dict) else data
                
                for c in clients:
                    c_name_norm = normalize_string(c.get("name", ""))
                    if norm_target in c_name_norm or c_name_norm in norm_target:
                        st.info(f"💡 Client rattaché : {c.get('name')} (ID: {c.get('id')})")
                        return c.get("id")
            else:
                code_str = res_search.status_code if res_search else "Pas de réponse"
                text_str = res_search.text if res_search else ""
                st.warning(f"⚠️ Recherche API client : Code {code_str} - {text_str}")
        except Exception as e:
            st.error(f"Erreur réseau recherche client : {e}")

    clean_myid = "CLI-" + re.sub(r"[^A-Za-z0-9]", "", clean_client_name).upper()[:6] + str(int(time.time()))[-4:]
    payload = {
        "name": clean_client_name,
        "myId": clean_myid,
        "address": "À renseigner",
        "city": "Paris",
        "zipCode": "75000",
        "country": "France"
    }
    
    res_create = safe_post("/customer/send", payload)
    if res_create:
        if res_create.status_code in [200, 201]:
            return res_create.json().get("id")
        else:
            st.error(f"❌ Erreur API Création Client Synchroteam ({res_create.status_code}) : {res_create.text}")
    else:
        st.error("❌ Pas de réponse du serveur Synchroteam (Timeout ou Secret manquant)")
        
    return None

# ==========================================
# 4. PARSER PDF & REGROUPEMENT CANONIQUE
# ==========================================
def extract_zone_num(text):
    if not text:
        return None
    
    if any(k in text.upper() for k in ["LISTE DES MESURES", "DURÉE", "OBJECTIF", "TYPE", "MESURE SUR OPÉRATEUR"]):
        return None

    m = re.search(r"((?:[^\n]+?-\s*)?(?:PHASE|ZONE|ZSE)\s*#?\s*[\d\.]+)", text, re.IGNORECASE)
    if m:
        return m.group(1).strip()
    return None

def clean_suivi_zone_name(raw_text):
    if not raw_text:
        return "SUIVI DE CHANTIER - ZONE 1"
    
    m = re.search(r"((?:SUIVI DE CHANTIER\s*-\s*)?(?:ZONE|PHASE|ZSE)\s*#?\s*\d+)", raw_text, re.IGNORECASE)
    if m:
        title = m.group(1).strip()
        if not title.upper().startswith("SUIVI DE CHANTIER"):
            title = f"SUIVI DE CHANTIER - {title}"
        return title.upper()
    return "SUIVI DE CHANTIER - ZONE 1"

def parse_pdf_file(uploaded_file):
    site_info = {"client": "", "name": "", "myid": "", "address": "", "zip": "", "city": ""}
    suivi_zones = {}
    phase_pair_objs = {}
    process_names = []
    total_j_proc = 0

    with pdfplumber.open(uploaded_file) as pdf:
        total_pages = len(pdf.pages)
        
        full_text = ""
        for p in pdf.pages:
            t = p.extract_text()
            if t:
                full_text += t + "\n"

        client_m = re.search(r"CLIENT\s*:\s*([^\n\r]+)", full_text, re.IGNORECASE)
        if client_m: 
            raw_client = client_m.group(1).strip()
            site_info["client"] = re.split(r"[\(-]", raw_client)[0].strip()

        dossier_m = re.search(r"DOSSIER\s*N°\s*:\s*([^\n(]+)\s*\(([^)]+)\)", full_text, re.IGNORECASE)
        if dossier_m:
            site_info["name"] = dossier_m.group(1).strip()
            site_info["myid"] = dossier_m.group(2).strip()

        adresse_m = re.search(r"ADRESSE D'INTERVENTION\s*:\s*([\s\S]+?)(?=\n\n|\n[A-Z\s]{4,}:|BON DE COMMANDE|$)", full_text, re.IGNORECASE)
        if adresse_m:
            raw_addr_block = adresse_m.group(1).strip()
            clean_addr_full = re.sub(r"\s+", " ", raw_addr_block).strip()
            
            cp_ville_m = re.search(r"(\d{5})\s+(.+)", clean_addr_full)
            if cp_ville_m:
                site_info["zip"] = cp_ville_m.group(1)
                site_info["city"] = cp_ville_m.group(2).strip()
                street_m = re.search(r"^(.*?)\s*\d{5}", clean_addr_full)
                site_info["address"] = street_m.group(1).strip() if street_m and street_m.group(1).strip() else clean_addr_full
            else:
                site_info["address"] = clean_addr_full

        if not site_info["client"]: 
            site_info["client"] = "CLIENT INCONNU"
        if not site_info["name"]: 
            site_info["name"] = uploaded_file.name.split(".")[0]

        bdc_start_idx = -1
        for idx in range(total_pages - 1, -1, -1):
            p_text = pdf.pages[idx].extract_text() or ""
            if "BON DE COMMANDE" in p_text.upper():
                bdc_start_idx = idx
                break

        if bdc_start_idx != -1:
            target_pages = pdf.pages[bdc_start_idx:min(bdc_start_idx + 2, total_pages)]
        else:
            target_pages = pdf.pages[-2:] if total_pages >= 2 else pdf.pages

        tables = []
        for p in target_pages:
            p_tables = p.extract_tables()
            if not p_tables:
                continue

            for t in p_tables:
                t_str = " ".join([" ".join([str(c) for c in r if c]) for r in t])
                if any(kw in t_str.upper() for kw in ["BON DE COMMANDE", "LISTE DES MESURES", "DURÉE", "OBJECTIF"]):
                    tables.append(t)

        current_zone = "Phase 1"

        for table in tables:
            for row in table:
                if not row or not any(row):
                    continue
                
                cell_zse = row[0].strip() if len(row) > 0 and row[0] else ""
                full_row_text = " ".join([str(c) for c in row if c])

                if "BON DE COMMANDE" in full_row_text.upper():
                    continue

                extracted_z = extract_zone_num(cell_zse) or extract_zone_num(full_row_text)
                if extracted_z:
                    current_zone = extracted_z

                suivi_key = clean_suivi_zone_name(current_zone)

                if current_zone not in phase_pair_objs:
                    phase_pair_objs[current_zone] = {}

                codes_found = re.findall(r"\b([A-Z]+(?:-[A-Z0-9]+)?)\s*\(\s*(\d+)\s*\)", full_row_text)
                for code, qty_str in codes_found:
                    qty = int(qty_str)
                    
                    if any(code.startswith(letter) for letter in ["D", "E", "G", "U", "V", "X", "Y"]):
                        phase_pair_objs[current_zone][code] = phase_pair_objs[current_zone].get(code, 0) + qty
                    elif code == "J-PROC":
                        total_j_proc += qty
                    else:
                        if suivi_key not in suivi_zones:
                            suivi_zones[suivi_key] = {"measures": {}, "j_proc": 0}
                        measures = suivi_zones[suivi_key]["measures"]
                        measures[code] = measures.get(code, 0) + qty

                for cell in row:
                    if cell and ("PRO" in str(cell).upper() or "PROCESSUS" in str(cell).upper()):
                        proc_clean = re.sub(r"\s+", " ", str(cell)).strip()
                        if proc_clean and proc_clean not in process_names and not re.match(r"^J-PROC", proc_clean, re.I):
                            process_names.append(proc_clean)

    for zone in suivi_zones:
        suivi_zones[zone]["j_proc"] = total_j_proc

    suivi_zones = {k: v for k, v in suivi_zones.items() if v["measures"]}
    phase_pair_objs = {k: v for k, v in phase_pair_objs.items() if v}

    return site_info, phase_pair_objs, suivi_zones, process_names

# ==========================================
# 5. TRAITEMENT SYNCHROTEAM
# ==========================================
def process_single_pdf(uploaded_file, job_types_map, user_email):
    logs = []
    created_jobs_count = 0
    site_info, phase_pair_objs, suivi_zones, process_names = parse_pdf_file(uploaded_file)
    
    logs.append(f"📄 **Fichier :** `{uploaded_file.name}`")
    logs.append(f"🏢 **Client capturé :** `{site_info['client']}`")
    logs.append(f"📍 **Dossier :** `{site_info['name']}` (Réf.: `{site_info['myid']}`)")
    logs.append(f"🏠 **Adresse capturée :** `{site_info['address']}` | `{site_info['zip']}` `{site_info['city']}`")

    site_id, customer_id = find_existing_site_by_myid(site_info["myid"])
    site_existed = False

    if site_id and customer_id:
        site_existed = True
        logs.append(f"🔗 **Site existant trouvé** (ID: `{site_id}`). Rattachement...")
    else:
        logs.append("🔍 Recherche / Création du client...")
        customer_id = get_or_create_customer(site_info["client"])
        if not customer_id:
            return False, "Échec lors de la création/récupération du client.", logs, 0

        site_payload = {
            "name": site_info["name"],
            "myId": site_info["myid"],
            "address": site_info["address"] or "À renseigner",
            "city": site_info["city"] or "Paris",
            "zipCode": site_info["zip"] or "75000",
            "country": "France",
            "customerId": int(customer_id),
        }
        res_site = safe_post("/site/send", site_payload)
        if not res_site or res_site.status_code not in [200, 201]:
            return False, "Échec lors de la création du site.", logs, 0

        site_id = res_site.json().get("id")
        logs.append(f"✅ Site créé (ID: `{site_id}`)")

    interventions_to_create = []

    LABEL_MAPPING = {
        "D": {"pose": "Pose conditions ambiantes (D)", "depose": "Dépose conditions ambiantes (D)"},
        "E": {"pose": "Pose Mesures après sinistre (E)", "depose": "Dépose Mesures après sinistre (E)"}
    }

    for zone_label, code_dict in phase_pair_objs.items():
        by_category = {}
        for code, qty in code_dict.items():
            cat = code.split("-")[0].upper()
            by_category.setdefault(cat, []).append(f"{code}: {qty}")

        for cat, list_measures in by_category.items():
            desc_cat = f"{zone_label} : " + " / ".join(list_measures)
            
            if cat in LABEL_MAPPING:
                pose_label = LABEL_MAPPING[cat]["pose"]
                depose_label = LABEL_MAPPING[cat]["depose"]
            else:
                pose_label = f"Pose {cat}"
                depose_label = f"Dépose {cat}"

            interventions_to_create.append({"type_name": pose_label, "description": desc_cat})
            interventions_to_create.append({"type_name": depose_label, "description": desc_cat})

    suivi_type_label = "Suivi 4h - Enviro + opé + MES + Mat"

    for zone_label, zone_data in suivi_zones.items():
        measures_dict = zone_data["measures"]
        j_proc_qty = zone_data["j_proc"]

        measures_str = " / ".join([f"{k}({v})" for k, v in measures_dict.items()])
        desc_lines = [f"{zone_label} : {measures_str}"]
        
        if j_proc_qty > 0 or process_names:
            desc_lines.append(f"J-PROC ({j_proc_qty if j_proc_qty > 0 else 1})")
            for proc in process_names:
                desc_lines.append(proc)

        interventions_to_create.append({
            "type_name": suivi_type_label,
            "description": "\n".join(desc_lines)
        })

    for job in interventions_to_create:
        target_clean = normalize_string(job["type_name"])
        job_type_id = job_types_map.get(target_clean)

        job_payload = {
            "customerId": int(customer_id),
            "siteId": int(site_id),
            "description": job["description"]
        }

        if job_type_id:
            job_payload["type"] = {"id": int(job_type_id)}
            logs.append(f"⚙️ `[{job['type_name']}]` -> ID : `{job_type_id}`")
        else:
            logs.append(f"⚠️ `[{job['type_name']}]` non trouvé dans l'API")

        time.sleep(0.5)

        res_job = safe_post("/job/send", job_payload)
        if res_job and res_job.status_code in [200, 201]:
            created_jobs_count += 1
        else:
            err_text = res_job.text if res_job else "Pas de réponse (Timeout ou erreur réseau)"
            code_text = f" Status {res_job.status_code}" if res_job else ""
            logs.append(f"❌ Erreur API pour `{job['type_name']}`{code_text} : {err_text}")

    save_history_entry({
        "timestamp": datetime.now().isoformat(),
        "date_str": datetime.now().strftime("%d/%m/%Y %H:%M"),
        "user_email": user_email,
        "filename": uploaded_file.name,
        "client": site_info["client"],
        "site": site_info["name"],
        "jobs_count": created_jobs_count,
        "attached_to_existing": site_existed
    })

    return True, f"Dossier **{site_info['name']}** traité avec succès !", logs, created_jobs_count

# ==========================================
# 6. INTERFACE UTILISATEUR
# ==========================================
with st.sidebar:
    try:
        st.image("ACD_WEB_RVB.png", width='stretch')
    except Exception:
        pass
    st.write("---")
    st.markdown(f"👤 **Utilisateur :**\n`{st.session_state.user_email}`")
    st.write("---")
    if st.button("Se déconnecter"):
        st.session_state.authenticated = False
        st.rerun()

header_col1, header_col2 = st.columns([3, 1])
with header_col1:
    st.markdown('<div class="main-title"><span class="highlight-letter">L</span>e <span class="highlight-letter">D</span>écrypteur - ADC</div>', unsafe_allow_html=True)
    st.caption("Importation et création automatique d'interventions Synchroteam")
with header_col2:
    try:
        st.image("ACD_WEB_RVB.png", width='stretch')
    except Exception:
        st.caption("[Logo ADC Labo]")
    st.markdown('<div class="hippo-badge">🦛</div>', unsafe_allow_html=True)

st.write("---")

job_types_map = fetch_job_types_map()

col1, col2 = st.columns(2)
with col1: 
    st.metric("Statut API", "Connecté" if SYNCHROTEAM_DOMAIN else "Configuration requise", delta=f"{len(job_types_map)} types")
with col2: 
    st.metric("Dossiers (48h)", len(load_history()))

st.write("---")

tab_import, tab_history = st.tabs(["🚀 Import", "📜 Historique"])

with tab_import:
    uploaded_files = st.file_uploader("Fichiers PDF", type=["pdf"], accept_multiple_files=True)
    if uploaded_files and st.button(f"Lancer ({len(uploaded_files)})", type="primary", width='stretch'):
        for file in uploaded_files:
            with st.expander(f"Traitement : {file.name}", expanded=True):
                ok, msg, logs, _ = process_single_pdf(file, job_types_map, st.session_state.user_email)
                for log in logs: 
                    st.markdown(log)
                if ok: 
                    st.success(msg)
                else: 
                    st.error(msg)

with tab_history:
    history_data = load_history()
    if not history_data:
        st.info("Aucun historique disponible sur les dernières 48 heures.")
    else:
        for entry in history_data:
            user_info = entry.get("user_email", "Utilisateur inconnu")
            st.write(
                f"📅 **{entry['date_str']}** | "
                f"👤 **{user_info}** | "
                f"🏢 **{entry['client']}** | "
                f"📍 {entry['site']}"
            )
            st.divider()
