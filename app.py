import re
import streamlit as st
import requests
import pdfplumber

# 1. Configuration de la page (Favicon Hippopotame)
st.set_page_config(
    page_title="Le Décrypteur ADC", 
    page_icon="🦛", 
    layout="centered"
)

# 2. Authentification obligatoire (Domaine @adc-labo.fr uniquement)
def check_email():
    if "authenticated" not in st.session_state:
        st.session_state["authenticated"] = False
        st.session_state["user_email"] = ""

    if not st.session_state["authenticated"]:
        st.title("🔒 Connexion requise")
        email_input = st.text_input("Saisissez votre adresse e-mail pour accéder à l'application :")
        
        if st.button("Se connecter"):
            email_clean = email_input.strip().lower()
            email_pattern = r"^[\w\.-]+@[\w\.-]+\.\w+$"
            
            if not email_clean:
                st.error("Veuillez renseigner une adresse e-mail.")
            elif not re.match(email_pattern, email_clean):
                st.error("Format d'adresse e-mail invalide.")
            elif not email_clean.endswith("@adc-labo.fr"):
                st.error("Accès refusé : l'adresse doit se terminer par @adc-labo.fr")
            else:
                st.session_state["authenticated"] = True
                st.session_state["user_email"] = email_clean
                st.rerun()
        return False
    return True

# L'application ne s'exécute que si l'utilisateur est authentifié
if check_email():

    # 3. En-tête : Titre à gauche, Logo ADC à droite
    col_title, col_logo = st.columns([3, 1])

    with col_title:
        st.title("Le Décrypteur ADC")
        st.caption(f"Connecté en tant que : **{st.session_state['user_email']}**")

    with col_logo:
        try:
            st.image("ADC ROGNÉ.jpg", use_container_width=True)
        except Exception:
            st.caption("[Logo ADC Labo]")

    # Configuration API Synchroteam
    DOMAIN = st.secrets.get("SYNCHROTEAM_DOMAIN", "mon-domaine")
    API_KEY = st.secrets.get("SYNCHROTEAM_API_KEY", "ma-cle-api")
    BASE_URL = f"https://{DOMAIN}.synchroteam.com/api/v3"
    AUTH = (DOMAIN, API_KEY)

    # 4. Extraction du texte du PDF
    def extract_text_from_pdf(uploaded_file):
        text = ""
        with pdfplumber.open(uploaded_file) as pdf:
            for page in pdf.pages:
                extracted = page.extract_text()
                if extracted:
                    text += extracted + "\n"
        return text

    # 5. Récupération paginée des types d'interventions Synchroteam
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

    # 6. Interface de dépôt du rapport PDF
    uploaded_file = st.file_uploader("Chargez votre rapport PDF ADC Labo", type=["pdf"])

    if uploaded_file is not None:
        text = extract_text_from_pdf(uploaded_file)
        st.success("PDF lu avec succès !")
        
        try:
            types_map = get_all_job_types()
            st.info(f"{len(types_map)} types d'interventions chargés depuis Synchroteam.")
        except Exception as e:
            st.error(f"Erreur Synchroteam : {e}")

        if st.button("Lancer la création des interventions"):
            st.write("Traitement en cours...")
