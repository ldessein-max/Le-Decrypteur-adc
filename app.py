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

# Injection CSS pour le fond bleuté et le design moderne
st.markdown("""
    <style>
        /* Fond global de l'application (Bleu très doux / Slate Light) */
        .stApp {
            background-color: #F0F4F8;
        }

        /* Cartes et conteneurs */
        div[data-testid="metric-container"] {
            background-color: #FFFFFF;
            padding: 15px 20px;
            border-radius: 12px;
            box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.05), 0 2px 4px -1px rgba(0, 0, 0, 0.03);
            border: 1px solid #E2E8F0;
        }

        /* Stylisation des onglets */
        .stTabs [data-baseweb="tab-list"] {
            gap: 10px;
        }
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

        /* Zone de drag & drop PDF */
        section[data-testid="stFileUploadDropzone"] {
            background-color: #FFFFFF;
            border: 2px dashed #93C5FD;
            border-radius: 12px;
        }

        /* Titres et sous-titres */
        h1 {
            color: #1E3A8A;
        }
        
        /* Expander de traitement */
        .streamlit-expanderHeader {
            background-color: #FFFFFF;
            border-radius: 8px;
            font-weight: bold;
        }
    </style>
""", unsafe_allow_html=True)

# ==========================================
# 2. CONFIGURATION SYNCHROTEAM & HISTORIQUE
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
        url = build_url(f"/jobType/list?page={page}&pageSize=50")
        try:
            res = requests.get(url, headers=HEADERS, timeout=10)
            if res.status_code == 200:
                data = res.json()
                records = data.get("data", [])
                for item in records:
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

def get_or_create_customer(pdf_client_name):
    search_url = build_url(f"/customer/list?name={requests.utils.quote(pdf_client_name)}")
    try:
        res_search = requests.get(search_url, headers=HEADERS, timeout=10)
        if res_search.status_code == 200:
            data = res_search.json()
            clients = []
            if isinstance(data, list):
                clients = data
            elif isinstance(data, dict):
                clients = data.get("customers", data.get("data", []))

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
    else:
        error_detail = res_create.text if res_create else "Pas de réponse serveur"
        status_code = res_create.status_code if res_create else "N/A"
        st.error(f"Détail erreur API Client (Code {status_code}): {error_detail}")
        return None

# ==========================================
# 3. PARSER DE PDF DYNAMIQUE
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
    
    g_objs = {}
    uv_objs = {}
    suivi_zones = {}
    j_procs = []
    process_names = []

    with pdfplumber.open(uploaded_file) as pdf:
        full_text = ""
        for page in pdf.pages:
            full_text += (page.extract_text() or "") + "\n"

        # 1. Cartouche Vert
        client_m = re.search(r"CLIENT\s*:\s*(.+)", full_text, re.IGNORECASE)
        if client_m:
            site_info["client"] = client_m.group(1).strip()

        dossier_m = re.search(r"DOSSIER\s*N°\s*:\s*([\d-]+)\s*\(([^)]+)\)", full_text, re.IGNORECASE)
        if dossier_m:
            dossier_num = dossier_m.group(1).strip()
            details = dossier_m.group(2).strip()
            
            if " - " in details:
                pdre_part, site_label = details.split(" - ", 1)
                site_info["myid"] = pdre_part.strip()
                site_info["name"] = f"{dossier_num} - {site_label.strip()}"
            else:
                site_info["name"] = f"{dossier_num} - {details}"
                site_info["myid"] = dossier_num

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

        # 2. Lecture par Zone
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
                    g_objs[code] = qty
                elif any(code.startswith(letter) for letter in ["U", "V", "X", "Y"]):
                    uv_objs[code] = qty
                elif code == "J-PROC":
                    j_procs.append(qty)
                else:
                    suivi_zones[current_zone][code] = qty

            if "PROCEDURE" in line.upper() or "PROC" in line.upper():
                proc_clean = line.strip()
                if proc_clean and proc_clean not in process_names and "LISTE" not in proc_clean:
                    process_names.append(proc_clean)

    suivi_zones = {k: v for k, v in suivi_zones.items() if v}
    return site_info, g_objs, suivi_zones, j_procs, uv_objs, process_names

# ==========================================
# 4. TRAITEMENT & SYNCHROTEAM
# ==========================================
def process_single_pdf(uploaded_file, job_types_map):
    logs = []
    created_jobs_count = 0
    site_info, g_objs, suivi_zones, j_procs, uv_objs, process_names = parse_pdf_file(uploaded_file)
    
    logs.append(f"📄 **Fichier :** `{uploaded_file.name}`")
    logs.append(f"👤 **Client :** `{site_info['client']}`")
    logs.append(f"📍 **Site :** `{site_info['name']}` (Réf.: `{site_info['myid']}`)")
    logs.append(f"🏠 **Adresse :** `{site_info['address']}`")
    
    # Client
    customer_id = get_or_create_customer(site_info["client"])
    if not customer_id:
        return False, "Échec récupération/création du Client.", logs, 0

    # Site
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
    logs.append(f"✅ Site OK dans Synchroteam (ID: `{site_id}`)")

    # Interventions
    interventions_to_create = []

    if g_objs:
        desc_g = " / ".join([f"{k}: {v}" for k, v in g_objs.items()])
        interventions_to_create.append({"type_name": "POSE G", "description": desc_g})
        interventions_to_create.append({"type_name": "DÉPOSE G", "description": desc_g})

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

    if uv_objs:
        by_category = {}
        for code, qty in uv_objs.items():
            cat = code.split("-")[0].upper()
            if cat not in by_category:
                by_category[cat] = []
            by_category[cat].append(f"{code}: {qty}")

        for cat, list_measures in by_category.items():
            desc_cat = " / ".join(list_measures)
            interventions_to_create.append({"type_name": f"POSE {cat}", "description": desc_cat})
            interventions_to_create.append({"type_name": f"DÉPOSE {cat}", "description": desc_cat})

    for job in interventions_to_create:
        target_name = job["type_name"].strip().upper()
        job_type_id = job_types_map.get(target_name)
        if not job_type_id:
            for k, v in job_types_map.items():
                if target_name in k or k in target_name:
                    job_type_id = v
                    break

        job_payload = {
            "customerId": customer_id,
            "siteId": site_id,
            "description": job["description"],
        }
        if job_type_id:
            job_payload["type"] = {"id": job_type_id}

        res_job = safe_post(build_url("/job/send"), job_payload)
        if res_job and res_job.status_code in [200, 201]:
            logs.append(f"⚙️ Intervention `{job['type_name']}` créée.")
            created_jobs_count += 1
        else:
            logs.append(f"❌ Erreur création intervention `{job['type_name']}`")

    history_entry = {
        "timestamp": datetime.now().isoformat(),
        "date_str": datetime.now().strftime("%d/%m/%Y %H:%M"),
        "filename": uploaded_file.name,
        "client": site_info["client"],
        "site": site_info["name"],
        "jobs_count": created_jobs_count
    }
    save_history_entry(history_entry)

    return True, f"Dossier **{site_info['name']}** traité avec succès !", logs, created_jobs_count

# ==========================================
# 5. INTERFACE UTILISATEUR
# ==========================================
st.title("🦛 Le Décrypteur ADC")
st.caption("Importation et création automatique des sites et interventions PDF vers Synchroteam")

job_types_map = fetch_job_types_map()

# Indicateurs de statut
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
        if st.button(f"⚡ Lancer le traitement des {len(uploaded_files)} fichier(s)", type="primary", use_container_width=True):
            for file in uploaded_files:
                with st.expander(f"⚙️ Traitement de : {file.name}", expanded=True):
                    success, message, logs, count = process_single_pdf(file, job_types_map)
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
                c1.write(f"📅 **{entry['date_str']}**")
                c2.write(f"🏢 **{entry['client']}**\n📍 {entry['site']}")
                c3.caption(f"⚙️ {entry['jobs_count']} int. créée(s)")
                st.divider()