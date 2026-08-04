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
# 1. CONFIGURATION STREAMLIT & STYLES (Branding ADC)
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
# 2. AUTHENTIFICATION
# ==========================================
def check_auth():
    if "authenticated" not in st.session_state:
        st.session_state.authenticated = False

    if not st.session_state.authenticated:
        col1, col2, col3 = st.columns([1, 2, 1])
        with col2:
            st.markdown('<div class="login-card">', unsafe_allow_html=True)
            try:
                st.image("ACD_WEB_RVB.png", use_container_width=True)
            except Exception:
                st.markdown('<div class="main-title"><span class="highlight-letter">L</span>e <span class="highlight-letter">D</span>écrypteur - ADC</div>', unsafe_allow_html=True)
            
            st.caption("Connexion requise pour accéder à la plateforme")
            st.write("---")

            with st.form("auth_form"):
                email_input = st.text_input("Saisissez votre e-mail professionnel :", placeholder=f"exemple@{ALLOWED_DOMAIN}")
                submit_button = st.form_submit_button("Se connecter 🚀", type="primary", use_container_width=True)

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

def normalize_string(text):
    if not text:
        return ""
    text = unicodedata.normalize('NFKC', str(text))
    text = re.sub(r"[\s\xa0\u200b\u202f]+", " ", text)
    return text.strip().upper()

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
        return [item for item in data if datetime.fromisoformat(item["timestamp"]) >= cutoff]
    except Exception:
        return []

def save_history_entry(entry):
    history = load_history()
    history.insert(0, entry)
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)

def fetch_job_types_map():
    job_types_map = {}
    page = 1
    page_size = 50
    
    while True:
        url = build_url(f"/jobType/list?page={page}&pageSize={page_size}")
        try:
            res = requests.get(url, headers=HEADERS, timeout=10)
            if res.status_code == 200:
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
        except Exception:
            break

    if job_types_map:
        st.toast(f"{len(job_types_map)} types d'interventions chargés", icon="✅")
    else:
        st.error("⚠️ Impossible de récupérer la liste des types Synchroteam.")

    return job_types_map

def find_existing_site_by_myid(myid):
    try:
        res = requests.get(build_url(f"/site/list?myId={requests.utils.quote(myid)}"), headers=HEADERS, timeout=10)
        if res.status_code == 200:
            data = res.json()
            sites = data.get("data", []) if isinstance(data, dict) else data
            for site in sites:
                if normalize_string(site.get("myId", "")) == normalize_string(myid):
                    return site.get("id"), site.get("customerId")
    except Exception:
        pass
    return None, None

def get_or_create_customer(pdf_client_name):
    try:
        res_search = requests.get(build_url(f"/customer/list?name={requests.utils.quote(pdf_client_name)}"), headers=HEADERS, timeout=10)
        if res_search.status_code == 200:
            data = res_search.json()
            clients = data.get("data", []) if isinstance(data, dict) else data
            for c in clients:
                if normalize_string(c.get("name", "")) == normalize_string(pdf_client_name):
                    return c.get("id")
    except Exception:
        pass

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

# ==========================================
# 4. PARSER PDF (RECONSTRUCTION STRICTE PAR PHASE)
# ==========================================
def parse_pdf_file(uploaded_file):
    site_info = {"client": "", "name": "", "myid": "", "address": "", "zip": "", "city": ""}
    g_objs_list = []
    uv_objs = {}
    suivi_zones = {}
    j_procs = []
    process_names = []

    with pdfplumber.open(uploaded_file) as pdf:
        full_text = "".join([(page.extract_text() or "") + "\n" for page in pdf.pages])

        client_m = re.search(r"CLIENT\s*:\s*(.+)", full_text, re.IGNORECASE)
        if client_m: 
            site_info["client"] = client_m.group(1).strip()

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
        
        # Extraction structurée par tableaux PDF
        tables = target_page.extract_tables()
        current_zse = None

        for table in tables:
            for row in table:
                if not row or not any(row):
                    continue
                
                # Nettoyage des cellules
                cell_zse = row[0].strip() if len(row) > 0 and row[0] else ""
                cell_obj = row[2].strip() if len(row) > 2 and row[2] else ""
                full_row_text = " ".join([c for c in row if c])

                # Mettre à jour la ZSE si une nouvelle phase/zone apparaît dans la première colonne
                if cell_zse and ("SUIVI DE CHANTIER" in cell_zse.upper() or "PHASE" in cell_zse.upper()):
                    current_zse = re.sub(r"\s+", " ", cell_zse).strip()

                # Recherche des mesures (N(1), Q(1), R(1), L(2), etc.)
                codes_found = re.findall(r"\b([A-Z]+(?:-[A-Z0-9]+)?)\s*\(\s*(\d+)\s*\)", full_row_text)
                for code, qty_str in codes_found:
                    qty = int(qty_str)
                    if code.startswith("G"):
                        g_objs_list.append({code: qty})
                    elif any(code.startswith(letter) for letter in ["U", "V", "X", "Y"]):
                        uv_objs[code] = qty
                    elif code == "J-PROC":
                        j_procs.append(qty)
                    else:
                        active_key = current_zse if current_zse else "SUIVI DE CHANTIER"
                        if active_key not in suivi_zones:
                            suivi_zones[active_key] = {}
                        suivi_zones[active_key][code] = suivi_zones[active_key].get(code, 0) + qty

                # Capture du libellé exact du processus
                if "PROCESSUS" in full_row_text.upper():
                    proc_m = re.search(r"(PROCESSUS\s*N°\s*\d+\s*:[^\n]+)", full_row_text, re.IGNORECASE)
                    if proc_m:
                        proc_clean = proc_m.group(1).strip()
                        proc_clean = re.sub(r"\s+[A-Z-]+(?:\(\d+\))?.*$", "", proc_clean).strip()
                        if proc_clean and proc_clean not in process_names:
                            process_names.append(proc_clean)

        # Mode de secours en texte brut si l'extraction de tableau est vide
        if not suivi_zones:
            lines = (target_page.extract_text() or "").split("\n")
            current_zse = None
            for line in lines:
                line_str = line.strip()
                if "SUIVI DE CHANTIER" in line_str.upper():
                    current_zse = re.sub(r"\s+[A-Z]\(\d+\).*", "", line_str).strip()

                codes_found = re.findall(r"\b([A-Z]+(?:-[A-Z0-9]+)?)\s*\(\s*(\d+)\s*\)", line_str)
                for code, qty_str in codes_found:
                    qty = int(qty_str)
                    if not code.startswith("G") and not code == "J-PROC" and not any(code.startswith(l) for l in ["U", "V", "X", "Y"]):
                        active_key = current_zse if current_zse else "SUIVI DE CHANTIER"
                        if active_key not in suivi_zones:
                            suivi_zones[active_key] = {}
                        suivi_zones[active_key][code] = suivi_zones[active_key].get(code, 0) + qty

    suivi_zones = {k: v for k, v in suivi_zones.items() if v}
    return site_info, g_objs_list, suivi_zones, j_procs, uv_objs, process_names

# ==========================================
# 5. TRAITEMENT ET SYNCHROTEAM
# ==========================================
def process_single_pdf(uploaded_file, job_types_map, user_email):
    logs = []
    created_jobs_count = 0
    site_info, g_objs_list, suivi_zones, j_procs, uv_objs, process_names = parse_pdf_file(uploaded_file)
    
    logs.append(f"📄 **Fichier :** `{uploaded_file.name}`")
    logs.append(f"📍 **Dossier :** `{site_info['name']}` (Réf.: `{site_info['myid']}`)")

    site_id, customer_id = find_existing_site_by_myid(site_info["myid"])
    site_existed = False

    if site_id and customer_id:
        site_existed = True
        logs.append(f"🔗 **Site existant trouvé** (ID: `{site_id}`). Rattachement...")
    else:
        logs.append("🔍 Création du site...")
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
            "customerId": customer_id,
        }
        res_site = safe_post(build_url("/site/send"), site_payload)
        if not res_site or res_site.status_code not in [200, 201]:
            return False, "Échec lors de la création du site.", logs, 0

        site_id = res_site.json().get("id")
        logs.append(f"✅ Site créé (ID: `{site_id}`)")

    interventions_to_create = []

    # 1. G : Pose G + Dépose G
    for g_item in g_objs_list:
        desc_g = " / ".join([f"{k}: {v}" for k, v in g_item.items()])
        interventions_to_create.append({"type_name": "Pose G", "description": desc_g})
        interventions_to_create.append({"type_name": "Dépose G", "description": desc_g})

    # 2. Suivi : Découpage exact par Zone / Phase
    suivi_type_label = "Suivi 4h - Enviro + opé + MES + Mat"
    total_j_proc = sum(j_procs) if j_procs else 0
    j_proc_line = f"+ J-PROC ({total_j_proc})" if total_j_proc > 0 else ""
    proc_list_str = "\n".join(process_names) if process_names else ""

    for zse_label, objs in suivi_zones.items():
        if objs:
            measures_str = " / ".join([f"{k}: {v}" for k, v in objs.items()])
            desc_lines = [f"{zse_label} : {measures_str}"]
            if j_proc_line: 
                desc_lines.append(j_proc_line)
            if proc_list_str: 
                desc_lines.append(proc_list_str)

            interventions_to_create.append({
                "type_name": suivi_type_label,
                "description": "\n".join(desc_lines)
            })

    # 3. U, V, X, Y : Pose + Dépose
    if uv_objs:
        by_category = {}
        for code, qty in uv_objs.items():
            cat = code.split("-")[0].upper()
            by_category.setdefault(cat, []).append(f"{code}: {qty}")

        for cat, list_measures in by_category.items():
            desc_cat = " / ".join(list_measures)
            interventions_to_create.append({"type_name": f"Pose {cat}", "description": desc_cat})
            interventions_to_create.append({"type_name": f"Dépose {cat}", "description": desc_cat})

    # Envoi Synchroteam
    for job in interventions_to_create:
        target_clean = normalize_string(job["type_name"])
        job_type_id = job_types_map.get(target_clean)

        job_payload = {
            "customerId": customer_id,
            "siteId": site_id,
            "description": job["description"]
        }

        if job_type_id:
            job_payload["type"] = {"id": int(job_type_id)}
            logs.append(f"⚙️ `[{job['type_name']}]` -> ID : `{job_type_id}`")
        else:
            logs.append(f"⚠️ `[{job['type_name']}]` non trouvé dans l'API")

        res_job = safe_post(build_url("/job/send"), job_payload)
        if res_job and res_job.status_code in [200, 201]:
            created_jobs_count += 1
        else:
            err_text = res_job.text if res_job else "Pas de réponse"
            logs.append(f"❌ Erreur API pour `{job['type_name']}` : {err_text}")

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
# 6. INTERFACE STREAMLIT
# ==========================================

with st.sidebar:
    try:
        st.image("ACD_WEB_RVB.png", use_container_width=True)
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
    st.markdown(
        '<div class="main-title"><span class="highlight-letter">L</span>e '
        '<span class="highlight-letter">D</span>écrypteur - ADC</div>', 
        unsafe_allow_html=True
    )
    st.caption("Importation et création automatique d'interventions Synchroteam")
with header_col2:
    try:
        st.image("ACD_WEB_RVB.png", use_container_width=True)
    except Exception:
        st.caption("[Logo ADC Labo]")
    st.markdown('<div class="hippo-badge">🦛</div>', unsafe_allow_html=True)

st.write("---")

job_types_map = fetch_job_types_map()

col1, col2 = st.columns(2)
with col1: 
    st.metric("Statut API", "Connecté", delta=f"{len(job_types_map)} types")
with col2: 
    st.metric("Dossiers (48h)", len(load_history()))

with st.expander("🔍 Vérification des types d'interventions chargés"):
    st.json(job_types_map)

st.write("---")

tab_import, tab_history = st.tabs(["🚀 Import", "📜 Historique"])

with tab_import:
    uploaded_files = st.file_uploader("Fichiers PDF", type=["pdf"], accept_multiple_files=True)
    if uploaded_files and st.button(f"Lancer ({len(uploaded_files)})", type="primary", use_container_width=True):
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
    for entry in load_history():
        st.write(f"📅 **{entry['date_str']}** | 🏢 **{entry['client']}** | 📍 {entry['site']}")
        st.divider()
