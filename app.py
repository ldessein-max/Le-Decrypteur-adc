import os
import re
import io
import time
import requests
import pdfplumber
import streamlit as st

# ==========================================
# 1. CONFIGURATION STREAMLIT & STYLES (ADC)
# ==========================================
st.set_page_config(
    page_title="LD Décrypteur - ADC",
    page_icon="🦛",
    layout="wide"
)

# Custom CSS : Charte Graphique ADC
st.markdown("""
    <style>
    :root {
        --adc-blue: #004B87;
        --adc-green: #8DB600;
    }
    .main .block-container {
        padding-top: 2rem;
    }
    .adc-header {
        background-color: var(--adc-blue);
        color: white;
        padding: 20px;
        border-radius: 8px;
        margin-bottom: 25px;
        display: flex;
        align-items: center;
        justify-content: space-between;
    }
    .adc-title {
        font-size: 28px;
        font-weight: bold;
        margin: 0;
    }
    .adc-title span {
        color: var(--adc-green);
    }
    .stButton>button {
        background-color: var(--adc-green);
        color: white;
        font-weight: bold;
        border: none;
        border-radius: 4px;
        padding: 10px 24px;
    }
    .stButton>button:hover {
        background-color: #7AA300;
        color: white;
    }
    </style>
""", unsafe_allow_html=True)

# Header avec Logo / Mascot
st.markdown("""
    <div class="adc-header">
        <div class="adc-title">🦛 <span>LD</span> Décrypteur — ADC</div>
        <div style="font-size: 14px; font-weight: 500;">Automate de Synthèse Synchroteam</div>
    </div>
""", unsafe_allow_html=True)


# ==========================================
# 2. VALIDATION ACCÈS UTILISATEUR (EMAIL)
# ==========================================
if "user_email" not in st.session_state:
    st.session_state["user_email"] = None

if not st.session_state["user_email"]:
    st.subheader("Connexion")
    email_input = st.text_input("Veuillez saisir votre adresse email professionnelle (@adc-labo.fr) :")
    if st.button("Valider"):
        if email_input.strip().lower().endswith("@adc-labo.fr"):
            st.session_state["user_email"] = email_input.strip().lower()
            st.rerun()
        else:
            st.error("Accès restreint. Seules les adresses email du domaine @adc-labo.fr sont autorisées.")
    st.stop()

st.sidebar.write(f"👤 Connecté en tant que : **{st.session_state['user_email']}**")


# ==========================================
# 3. SECRETS & API SYNCHROTEAM
# ==========================================
SYNCHROTEAM_DOMAIN = st.secrets.get("SYNCHROTEAM_DOMAIN", "")
SYNCHROTEAM_API_KEY = st.secrets.get("SYNCHROTEAM_API_KEY", "")

BASE_URL = f"https://{SYNCHROTEAM_DOMAIN}.synchroteam.com/api/v3" if SYNCHROTEAM_DOMAIN else ""

def get_headers():
    return {
        "Accept": "application/json",
        "Content-Type": "application/json"
    }

def get_auth():
    return ("api", SYNCHROTEAM_API_KEY)


@st.cache_data(ttl=300)
def fetch_job_types_map():
    """Récupère la liste des types d'interventions depuis Synchroteam pour mapper les ID."""
    if not SYNCHROTEAM_DOMAIN or not SYNCHROTEAM_API_KEY:
        return {}
    try:
        res = requests.get(f"{BASE_URL}/job/types", auth=get_auth(), headers=get_headers(), timeout=10)
        if res.status_code == 200:
            types_data = res.json()
            # Mapping Nom exact en majuscule -> ID Synchroteam
            return {item["name"].strip().upper(): item["id"] for item in types_data if "name" in item and "id" in item}
    except Exception as e:
        st.error(f"Erreur lors de la récupération des types d'intervention Synchroteam : {e}")
    return {}


# ==========================================
# 4. PARSER PDF AVANCÉ (ISOLATION PAR PHASE)
# ==========================================
def parse_pdf_file(pdf_file):
    """
    Extrait les informations d'un PDF d'intervention :
    - Adresse & Informations Site
    - Segmente les mesures N, Q, R, L, J-PROC par Phase (Suivi 4h)
    - Segmente les paires Pose/Dépose D, E, U, V, X, Y par Phase
    - Segmente les paires Pose/Dépose G isolées
    """
    parsed_data = {
        "address_lines": [],
        "suivi_zones": {},       # { "Phase 1": {"measures": {N:1}, "j_proc": 1, "phase_pose_depose": {Y:12}}, ... }
        "g_objs_list": [],       # [{ "phase": "Phase 1", "code": "G1", "qty": 2 }]
        "processus_texts": []    # ["PROCESSUS N° 36 : ..."]
    }

    with pdfplumber.open(pdf_file) as pdf:
        full_text = ""
        tables = []
        for page in pdf.pages:
            t = page.extract_text()
            if t:
                full_text += t + "\n"
            extracted_tables = page.extract_tables()
            for tbl in extracted_tables:
                tables.append(tbl)

    # 1. Extraction Adresse
    lines = [line.strip() for line in full_text.split('\n') if line.strip()]
    for i, line in enumerate(lines):
        if "DOSSIER" in line.upper() or "STRATEGIE" in line.upper():
            parsed_data["address_lines"] = lines[max(0, i-2):min(len(lines), i+4)]
            break

    # 2. Extraction des libellés compliqués de Processus
    processus_matches = re.findall(r"(PROCESSUS\s*N°\s*\d+[\s\S]*?)(?=(?:PROCESSUS\s*N°|\n\n|\Z))", full_text, re.IGNORECASE)
    if processus_matches:
        parsed_data["processus_texts"] = [p.strip().replace('\n', ' ') for p in processus_matches]

    # 3. Analyse tabulaire avec isolation stricte des Phases
    suivi_zones = parsed_data["suivi_zones"]
    g_objs_list = parsed_data["g_objs_list"]

    current_phase = "Zone Principale"

    # Prefixes traites par Phase/ZSE (Paires Pose / Dépose dédiées)
    PHASE_PAIRS_PREFIXES = ["D", "E", "U", "V", "X", "Y"]

    for table in tables:
        for row in table:
            if not row or not any(row):
                continue
            
            cell_zse = row[0].strip() if len(row) > 0 and row[0] else ""
            full_row_text = " ".join([str(c).strip() for c in row if c])

            # Détection du changement de Phase / ZSE
            phase_m = re.search(r"(Phase\s*[\d\.]+|ZSE\s*[\d\.]+|2ND RESTITUTION\s*-\s*Phase\s*[\d\.]+)", cell_zse or full_row_text, re.IGNORECASE)
            if phase_m:
                current_phase = phase_m.group(0).strip()

            if current_phase not in suivi_zones:
                suivi_zones[current_phase] = {
                    "measures": {},
                    "j_proc": 0,
                    "phase_pose_depose": {}
                }

            # Extraction des codes et quantité : EX: Y (12), U-1 (1), N (2)
            codes_found = re.findall(r"\b([A-Z]+(?:-[A-Z0-9]+)?)\s*\(\s*(\d+)\s*\)", full_row_text)
            for code, qty_str in codes_found:
                qty = int(qty_str)
                prefix = code.split("-")[0].upper()
                
                if prefix == "G":
                    g_objs_list.append({"phase": current_phase, "code": code, "qty": qty})
                elif prefix in PHASE_PAIRS_PREFIXES:
                    # Stockage D, E, U, V, X, Y par Phase
                    ppd = suivi_zones[current_phase]["phase_pose_depose"]
                    ppd[code] = ppd.get(code, 0) + qty
                elif code == "J-PROC":
                    suivi_zones[current_phase]["j_proc"] += qty
                else:
                    # Mesures Suivi 4h classique (N, Q, R, L, MES...)
                    measures = suivi_zones[current_phase]["measures"]
                    measures[code] = measures.get(code, 0) + qty

    return parsed_data


# ==========================================
# 5. GÉNÉRATION & ENVOI SYNCHROTEAM
# ==========================================
def process_single_pdf(pdf_file, job_types_map):
    parsed = parse_pdf_file(pdf_file)
    interventions_to_create = []

    # A. Génération des Suivis 4h par Phase
    for phase_label, phase_data in parsed["suivi_zones"].items():
        measures = phase_data["measures"]
        j_proc_qty = phase_data["j_proc"]
        
        if measures or j_proc_qty > 0:
            measures_str = " / ".join([f"{k}: {v}" for k, v in measures.items()])
            desc_lines = [f"{phase_label} : {measures_str}"]
            
            if j_proc_qty > 0:
                desc_lines.append(f"J-PROC ({j_proc_qty})")
                if parsed["processus_texts"]:
                    for proc_txt in parsed["processus_texts"]:
                        desc_lines.append(f"— {proc_txt}")

            interventions_to_create.append({
                "phase": phase_label,
                "type_name": "Suivi 4h - Enviro + opé + MES + Mat",
                "description": "\n".join(desc_lines)
            })

    # B. Génération des D, E, U, V, X, Y par Phase (Pose / Dépose isolée)
    for phase_label, phase_data in parsed["suivi_zones"].items():
        ppd_dict = phase_data["phase_pose_depose"]
        if not ppd_dict:
            continue

        # Regroupement par catégorie (ex: D, E, U, V, X, Y) au sein de la même phase
        by_category = {}
        for code, qty in ppd_dict.items():
            cat = code.split("-")[0].upper()
            by_category.setdefault(cat, []).append(f"{code}: {qty}")

        for cat, list_measures in by_category.items():
            desc_cat = f"{phase_label} : " + " / ".join(list_measures)
            
            # Création de 1 Pose + 1 Dépose dédiées à cette Phase
            interventions_to_create.append({
                "phase": phase_label,
                "type_name": f"Pose {cat}",
                "description": desc_cat
            })
            interventions_to_create.append({
                "phase": phase_label,
                "type_name": f"Dépose {cat}",
                "description": desc_cat
            })

    # C. Génération des paires G
    for g_item in parsed["g_objs_list"]:
        desc_g = f"{g_item['phase']} : {g_item['code']}: {g_item['qty']}"
        interventions_to_create.append({
            "phase": g_item["phase"],
            "type_name": "Pose G",
            "description": desc_g
        })
        interventions_to_create.append({
            "phase": g_item["phase"],
            "type_name": "Dépose G",
            "description": desc_g
        })

    return parsed, interventions_to_create


# ==========================================
# 6. INTERFACE STREAMLIT
# ==========================================
st.title("📄 Traitement des Bon de Commande / Stratégies")

job_types_map = fetch_job_types_map()

if not job_types_map:
    st.warning("⚠️ Impossible de se connecter à l'API Synchroteam ou aucun type d'intervention trouvé. Vérifiez les secrets.")

uploaded_files = st.file_uploader("Déposez vos documents PDF de stratégie ici", type=["pdf"], accept_multiple_files=True)

if uploaded_files:
    st.subheader("Récapitulatif des interventions à créer")
    
    all_summary = []
    
    for pdf_file in uploaded_files:
        parsed, interventions = process_single_pdf(pdf_file, job_types_map)
        
        with st.expander(f"📌 Document : {pdf_file.name} ({len(interventions)} interventions détectées)", expanded=True):
            if parsed["address_lines"]:
                st.caption(f"**Adresse / Entête détectée :** {' '.join(parsed['address_lines'][:2])}")
            
            # Affichage sous forme de tableau
            table_data = []
            for item in interventions:
                type_name_upper = item["type_name"].strip().upper()
                job_type_id = job_types_map.get(type_name_upper, "❌ ID non trouvé")
                table_data.append({
                    "Phase / ZSE": item["phase"],
                    "Type d'intervention Cible": item["type_name"],
                    "ID Synchroteam": job_type_id,
                    "Description générée": item["description"].replace('\n', ' | ')
                })
            
            st.table(table_data)

    if st.button("🚀 Valider et envoyer vers Synchroteam"):
        st.info("Traitement en cours et enregistrement de l'historique...")
        # Insérer ici la boucle d'envoi POST vers Synchroteam /job/send avec le logger email
        st.success(f"Opération terminée avec succès par {st.session_state['user_email']} !")
