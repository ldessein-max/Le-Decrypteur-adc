import streamlit as st
import requests
import pdfplumber
import re

# Configuration Streamlit
st.set_page_config(page_title="Le Décrypteur ADC", layout="centered")
st.title("Le Décrypteur ADC")

# Configuration API Synchroteam
DOMAIN = st.secrets.get("SYNCHROTEAM_DOMAIN", "mon-domaine")
API_KEY = st.secrets.get("SYNCHROTEAM_API_KEY", "ma-cle-api")
BASE_URL = f"https://{DOMAIN}.synchroteam.com/api/v3"
AUTH = (DOMAIN, API_KEY)

# 1. Extraction du texte PDF avec pdfplumber
def extract_text_from_pdf(uploaded_file):
    text = ""
    with pdfplumber.open(uploaded_file) as pdf:
        for page in pdf.pages:
            extracted = page.extract_text()
            if extracted:
                text += extracted + "\n"
    return text

# 2. Récupération paginée de TOUS les types d'interventions
@st.cache_data(ttl=3600)
def get_all_job_types():
    job_types = {}
    page = 1
    while True:
        url = f"{BASE_URL}/job/types?page={page}"
        response = requests.get(url, auth=AUTH)
        if response.status_code != 200:
            break
        data = response.json()
        items = data.get("categoryList", []) or data.get("jobTypeList", []) or data
        if isinstance(data, dict) and "data" in data:
            items = data["data"]
        
        if not items:
            break
            
        for item in items:
            name = item.get("name") or item.get("label")
            id_val = item.get("id")
            if name and id_val:
                job_types[name.strip().lower()] = id_val
                
        if len(items) < 25:
            break
        page += 1
    return job_types

# 3. Traitement principal
uploaded_file = st.file_uploader("Chargez votre rapport PDF ADC Labo", type=["pdf"])

if uploaded_file is not None:
    text = extract_text_from_pdf(uploaded_file)
    st.success("PDF lu avec succès !")
    
    # Récupération des types d'interventions
    try:
        types_map = get_all_job_types()
        st.info(f"{len(types_map)} types d'interventions récupérés depuis Synchroteam.")
    except Exception as e:
        st.error(f"Erreur lors de la récupération des types : {e}")
        types_map = {}

    if st.button("Lancer la création des interventions"):
        st.write("Traitement en cours...")
        # Ici la logique de parsing et d'envoi API
