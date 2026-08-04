import re
import requests
import fitz  # PyMuPDF pour lire le PDF
import streamlit as st

# -------------------------------------------------------------------
# CONFIGURATION ET CONSTANTES
# -------------------------------------------------------------------
PAIR_TYPES = {"G", "U", "V", "X", "Y"}

st.set_page_config(
    page_title="Automation Synchroteam", page_icon="⚡", layout="wide"
)

st.title("⚡ Générateur d'Interventions Synchroteam")
st.markdown(
    "Téléverse un rapport PDF pour créer automatiquement les paires **Pose/Dépose** par zone (G, U, V, X, Y) et les **Suivis** à l'unité."
)

# -------------------------------------------------------------------
# 1. API SYNCHROTEAM : RÉCUPÉRATION COMPLÈTE DES TYPES (PAGINATION)
# -------------------------------------------------------------------
def get_all_job_types(domain, api_key):
    """Récupère l'ensemble des types d'interventions via la v3 de l'API Synchroteam

    en gérant la pagination (pour avoir les 46 types).
    """
    url = f"https://{domain}.synchroteam.com/api/v3/jobType/list"
    auth = (domain, api_key)
    headers = {"Accept": "application/json"}

    job_types_mapping = {}
    page = 1
    has_more = True

    while has_more:
        params = {"page": page}
        try:
            response = requests.get(
                url, auth=auth, headers=headers, params=params, timeout=10
            )
            if response.status_code == 200:
                data = response.json()
                items = data.get("jobTypes", data.get("items", []))

                for item in items:
                    # Enregistre le nom et l'ID
                    job_types_mapping[item["name"].strip()] = item["id"]

                # Vérification de la pagination
                total_pages = data.get("pagesTotal", 1)
                if page >= total_pages or not items:
                    has_more = False
                else:
                    page += 1
            else:
                st.error(
                    f"Erreur API Synchroteam lors de la récupération des types ({response.status_code})."
                )
                has_more = False
        except Exception as e:
            st.error(f"Erreur de connexion API : {e}")
            has_more = False

    return job_types_mapping


# -------------------------------------------------------------------
# 2. PARSER PDF : LOGIQUE PAIRES PAR ZONE & SUIVIS UNIQUE
# -------------------------------------------------------------------
def extract_text_from_pdf(uploaded_file):
    """Extrait le texte de toutes les pages du fichier PDF téléversé."""
    doc = fitz.open(stream=uploaded_file.read(), filetype="pdf")
    text = ""
    for page in doc:
        text += page.get_text() + "\n"
    return text


def parse_pdf_interventions(pdf_text):
    """Analyse le texte du PDF :

    - 1 paire (Pose + Dépose) par ZONE détectée pour G, U, V, X, Y.
    - 1 création simple à l'unité pour les Suivis et MES.
    """
    interventions_to_create = []

    # A. PAIRES POSE/DÉPOSE PAR ZONE (G, U, V, X, Y)
    for target in PAIR_TYPES:
        zone_pattern = rf"(?:Zone\s*\d+|ZSE[^\n]*)\b.*?\b{target}\s*\(\s*\d+\s*\)"
        zone_matches = re.findall(zone_pattern, pdf_text, re.IGNORECASE)

        if zone_matches:
            nb_zones = len(zone_matches)
        else:
            direct_pattern = rf"\b{target}\s*\(\s*\d+\s*\)"
            direct_matches = re.findall(direct_pattern, pdf_text)
            nb_zones = len(direct_matches)

        for _ in range(nb_zones):
            interventions_to_create.append(f"Pose {target}")
            interventions_to_create.append(f"Dépose {target}")

    # B. SUIVIS & MES (À L'UNITÉ)
    suivi_pattern = r"\b(Suivi\s*4h|MES|J-PROC|[NPQM])\s*\(\s*(\d+)\s*\)"
    suivi_matches = re.findall(suivi_pattern, pdf_text, re.IGNORECASE)

    for item_type, count in suivi_matches:
        nb = int(count)
        clean_type = item_type.strip()
        if "SUIVI" in clean_type.upper():
            clean_type = "Suivi 4h"
        else:
            clean_type = clean_type.upper()

        for _ in range(nb):
            interventions_to_create.append(clean_type)

    return interventions_to_create


# -------------------------------------------------------------------
# 3. INTERFACE STREAMLIT ET EXÉCUTION
# -------------------------------------------------------------------
st.sidebar.header("🔑 Identifiants Synchroteam")
domain = st.sidebar.text_input("Domaine (ex: monentreprise)", value="")
api_key = st.sidebar.text_input("Clé API", type="password", value="")

customer_id = st.sidebar.text_input("ID Client (Customer ID)", value="")
site_id = st.sidebar.text_input("ID Site (Site ID)", value="")

uploaded_file = st.file_uploader(
    "Téléverse ton rapport PDF", type=["pdf"]
)

if uploaded_file and domain and api_key and customer_id and site_id:
    if st.button("🚀 Analyser le PDF et Créer les Interventions"):
        with st.spinner("Récupération des types d'interventions..."):
            mapping_types = get_all_job_types(domain, api_key)
            st.info(
                f"📋 {len(mapping_types)} types d'interventions récupérés depuis Synchroteam."
            )

        with st.spinner("Analyse du PDF en cours..."):
            pdf_text = extract_text_from_pdf(uploaded_file)
            interventions = parse_pdf_interventions(pdf_text)

        if not interventions:
            st.warning("Aucune intervention détectée dans ce PDF.")
        else:
            st.write(
                f"### 🎯 Interventions détectées ({len(interventions)}) :"
            )
            st.json(interventions)

            # Création dans Synchroteam
            st.write("### ⚙️ Création dans Synchroteam...")
            url_create = f"https://{domain}.synchroteam.com/api/v3/job/create"
            auth = (domain, api_key)
            headers = {"Content-Type": "application/json"}

            success_count = 0
            for item in interventions:
                if item not in mapping_types:
                    st.error(
                        f"❌ Le type **'{item}'** n'existe pas dans ton compte Synchroteam."
                    )
                    continue

                type_id = mapping_types[item]
                payload = {
                    "myId": "",
                    "type": {"id": type_id},
                    "customer": {"id": int(customer_id)},
                    "site": {"id": int(site_id)},
                    "description": f"Création auto : {item}",
                }

                resp = requests.post(
                    url_create,
                    json=payload,
                    auth=auth,
                    headers=headers,
                    timeout=10,
                )
                if resp.status_code in (200, 201):
                    st.success(f"✅ Créé : **{item}**")
                    success_count += 1
                else:
                    st.error(
                        f"❌ Erreur sur **{item}** ({resp.status_code}) : {resp.text}"
                    )

            st.balloons()
            st.success(
                f"🎉 Terminé : {success_count} / {len(interventions)} interventions créées !"
            )
