import base64
import json
import os
import re
import time
from datetime import datetime, timedelta
import pdfplumber
import requests
import streamlit as st

# ==========================================
# 1. CONFIGURATION STREAMLIT & STYLES CSS
# ==========================================
st.set_page_config(
    page_title="Le Décrypteur ADC",
    page_icon="🦛",
    layout="centered"
)

ALLOWED_DOMAIN = "adc-labo.fr"

st.markdown("""
    <style>
        .stApp { background-color: #F0F4F8; }
        div[data-testid="metric-container"] {
            background-color: #FFFFFF;
            padding: 15px 20px;
            border-radius: 12px;
            box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.05);
            border: 1px solid #E2E8F0;
        }
        .stTabs [data-baseweb="tab-list"] { gap: 10px; }
        .stTabs [data-baseweb="tab"] {
            background-color: #E2E8F0;
            border-radius: 8px 8px 0 0;
            padding: 10px 20px;
            color: #334155;
            font-weight: 600;
        }
        .stTabs [aria-selected="true"] {
            background-color: #1E40AF !important;
            color: #FFFFFF !important;
        }
        section[data-testid="stFileUploadDropzone"] {
            background-color: #FFFFFF;
            border: 2px dashed #93C5FD;
            border-radius: 12px;
        }
        h1 { color: #1E3A8A; }
        .streamlit-expanderHeader {
            background-color: #FFFFFF;
            border-radius: 8px;
            font-weight: bold;
        }
    </style>
""", unsafe_allow_html=True)

# ==========================================
# 2. GESTION AUTHENTIFICATION
# ==========================================
def check_auth():
    if "authenticated" not in st.session_state:
        st.session_state.authenticated = False

    if not st.session_state.authenticated:
        st.title("🦛 Le Décrypteur ADC")
        st.caption("Connexion requise pour accéder à la plateforme")
        st.divider()

        with st.form("auth_form"):
            email_input = st.text_input("Saisissez votre e-mail professionnel :", placeholder=f"exemple@{ALLOWED_DOMAIN}")
            submit_button = st.form_submit_button("Se connecter", type="primary", use_container_width=True)

            if submit_button:
                clean_email = email_input.strip().lower()
                if clean_email.endswith(f"@{ALLOWED_DOMAIN.lower()}"):
                    st.session_state.authenticated = True
                    st.session_state.user_email = clean_email
                    st.rerun()
                else:
                    st.error(f"Accès refusé. Seules les adresses e-mail finissant par @{ALLOWED_DOMAIN} sont autorisées.")
        return False
    return True

if not check_auth():
    st.stop()

# ==========================================
# 3. CONFIGURATION SYNCHROTEAM & HISTORIQUE
# ==========================================
SYNCHROTEAM_DOMAIN = st.secrets["SYNCHROTEAM_DOMAIN"]
SYNCHROTEAM_API_KEY = st.secrets["SYNCHROTEAM_API_KEY"]
BASE_URL = "https://ws.synchroteam.com/api/v3"
HISTORY_FILE = "import_history.json"

auth_str = f"{SYNCHROTEAM_DOMAIN}:{SYNCHROTEAM_API_KEY}"
b64_auth = base64.b64encode(auth_str.encode()).decode()

HEADERS = {
    "Authorization": f"Basic {b64_auth}",
    "Content-Type": "application/json",
    "Accept": "application/json",
}

def build_url(endpoint):
    return f"{BASE_URL}{endpoint}"

def safe_post(url, json_data, retries=3, delay=2):
    for attempt in range(retries):
        try:
            res = requests.post(url, headers=HEADERS, json=json_data, timeout=15)
            if res.status_code in [200, 201]:
                return res
            elif res.status_code in [502, 503, 504]:
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
        valid_history = []
        for item in data:
            item_date = datetime.fromisoformat(item["timestamp"])
            if item_date >= cutoff:
                valid_history.append(item)
        return valid_history
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
    page = 1
    while True:
        url = build_url(f"/job/type/list?page={page}&pageSize=50")
        try:
            res = requests.get(url, headers=HEADERS, timeout=10)
            if res.status_code == 200:
                data = res.json()
                records = data.get("data", [])
                for item in records:
                    # Stocke exactement le nom retourné par Synchroteam (en majuscules pour comparaison stricte)
                    clean_name = item["name"].strip().upper()
                    job_types_map[clean_name] = item["id"]

                if page * 50 >= data.get("recordsTotal", 0):
                    break
                page += 1
            else:
                break
        except Exception as e:
            st.error(f"Erreur chargement types interventions : {e}")
            break
    return job_types_map

def find_existing_site_by_myid(myid):
    """Recherche si un site existe déjà via son numéro de dossier personnalisé (myId)."""
    search_url = build_url(f"/site/list?myId={requests.utils.quote(myid)}")
    try:
        res = requests.get(search_url, headers=HEADERS, timeout=10)
        if res.status_code == 200:
            data = res.json()
            sites = data.get("data", []) if isinstance(data, dict) else data
            for site in sites:
                if site.get("myId", "").strip().upper() == myid.strip().upper():
                    return site.get("id"), site.get("customerId")
    except Exception:
        pass
    return None, None

def get_or_create_customer(pdf_client_name):
    search_url = build_url(f"/customer/list?name={requests.utils.quote(pdf_client_name)}")
    try:
        res_search = requests.get(search_url, headers=HEADERS, timeout=10)
        if res_search.status_code == 200:
            data = res_search.json()
            clients = data.get("data", []) if isinstance(data, dict) else data

            for c in clients:
                if c.get("name", "").strip().upper() == pdf_client_name.strip().upper():
                    return c.get("id")
    except Exception as e:
        st.warning(f"Note recherche client : {e}")

    clean_myid = re.sub(r"[^A-Za-z0-9]", "", pdf_client_name).upper()[:20]
    payload = {
        "name": pdf_client_name,
        "myId": clean_myid,
        "address": "À renseigner",
        "city": "Paris",
        "zipCode": "75000",
        "country": "France"
    }

    res_create = safe_post(build_url("/customer/send"), payload)
    if res_create and res_create.status_code in [200, 201]:
        return res_create.json().get("id")
    return None

def resolve_job_type_id(target_label, job_types_map):
    """Mappe directement vers l'ID exact récupéré de l'API Synchroteam."""
    target_clean = target_label.strip().upper()
    return job_types_map.get(target_clean)

# ==========================================
# 4. PARSER DE PDF
# ==========================================
def parse_pdf_file(uploaded_file):
    site_info = {
        "client": "",
        "name": "",
        "myid": "",
        "address": "",
        "zip": "",
        "city": ""
    }
    
    g_objs_list = []
    uv_objs = {}
    suivi_zones = {}
    j_procs = []
    process_names = []

    with pdfplumber.open(uploaded_file) as pdf:
        full_text = ""
        for page in pdf.pages:
            full_text += (page.extract_text() or "") + "\n"

        client_m = re.search(r"CLIENT\s*:\s*(.+)", full_text, re.IGNORECASE)
        if client_m:
            site_info["client"] = client_m.group(1).strip()

        # Extraire le DOSSIER N° : 2607-107 (PDRE P2026071702Q - 26-015)
        dossier_m = re.search(r"DOSSIER\s*N°\s*:\s*([^\n(]+)\s*\(([^)]+)\)", full_text, re.IGNORECASE)
        if dossier_m:
            site_info["name"] = dossier_m.group(1).strip()
            site_info["myid"] = dossier_m.group(2).strip()

        adresse_m = re.search(r"ADRESSE D'INTERVENTION\s*:\s*(.+)", full_text, re.IGNORECASE)
        if adresse_m:
            raw_addr = adresse_m.group(1).strip()
            site_info["address"] = raw_addr
            
            cp_ville_m = re.search(r"(\d{5})\s+(.+)", raw_addr)
            if cp_ville_m:
                site_info["zip"] = cp_ville_m.group(1)
                site_info["city"] = cp_ville_m.group(2).strip()

        if not site_info["client"]:
            site_info["client"] = "CLIENT INCONNU"
        if not site_info["name"]:
            site_info["name"] = uploaded_file.name.split(".")[0]

        target_page = pdf.pages[-1]
        lines = (target_page.extract_text() or "").split("\n")
        current_zone = "Zone 1"

        for line in lines:
            zone_match = re.search(r"\b(Zone\s*\d+)\b", line, re.IGNORECASE)
            if zone_match:
                current_zone = zone_match.group(1).title()

            if current_zone not in suivi_zones:
                suivi_zones[current_zone] = {}

            codes_found = re.findall(r"\b([A-Z]+(?:-[A-Z0-9]+)?)\s*\(\s*(\d+)\s*\)", line)
            for code, qty_str in codes_found:
                qty = int(qty_str)

                if code.startswith("G"):
                    g_objs_list.append({code: qty})
                elif any(code.startswith(letter) for letter in ["U", "V", "X", "Y"]):
                    uv_objs[code] = qty
                elif code == "J-PROC":
                    j_procs.append(qty)
                else:
                    suivi_zones[current_zone][code] = suivi_zones[current_zone].get(code, 0) + qty

            if "PROCEDURE" in line.upper() or "PROC" in line.upper():
                proc_clean = line.strip()
                if proc_clean and proc_clean not in process_names and "LISTE" not in proc_clean:
                    process_names.append(proc_clean)

    suivi_zones = {k: v for k, v in suivi_zones.items() if v}
    return site_info, g_objs_list, suivi_zones, j_procs, uv_objs, process_names

# ==========================================
# 5. TRAITEMENT & SYNCHROTEAM
# ==========================================
def process_single_pdf(uploaded_file, job_types_map, user_email):
    logs = []
    created_jobs_count = 0
    site_info, g_objs_list, suivi_zones, j_procs, uv_objs, process_names = parse_pdf_file(uploaded_file)
    
    logs.append(f"📄 **Fichier :** `{uploaded_file.name}`")
    logs.append(f"📍 **Dossier :** `{site_info['name']}` (Réf.: `{site_info['myid']}`)")

    # 1. Recherche du site existant par son myId exact
    site_id, customer_id = find_existing_site_by_myid(site_info["myid"])
    site_existed = False

    if site_id and customer_id:
        site_existed = True
        logs.append(f"🔗 **Site existant trouvé** (ID: `{site_id}`). Rattachement direct...")
    else:
        # 2. Création si non trouvé
        logs.append("🔍 Site non trouvé. Création du dossier...")
        customer_id = get_or_create_customer(site_info["client"])
        if not customer_id:
            return False, "Échec récupération/création du Client.", logs, 0

        site_payload = {
            "name": site_info["name"],
            "myId": site_info["myid"],
            "address": site_info["address"] if site_info["address"] else "À renseigner",
            "city": site_info["city"] if site_info["city"] else "Paris",
            "zipCode": site_info["zip"] if site_info["zip"] else "75000",
            "country": "France",
            "customerId": customer_id,
        }

        res_site = safe_post(build_url("/site/send"), site_payload)
        if not res_site or res_site.status_code not in [200, 201]:
            err_msg = res_site.text if res_site else "Erreur réseau"
            return False, f"Échec création du site : {err_msg}", logs, 0

        site_id = res_site.json().get("id")
        logs.append(f"✅ Nouveau site créé dans Synchroteam (ID: `{site_id}`)")

    # 3. Création des interventions avec les EXACTES CORRESPONDANCES SYNCHROTEAM
    interventions_to_create = []

    # G
    for g_item in g_objs_list:
        desc_g = " / ".join([f"{k}: {v}" for k, v in g_item.items()])
        interventions_to_create.append({"type_name": "Pose G", "description": desc_g})
        interventions_to_create.append({"type_name": "Dépose G", "description": desc_g})

    # Suivi 4h
    suivi_type_label = "Suivi 4h - Enviro + opé + MES + Mat"
    total_j_proc = sum(j_procs) if j_procs else 0
    j_proc_line = f"+ J-PROC ({total_j_proc})" if total_j_proc > 0 else ""
    proc_list_str = "\n".join(process_names) if process_names else ""

    for zone_name, objs in suivi_zones.items():
        if objs:
            measures_str = " / ".join([f"{k}: {v}" for k, v in objs.items()])
            desc_lines = [f"{zone_name} : {measures_str}"]
            if j_proc_line:
                desc_lines.append(j_proc_line)
            if proc_list_str:
                desc_lines.append(proc_list_str)

            interventions_to_create.append({
                "type_name": suivi_type_label,
                "description": "\n".join(desc_lines)
            })

    # U, V, X, Y (Mapping dynamique sur les libellés exacts)
    if uv_objs:
        by_category = {}
        for code, qty in uv_objs.items():
            cat = code.split("-")[0].upper()
            if cat not in by_category:
                by_category[cat] = []
            by_category[cat].append(f"{code}: {qty}")

        for cat, list_measures in by_category.items():
            desc_cat = " / ".join(list_measures)
            
            # Gestion explicite des cas spécifiques (ex: Pose de V sur 4h vs Pose V)
            pose_label = "Pose de V sur 4h" if cat == "V" and "Pose de V sur 4h" in [k.title() for k in job_types_map.keys()] else f"Pose {cat}"
            depose_label = "Dépose V de 4h" if cat == "V" and "Dépose V de 4h" in [k.title() for k in job_types_map.keys()] else f"Dépose {cat}"
            
            interventions_to_create.append({"type_name": pose_label, "description": desc_cat})
            interventions_to_create.append({"type_name": depose_label, "description": desc_cat})

    for job in interventions_to_create:
        job_type_id = resolve_job_type_id(job["type_name"], job_types_map)

        job_payload = {
            "customerId": customer_id,
            "siteId": site_id,
            "description": job["description"],
        }
        
        if job_type_id:
            job_payload["type"] = {"id": job_type_id}

        res_job = safe_post(build_url("/job/send"), job_payload)
        if res_job and res_job.status_code in [200, 201]:
            logs.append(f"⚙️ Intervention `{job['type_name']}` créée (Type ID: `{job_type_id}`).")
            created_jobs_count += 1
        else:
            logs.append(f"❌ Erreur création intervention `{job['type_name']}`")

    # Enregistrement historique
    history_entry = {
        "timestamp": datetime.now().isoformat(),
        "date_str": datetime.now().strftime("%d/%m/%Y %H:%M"),
        "user_email": user_email,
        "filename": uploaded_file.name,
        "client": site_info["client"],
        "site": site_info["name"],
        "jobs_count": created_jobs_count,
        "attached_to_existing": site_existed
    }
    save_history_entry(history_entry)

    status_txt = "rattachées au site existant" if site_existed else "créées avec le nouveau site"
    return True, f"Dossier **{site_info['name']}** : {created_jobs_count} intervention(s) {status_txt} !", logs, created_jobs_count

# ==========================================
# 6. INTERFACE PRINCIPALE
# ==========================================
header_col1, header_col2 = st.columns([4, 1])
with header_col1:
    st.title("🦛 Le Décrypteur ADC")
    st.caption("Importation et création automatique des sites et interventions PDF vers Synchroteam")
with header_col2:
    st.write(f"👤 **{st.session_state.user_email.split('@')[0]}**")
    if st.button("Déconnexion", type="secondary", use_container_width=True):
        st.session_state.authenticated = False
        st.session_state.user_email = ""
        st.rerun()

job_types_map = fetch_job_types_map()

# Metrics
col1, col2 = st.columns(2)
with col1:
    st.metric(label="Statut API Synchroteam", value="Connecté", delta=f"{len(job_types_map)} types d'int.")
with col2:
    history_data = load_history()
    st.metric(label="Dossiers traités (48h)", value=len(history_data))

st.markdown("---")

tab_import, tab_history = st.tabs(["🚀 Nouvel Import", "📜 Historique (48h)"])

with tab_import:
    uploaded_files = st.file_uploader(
        "Glissez-déposez vos stratégies PDF ci-dessous",
        type=["pdf"],
        accept_multiple_files=True
    )

    if uploaded_files:
        if st.button(f"⚡ Lancer le traitement ({len(uploaded_files)} fichier(s))", type="primary", use_container_width=True):
            for file in uploaded_files:
                with st.expander(f"⚙️ Traitement de : {file.name}", expanded=True):
                    success, message, logs, count = process_single_pdf(
                        file, job_types_map, st.session_state.user_email
                    )
                    for log in logs:
                        st.markdown(log)
                    if success:
                        st.success(message)
                    else:
                        st.error(message)

with tab_history:
    st.subheader("Dossiers traités au cours des 48 dernières heures")
    history_data = load_history()
    
    if not history_data:
        st.info("Aucun historique récent enregistré pour les dernières 48 heures.")
    else:
        for entry in history_data:
            with st.container():
                c1, c2, c3 = st.columns([2, 3, 2])
                user_label = entry.get('user_email', 'Utilisateur inconnu')
                tag_site = " 🔗 (Site existant)" if entry.get("attached_to_existing") else " ✨ (Nouveau site)"
                c1.write(f"📅 **{entry['date_str']}**\n\n👤 `{user_label}`")
                c2.write(f"🏢 **{entry['client']}**\n📍 {entry['site']}{tag_site}")
                c3.caption(f"⚙️ {entry['jobs_count']} int. créée(s)")
                st.divider()
